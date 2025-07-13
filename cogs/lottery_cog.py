
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random
from google.cloud import firestore
from google.cloud.firestore_v1.async_client import async_transactional

from .manager_cog import ManagerCog

class LotteryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None
        self.lottery_ref: Optional[firestore.AsyncDocumentReference] = None

    async def cog_load(self):
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager or not self.manager.db:
            return print("ERREUR CRITIQUE: LotteryCog n'a pas pu trouver le ManagerCog ou la BDD.")
        self.lottery_ref = self.manager.db.collection('system').document('lottery')
        print("✅ LotteryCog chargé.")

    async def _join_lottery_transaction(self, user_id_str: str, display_name: str, cost: float):
        """Transactional logic for joining the lottery."""
        @async_transactional
        async def tx_logic(transaction: firestore.AsyncTransaction):
            user_ref = self.manager.db.collection('users').document(user_id_str)
            user_data = (await user_ref.get(transaction=transaction)).to_dict()

            if user_data.get("store_credit", 0.0) < cost:
                return {"success": False, "reason": "crédits insuffisants"}
                
            lottery_doc = await self.lottery_ref.get(transaction=transaction)
            lottery_pot = lottery_doc.to_dict().get('pot', []) if lottery_doc.exists else []

            if any(p['id'] == user_id_str for p in lottery_pot):
                return {"success": False, "reason": "déjà participant"}

            lottery_pot.append({"id": user_id_str, "name": display_name})
            transaction.set(self.lottery_ref, {'pot': lottery_pot}, merge=True)
            await self.manager.add_transaction(transaction, user_ref, "store_credit", -cost, "Participation à la loterie")
            
            return {"success": True, "new_pot": lottery_pot}

        return await tx_logic(self.manager.db.transaction())

    async def _trigger_draw(self, interaction_or_channel: any, lottery_pot: list, config: dict):
        """Triggers the draw, announces winner, and resets the pot."""
        winner_data = random.choice(lottery_pot)
        winner_id = winner_data['id']
        prize = config.get("WINNER_PRIZE", 0.70)
        
        winner_ref = self.manager.db.collection('users').document(winner_id)
        await self.manager.add_transaction(self.manager.db.transaction(), winner_ref, "store_credit", prize, "Gagnant de la loterie")

        lottery_channel_name = self.manager.config["CHANNELS"].get("LOTTERY")
        channel = discord.utils.get(interaction_or_channel.guild.text_channels, name=lottery_channel_name)
        
        participant_mentions = [f"<@{p['id']}>" for p in lottery_pot]
        
        if channel:
            embed = discord.Embed(
                title="🎉 Tirage de la Loterie ! 🎉",
                description=f"Le pot est plein ! Le tirage a été effectué parmi les participants : {', '.join(participant_mentions)}",
                color=discord.Color.gold()
            )
            embed.add_field(name="🏆 Gagnant 🏆", value=f"<@{winner_id}> remporte **{prize:.2f} crédits** !", inline=False)
            await channel.send(embed=embed)
        
        await self.lottery_ref.set({'pot': []})

    async def handle_lottery_join(self, interaction: discord.Interaction, cost: float):
        """Reusable logic for joining the lottery, callable from commands or views."""
        config = self.manager.config.get("LOTTERY_CONFIG", {})
        
        result = await self._join_lottery_transaction(
            user_id_str=str(interaction.user.id),
            display_name=interaction.user.display_name,
            cost=cost
        )

        if not result["success"]:
            message = ""
            if result["reason"] == "crédits insuffisants":
                message = f"Il vous faut **{cost:.2f} crédits** pour participer."
            elif result["reason"] == "déjà participant":
                message = "Vous êtes déjà dans le pot pour ce tour !"
            else:
                message = "Une erreur est survenue."
            
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        lottery_pot = result["new_pot"]
        pot_size = len(lottery_pot)
        required_size = config.get("PLAYERS_PER_ROUND", 3)
        
        if pot_size < required_size:
            message = f"Vous avez rejoint la loterie pour **{cost:.2f} crédits** ! Il manque **{required_size - pot_size}** joueur(s) pour le tirage."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        else:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await self._trigger_draw(interaction, lottery_pot, config)
            await interaction.followup.send("Le tirage de la loterie a eu lieu ! Consultez le salon dédié.", ephemeral=True)

    @app_commands.command(name="loterie", description="Participe à la loterie pour tenter de gagner des crédits.")
    async def lottery(self, interaction: discord.Interaction):
        if not self.manager: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        config = self.manager.config.get("LOTTERY_CONFIG", {})
        if not config.get("ENABLED", False):
            return await interaction.response.send_message("Le système de loterie est désactivé.", ephemeral=True)

        cost = config.get("TICKET_COST", 0.25)
        await self.handle_lottery_join(interaction, cost)

async def setup(bot: commands.Bot):
    await bot.add_cog(LotteryCog(bot))