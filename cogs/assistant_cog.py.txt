
import discord
from discord.ext import commands
import json
import os
from typing import Dict, Any, Optional
import re

# Importation de ManagerCog pour l'autocomplétion
from .manager_cog import ManagerCog

# Importation de la librairie Gemini
try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

class AssistantCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None
        self.model: Optional[genai.GenerativeModel] = None

    async def cog_load(self):
        # Cette méthode est appelée lors du chargement du cog.
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager:
            return print("ERREUR CRITIQUE: AssistantCog n'a pas pu trouver le ManagerCog.")
        
        if AI_AVAILABLE and self.manager.model:
            self.model = self.manager.model
            print("✅ Assistant Cog: Modèle Gemini partagé par ManagerCog chargé.")
        else:
            print("⚠️ ATTENTION: AssistantCog désactivé car aucun modèle AI n'est disponible.")
            
    async def query_gemini_for_answer(self, question: str) -> Optional[Dict[str, Any]]:
        if not self.model or not self.manager:
            return None

        knowledge_base_str = json.dumps(self.manager.knowledge_base.get("faqs", []))
        products_list_str = json.dumps([{'id': p.get('id'), 'name': p.get('name'), 'category': p.get('category')} for p in self.manager.products])

        prompt = f"""
        Tu es "ResellBoost Assistant", un support IA pour le serveur Discord "ResellBoost". Ta mission est de répondre aux questions des utilisateurs en te basant sur les informations fournies.
        
        Question de l'utilisateur: "{question}"

        Base de connaissances (FAQs):
        {knowledge_base_str}

        Liste des produits disponibles (pour référence, ne donne pas les prix):
        {products_list_str}

        Instructions:
        1. Analyse la question de l'utilisateur.
        2. Si la réponse se trouve dans la base de connaissances, formule une réponse claire et amicale.
        3. Si la question est d'ordre personnel (problème de paiement, de compte) ou si tu ne trouves pas de réponse, escalade en suggérant de créer un ticket.
        4. Si un produit du catalogue est pertinent pour la question, mentionne-le par son nom.
        5. Termine toujours ta réponse par une suggestion de question de suivi naturelle.

        Tu DOIS répondre au format JSON suivant. Ne mets rien d'autre que le JSON dans ta réponse.
        {{
          "response_type": "answer" | "escalate",
          "content": "Ton texte de réponse ici. Pour une escalade, guide l'utilisateur vers la création d'un ticket avec la commande /ticket.",
          "suggested_follow_up": "Une suggestion de question de suivi pertinente" | null
        }}
        """
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
            print(f"Erreur Gemini (Assistant): {e}")
            return {"response_type": "escalate", "content": "Désolé, une erreur technique est survenue lors de l'analyse de votre question.", "suggested_follow_up": "Puis-je vous aider avec autre chose ?"}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.manager or not self.manager.config.get("ASSISTANT_CONFIG", {}).get("ENABLED", False):
            return
        
        assistant_config = self.manager.config.get("ASSISTANT_CONFIG", {})
        monitored_channels = self.manager.config.get("CHANNELS", {}).get("ASSISTANT_MONITORED", [])
        
        is_monitored_channel = message.channel.name in monitored_channels
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.bot.user.mentioned_in(message)
        
        triggered = is_dm or is_mention
        if not triggered and is_monitored_channel:
            if any(keyword in message.content.lower() for keyword in assistant_config.get("PASSIVE_KEYWORDS", [])):
                triggered = True

        if triggered:
            question = re.sub(r'<@!?\d+>', '', message.content).strip()
            if not question: return
            
            async with message.channel.typing():
                response_data = await self.query_gemini_for_answer(question)
            
            if response_data:
                await self.handle_ia_response(message, response_data)

    async def handle_ia_response(self, message: discord.Message, response_data: Dict[str, Any]):
        response_type = response_data.get("response_type")
        content = response_data.get("content", "Désolé, je n'ai pas de réponse à cela.")
        follow_up = response_data.get("suggested_follow_up")
        
        embed = discord.Embed()
        
        if response_type == "answer":
            embed.title = "💡 Assistant ResellBoost"
            embed.color = discord.Color.blue()
        else: # escalate
            embed.title = "🤔 Une aide humaine est peut-être nécessaire"
            embed.color = discord.Color.orange()
            
        embed.description = content
        if follow_up:
            embed.set_footer(text=f"Suggestion : {follow_up}")
        
        await message.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(AssistantCog(bot))