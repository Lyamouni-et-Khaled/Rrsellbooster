
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from datetime import datetime, timedelta, timezone
import random
from typing import Optional
import os
import asyncio
import re

# Importation de ManagerCog pour l'autocomplétion
from .manager_cog import ManagerCog

def parse_duration(duration_str: str) -> Optional[timedelta]:
    """Parses a duration string like '1d3h30m' into a timedelta object."""
    regex = re.compile(r'((?P<days>\d+)d)?((?P<hours>\d+)h)?((?P<minutes>\d+)m)?((?P<seconds>\d+)s)?')
    parts = regex.match(duration_str)
    if not parts:
        return None
    parts = parts.groupdict()
    time_params = {}
    for (name, param) in parts.items():
        if param:
            time_params[name] = int(param)
    if not time_params:
        return None
    return timedelta(**time_params)

class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None

    async def cog_load(self):
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager or not self.manager.db:
            return print("ERREUR CRITIQUE: GiveawayCog n'a pas pu trouver le ManagerCog ou la BDD.")
        
        self.check_giveaways.start()
        print("✅ GiveawayCog chargé et tâche de vérification démarrée.")

    def cog_unload(self):
        self.check_giveaways.cancel()
        print("GiveawayCog déchargé.")

    @app_commands.command(name="giveaway_start", description="[Admin] Lance un nouveau giveaway.")
    @app_commands.describe(duree="Durée du giveaway (ex: 7d, 12h, 30m).", gagnants="Nombre de gagnants.", prix="Le prix à gagner.")
    @app_commands.default_permissions(administrator=True)
    async def giveaway_start(self, interaction: discord.Interaction, duree: str, gagnants: app_commands.Range[int, 1, 25], prix: str):
        if not self.manager:
            return await interaction.response.send_message("Erreur interne.", ephemeral=True)
            
        duration = parse_duration(duree)
        if not duration:
            return await interaction.response.send_message("Format de durée invalide. Utilisez un format comme `7d`, `12h`, `30m` ou une combinaison comme `1d12h`.", ephemeral=True)

        end_time = datetime.now(timezone.utc) + duration
        end_timestamp = int(end_time.timestamp())

        channel_name = self.manager.config["CHANNELS"].get("GIVEAWAYS")
        if not channel_name:
            return await interaction.response.send_message("Le canal de giveaway n'est pas configuré.", ephemeral=True)
        
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            return await interaction.response.send_message(f"Le canal `{channel_name}` est introuvable.", ephemeral=True)

        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"**Prix :** {prix}",
            color=discord.Color.magenta()
        )
        embed.add_field(name="Fin du giveaway", value=f"<t:{end_timestamp}:R> (<t:{end_timestamp}:F>)", inline=False)
        embed.add_field(name="Gagnants", value=str(gagnants), inline=True)
        embed.set_footer(text=f"Réagissez avec 🎉 pour participer !")

        try:
            giveaway_msg = await channel.send(embed=embed)
            await giveaway_msg.add_reaction("🎉")
        except discord.Forbidden:
            return await interaction.response.send_message(f"Je n'ai pas la permission d'envoyer des messages ou d'ajouter des réactions dans {channel.mention}.", ephemeral=True)
        
        giveaway_data = {
            "end_time": end_time.isoformat(),
            "winner_count": gagnants,
            "prize": prix,
            "channel_id": channel.id,
            "guild_id": interaction.guild.id
        }
        await self.manager.db.collection('giveaways').document(str(giveaway_msg.id)).set(giveaway_data)
        
        await interaction.response.send_message(f"Giveaway lancé dans {channel.mention} !", ephemeral=True)

    @app_commands.command(name="giveaway_reroll", description="[Admin] Relance le tirage au sort pour un giveaway terminé.")
    @app_commands.describe(message_id="L'ID du message du giveaway.")
    @app_commands.default_permissions(administrator=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            msg_id_int = int(message_id)
            channel = interaction.channel 
            giveaway_msg = await channel.fetch_message(msg_id_int)
        except (ValueError, discord.NotFound, discord.Forbidden):
            return await interaction.followup.send("Impossible de trouver le message du giveaway. Assurez-vous d'utiliser la commande dans le bon canal avec un ID de message valide.", ephemeral=True)

        if not giveaway_msg.embeds:
            return await interaction.followup.send("Ce message n'est pas un message de giveaway.", ephemeral=True)

        reaction = discord.utils.get(giveaway_msg.reactions, emoji="🎉")
        if not reaction:
            return await interaction.followup.send("Aucune réaction de participation trouvée.", ephemeral=True)

        users = [user async for user in reaction.users() if not user.bot]
        if not users:
            return await interaction.followup.send("Personne n'a participé à ce giveaway.", ephemeral=True)

        winner = random.choice(users)
        
        await giveaway_msg.channel.send(f"🎉 Nouveau tirage ! Le nouveau gagnant est {winner.mention} ! Félicitations !")
        await interaction.followup.send("Le nouveau gagnant a été tiré au sort.", ephemeral=True)

    @tasks.loop(seconds=15)
    async def check_giveaways(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        
        ended_giveaways_query = self.manager.db.collection('giveaways').where(field_path='end_time', op_string='<=', value=now_iso)
        ended_giveaways_stream = ended_giveaways_query.stream()

        async for giveaway_doc in ended_giveaways_stream:
            await self.end_giveaway(giveaway_doc.id, giveaway_doc.to_dict())
            await giveaway_doc.reference.delete()

    async def end_giveaway(self, msg_id: str, data: dict):
        guild = self.bot.get_guild(data["guild_id"])
        if not guild: return
        
        channel = guild.get_channel(data["channel_id"])
        if not channel: return

        try:
            giveaway_msg = await channel.fetch_message(int(msg_id))
        except (discord.NotFound, discord.Forbidden):
            return

        reaction = discord.utils.get(giveaway_msg.reactions, emoji="🎉")
        users = [user async for user in reaction.users() if not user.bot] if reaction else []

        if not users:
            winners_text = "Personne n'a participé... 😢"
            await channel.send(f"Le giveaway pour **{data['prize']}** est terminé. {winners_text}")
        else:
            winner_count = min(data["winner_count"], len(users))
            winners = random.sample(users, winner_count)
            winners_mention = ", ".join([w.mention for w in winners])
            winners_text = f"Félicitations à {winners_mention} ! Vous avez gagné **{data['prize']}** !"
            await channel.send(winners_text)

        new_embed = giveaway_msg.embeds[0].copy()
        new_embed.title = "🎉 GIVEAWAY TERMINÉ 🎉"
        new_embed.description = f"**Prix :** {data['prize']}"
        new_embed.color = discord.Color.dark_grey()
        if users and 'winners' in locals():
            new_embed.add_field(name="Gagnant(s)", value=", ".join([w.display_name for w in winners]), inline=False)
        else:
            new_embed.add_field(name="Gagnant(s)", value="Aucun participant.", inline=False)
        
        # Clean up fields
        new_embed.clear_fields()
        new_embed.add_field(name="Gagnant(s)", value=new_embed.fields[0].value if new_embed.fields else "Aucun participant.", inline=False)
        
        await giveaway_msg.edit(embed=new_embed, view=None)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
