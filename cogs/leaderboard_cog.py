

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Any
from google.cloud.firestore_v1.base_query import AsyncFieldFilter
from google.cloud import firestore

from .manager_cog import ManagerCog

class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None

    async def cog_load(self):
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager or not self.manager.db:
            return print("ERREUR CRITIQUE: LeaderboardCog n'a pas pu trouver le ManagerCog ou la BDD.")
        print("✅ LeaderboardCog chargé.")

    async def get_leaderboard_data(self, key: str, top_n: int = 10) -> List[Dict[str, Any]]:
        """Gets sorted leaderboard data from Firestore."""
        query = self.manager.db.collection('users').where(filter=AsyncFieldFilter(key, '>', 0)).order_by(key, direction=firestore.Query.DESCENDING).limit(top_n)
        docs = query.stream()
        
        sorted_users = [{"id": doc.id, "value": doc.to_dict().get(key, 0)} async for doc in docs]
        return sorted_users

    async def create_leaderboard_embed(self, interaction: discord.Interaction, leaderboard_type: str, data_key: str, unit: str = "") -> discord.Embed:
        """Creates a standardized embed for a leaderboard."""
        leaderboard_data = await self.get_leaderboard_data(data_key)
        
        embed = discord.Embed(
            title=f"🏆 Classement - {leaderboard_type} 🏆",
            description=f"Voici le top 10 des membres pour la catégorie '{leaderboard_type}'.",
            color=discord.Color.gold()
        )

        if not leaderboard_data:
            embed.description = "Personne n'est encore dans le classement pour cette catégorie."
            return embed

        leaderboard_text = ""
        for i, user_entry in enumerate(leaderboard_data):
            rank_emoji = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"**#{i+1}**")
            try:
                member = interaction.guild.get_member(int(user_entry['id']))
                member_name = member.display_name if member else f"Utilisateur Inconnu ({user_entry['id']})"
            except (ValueError, TypeError):
                member_name = f"Utilisateur Inconnu ({user_entry['id']})"

            value = user_entry['value']
            value_str = f"{value:,.0f}".replace(",", " ") if isinstance(value, (int, float)) and value == int(value) else f"{value:,.2f}".replace(",", " ")

            leaderboard_text += f"{rank_emoji} **{member_name}** - `{value_str}{unit}`\n"
        
        if leaderboard_text:
            embed.add_field(name="Top 10", value=leaderboard_text, inline=False)
        else:
            embed.description = "Le classement est actuellement vide."
            
        embed.set_footer(text=f"Classement mis à jour le {discord.utils.format_dt(interaction.created_at, style='f')}")
        
        return embed

    @app_commands.command(name="classement", description="Affiche les différents classements du serveur.")
    @app_commands.describe(categorie="La catégorie de classement à afficher.")
    @app_commands.choices(categorie=[
        app_commands.Choice(name="XP Total", value="xp"),
        app_commands.Choice(name="XP Hebdomadaire", value="weekly_xp"),
        app_commands.Choice(name="Crédits Boutique", value="store_credit"),
        app_commands.Choice(name="Gains d'Affiliation (Hebdo)", value="weekly_affiliate_earnings"),
        app_commands.Choice(name="Gains d'Affiliation (Total)", value="affiliate_earnings"),
    ])
    async def leaderboard(self, interaction: discord.Interaction, categorie: app_commands.Choice[str]):
        if not self.manager:
            return await interaction.response.send_message("Erreur interne.", ephemeral=True)

        await interaction.response.defer()
        
        embed = await self.create_leaderboard_embed(
            interaction=interaction,
            leaderboard_type=categorie.name,
            data_key=categorie.value,
            unit=" XP" if "xp" in categorie.value else " ©"
        )

        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
