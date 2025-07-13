



import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import os
import re
import uuid

# Importation de ManagerCog pour l'autocomplétion
from .manager_cog import ManagerCog
from .catalogue_cog import PurchasePromoView
from google.cloud import firestore
from google.cloud.firestore_v1.transaction import async_transactional

# Importation de la librairie Gemini
try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

class ModeratorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None
        self.model: Optional[genai.GenerativeModel] = None

    async def cog_load(self):
        # Cette méthode est appelée lors du chargement du cog.
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager:
            return print("ERREUR CRITIQUE: ModeratorCog n'a pas pu trouver le ManagerCog.")
        
        if AI_AVAILABLE and self.manager.model:
            self.model = self.manager.model
            print("✅ Moderator Cog: Modèle Gemini partagé par ManagerCog chargé.")
        else:
            print("⚠️ ATTENTION: ModeratorCog désactivé car aucun modèle AI n'est disponible.")

    async def query_gemini_moderation(self, message: discord.Message) -> Optional[Dict[str, Any]]:
        if not self.model or not self.manager: return None
        
        mod_config = self.manager.config.get("MODERATION_CONFIG", {})
        prompt_template = mod_config.get("AI_MODERATION_PROMPT")
        if not prompt_template:
             print("ATTENTION: Le prompt de modération IA est manquant dans config.json")
             return {"action": "PASS", "reason": "Configuration IA manquante."}
             
        prompt = prompt_template.format(
            user_message=message.content,
            channel_name=message.channel.name
        )

        try:
            generation_config = GenerationConfig(
                response_mime_type="application/json"
            )
            response = await self.model.generate_content_async(
                contents=prompt,
                generation_config=generation_config
            )
            return await self.manager._parse_gemini_json_response(response.text)
        except Exception as e:
            print(f"Erreur Gemini (Modération): {e}")
            return {"action": "PASS", "reason": f"Erreur d'analyse IA."}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not self.manager: return

        mod_config = self.manager.config.get("MODERATION_CONFIG", {})
        if not mod_config.get("ENABLED", False):
            return
        
        # Ignorer les canaux où la promotion est autorisée
        promo_channels = [
            self.manager.config.get("CHANNELS", {}).get("PUBLIC_PROMO"),
            self.manager.config.get("CHANNELS", {}).get("MARKETPLACE"),
            self.manager.config.get("CHANNELS", {}).get("PROMO_FLASH")
        ]
        if message.channel.name in promo_channels:
            return

        # Ignorer le staff
        staff_role_names = self.manager.config.get("ROLES", {}).get("STAFF", [])
        author_roles = [role.name for role in message.author.roles]
        if any(role_name in author_roles for role_name in staff_role_names):
            return

        result = await self.query_gemini_moderation(message)
        if not result: return
        
        action = result.get("action", "PASS")
        reason = result.get("reason", "Aucune raison spécifiée.")

        if action == "PASS": return
        
        action_handlers = {
            "DELETE_AND_WARN": self.handle_delete_and_warn,
            "WARN": self.handle_warn,
            "NOTIFY_STAFF": self.handle_notify_staff,
            "CREATE_SUPPORT_TICKET": self.handle_create_support_ticket
        }
        
        handler = action_handlers.get(action)
        if handler:
            await handler(message, reason)
        else:
            print(f"Action de modération IA non reconnue: {action}")
            await self.handle_notify_staff(message, f"Action IA non reconnue: `{action}`. Raison: `{reason}`")


    async def handle_delete_and_warn(self, message: discord.Message, reason: str):
        try: await message.delete()
        except discord.NotFound: pass
        await self.apply_warning(message.author, reason, message.jump_url, is_dm=True)

    async def handle_warn(self, message: discord.Message, reason: str):
        await self.apply_warning(message.author, reason, message.jump_url, is_dm=True)
        try:
            await message.add_reaction("⚠️")
        except discord.Forbidden:
            pass # Can't add reaction, not critical

    async def handle_notify_staff(self, message: discord.Message, reason: str):
        await self.notify_staff(message.guild, f"Alerte de Modération IA", f"Raison : {reason}\nMessage de {message.author.mention}: [cliquer ici]({message.jump_url})")

    async def handle_create_support_ticket(self, message: discord.Message, reason: str):
        if not self.manager: return
        
        ticket_types = self.manager.config.get("TICKET_SYSTEM", {}).get("TICKET_TYPES", [])
        ticket_type = next((tt for tt in ticket_types if "Signaler" in tt["label"]), ticket_types[0] if ticket_types else None)
        
        if ticket_type:
            embed = discord.Embed(title=f"Ticket : {ticket_type['label']}", description=f"Ticket créé automatiquement par IA pour {message.author.mention}.\n\n**Raison IA :** {reason}\n**Message original :**\n> {message.content}", color=discord.Color.orange())
            ticket_channel = await self.manager.create_ticket(message.author, message.guild, ticket_type, embed=embed)
            if ticket_channel:
                await message.reply(f"{message.author.mention}, un ticket de support a été automatiquement créé pour vous. Rendez-vous dans {ticket_channel.mention}.", delete_after=20)
        else:
            await self.notify_staff(message.guild, "L'IA a tenté de créer un ticket, mais aucun type de ticket pour signalement n'est configuré.", f"Message original : [cliquer ici]({message.jump_url})")

    async def notify_staff(self, guild: discord.Guild, title: str, description: str):
        if not self.manager: return
        channel_name = self.manager.config.get("CHANNELS", {}).get("MOD_ALERTS")
        if not channel_name: return
        mod_channel = discord.utils.get(guild.text_channels, name=channel_name)
        if mod_channel:
            embed = discord.Embed(title=f"🚨 {title}", description=description, color=discord.Color.orange())
            await mod_channel.send(embed=embed)

    async def apply_warning(self, member: discord.Member, reason: str, jump_url: str, is_dm: bool = True):
        if not self.manager or not self.manager.db: return
        user_ref = self.manager.db.collection('users').document(str(member.id))
        
        @async_transactional
        async def increment_warning(transaction, ref):
            user_doc = await ref.get(transaction=transaction)
            if not user_doc.exists:
                await self.manager.get_or_create_user_data(ref)
                user_doc = await ref.get(transaction=transaction)

            user_data = user_doc.to_dict()
            new_warning_count = user_data.get('warnings', 0) + 1
            transaction.update(ref, {'warnings': new_warning_count})
            return new_warning_count

        warning_count = await increment_warning(self.manager.db.transaction(), user_ref)
        
        threshold = self.manager.config.get("MODERATION_CONFIG", {}).get("WARNING_THRESHOLD", 3)

        if is_dm:
            try:
                await member.send(f"Vous avez reçu un avertissement sur le serveur **{member.guild.name}** pour la raison suivante : **{reason}**. C'est votre avertissement n°{warning_count}.")
            except discord.Forbidden:
                pass 

        await self.notify_staff(member.guild, f"Avertissement appliqué à {member.mention}", f"Raison : {reason}\nTotal d'avertissements : **{warning_count}/{threshold}**\n[Lien vers le message]({jump_url})")
        
        if warning_count >= threshold:
            try:
                await member.timeout(timedelta(days=1), reason=f"Seuil d'avertissement ({threshold}) atteint.")
                await self.notify_staff(member.guild, f"Seuil d'avertissement atteint pour {member.mention}", "L'utilisateur a été mis en silencieux pour 24h.")
                await user_ref.update({'warnings': 0})
            except discord.Forbidden:
                 await self.notify_staff(member.guild, f"ERREUR: Tentative de Mute sur {member.mention} a échoué (permissions).", "Seuil d'avertissement atteint.")

    promo = app_commands.Group(name="promo", description="[Admin] Commandes pour gérer les promotions flash.", default_permissions=discord.Permissions(administrator=True))

    @promo.command(name="creer", description="Créer une promotion flash avec une description améliorée par IA.")
    @app_commands.describe(
        nom="Le nom du produit en promotion.",
        description_courte="Une description brève que l'IA va améliorer.",
        prix="Le prix de vente final en euros.",
        prix_achat="Le coût d'achat pour vous (pour le calcul de la marge d'affiliation)."
    )
    async def promo_creer(self, interaction: discord.Interaction, nom: str, description_courte: str, prix: float, prix_achat: float):
        if not self.manager or not self.manager.model:
            return await interaction.response.send_message("Le module IA n'est pas disponible.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # 1. Generate description with AI
        generated_desc = await self.manager.query_gemini_for_promo(nom, description_courte)

        # 2. Store promo data in Firestore
        promo_id = str(uuid.uuid4())
        promo_data = {
            "name": nom,
            "description": generated_desc,
            "price": prix,
            "purchase_cost": prix_achat,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await self.manager.db.collection('active_promos').document(promo_id).set(promo_data)

        # 3. Create Embed
        embed = discord.Embed(
            title=f"⚡ PROMOTION FLASH : {nom} ⚡",
            description=generated_desc,
            color=discord.Color.from_str("#f59e0b") # Gold color
        )
        embed.add_field(name="Prix Exceptionnel", value=f"**{prix:.2f} €**", inline=True)
        embed.add_field(name="Disponibilité", value="Offre à durée limitée !", inline=True)
        embed.set_footer(text=f"Cliquez sur le bouton ci-dessous pour en profiter !\nID de l'Offre: {promo_id}")
        
        # 4. Send to promo channel
        promo_channel_name = self.manager.config["CHANNELS"].get("PROMO_FLASH")
        promo_channel = discord.utils.get(interaction.guild.text_channels, name=promo_channel_name)

        if not promo_channel:
            return await interaction.followup.send(f"Le canal de promotion `{promo_channel_name}` est introuvable.", ephemeral=True)
        
        view = PurchasePromoView(self.manager)
        await promo_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ La promotion a été publiée dans {promo_channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModeratorCog(bot))
