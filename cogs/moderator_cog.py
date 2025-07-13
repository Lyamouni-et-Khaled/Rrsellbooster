





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
        
        ticket_types =