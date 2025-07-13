
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict
from datetime import datetime, timezone
import re
import uuid

from .manager_cog import ManagerCog
from google.cloud import firestore
from google.cloud.firestore_v1.async_client import async_transactional

def is_hex_color(s: str) -> bool:
    if not s: return False
    return re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', s) is not None

class GuildInviteView(discord.ui.View):
    def __init__(self, manager: 'ManagerCog', guild_id: str, guild_name: str, inviter: discord.Member):
        super().__init__(timeout=3600) # 1 hour
        self.manager = manager
        self.guild_id = guild_id
        self.guild_name = guild_name
        self.inviter = inviter

    async def _handle_response(self, interaction: discord.Interaction, accepted: bool):
        for item in self.children: item.disabled = True
        
        original_embed = interaction.message.embeds[0]
        
        if accepted:
            user_ref = self.manager.db.collection('users').document(str(interaction.user.id))
            user_data = await self.manager.get_or_create_user_data(user_ref)
            if user_data.get("guild_id"):
                original_embed.description = "Vous êtes déjà dans une guilde."
                original_embed.color = discord.Color.orange()
                await interaction.response.edit_message(embed=original_embed, view=self)
                return
            
            guild_ref = self.manager.db.collection('guilds').document(self.guild_id)
            guild_data = (await guild_ref.get()).to_dict()
            
            if len(guild_data.get('members', [])) >= self.manager.config.get("GUILD_SYSTEM", {}).get("MAX_MEMBERS", 10):
                 original_embed.description = f"La guilde **{self.guild_name}** est pleine."
                 original_embed.color = discord.Color.orange()
                 await interaction.response.edit_message(embed=original_embed, view=self)
                 return
            
            role = interaction.guild.get_role(guild_data['role_id'])
            if role: await interaction.user.add_roles(role)
            
            await user_ref.update({"guild_id": self.guild_id})
            await guild_ref.update({"members": firestore.ArrayUnion([str(interaction.user.id)])})
            
            original_embed.description = f"Vous avez rejoint la guilde **{self.guild_name}** !"
            original_embed.color = discord.Color.green()
        else:
            original_embed.description = f"Vous avez refusé l'invitation à rejoindre **{self.guild_name}**."
            original_embed.color = discord.Color.red()
            
        await interaction.response.edit_message(embed=original_embed, view=self)

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_response(interaction, accepted=True)
        
    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_response(interaction, accepted=False)
        
class GuildDissolveView(discord.ui.View):
    def __init__(self, cog: 'GuildCog', guild_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        
    @discord.ui.button(label="Oui, dissoudre la guilde", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.cog.execute_dissolve(interaction, self.guild_id)
        for item in self.children: item.disabled = True
        await interaction.edit_original_response(content="La guilde est en cours de dissolution...", view=self)

    @discord.ui.button(label="Non, annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="Opération annulée.", view=self)
        
class GuildCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None

    async def cog_load(self):
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager or not self.manager.db:
            return print("ERREUR CRITIQUE: GuildCog n'a pas pu trouver le ManagerCog ou la BDD.")
        print("✅ GuildCog chargé.")
    
    guild_group = app_commands.Group(name="guilde", description="Gère les guildes et leurs membres.")

    @guild_group.command(name="creer", description="Crée une nouvelle guilde (coûte des crédits).")
    @app_commands.describe(nom="Le nom de votre future guilde.", couleur="La couleur de la guilde en hexadécimal (ex: #3b82f6).")
    async def creer(self, interaction: discord.Interaction, nom: str, couleur: Optional[str]):
        if not self.manager: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        guild_config = self.manager.config.get("GUILD_SYSTEM", {})
        if not guild_config.get("ENABLED", False):
            return await interaction.response.send_message("Le système de guildes est actuellement désactivé.", ephemeral=True)
        
        user_ref = self.manager.db.collection('users').document(str(interaction.user.id))
        user_data = await self.manager.get_or_create_user_data(user_ref)
        
        if user_data.get("guild_id"):
            return await interaction.response.send_message("❌ Vous êtes déjà dans une guilde.", ephemeral=True)
            
        existing_guild_query = self.manager.db.collection('guilds').where(field_path='name_lower', op_string='==', value=nom.lower()).limit(1).stream()
        if len([doc async for doc in existing_guild_query]) > 0:
            return await interaction.response.send_message("❌ Une guilde avec ce nom existe déjà.", ephemeral=True)

        cost = guild_config.get("CREATION_COST", 3)
        if user_data.get("store_credit", 0) < cost:
            return await interaction.response.send_message(f"❌ Il vous faut **{cost} crédits** pour créer une guilde. Vous en avez {user_data.get('store_credit', 0):.2f}.", ephemeral=True)
        
        final_color = couleur if couleur and is_hex_color(couleur) else "#99aab5"
        await interaction.response.defer(ephemeral=True)

        guild_id = str(uuid.uuid4())
        guild_ref = self.manager.db.collection('guilds').document(guild_id)
        
        guild_role = None
        text_channel = None
        voice_channel = None

        try:
            # Create Discord assets first
            guild_category_name = guild_config.get("GUILD_CATEGORY_NAME", "Guildes")
            category = discord.utils.get(interaction.guild.categories, name=guild_category_name)
            if not category:
                category = await interaction.guild.create_category(guild_category_name)

            guild_role = await interaction.guild.create_role(name=f"Guilde - {nom}", colour=discord.Color.from_str(final_color), hoist=True, reason=f"Création de la guilde {nom}")
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)
            }
            text_channel = await interaction.guild.create_text_channel(f"│💬│{nom.lower().replace(' ', '-')}", category=category, overwrites=overwrites)
            voice_channel = await interaction.guild.create_voice_channel(f"│🔊│{nom}", category=category, overwrites=overwrites)
            await interaction.user.add_roles(guild_role)

            # Atomically update DB
            @async_transactional
            async def create_guild_transaction(trans, user_ref, guild_ref):
                # Deduct cost
                await self.manager.add_transaction(trans, user_ref, "store_credit", -cost, f"Création de la guilde '{nom}'")
                
                # Create guild doc and update user
                guild_db_data = {
                    "name": nom, "name_lower": nom.lower(), "owner_id": str(interaction.user.id),
                    "members": [str(interaction.user.id)], "created_at": datetime.now(timezone.utc).isoformat(),
                    "color": final_color, "weekly_xp": 0, "role_id": guild_role.id,
                    "text_channel_id": text_channel.id, "voice_channel_id": voice_channel.id
                }
                trans.set(guild_ref, guild_db_data)
                trans.update(user_ref, {"guild_id": guild_id})
            
            await create_guild_transaction(self.manager.db.transaction(), user_ref, guild_ref)
        except Exception as e:
            # Rollback Discord assets if they were created
            if guild_role: await guild_role.delete()
            if text_channel: await text_channel.delete()
            if voice_channel: await voice_channel.delete()
            print(f"Erreur création guilde : {e}")
            return await interaction.followup.send("Une erreur est survenue. L'opération a été annulée.", ephemeral=True)
        
        await interaction.followup.send(f"✅ Félicitations ! Votre guilde **{nom}** a été créée. Rendez-vous dans {text_channel.mention}.", ephemeral=True)


    @guild_group.command(name="info", description="Affiche les informations sur une guilde.")
    @app_commands.describe(nom="Le nom de la guilde (optionnel, affiche la vôtre par défaut).")
    async def info(self, interaction: discord.Interaction, nom: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        
        guild_data = None
        if nom:
            query = self.manager.db.collection('guilds').where(field_path='name_lower', op_string='==', value=nom.lower()).limit(1).stream()
            async for doc in query: guild_data = doc.to_dict()
        else:
            user_data = await self.manager.get_or_create_user_data(self.manager.db.collection('users').document(str(interaction.user.id)))
            guild_id = user_data.get('guild_id')
            if guild_id:
                guild_data = (await self.manager.db.collection('guilds').document(guild_id).get()).to_dict()

        if not guild_data:
            return await interaction.followup.send("❌ Guilde introuvable.", ephemeral=True)
        
        owner = await self.bot.fetch_user(int(guild_data['owner_id']))
        created_dt = datetime.fromisoformat(guild_data['created_at'])
        max_members = self.manager.config.get('GUILD_SYSTEM', {}).get('MAX_MEMBERS', 10)

        embed = discord.Embed(
            title=f"🛡️ Informations sur la Guilde: {guild_data['name']}",
            color=discord.Color.from_str(guild_data['color'])
        )
        embed.add_field(name="Chef de Guilde", value=owner.mention)
        embed.add_field(name="Membres", value=f"{len(guild_data.get('members', []))}/{max_members}")
        embed.add_field(name="XP Hebdomadaire", value=f"{guild_data.get('weekly_xp', 0)} XP")
        embed.set_footer(text=f"Créée le {discord.utils.format_dt(created_dt, style='D')}")

        members_list = []
        for member_id in guild_data.get('members', []):
            member = interaction.guild.get_member(int(member_id))
            members_list.append(member.display_name if member else "Utilisateur parti")
        
        embed.add_field(name="Liste des Membres", value="• " + "\n• ".join(members_list), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @guild_group.command(name="inviter", description="Invite un membre à rejoindre votre guilde.")
    @app_commands.describe(membre="Le membre à inviter.")
    async def inviter(self, interaction: discord.Interaction, membre: discord.Member):
        if membre.bot or membre.id == interaction.user.id:
            return await interaction.response.send_message("❌ Vous ne pouvez pas vous inviter vous-même ou un bot.", ephemeral=True)

        user_ref = self.manager.db.collection('users').document(str(interaction.user.id))
        user_data = (await user_ref.get()).to_dict()
        guild_id = user_data.get("guild_id")
        
        if not guild_id:
            return await interaction.response.send_message("❌ Vous devez être dans une guilde pour inviter.", ephemeral=True)
            
        guild_ref = self.manager.db.collection('guilds').document(guild_id)
        guild_data = (await guild_ref.get()).to_dict()
        
        max_members = self.manager.config.get("GUILD_SYSTEM", {}).get("MAX_MEMBERS", 10)
        if len(guild_data.get('members', [])) >= max_members:
             return await interaction.response.send_message(f"❌ Votre guilde est pleine.", ephemeral=True)
             
        try:
            embed = discord.Embed(
                title=f"🛡️ Invitation de Guilde",
                description=f"{interaction.user.mention} vous invite à rejoindre la guilde **{guild_data['name']}** !",
                color=discord.Color.from_str(guild_data['color'])
            )
            view = GuildInviteView(self.manager, guild_id, guild_data['name'], interaction.user)
            await membre.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Invitation envoyée à {membre.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Impossible d'envoyer un message privé à {membre.mention}. L'utilisateur a peut-être bloqué ses MPs.", ephemeral=True)
    
    @guild_group.command(name="quitter", description="Quitte votre guilde actuelle.")
    async def quitter(self, interaction: discord.Interaction):
        user_ref = self.manager.db.collection('users').document(str(interaction.user.id))
        user_data = (await user_ref.get()).to_dict()
        guild_id = user_data.get("guild_id")
        
        if not guild_id:
            return await interaction.response.send_message("❌ Vous n'êtes dans aucune guilde.", ephemeral=True)

        guild_ref = self.manager.db.collection('guilds').document(guild_id)
        guild_data = (await guild_ref.get()).to_dict()

        if guild_data["owner_id"] == str(interaction.user.id):
            return await interaction.response.send_message("❌ Le chef ne peut pas quitter. Promouvez quelqu'un ou dissolvez la guilde.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        role = interaction.guild.get_role(guild_data["role_id"])
        if role: await interaction.user.remove_roles(role)
        
        await user_ref.update({"guild_id": None, "guild_bonus": firestore.DELETE_FIELD})
        await guild_ref.update({"members": firestore.ArrayRemove([str(interaction.user.id)])})
        
        await interaction.followup.send(f"✅ Vous avez quitté la guilde **{guild_data['name']}**.", ephemeral=True)

    @guild_group.command(name="dissoudre", description="Dissout votre guilde (action irréversible).")
    async def dissoudre(self, interaction: discord.Interaction):
        user_ref = self.manager.db.collection('users').document(str(interaction.user.id))
        user_data = (await user_ref.get()).to_dict()
        guild_id = user_data.get("guild_id")

        if not guild_id:
            return await interaction.response.send_message("❌ Vous n'êtes dans aucune guilde.", ephemeral=True)

        guild_ref = self.manager.db.collection('guilds').document(guild_id)
        guild_data = (await guild_ref.get()).to_dict()

        if guild_data["owner_id"] != str(interaction.user.id):
            return await interaction.response.send_message("❌ Seul le chef de guilde peut la dissoudre.", ephemeral=True)
            
        view = GuildDissolveView(self, guild_id)
        await interaction.response.send_message(
            f"Êtes-vous sûr de vouloir dissoudre la guilde **{guild_data['name']}** ? Cette action est **IRRÉVERSIBLE** et supprimera le rôle et les salons associés.",
            view=view,
            ephemeral=True
        )

    async def execute_dissolve(self, interaction: discord.Interaction, guild_id: str):
        guild_ref = self.manager.db.collection('guilds').document(guild_id)
        guild_data = (await guild_ref.get()).to_dict()

        # Delete Discord assets
        role = interaction.guild.get_role(guild_data.get('role_id', 0))
        if role: await role.delete()
        
        txt_chan = interaction.guild.get_channel(guild_data.get('text_channel_id', 0))
        if txt_chan: await txt_chan.delete()
        
        vc_chan = interaction.guild.get_channel(guild_data.get('voice_channel_id', 0))
        if vc_chan: await vc_chan.delete()
        
        # Update users
        for member_id_str in guild_data.get('members', []):
            member_ref = self.manager.db.collection('users').document(member_id_str)
            await member_ref.update({'guild_id': None, 'guild_bonus': firestore.DELETE_FIELD})
            
        # Delete guild doc
        await guild_ref.delete()
        
        await interaction.followup.send(f"✅ La guilde **{guild_data['name']}** a été dissoute.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildCog(bot))