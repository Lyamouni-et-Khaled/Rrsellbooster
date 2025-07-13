

import discord
from discord.ext import commands, tasks
from discord import app_commands
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from google.cloud import firestore

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

class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager: Optional[ManagerCog] = None

    async def cog_load(self):
        self.manager = self.bot.get_cog('ManagerCog')
        if not self.manager or not self.manager.db:
            return print("ERREUR CRITIQUE: EventsCog n'a pas pu trouver le ManagerCog ou la BDD.")
        
        self.check_expired_events.start()
        print("✅ EventsCog chargé.")
        
    def cog_unload(self):
        self.check_expired_events.cancel()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Vérifie si l'utilisateur est l'administrateur défini dans la config."""
        admin_id = self.manager.config.get("ADMIN_USER_ID")
        if not admin_id or str(interaction.user.id) != admin_id:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return False
        return True

    event_group = app_commands.Group(name="event", description="Gère les événements spéciaux du serveur.")

    @event_group.command(name="start", description="Démarre un événement serveur pour une durée limitée.")
    @app_commands.describe(type="Le type d'événement à démarrer.", duree="La durée de l'événement (ex: 2d, 8h, 45m).")
    @app_commands.choices(type=[
        app_commands.Choice(name="Double XP", value="double_xp"),
        app_commands.Choice(name="Bonus Commission (+10%)", value="commission_boost_10")
    ])
    async def start(self, interaction: discord.Interaction, type: app_commands.Choice[str], duree: str):
        if not self.manager: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        duration = parse_duration(duree)
        if not duration:
            return await interaction.response.send_message("Format de durée invalide. Ex: `2d`, `8h`, `45m`.", ephemeral=True)
            
        event_config_list = self.manager.config.get("EVENTS_CONFIG", {}).get("AVAILABLE_EVENTS", [])
        event_config = next((e for e in event_config_list if e["id"] == type.value), None)

        if not event_config:
             return await interaction.response.send_message("Type d'événement non trouvé dans la configuration.", ephemeral=True)

        if type.value in self.manager.active_events:
            return await interaction.response.send_message(f"L'événement `{event_config['name']}` est déjà en cours.", ephemeral=True)

        end_time = datetime.now(timezone.utc) + duration
        event_data = {
            "name": event_config["name"],
            "ends_at": end_time.isoformat(),
            **event_config
        }
        
        # Update in-memory cache and Firestore
        self.manager.active_events[type.value] = event_data
        await self.manager.db.collection('system').document('events').set({'active': self.manager.active_events}, merge=True)
        
        announce_channel_name = self.manager.config["CHANNELS"].get("ANNOUNCEMENTS")
        channel = discord.utils.get(interaction.guild.text_channels, name=announce_channel_name)
        if channel:
            embed = discord.Embed(title=f"🎉 Événement Serveur Activé : {event_config['name']} ! 🎉",
                                  description=f"Profitez de cet avantage exceptionnel jusqu'au <t:{int(end_time.timestamp())}:F> (<t:{int(end_time.timestamp())}:R>) !",
                                  color=discord.Color.gold())
            await channel.send(embed=embed)
        
        await interaction.response.send_message(f"✅ L'événement `{event_config['name']}` a été démarré pour une durée de `{duree}`.", ephemeral=True)

    @event_group.command(name="stop", description="Arrête manuellement un événement serveur.")
    @app_commands.describe(type="L'événement à arrêter.")
    @app_commands.choices(type=[
        app_commands.Choice(name="Double XP", value="double_xp"),
        app_commands.Choice(name="Bonus Commission (+10%)", value="commission_boost_10")
    ])
    async def stop(self, interaction: discord.Interaction, type: app_commands.Choice[str]):
        if not self.manager: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        if type.value not in self.manager.active_events:
            return await interaction.response.send_message(f"L'événement `{type.name}` n'est pas en cours.", ephemeral=True)
        
        event_name = self.manager.active_events[type.value]['name']
        del self.manager.active_events[type.value]
        await self.manager.db.collection('system').document('events').set({'active': self.manager.active_events})
            
        await interaction.response.send_message(f"✅ L'événement `{event_name}` a été arrêté manuellement.", ephemeral=True)
    
    @event_group.command(name="status", description="Affiche les événements serveur actuellement en cours.")
    async def status(self, interaction: discord.Interaction):
        if not self.manager: return await interaction.response.send_message("Erreur interne.", ephemeral=True)
        
        if not self.manager.active_events:
             return await interaction.response.send_message("Aucun événement n'est en cours.", ephemeral=True)

        embed = discord.Embed(title="Statut des Événements Serveur", color=discord.Color.blue())
        for event_id, event_data in self.manager.active_events.items():
            ends_at_dt = datetime.fromisoformat(event_data['ends_at'])
            embed.add_field(name=event_data['name'], value=f"Se termine <t:{int(ends_at_dt.timestamp())}:R>", inline=False)
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(minutes=1)
    async def check_expired_events(self):
        if not self.manager: return
        now = datetime.now(timezone.utc)
        expired_events_detected = False
        
        active_events_copy = self.manager.active_events.copy()
        for event_id, event_data in active_events_copy.items():
            ends_at = datetime.fromisoformat(event_data['ends_at'])
            if now >= ends_at:
                del self.manager.active_events[event_id]
                expired_events_detected = True
        
        if expired_events_detected:
            print(f"Événements expirés détectés et retirés de la mémoire.")
            await self.manager.db.collection('system').document('events').set({'active': self.manager.active_events})
    
    @check_expired_events.before_loop
    async def before_check_events(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
