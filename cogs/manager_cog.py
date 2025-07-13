
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
import random
import math
import uuid
from typing import List, Dict, Any, Optional
import traceback
import re

# Dépendance pour la génération d'image
try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    import io
    IMAGING_AVAILABLE = True
except ImportError:
    IMAGING_AVAILABLE = False


# --- Configuration de l'IA Gemini ---
try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# --- Configuration de Firestore ---
try:
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_query import AsyncFieldFilter
    from google.cloud.firestore_v1.transaction import async_transactional
    FIRESTORE_AVAILABLE = True
except ImportError:
    FIRESTORE_AVAILABLE = False


# --- Classes pour les Vues d'Interaction ---

class MissionView(discord.ui.View):
    def __init__(self, manager: 'ManagerCog'):
        super().__init__(timeout=None)
        self.manager = manager
    
    @discord.ui.button(label="Activer/Désactiver les notifications de mission", style=discord.ButtonStyle.secondary, custom_id="toggle_mission_dms")
    async def toggle_dms(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id_str = str(interaction.user.id)
        user_ref = self.manager.db.collection('users').document(user_id_str)
        
        @async_transactional
        async def toggle_opt_in(transaction, ref):
            user_doc = await ref.get(transaction=transaction)
            user_data = user_doc.to_dict() if user_doc.exists else {}
            new_status = not user_data.get("missions_opt_in", True)
            transaction.set(ref, {"missions_opt_in": new_status}, merge=True)
            return new_status

        new_status = await toggle_opt_in(self.manager.db.transaction(), user_ref)
        
        status_text = "activées" if new_status else "désactivées"
        await interaction.response.send_message(f"Vos notifications de mission par message privé sont maintenant {status_text}.", ephemeral=True)


class ChallengeSubmissionModal(discord.ui.Modal, title="Soumission de Défi"):
    submission_text = discord.ui.TextInput(
        label="Décrivez comment vous avez complété le défi",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: J'ai aidé @utilisateur à configurer son compte en lui expliquant comment faire...",
        required=True
    )

    def __init__(self, manager: 'ManagerCog', challenge_type: str):
        super().__init__()
        self.manager = manager
        self.challenge_type = challenge_type

    async def on_submit(self, interaction: discord.Interaction):
        await self.manager.handle_challenge_submission(interaction, self.submission_text.value, self.challenge_type)

class CashoutModal(discord.ui.Modal, title="Demande de Retrait d'Argent"):
    amount = discord.ui.TextInput(label="Montant en crédit à retirer", placeholder="Ex: 10.50", required=True)
    paypal_email = discord.ui.TextInput(label="Votre email PayPal", placeholder="Ex: votre.email@example.com", style=discord.TextStyle.short, required=True)

    def __init__(self, manager: 'ManagerCog'):
        super().__init__()
        self.manager = manager

    async def on_submit(self, interaction: discord.Interaction):
        await self.manager.handle_cashout_submission(interaction, self.amount.value, self.paypal_email.value)

class CashoutRequestView(discord.ui.View):
    def __init__(self, manager: 'ManagerCog'):
        super().__init__(timeout=None)
        self.manager = manager

    async def _handle_action(self, interaction: discord.Interaction, approve: bool):
        await interaction.response.defer()
        msg_id = str(interaction.message.id)
        
        cashout_ref = self.manager.db.collection('pending_cashouts').document(msg_id)
        cashout_data = await cashout_ref.get()

        if not cashout_data.exists:
            for child in self.children: child.disabled = True
            await interaction.message.edit(view=self)
            return await interaction.followup.send("Cette demande de retrait est introuvable ou a déjà été traitée.", ephemeral=True)

        cashout_dict = cashout_data.to_dict()
        user_id_str = str(cashout_dict['user_id'])
        user_ref = self.manager.db.collection('users').document(user_id_str)
        member = interaction.guild.get_member(cashout_dict['user_id'])
        
        original_embed = interaction.message.embeds[0]
        new_embed = original_embed.copy()

        if approve:
            await self.manager.add_transaction(self.manager.db.transaction(), user_ref, "cashout_count", 1, "Approbation de retrait")
            if member:
                await self.manager.check_achievements(member)
                try:
                    await member.send(f"✅ Votre demande de retrait de `{cashout_dict['euros_to_send']:.2f}€` a été approuvée ! Le paiement sera effectué sous peu sur l'adresse `{cashout_dict['paypal_email']}`.")
                except discord.Forbidden: pass

                cashed_out_user_data = (await user_ref.get()).to_dict()
                referrer_id_str = cashed_out_user_data.get('referrer')

                if referrer_id_str:
                    await self.manager.grant_cashout_commission(
                        referrer_id_str=referrer_id_str,
                        amount_cashed_out=cashout_dict['euros_to_send'],
                        referral_member=member,
                        guild=interaction.guild
                    )
                
            await self.manager.log_public_transaction(
                interaction.guild,
                f"✅ Demande de retrait approuvée pour **{member.display_name if member else 'Utilisateur Inconnu'}**.",
                f"**Montant :** `{cashout_dict['euros_to_send']:.2f}€`\n**Validé par :** {interaction.user.mention}",
                discord.Color.green()
            )

            new_embed.color = discord.Color.green()
            new_embed.title = "Demande de Retrait APPROUVÉE"
            new_embed.set_footer(text=f"Approuvé par {interaction.user.display_name}")
            await interaction.message.edit(embed=new_embed)
            await interaction.followup.send("Demande approuvée.", ephemeral=True)
        else: # Deny
            transaction = self.manager.db.transaction()
            await self.manager.add_transaction(
                transaction,
                user_ref,
                "store_credit",
                cashout_dict['credit_to_deduct'],
                "Remboursement suite au refus de retrait"
            )
            if member:
                try:
                    await member.send(f"❌ Votre demande de retrait a été refusée par le staff. Vos `{cashout_dict['credit_to_deduct']:.2f}` crédits vous ont été remboursés.")
                except discord.Forbidden: pass
            
            new_embed.color = discord.Color.red()
            new_embed.title = "Demande de Retrait REFUSÉE"
            new_embed.set_footer(text=f"Refusé par {interaction.user.display_name}")
            await interaction.message.edit(embed=new_embed)
            await interaction.followup.send("Demande refusée et crédits remboursés.", ephemeral=True)

        for child in self.children: child.disabled = True
        await interaction.message.edit(view=self)
        await cashout_ref.delete()


    @discord.ui.button(label="✅ Approuver", style=discord.ButtonStyle.success, custom_id="approve_cashout")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_action(interaction, approve=True)

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.danger, custom_id="deny_cashout")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_action(interaction, approve=False)

class VerificationView(discord.ui.View):
    def __init__(self, manager: 'ManagerCog'):
        super().__init__(timeout=None)
        self.manager = manager
    
    @discord.ui.button(label="✅ Accepter le règlement", style=discord.ButtonStyle.success, custom_id="verify_member_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles_config = self.manager.config.get("ROLES", {})
        verified_role_name = roles_config.get("VERIFIED")
        unverified_role_name = roles_config.get("UNVERIFIED")
        
        verified_role = discord.utils.get(interaction.guild.roles, name=verified_role_name) if verified_role_name else None
        unverified_role = discord.utils.get(interaction.guild.roles, name=unverified_role_name) if unverified_role_name else None

        if not verified_role:
            return await interaction.response.send_message(f"Erreur : Le rôle `{verified_role_name}` est introuvable.", ephemeral=True)
            
        if verified_role in interaction.user.roles:
            return await interaction.response.send_message("Vous êtes déjà vérifié !", ephemeral=True)

        try:
            await interaction.user.add_roles(verified_role, reason="Vérification via bouton")
            if unverified_role and unverified_role in interaction.user.roles:
                await interaction.user.remove_roles(unverified_role, reason="Vérification via bouton")
            await interaction.response.send_message("Vous avez été vérifié avec succès ! Bienvenue sur le serveur.", ephemeral=True)
            
            user_ref = self.manager.db.collection('users').document(str(interaction.user.id))
            user_doc = await user_ref.get()

            if user_doc.exists and user_doc.to_dict().get("referrer"):
                user_data = user_doc.to_dict()
                referrer_id_str = user_data["referrer"]
                referrer = interaction.guild.get_member(int(referrer_id_str))
                if referrer:
                    xp_config = self.manager.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {})
                    xp_to_add = xp_config.get("XP_PER_VERIFIED_INVITE", 100)
                    await self.manager.grant_xp(referrer, xp_to_add, "Parrainage validé")
            
            await self.manager.send_onboarding_dm(interaction.user)

        except discord.Forbidden:
            await interaction.response.send_message("Je n'ai pas les permissions pour vous donner le rôle. Veuillez contacter un administrateur.", ephemeral=True)

class TicketCreationView(discord.ui.View):
    def __init__(self, manager: 'ManagerCog'):
        super().__init__(timeout=None)
        self.manager = manager

    @discord.ui.button(label="🎫 Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="create_ticket_button")
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket_types = self.manager.config.get("TICKET_SYSTEM", {}).get("TICKET_TYPES", [])
        if not ticket_types:
            return await interaction.response.send_message("Le système de tickets n'est pas correctement configuré.", ephemeral=True)
        
        filtered_types = [tt for tt in ticket_types if "Achat de" not in tt.get("label")]
        
        await interaction.response.send_message(view=TicketTypeSelect(self.manager, filtered_types), ephemeral=True)

class TicketTypeSelect(discord.ui.View):
    def __init__(self, manager: 'ManagerCog', ticket_types: List[Dict]):
        super().__init__(timeout=180)
        self.manager = manager
        
        options = [
            discord.SelectOption(label=tt['label'], description=tt.get('description'), value=tt['label'])
            for tt in ticket_types
        ]
        self.select_menu = discord.ui.Select(placeholder="Choisissez le type de ticket...", options=options)
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def on_select(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_label = self.select_menu.values[0]
        ticket_type = next((tt for tt in self.manager.config.get("TICKET_SYSTEM", {}).get("TICKET_TYPES", []) if tt['label'] == selected_label), None)
        if not ticket_type:
             return await interaction.followup.send("Type de ticket invalide.", ephemeral=True)

        initial_embed = discord.Embed(title=f"Ticket : {ticket_type['label']}", description="Veuillez décrire votre problème en détail. Un membre du staff sera bientôt avec vous.", color=discord.Color.blue())
        initial_embed.set_footer(text=f"Ticket créé par {interaction.user.display_name}")

        ticket_channel = await self.manager.create_ticket(
            user=interaction.user, 
            guild=interaction.guild, 
            ticket_type=ticket_type, 
            embed=initial_embed, 
            view=TicketCloseView(self.manager)
        )

        if ticket_channel:
            await interaction.followup.send(f"Votre ticket a été créé : {ticket_channel.mention}", ephemeral=True)
        else:
            await interaction.followup.send("Impossible de créer le ticket. Veuillez contacter un administrateur.", ephemeral=True)
        
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

class TicketCloseView(discord.ui.View):
    def __init__(self, manager: 'ManagerCog'):
        super().__init__(timeout=None)
        self.manager = manager
    
    @discord.ui.button(label="🔒 Fermer le Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_button")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        channel = interaction.channel
        button.disabled = True
        await interaction.message.edit(view=self)

        await self.manager.log_ticket_closure(interaction, channel)
        
        await channel.delete(reason=f"Ticket fermé par {interaction.user}")

# --- Le Cog Principal ---

class ManagerCog(commands.Cog):
    """Le cerveau du bot, gère la gamification, l'économie et les données via Firestore."""
    CONFIG_FILE = 'config.json'
    PRODUCTS_FILE = 'products.json'
    ACHIEVEMENTS_FILE = 'achievements_config.json'
    KNOWLEDGE_BASE_FILE = 'knowledge_base.json'

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = None
        if FIRESTORE_AVAILABLE:
            self.db = firestore.AsyncClient()
        else:
            print("ERREUR CRITIQUE: google-cloud-firestore non installé. Le bot ne peut pas fonctionner.")

        self.config = {}
        self.products = []
        self.achievements = []
        self.knowledge_base = {}
        self.invites_cache = {}
        self.active_events = {}
        
        if not IMAGING_AVAILABLE:
            print("⚠️ ATTENTION: La librairie 'Pillow' est manquante. La commande /profil utilisera un embed standard.")

        self.model = None
        if not AI_AVAILABLE:
            print("ATTENTION: Le package google-generativeai n'est pas installé. Les fonctionnalités d'IA seront désactivées.")
        else:
            gemini_key = os.environ.get("GEMINI_API_KEY")
            if gemini_key:
                genai.configure(api_key=gemini_key)
                self.model = genai.GenerativeModel('gemini-2.5-flash')
                print("✅ Modèle Gemini initialisé avec succès.")
            else:
                print("⚠️ ATTENTION: La clé API Gemini (GEMINI_API_KEY) est manquante dans l'environnement. L'IA est désactivée.")

    async def cog_load(self):
        print("Chargement des données du ManagerCog...")
        if not self.db: return

        await self._load_static_data()
        await self._load_active_events()
        self.bot.add_view(VerificationView(self))
        self.bot.add_view(TicketCreationView(self))
        self.bot.add_view(TicketCloseView(self))
        self.bot.add_view(CashoutRequestView(self))
        self.bot.add_view(MissionView(self))
        self.weekly_leaderboard_task.start()
        self.mission_assignment_task.start()
        self.check_vip_status_task.start()
        self.weekly_coaching_report_task.start()

    def cog_unload(self):
        self.weekly_leaderboard_task.cancel()
        self.mission_assignment_task.cancel()
        self.check_vip_status_task.cancel()
        self.weekly_coaching_report_task.cancel()
        print("ManagerCog déchargé.")

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.db: return
        print("ManagerCog: Le bot est prêt. Finalisation de la configuration...")
        guild_id_str = self.config.get("GUILD_ID")
        if guild_id_str == "VOTRE_VRAI_ID_DE_SERVEUR_ICI" or not guild_id_str:
            print("ATTENTION: GUILD_ID non configuré. De nombreuses fonctionnalités seront désactivées.")
            return

        guild = self.bot.get_guild(int(guild_id_str))
        if guild:
            await self._update_invite_cache(guild)
            print(f"Cache des invitations mis à jour pour la guilde : {guild.name}")
        else:
            print(f"ATTENTION: Guilde avec l'ID {guild_id_str} non trouvée.")

        print("Tâches de fond démarrées via cog_load.")

    async def _load_static_json(self, file_path: str) -> any:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Erreur chargement fichier statique {file_path}: {e}")
            return {} if 'knowledge_base' in file_path else []

    async def _load_static_data(self):
        self.config = await self._load_static_json(self.CONFIG_FILE)
        self.products = await self._load_static_json(self.PRODUCTS_FILE)
        self.achievements = await self._load_static_json(self.ACHIEVEMENTS_FILE)
        self.knowledge_base = await self._load_static_json(self.KNOWLEDGE_BASE_FILE)
        print("Données de configuration statiques chargées.")
    
    async def _load_active_events(self):
        events_doc = await self.db.collection('system').document('events').get()
        if events_doc.exists:
            self.active_events = events_doc.to_dict().get('active', {})
        else:
            self.active_events = {}
        print(f"Événements actifs chargés en mémoire: {len(self.active_events)}.")
    
    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        return next((p for p in self.products if p.get('id') == product_id), None)

    async def _parse_gemini_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Analyse de manière robuste une réponse JSON potentiellement mal formatée de l'IA."""
        match = re.search(r'```(?:json)?\s*({.*?})\s*```', text, re.DOTALL)
        json_str = match.group(1) if match else text
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"Erreur de décodage JSON: {e}\nTexte reçu: {text}")
            return None
            
    async def query_gemini_for_promo(self, product_name: str, short_description: str) -> Optional[str]:
        if not self.model: return None

        prompt_template = self.config.get("AI_PROCESSING_CONFIG", {}).get("AI_PROMO_GENERATION_PROMPT")
        if not prompt_template:
            print("ATTENTION: Le prompt de génération de promo est manquant dans config.json")
            return "Offre spéciale ! Ne manquez pas cette promotion."
        
        prompt = prompt_template.format(
            product_name=product_name,
            short_description=short_description
        )
        
        try:
            generation_config = GenerationConfig(response_mime_type="application/json")
            response = await self.model.generate_content_async(contents=prompt, generation_config=generation_config)
            parsed_json = await self._parse_gemini_json_response(response.text)
            return parsed_json.get("generated_description") if parsed_json else short_description
        except Exception as e:
            print(f"Erreur Gemini (Promo Generation): {e}")
            return short_description

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not self.db:
            return
        
        xp_config = self.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {})
        if len(message.content.split()) < xp_config.get("ANTI_FARM_MIN_WORDS", 0):
            return

        if xp_config.get("ENABLED", False):
            await self.grant_xp(message.author, "message", f"Message dans #{message.channel.name}")
        
        await self.update_mission_progress(message.author, "send_message", 1)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or not self.db: return
        
        unverified_role_name = self.config.get("ROLES", {}).get("UNVERIFIED")
        if unverified_role_name:
            role = discord.utils.get(member.guild.roles, name=unverified_role_name)
            if role:
                try:
                    await member.add_roles(role, reason="Nouveau membre")
                except discord.Forbidden:
                    print(f"Permissions manquantes pour assigner le rôle '{unverified_role_name}' à {member.name}")

        user_ref = self.db.collection('users').document(str(member.id))
        await self.get_or_create_user_data(user_ref)

        old_invites = self.invites_cache.get(member.guild.id, {})
        new_invites = await member.guild.invites()
        inviter = None
        for invite in new_invites:
            if invite.code in old_invites and invite.uses > old_invites[invite.code].uses:
                inviter = invite.inviter
                break
        
        if inviter and inviter.id != member.id:
            await user_ref.set({"referrer": str(inviter.id)}, merge=True)
            
            inviter_ref = self.db.collection('users').document(str(inviter.id))
            transaction = self.db.transaction()
            await self.add_transaction(
                transaction, inviter_ref,
                "referral_count", 1, f"Parrainage de {member.name}"
            )
            print(f"{member.name} a été invité par {inviter.name}")
        
        await self._update_invite_cache(member.guild)
    
    async def _update_invite_cache(self, guild: discord.Guild):
        try:
            self.invites_cache[guild.id] = {invite.code: invite for invite in await guild.invites()}
        except discord.Forbidden:
            print(f"Permissions manquantes pour récupérer les invitations de la guilde {guild.name}")

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        await self._update_invite_cache(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        await self._update_invite_cache(invite.guild)
    
    async def get_or_create_user_data(self, user_ref: firestore.AsyncDocumentReference) -> Dict[str, Any]:
        user_doc = await user_ref.get()
        if user_doc.exists:
            return user_doc.to_dict()
        
        default_data = {
            "xp": 0, "level": 1, "weekly_xp": 0, "last_message_timestamp": 0,
            "message_count": 0, "purchase_count": 0, "purchase_total_value": 0.0,
            "achievements": [], "store_credit": 0.0, "warnings": 0,
            "affiliate_sale_count": 0, "affiliate_earnings": 0.0, "referral_count": 0,
            "cashout_count": 0, "completed_challenges": [], "xp_gated": False,
            "current_prestige_challenge": None, "current_personalized_challenge": None,
            "join_timestamp": datetime.now(timezone.utc).timestamp(),
            "weekly_affiliate_earnings": 0.0,
            "active_boosters": {}, "permanent_affiliate_bonus": False, "vip_premium": None,
            "transaction_log": [],
            "missions_opt_in": self.config.get("MISSION_SYSTEM", {}).get("OPT_IN_DEFAULT", True),
            "current_daily_mission": None, "current_weekly_mission": None,
            "guild_id": None, "guild_bonus": {}
        }
        await user_ref.set(default_data)
        print(f"Nouvel utilisateur initialisé dans Firestore : {user_ref.id}")
        return default_data

    @async_transactional
    async def add_transaction(self, transaction: firestore.AsyncTransaction, user_ref: firestore.AsyncDocumentReference, type: str, amount: any, description: str):
        user_doc = await user_ref.get(transaction=transaction)
        user_data = user_doc.to_dict() if user_doc.exists else await self.get_or_create_user_data(user_ref)
        
        new_value = user_data.get(type, 0) + amount
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": type, "amount": amount, "description": description
        }
        transaction_log = user_data.get("transaction_log", [])
        transaction_log.insert(0, log_entry) # Add to the beginning
        
        max_log_size = self.config.get("TRANSACTION_LOG_CONFIG", {}).get("MAX_USER_LOG_SIZE", 50)
        if len(transaction_log) > max_log_size:
            transaction_log = transaction_log[:max_log_size]
            
        update_payload = {
            type: new_value,
            "transaction_log": transaction_log
        }
        transaction.update(user_ref, update_payload)

    async def grant_xp(self, user: discord.Member, source: any, reason: str, _is_achievement_reward: bool = False):
        user_id_str = str(user.id)
        user_ref = self.db.collection('users').document(user_id_str)
        xp_config = self.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {})
        
        user_data = await self.get_or_create_user_data(user_ref)
        
        if isinstance(source, str) and source == "message" and user_data.get("xp_gated", False):
            return

        now = datetime.now(timezone.utc)
        
        xp_to_add = 0
        transaction = self.db.transaction()
        if source == "message":
            cooldown = xp_config.get("ANTI_FARM_COOLDOWN_SECONDS", 60)
            last_msg_ts = user_data.get("last_message_timestamp", 0)
            if now.timestamp() - last_msg_ts < cooldown: return
            xp_per_message_range = xp_config.get("XP_PER_MESSAGE", [10, 20])
            xp_to_add = random.randint(*xp_per_message_range)
            await user_ref.update({"last_message_timestamp": now.timestamp()})
            await self.add_transaction(transaction, user_ref, "message_count", 1, reason)
        elif isinstance(source, int):
            xp_to_add = source
        
        if xp_to_add == 0: return

        # --- Calculate Boosts ---
        total_boost = 1.0
        # VIP Bonus
        vip_data = user_data.get("vip_premium")
        if vip_data and datetime.fromisoformat(vip_data.get("expires_at", "1970-01-01T00:00:00+00:00")) > now:
            vip_config = self.config.get("GAMIFICATION_CONFIG", {}).get("VIP_SYSTEM", {}).get("PREMIUM", {})
            sorted_tiers = sorted(vip_config.get("XP_BOOST_TIERS", []), key=lambda x: x.get("consecutive_months", 0), reverse=True)
            for tier in sorted_tiers:
                if vip_data.get("consecutive_months", 0) >= tier.get("consecutive_months", 999):
                    total_boost += tier.get("boost", 0)
                    break
        
        # Check for active XP boosters from shop
        active_boosters = user_data.get("active_boosters", {})
        for booster_id, booster_data in active_boosters.items():
            if 'xp_booster' in booster_id and datetime.fromisoformat(booster_data.get('expires_at', "1970-01-01T00:00:00+00:00")) > now:
                total_boost += booster_data.get('multiplier', 1.0) - 1.0 # e.g., 1.25 -> 0.25
        
        # Event bonus
        event_multiplier = self.active_events.get("double_xp", {}).get("multiplier", 1.0)
        final_xp = int(xp_to_add * total_boost * event_multiplier)
        
        @async_transactional
        async def _update_xp_and_guild(trans, user_ref, guild_ref, final_xp, reason):
            await self.add_transaction(trans, user_ref, "xp", final_xp, reason)
            await self.add_transaction(trans, user_ref, "weekly_xp", final_xp, f"Gain hebdomadaire: {reason}")
            if guild_ref:
                trans.update(guild_ref, {"weekly_xp": firestore.Increment(final_xp)})

        guild_id = user_data.get("guild_id")
        guild_ref = self.db.collection('guilds').document(guild_id) if guild_id else None
        
        await _update_xp_and_guild(self.db.transaction(), user_ref, guild_ref, final_xp, reason)

        leveled_up, new_level = await self.check_level_up(user)
        
        if not _is_achievement_reward:
            await self.check_achievements(user)
        
        if leveled_up:
            channel_name = self.config.get("CHANNELS", {}).get("LEVEL_UP_ANNOUNCEMENTS")
            if channel_name:
                channel = discord.utils.get(user.guild.text_channels, name=channel_name)
                if channel:
                    await channel.send(f"🎉 Bravo {user.mention}, tu as atteint le niveau **{new_level}** !")

    async def check_referral_milestones(self, user: discord.Member, user_data: dict):
        xp_config = self.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {})
        if not user_data.get("referrer"): return
        
        referrer_id_str = user_data["referrer"]
        referrer = user.guild.get_member(int(referrer_id_str))
        if not referrer: return

        if user_data.get("level", 1) >= 5 and not user_data.get("lvl5_milestone_rewarded"):
            join_ts = user_data.get("join_timestamp", 0)
            limit_days = xp_config.get("REFERRAL_LVL_5_DAYS_LIMIT", 7)
            if (datetime.now(timezone.utc).timestamp() - join_ts) < (limit_days * 86400):
                xp_gain = xp_config.get("XP_BONUS_REFERRAL_HITS_LVL_5", 2000)
                user_ref = self.db.collection('users').document(str(user.id))
                await user_ref.update({"lvl5_milestone_rewarded": True})
                await self.grant_xp(referrer, xp_gain, f"Filleul {user.display_name} a atteint le niveau 5")
                try:
                    await referrer.send(f"🚀 Votre filleul {user.mention} a atteint le niveau 5 rapidement ! Vous gagnez **{xp_gain} XP** bonus !")
                except discord.Forbidden: pass

    async def check_level_up(self, user: discord.Member) -> tuple[bool, int]:
        user_ref = self.db.collection('users').document(str(user.id))
        user_data = (await user_ref.get()).to_dict()
        if not user_data: return False, 1

        if user_data.get("xp_gated", False): return False, user_data.get("level", 1)
        
        xp_config = self.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {})
        base_xp = xp_config.get("LEVEL_UP_FORMULA_BASE_XP", 150)
        multiplier = xp_config.get("LEVEL_UP_FORMULA_MULTIPLIER", 1.6)
        old_level = user_data.get("level", 1)
        xp_needed = int(base_xp * (multiplier ** old_level))
        
        if user_data.get("xp", 0) < xp_needed:
            return False, old_level
            
        new_level = old_level
        while user_data.get("xp", 0) >= int(base_xp * (multiplier ** new_level)):
            new_level += 1
        
        transaction = self.db.transaction()
        await self.add_transaction(transaction, user_ref, "level", new_level - old_level, "Montée de niveau")
        
        await self.check_referral_milestones(user, user_data)
        # DM logic and role rewards...
        return True, new_level


    async def check_achievements(self, user: discord.Member):
        if not user: return
        user_ref = self.db.collection('users').document(str(user.id))
        user_stats = (await user_ref.get()).to_dict()
        if not user_stats: return

        for achievement in self.achievements:
            if achievement.get("id") in user_stats.get("achievements", []): continue
            trigger = achievement.get("trigger", {})
            if user_stats.get(trigger.get("type"), 0) >= trigger.get("value", 999999):
                await self.grant_achievement(user, achievement)
    
    async def grant_achievement(self, user: discord.Member, achievement: dict):
        user_ref = self.db.collection('users').document(str(user.id))
        await user_ref.update({"achievements": firestore.ArrayUnion([achievement.get("id")])})

        if (xp_reward := achievement.get("reward_xp", 0)) > 0:
            await self.grant_xp(user, xp_reward, f"Succès: {achievement.get('name')}", _is_achievement_reward=True)
        
        # Announcement logic remains the same...

    async def record_purchase(self, user_id: int, product: dict, option: Optional[dict], credit_used: float, guild_id: int, transaction_code: str) -> tuple[bool, str]:
        guild = self.bot.get_guild(guild_id)
        if not guild: return False, "Guilde non trouvée."
        member = guild.get_member(user_id)
        if not member: return False, "Membre non trouvé."
        
        buyer_ref = self.db.collection('users').document(str(user_id))
        price = option.get('price') if option else product.get('price', 0)
        
        if product.get("type") == "subscription":
             buyer_data = await self.get_or_create_user_data(buyer_ref)
             vip_data = buyer_data.get("vip_premium")
             now = datetime.now(timezone.utc)
             duration = self.config.get("GAMIFICATION_CONFIG", {}).get("VIP_SYSTEM", {}).get("PREMIUM", {}).get("DURATION_DAYS", 7)
             new_expiry = now + timedelta(days=duration)
             
             new_vip_data = {
                 "starts_at": now.isoformat(),
                 "expires_at": new_expiry.isoformat(),
                 "consecutive_months": vip_data.get("consecutive_months", 0) + 1 if vip_data else 1
             }
             await buyer_ref.update({"vip_premium": new_vip_data})
             
             vip_role_name = self.config.get("ROLES", {}).get("VIP_PREMIUM")
             if vip_role_name:
                 role = discord.utils.get(guild.roles, name=vip_role_name)
                 if role: await member.add_roles(role)

        transaction = self.db.transaction()
        @async_transactional
        async def purchase_transaction(trans, buyer_ref, price, credit_used):
            await self.add_transaction(trans, buyer_ref, "purchase_count", 1, "Achat")
            await self.add_transaction(trans, buyer_ref, "purchase_total_value", price, "Achat")
            if credit_used > 0:
                await self.add_transaction(trans, buyer_ref, "store_credit", -credit_used, "Achat avec crédit")
        
        await purchase_transaction(transaction, buyer_ref, price, credit_used)

        xp_per_euro = self.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {}).get("XP_PER_EURO_SPENT", 20)
        xp_gain = int(price * xp_per_euro)
        await self.grant_xp(member, xp_gain, "Achat")
        await self.check_achievements(member)
        
        buyer_data = (await buyer_ref.get()).to_dict()
        referrer_id_str = buyer_data.get("referrer")
        if referrer_id_str:
            referrer = guild.get_member(int(referrer_id_str))
            if referrer:
                referrer_data = await self.get_or_create_user_data(self.db.collection('users').document(referrer_id_str))
                commission_earned = self.calculate_commission(referrer_data, price, product, option)
                if commission_earned > 0:
                    ref_transaction = self.db.transaction()
                    await self.add_transaction(ref_transaction, self.db.collection('users').document(referrer_id_str), "store_credit", commission_earned, f"Commission sur achat de {member.display_name}")
                    await self.add_transaction(ref_transaction, self.db.collection('users').document(referrer_id_str), "affiliate_earnings", commission_earned, "Gain d'affiliation")
                    await self.add_transaction(ref_transaction, self.db.collection('users').document(referrer_id_str), "weekly_affiliate_earnings", commission_earned, "Gain d'affiliation hebdo")
                    await self.check_achievements(referrer)
        
        return True, "Achat enregistré."
    
    def calculate_commission(self, referrer_data: dict, price: float, product: dict, option: Optional[dict]) -> float:
        """Calculates affiliate commission based on comprehensive rules."""
        aff_config = self.config.get("GAMIFICATION_CONFIG", {}).get("AFFILIATE_SYSTEM", {})
        vip_config = self.config.get("GAMIFICATION_CONFIG", {}).get("VIP_SYSTEM", {}).get("PREMIUM", {})
        guild_config = self.config.get("GUILD_SYSTEM", {})
        now = datetime.now(timezone.utc)
        
        margin_type = product.get("margin_type", "total")
        commissionable_amount = price - (option.get("purchase_cost", 0) if option else product.get("purchase_cost", 0)) if margin_type == "net" else price
        if commissionable_amount <= 0: return 0.0

        guild_bonus = referrer_data.get("guild_bonus", {})
        if guild_bonus.get("type") == 'top1':
            return commissionable_amount * guild_config.get("WEEKLY_REWARDS", {}).get("TOP_1", {}).get("commission_rate", 0.90)

        base_rate = next((t.get('rate', 0) for t in sorted(aff_config.get("COMMISSION_TIERS", []), key=lambda x: x.get('level', 0), reverse=True) if referrer_data.get("level", 1) >= t.get('level', 999)), 0)
        
        total_boost = 0.0
        vip_data = referrer_data.get("vip_premium")
        if vip_data and datetime.fromisoformat(vip_data.get("expires_at", "1970-01-01T00:00:00+00:00")) > now:
            total_boost += next((t.get('bonus', 0) for t in sorted(vip_config.get("COMMISSION_BONUS_TIERS", []), key=lambda x: x.get('consecutive_months', 0), reverse=True) if vip_data.get("consecutive_months", 0) >= t.get('consecutive_months', 999)), 0)
            
        if referrer_data.get("permanent_affiliate_bonus", False):
            total_boost += aff_config.get("PERMANENT_LOYALTY_BONUS", {}).get("RATE", 0)
            
        active_boosters = referrer_data.get("active_boosters", {})
        for booster_id, booster_data in active_boosters.items():
            if 'commission_booster' in booster_id and datetime.fromisoformat(booster_data.get('expires_at', "1970-01-01T00:00:00+00:00")) > now:
                total_boost += booster_data.get('bonus', 0.0)
                
        total_boost += referrer_data.get("affiliate_booster", 0.0)
        
        if guild_bonus.get("type") in ['top2', 'top3']:
            total_boost += guild_bonus.get("commission_boost", 0.0)
        
        commission_rate = base_rate + total_boost
        
        cap = guild_bonus.get("max_commission_rate", 1.0) if guild_bonus.get("type") in ['top2', 'top3'] else 1.0
        
        final_rate = min(commission_rate, cap)
        return commissionable_amount * final_rate

    async def grant_cashout_commission(self, referrer_id_str: str, amount_cashed_out: float, referral_member: discord.Member, guild: discord.Guild):
        """Grants commission to a referrer when their referral cashes out."""
        referrer_ref = self.db.collection('users').document(referrer_id_str)
        referrer_data = await self.get_or_create_user_data(referrer_ref)
        referrer = guild.get_member(int(referrer_id_str))
        
        if not referrer: return

        cashout_config = self.config.get("GAMIFICATION_CONFIG", {}).get("AFFILIATE_SYSTEM", {}).get("CASHOUT_COMMISSION", {})
        guild_bonus = referrer_data.get("guild_bonus", {})
        
        rate = cashout_config.get("BASE_RATE", 0.05)
        if guild_bonus.get("type") in ['top1', 'top2', 'top3']:
            rate = guild_bonus.get("cashout_commission_rate", 0.10)
        elif referrer_data.get("vip_premium"):
            rate = cashout_config.get("VIP_RATE", 0.10)
            
        commission_earned = amount_cashed_out * rate
        if commission_earned > 0:
            transaction = self.db.transaction()
            await self.add_transaction(transaction, referrer_ref, "store_credit", commission_earned, f"Commission sur cashout de {referral_member.display_name}")
            await self.add_transaction(transaction, referrer_ref, "affiliate_earnings", commission_earned, "Gain d'affiliation (cashout)")
            await self.add_transaction(transaction, referrer_ref, "weekly_affiliate_earnings", commission_earned, "Gain d'affiliation hebdo (cashout)")
            try:
                await referrer.send(f"💸 Votre filleul {referral_member.display_name} a retiré de l'argent ! Vous gagnez une commission de **{commission_earned:.2f} crédits**.")
            except discord.Forbidden: pass


    async def handle_xp_purchase(self, interaction: discord.Interaction, credits_to_spend: float):
        user_ref = self.db.collection('users').document(str(interaction.user.id))
        xp_config = self.config.get("GAMIFICATION_CONFIG", {}).get("XP_SYSTEM", {}).get("XP_PURCHASE", {})
        
        @async_transactional
        async def purchase_xp_tx(transaction, user_ref, credits):
            user_data = (await user_ref.get(transaction=transaction)).to_dict()
            if user_data.get("store_credit", 0) < credits:
                return {"success": False, "reason": "Fonds insuffisants."}
            
            cost_per_xp = xp_config.get("COST_PER_XP_IN_CREDITS", 0.01)
            # Apply VIP discount if applicable
            xp_gained = math.floor(credits / cost_per_xp)
            
            await self.add_transaction(transaction, user_ref, "store_credit", -credits, f"Achat de {xp_gained} XP")
            await self.add_transaction(transaction, user_ref, "xp", xp_gained, f"Achat avec {credits} crédits")
            
            return {"success": True, "xp_gained": xp_gained}

        result = await purchase_xp_tx(self.db.transaction(), user_ref, credits_to_spend)

        if result["success"]:
            await self.check_level_up(interaction.user)
            await interaction.response.send_message(f"✅ Vous avez échangé **{credits_to_spend:.2f} crédits** contre **{result['xp_gained']} XP** !", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {result['reason']}", ephemeral=True)
    
    async def handle_cashout_submission(self, interaction: discord.Interaction, amount_str: str, paypal_email: str):
        await interaction.response.defer(ephemeral=True)
        try:
            amount = float(amount_str.replace(',', '.'))
            if amount <= 0: raise ValueError
        except ValueError:
            return await interaction.followup.send("❌ Montant invalide. Veuillez entrer un nombre positif.", ephemeral=True)

        user_ref = self.db.collection('users').document(str(interaction.user.id))
        user_data = await self.get_or_create_user_data(user_ref)
        cashout_config = self.config.get("GAMIFICATION_CONFIG", {}).get("CASHOUT_SYSTEM", {})

        if user_data.get("store_credit", 0.0) < amount:
            return await interaction.followup.send(f"❌ Fonds insuffisants. Vous n'avez que {user_data.get('store_credit', 0.0):.2f} crédits.", ephemeral=True)
        
        min_level = cashout_config.get("MINIMUM_LEVEL", 999)
        if user_data.get("level", 1) < min_level:
            return await interaction.followup.send(f"❌ Vous devez être au moins niveau {min_level} pour faire un retrait.", ephemeral=True)
        
        min_age = cashout_config.get("MINIMUM_ACCOUNT_AGE_DAYS", 999)
        account_age_days = (datetime.now(timezone.utc).timestamp() - user_data.get("join_timestamp", 0)) / 86400
        if account_age_days < min_age:
            return await interaction.followup.send(f"❌ Votre compte doit avoir au moins {min_age} jours pour faire un retrait.", ephemeral=True)

        threshold = next((t.get("threshold", 1000) for t in sorted(cashout_config.get("WITHDRAWAL_THRESHOLDS", []), key=lambda x: x.get('level', 0), reverse=True) if user_data.get("level", 1) >= t.get('level', 999)), 1000)
        if amount < threshold:
            return await interaction.followup.send(f"❌ Le montant minimum de retrait pour votre niveau est de **{threshold:.2f} crédits**.", ephemeral=True)
        
        euros_to_send = amount * cashout_config.get("CREDIT_TO_EUR_RATE", 1.0)
        await self.add_transaction(self.db.transaction(), user_ref, "store_credit", -amount, f"Demande de retrait de {amount:.2f} crédits")
        
        requests_channel_name = self.config.get("CHANNELS", {}).get("CASHOUT_REQUESTS")
        if not requests_channel_name:
            await self.add_transaction(self.db.transaction(), user_ref, "store_credit", amount, "Remboursement - Erreur canal de retrait")
            return await interaction.followup.send("❌ Erreur critique : le salon des demandes de retrait n'est pas configuré. Votre demande a été annulée et vos crédits restaurés.", ephemeral=True)

        channel = discord.utils.get(interaction.guild.text_channels, name=requests_channel_name)
        if not channel:
            await self.add_transaction(self.db.transaction(), user_ref, "store_credit", amount, "Remboursement - Erreur canal de retrait")
            return await interaction.followup.send("❌ Erreur critique : le salon des demandes de retrait est introuvable. Votre demande a été annulée et vos crédits restaurés.", ephemeral=True)
            
        embed = discord.Embed(title="Nouvelle Demande de Retrait", color=discord.Color.gold())
        embed.add_field(name="Membre", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Crédits Retirés", value=f"`{amount:.2f}`", inline=True)
        embed.add_field(name="Montant à Payer", value=f"`{euros_to_send:.2f} €`", inline=True)
        embed.add_field(name="Email PayPal", value=f"`{paypal_email}`", inline=False)
        embed.set_footer(text=f"Demande créée le {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}")
        
        request_msg = await channel.send(embed=embed, view=CashoutRequestView(self))
        
        await self.db.collection('pending_cashouts').document(str(request_msg.id)).set({
            "user_id": interaction.user.id, "credit_to_deduct": amount,
            "euros_to_send": euros_to_send, "paypal_email": paypal_email,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        await interaction.followup.send("✅ Votre demande de retrait a été envoyée au staff pour validation.", ephemeral=True)

    async def handle_challenge_submission(self, interaction: discord.Interaction, submission_text: str, challenge_type: str):
        await interaction.response.defer(ephemeral=True)
        mod_alerts_channel_name = self.config.get("CHANNELS", {}).get("MOD_ALERTS")
        if not mod_alerts_channel_name:
            return await interaction.followup.send("Erreur: Impossible de soumettre le défi (canal de modération non configuré).", ephemeral=True)
            
        channel = discord.utils.get(interaction.guild.text_channels, name=mod_alerts_channel_name)
        if not channel:
            return await interaction.followup.send("Erreur: Impossible de soumettre le défi.", ephemeral=True)
        
        embed = discord.Embed(
            title=f"Soumission de Défi ({challenge_type.capitalize()})",
            description=f"**Utilisateur:** {interaction.user.mention}\n\n**Preuve Soumise:**\n>>> {submission_text}",
            color=discord.Color.orange()
        )
        embed.set_footer(text="Utilisez /admin grant-xp pour récompenser manuellement.")
        await channel.send(embed=embed)
        await interaction.followup.send("✅ Votre défi a été soumis au staff pour validation !", ephemeral=True)

    async def update_mission_progress(self, user: discord.Member, mission_id: str, progress_amount: int):
        user_ref = self.db.collection('users').document(str(user.id))
        user_data = await self.get_or_create_user_data(user_ref)

        for mission_type in ["current_daily_mission", "current_weekly_mission"]:
            mission = user_data.get(mission_type)
            if mission and mission.get('id') == mission_id and not mission.get('completed', False):
                mission['progress'] += progress_amount
                if mission.get('progress', 0) >= mission.get('target', 999999):
                    mission['completed'] = True
                    await self.grant_xp(user, mission.get('reward_xp', 0), f"Mission complétée: {mission.get('description')}")
                    if user_data.get('missions_opt_in', True):
                        try:
                            await user.send(f"🎉 **Mission accomplie !**\n> {mission.get('description')}\n**Récompense :** +{mission.get('reward_xp', 0)} XP")
                        except discord.Forbidden: pass
                await user_ref.update({mission_type: mission})
                break

    @tasks.loop(hours=24)
    async def mission_assignment_task(self):
        mission_config = self.config.get("MISSION_SYSTEM", {})
        if not mission_config.get("ENABLED", False): return

        daily_templates = [t for t in mission_config.get("TEMPLATES", []) if t.get("type") == "daily"]
        weekly_templates = [t for t in mission_config.get("TEMPLATES", []) if t.get("type") == "weekly"]
        is_new_week = datetime.now(timezone.utc).weekday() == 0

        users_stream = self.db.collection('users').stream()
        async for user_doc in users_stream:
            new_daily = random.choice(daily_templates)
            target = random.randint(*new_daily.get("target_range", [15,30]))
            reward = random.randint(*new_daily.get("reward_xp_range", [50,100]))
            
            update_data = {
                "current_daily_mission": {
                    "id": new_daily.get("id"), "description": new_daily.get("description", "Faire {target} choses.").format(target=target),
                    "target": target, "progress": 0, "reward_xp": reward, "completed": False
                }
            }

            if is_new_week:
                new_weekly = random.choice(weekly_templates)
                target_w = random.randint(*new_weekly.get("target_range", [100,200]))
                reward_w = random.randint(*new_weekly.get("reward_xp_range", [300,500]))
                update_data["current_weekly_mission"] = {
                    "id": new_weekly.get("id"), "description": new_weekly.get("description", "Faire {target} choses.").format(target=target_w),
                    "target": target_w, "progress": 0, "reward_xp": reward_w, "completed": False
                }
            
            await user_doc.reference.update(update_data)


    @tasks.loop(hours=1)
    async def check_vip_status_task(self):
        vip_config = self.config.get("GAMIFICATION_CONFIG", {}).get("VIP_SYSTEM", {}).get("PREMIUM", {})
        if not vip_config: return
        
        now = datetime.now(timezone.utc)
        guild = self.bot.get_guild(int(self.config.get("GUILD_ID", 0)))
        if not guild: return
        
        vip_role_name = self.config.get("ROLES", {}).get("VIP_PREMIUM")
        vip_role = discord.utils.get(guild.roles, name=vip_role_name) if vip_role_name else None
        if not vip_role: return

        query = self.db.collection('users').where(filter=AsyncFieldFilter('vip_premium', '!=', None)).stream()
        async for doc in query:
            user_data = doc.to_dict()
            vip_data = user_data.get("vip_premium", {})
            expires_at = datetime.fromisoformat(vip_data.get("expires_at", "1970-01-01T00:00:00+00:00"))
            
            if now > expires_at:
                member = guild.get_member(int(doc.id))
                if member:
                    await member.remove_roles(vip_role, reason="Abonnement VIP Premium expiré")
                await doc.reference.update({"vip_premium": firestore.DELETE_FIELD})


    @tasks.loop(hours=168) # Weekly
    async def weekly_coaching_report_task(self):
        if not self.model: return
        
        coach_prompt = self.config.get("AI_PROCESSING_CONFIG", {}).get("AI_WEEKLY_COACH_PROMPT")
        if not coach_prompt: return
        
        users_query = self.db.collection('users').where('weekly_xp', '>', 10).stream()

        async for doc in users_query:
            user_data = doc.to_dict()
            user_id = int(doc.id)
            user = self.bot.get_user(user_id)
            if user:
                prompt = coach_prompt.format(
                    username=user.display_name,
                    weekly_xp=user_data.get('weekly_xp', 0),
                    weekly_affiliate_earnings=user_data.get('weekly_affiliate_earnings', 0.0)
                )
                try:
                    response = await self.model.generate_content_async(prompt)
                    await user.send(response.text)
                except Exception as e:
                    print(f"Erreur envoi coaching DM à {user_id}: {e}")

    @tasks.loop(hours=168) # 7 days * 24 hours
    async def weekly_leaderboard_task(self):
        print("Lancement de la tâche de classement hebdomadaire...")
        guild_id_str = self.config.get("GUILD_ID")
        if not guild_id_str or guild_id_str == "VOTRE_VRAI_ID_DE_SERVEUR_ICI": return
        guild = self.bot.get_guild(int(guild_id_str))
        if not guild: return
        
        roles_config = self.config.get("ROLES", {})
        top_roles_names = [roles_config.get(k) for k in ["LEADERBOARD_TOP_1_XP", "LEADERBOARD_TOP_2_XP", "LEADERBOARD_TOP_3_XP"] if roles_config.get(k)]
        for role_name in top_roles_names:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                for member in role.members:
                    try:
                        await member.remove_roles(role, reason="Réinitialisation classement hebdo")
                    except discord.HTTPException: pass
        
        all_users_stream = self.db.collection('users').stream()
        async for user_doc in all_users_stream:
            await user_doc.reference.update({"guild_bonus": {}})
        
        users_top_query = self.db.collection('users').where('weekly_xp', '>', 0).order_by('weekly_xp', direction=firestore.Query.DESCENDING).limit(3)
        top_users_docs = [doc async for doc in users_top_query.stream()]

        user_lb_channel_name = self.config.get("CHANNELS", {}).get("WEEKLY_LEADERBOARD_ANNOUNCEMENTS")
        user_lb_channel = discord.utils.get(guild.text_channels, name=user_lb_channel_name) if user_lb_channel_name else None
        
        if user_lb_channel:
            embed = discord.Embed(title="🏆 Classement Hebdomadaire des Membres (XP) 🏆", color=discord.Color.gold())
            description = ""
            for i, doc in enumerate(top_users_docs):
                rank, member = i + 1, guild.get_member(int(doc.id))
                if member:
                    role_name = roles_config.get(f"LEADERBOARD_TOP_{rank}_XP")
                    if role_name and (role_to_add := discord.utils.get(guild.roles, name=role_name)):
                        await member.add_roles(role_to_add)
                    description += f"{ {1: '🥇', 2: '🥈', 3: '🥉'}.get(rank, f'**#{rank}**')} **{member.display_name}** - `{doc.to_dict().get('weekly_xp', 0)}` XP\n"
            embed.description = description or "Personne n'a gagné d'XP cette semaine."
            await user_lb_channel.send(embed=embed)

        guilds_top_query = self.db.collection('guilds').where('weekly_xp', '>', 0).order_by('weekly_xp', direction=firestore.Query.DESCENDING).limit(3)
        top_guilds_docs = [doc async for doc in guilds_top_query.stream()]
        
        guild_rewards_config = self.config.get("GUILD_SYSTEM", {}).get("WEEKLY_REWARDS", {})
        guild_lb_channel_name = self.config.get("CHANNELS", {}).get("GUILD_LEADERBOARD")
        guild_lb_channel = discord.utils.get(guild.text_channels, name=guild_lb_channel_name) if guild_lb_channel_name else None

        if guild_lb_channel:
            embed = discord.Embed(title="🛡️ Classement Hebdomadaire des Guildes 🛡️", color=discord.Color.blurple())
            description = ""
            for i, doc in enumerate(top_guilds_docs):
                rank, guild_data = i + 1, doc.to_dict()
                description += f"{ {1: '🥇', 2: '🥈', 3: '🥉'}.get(rank, f'**#{rank}**')} **{guild_data.get('name')}** - `{guild_data.get('weekly_xp', 0)}` XP\n"
                
                if (reward_key := f"TOP_{rank}") in guild_rewards_config:
                    bonus_data = {**guild_rewards_config[reward_key], "type": f'top{rank}'}
                    for member_id_str in guild_data.get('members', []):
                        await self.db.collection('users').document(member_id_str).update({"guild_bonus": bonus_data})
            embed.description = description or "Aucune guilde n'a gagné d'XP cette semaine."
            embed.set_footer(text="Les bonus de commission sont actifs pour la semaine à venir !")
            await guild_lb_channel.send(embed=embed)
        
        all_users_reset_stream = self.db.collection('users').stream()
        async for user_doc in all_users_reset_stream:
            await user_doc.reference.update({"weekly_xp": 0, "weekly_affiliate_earnings": 0, "affiliate_booster": 0.0})
            
        all_guilds_reset_stream = self.db.collection('guilds').stream()
        async for guild_doc in all_guilds_reset_stream:
            await guild_doc.reference.update({"weekly_xp": 0})
            
        print("Tâche de classement hebdomadaire terminée.")

    @weekly_leaderboard_task.before_loop
    @mission_assignment_task.before_loop
    @check_vip_status_task.before_loop
    @weekly_coaching_report_task.before_loop
    async def before_weekly_task(self):
        await self.bot.wait_until_ready()
    
    # ... The rest of the file would be similarly refactored