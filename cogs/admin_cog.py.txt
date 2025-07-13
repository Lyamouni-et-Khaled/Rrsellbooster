import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from .manager_cog import ManagerCog, VerificationView, TicketCreationView, MissionView

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None

    async def cog_load(self):
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager:
            return print("ERREUR CRITIQUE: AdminCog n'a pas pu trouver le ManagerCog.")
        print("✅ AdminCog chargé.")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie si l'utilisateur est l'administrateur défini dans la config."""
        admin_id = self.manager.config.get("ADMIN_USER_ID")
        if not admin_id or str(interaction.user.id) != admin_id:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return False
        return True

    # --- Groupe de commandes /admin ---
    admin_group = app_commands.Group(name="admin", description="Commandes de gestion des utilisateurs réservées à l'administrateur.")

    @admin_group.command(name="grant-credits", description="Accorde des crédits à un membre.")
    @app_commands.describe(membre="Le membre à qui donner des crédits.", montant="Le nombre de crédits à donner.", raison="La raison de cet octroi.")
    async def grant_credits(self, interaction: discord.Interaction, membre: discord.Member, montant: float, raison: str):
        if not self.manager or not self.manager.db: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        user_ref = self.manager.db.collection('users').document(str(membre.id))
        
        transaction = self.manager.db.transaction()
        await self.manager.add_transaction(transaction, user_ref, "store_credit", montant, f"Octroi Admin : {raison}")

        user_data = (await user_ref.get()).to_dict()
        current_credits = user_data.get("store_credit", 0.0)

        await interaction.response.send_message(f"✅ **{montant:.2f} crédits** ont été accordés à {membre.mention}. Nouveau solde : **{current_credits:.2f} crédits**.", ephemeral=True)
        try:
            await membre.send(f"🎉 Un administrateur vous a accordé **{montant:.2f} crédits** ! Raison : {raison}")
        except discord.Forbidden:
            pass

    @admin_group.command(name="grant-xp", description="Accorde de l'XP à un membre.")
    @app_commands.describe(membre="Le membre à qui donner de l'XP.", montant="La quantité d'XP à donner.", raison="La raison de cet octroi.")
    async def grant_xp(self, interaction: discord.Interaction, membre: discord.Member, montant: int, raison: str):
        if not self.manager: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        await self.manager.grant_xp(membre, montant, f"Octroi Admin : {raison}")
        
        await interaction.response.send_message(f"✅ **{montant} XP** ont été accordés à {membre.mention}.", ephemeral=True)
        try:
            await membre.send(f"🌟 Un administrateur vous a accordé **{montant} XP** ! Raison : {raison}")
        except discord.Forbidden:
            pass
            
    @admin_group.command(name="check-user", description="Affiche les données d'un utilisateur.")
    @app_commands.describe(membre="L'utilisateur à inspecter.")
    async def check_user(self, interaction: discord.Interaction, membre: discord.Member):
        if not self.manager or not self.manager.db: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        user_ref = self.manager.db.collection('users').document(str(membre.id))
        user_data = (await user_ref.get()).to_dict()

        if not user_data:
            return await interaction.response.send_message("Aucune donnée trouvée pour cet utilisateur.", ephemeral=True)

        embed = discord.Embed(title=f"🔍 Inspection de {membre.display_name}", color=membre.color)
        embed.set_thumbnail(url=membre.display_avatar.url)
        embed.set_footer(text=f"ID: {membre.id}")

        embed.add_field(name="Niveau", value=f"{user_data.get('level', 1)}", inline=True)
        embed.add_field(name="XP", value=f"{user_data.get('xp', 0)}", inline=True)
        embed.add_field(name="Crédits", value=f"{user_data.get('store_credit', 0.0):.2f}", inline=True)
        
        referrer_id = user_data.get('referrer')
        referrer_text = "Aucun"
        if referrer_id:
            try:
                referrer_user = await self.bot.fetch_user(int(referrer_id))
                referrer_text = f"{referrer_user.mention} (`{referrer_id}`)"
            except (discord.NotFound, ValueError):
                referrer_text = f"ID Invalide (`{referrer_id}`)"
        embed.add_field(name="Parrain", value=referrer_text, inline=True)

        guild_id = user_data.get("guild_id")
        guild_text = "Aucune"
        if guild_id:
            guild_doc = await self.manager.db.collection('guilds').document(guild_id).get()
            guild_data = guild_doc.to_dict()
            guild_text = guild_data.get('name', f"ID: {guild_id}") if guild_data else "Guilde Invalide"
        embed.add_field(name="Guilde", value=guild_text, inline=True)

        embed.add_field(name="Avertissements", value=f"{user_data.get('warnings', 0)}", inline=True)

        transaction_log = user_data.get("transaction_log", [])
        if transaction_log:
            log_text = "\n".join([f"`{entry['type']}`: {entry['amount']}" for entry in transaction_log[-5:]])
            embed.add_field(name="5 Dernières Transactions", value=log_text, inline=False)
        else:
            embed.add_field(name="Transactions", value="Aucune transaction enregistrée.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Groupe de commandes /setup ---
    setup_group = app_commands.Group(name="setup", description="Commandes de configuration initiale du serveur.")

    @setup_group.command(name="reglement", description="Poste le message du règlement.")
    async def setup_reglement(self, interaction: discord.Interaction):
        config = self.manager.config.get("SERVER_RULES")
        channel_name = self.manager.config["CHANNELS"].get("RULES")
        if not config or not channel_name:
            return await interaction.response.send_message("Configuration `SERVER_RULES` ou `CHANNELS.RULES` manquante.", ephemeral=True)
        
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            return await interaction.response.send_message(f"Le salon `{channel_name}` est introuvable.", ephemeral=True)

        embed = discord.Embed(title=config["TITLE"], description=config["INTRODUCTION"], color=discord.Color.orange())
        embed.add_field(name="\u200b", value="\n\n".join(config["RULES_LIST"]), inline=False)
        embed.set_footer(text=config["CONCLUSION"])

        await channel.purge(limit=10)
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Message du règlement posté dans {channel.mention}.", ephemeral=True)

    @setup_group.command(name="verification", description="Poste le message de vérification.")
    async def setup_verification(self, interaction: discord.Interaction):
        config = self.manager.config.get("VERIFICATION_SYSTEM")
        channel_name = self.manager.config["CHANNELS"].get("VERIFICATION")
        rules_channel_name = self.manager.config["CHANNELS"].get("RULES")
        
        if not all([config, channel_name, rules_channel_name]):
            return await interaction.response.send_message("Configuration incomplète pour le système de vérification.", ephemeral=True)

        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        rules_channel = discord.utils.get(interaction.guild.text_channels, name=rules_channel_name)

        if not channel:
            return await interaction.response.send_message(f"Le salon `{channel_name}` est introuvable.", ephemeral=True)
        
        description = config["WELCOME_MESSAGE_DESCRIPTION"].format(rules_channel=rules_channel.mention if rules_channel else f"#{rules_channel_name}")
        embed = discord.Embed(title=config["WELCOME_MESSAGE_TITLE"], description=description, color=discord.Color.green())
        
        view = VerificationView(self.manager)
        await channel.purge(limit=10)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Message de vérification posté dans {channel.mention}.", ephemeral=True)

    @setup_group.command(name="tickets", description="Poste le message pour la création de tickets.")
    async def setup_tickets(self, interaction: discord.Interaction):
        config = self.manager.config.get("TICKET_SYSTEM")
        channel_name = self.manager.config["CHANNELS"].get("TICKET_CREATION")
        if not config or not channel_name:
            return await interaction.response.send_message("Configuration `TICKET_SYSTEM` ou `CHANNELS.TICKET_CREATION` manquante.", ephemeral=True)
        
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            return await interaction.response.send_message(f"Le salon `{channel_name}` est introuvable.", ephemeral=True)

        embed = discord.Embed(
            title=config.get("TICKET_CREATION_MESSAGE_TITLE", "Support"),
            description=config.get("TICKET_CREATION_MESSAGE"),
            color=discord.Color.blue()
        )
        view = TicketCreationView(self.manager)

        await channel.purge(limit=10)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Panneau de création de tickets posté dans {channel.mention}.", ephemeral=True)

    @setup_group.command(name="gamification-info", description="Poste ou met à jour le message d'info sur la gamification.")
    async def setup_gamification_info(self, interaction: discord.Interaction):
        info_config = self.manager.config.get("GAMIFICATION_INFO_MESSAGE")
        if not info_config:
            return await interaction.response.send_message("❌ La section `GAMIFICATION_INFO_MESSAGE` est manquante dans `config.json`.", ephemeral=True)
        
        channel_name = self.manager.config["CHANNELS"].get("GAMIFICATION_INFO")
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            return await interaction.response.send_message(f"❌ Le salon `{channel_name}` est introuvable.", ephemeral=True)
            
        embed = discord.Embed(
            title=info_config.get("title", "Info Gamification"),
            description=info_config.get("description"),
            color=discord.Color.from_str(info_config.get("color", "#ffffff"))
        )
        for field in info_config.get("fields", []):
            embed.add_field(name=field.get("name"), value=field.get("value"), inline=field.get("inline", False))
        
        if "footer" in info_config:
            embed.set_footer(text=info_config.get("footer"))
            
        await channel.purge(limit=10) # Clean channel before posting
        await channel.send(embed=embed, view=MissionView(self.manager))
        await interaction.response.send_message(f"✅ Le message d'information a été posté dans {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))