"""
Party Cog - Správa družin
SAO × Aurionis edition ⚔️
"""
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List

from src.database.party import PartyManager
from src.utils.embeds import (
    create_error_embed,
    create_success_embed,
    create_party_embed,
    create_parties_list_embed,
)

# ============================================================
# AUTOCOMPLETE HELPERS
# ============================================================

async def public_party_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Autocomplete — zobrazí pouze veřejné party (pro join)."""
    try:
        cog = interaction.client.get_cog("Party")
        if not cog:
            return []
        parties = cog.party_db.list_all_parties()
        items = [name for name, data in parties.items() if not data.get("is_private", False)]
        current_lower = (current or "").lower()
        return [
            app_commands.Choice(name=name, value=name)
            for name in items
            if current_lower in name
        ][:25]
    except Exception:
        return []


async def any_party_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Autocomplete — zobrazí všechny party."""
    try:
        cog = interaction.client.get_cog("Party")
        if not cog:
            return []
        parties = cog.party_db.list_all_parties()
        current_lower = (current or "").lower()
        return [
            app_commands.Choice(name=name, value=name)
            for name in parties
            if current_lower in name
        ][:25]
    except Exception:
        return []


async def user_party_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Autocomplete — zobrazí pouze party ve kterých je daný hráč."""
    try:
        cog = interaction.client.get_cog("Party")
        if not cog:
            return []
        user_parties = cog.party_db.get_user_parties(interaction.user.id)
        current_lower = (current or "").lower()
        return [
            app_commands.Choice(name=name, value=name)
            for name in user_parties
            if current_lower in name
        ][:25]
    except Exception:
        return []


async def party_member_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """
    Autocomplete pro členy party.
    Závisí na parametru 'jmeno' — zobrazí členy zadané party (kromě autora).
    Vrací Choice(name=display_name, value=str(member_id)).
    """
    try:
        cog = interaction.client.get_cog("Party")
        if not cog:
            return []

        party_name = getattr(interaction.namespace, "jmeno", None)
        if not party_name:
            return []

        party_name = party_name.lower()
        party = cog.party_db.get_party(party_name)
        if not party:
            return []

        members = party.get("members", [])
        current_lower = (current or "").lower()
        choices = []
        for member_id in members:
            if member_id == interaction.user.id:
                continue
            member = interaction.guild.get_member(member_id) if interaction.guild else None
            if member:
                display = member.display_name
                if current_lower in display.lower():
                    choices.append(app_commands.Choice(name=display, value=str(member_id)))
        return choices[:25]
    except Exception:
        return []


# ============================================================
# INVITE ACCEPT VIEW
# ============================================================

class InviteAcceptView(discord.ui.View):
    """View pro přijetí/zamítnutí pozvánky do družiny."""

    def __init__(self, bot: commands.Bot, party_db: PartyManager, party_name: str, user_id: int):
        super().__init__(timeout=86400)  # 24 hodin
        self.bot = bot
        self.party_db = party_db
        self.party_name = party_name
        self.user_id = user_id

    @discord.ui.button(label="Přijmout", style=discord.ButtonStyle.green, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Toto není pro tebe!", ephemeral=True)
            return

        # Multi-party check — max 3
        user_parties = self.party_db.get_user_parties(self.user_id)
        if len(user_parties) >= 3:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Plno Družin",
                    "Jsi již ve třech družinách. Nejdřív jednu opusť!"
                ),
                ephemeral=True
            )
            return

        self.party_db.add_member(self.party_name, self.user_id)

        # Přidat do threadu
        party = self.party_db.get_party(self.party_name)
        thread_id = party.get("thread_id") if party else None
        if thread_id:
            thread = self.bot.get_channel(thread_id)
            try:
                if thread:
                    await thread.add_user(interaction.user)
            except Exception:
                pass

        await interaction.response.send_message(
            embed=create_success_embed(
                "⚔️ Vítej v Družině!",
                f"Přijal/a jsi pozvánku do **{self.party_name}**!"
            ),
            ephemeral=True
        )
        await interaction.message.edit(view=None)
        await interaction.message.reply(
            f"✅ {interaction.user.mention} přijal/a pozvánku do **{self.party_name}**!"
        )

    @discord.ui.button(label="Zamítnout", style=discord.ButtonStyle.red, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Toto není pro tebe!", ephemeral=True)
            return

        await interaction.response.send_message(
            "❌ Pozvánku jsi odmítl/a. Tvá volba!",
            ephemeral=True
        )
        await interaction.message.edit(view=None)


# ============================================================
# PARTY SET MODAL
# ============================================================

class PartySetModal(discord.ui.Modal, title="⚔️ Nastavit Identitu Družiny"):
    """Modal pro nastavení identity družiny."""

    def __init__(self, bot: commands.Bot, party_db: PartyManager, party_cog: "Party", party_name: str):
        super().__init__()
        self.bot = bot
        self.party_db = party_db
        self.cog = party_cog
        self.party_name = party_name

        self.new_name = discord.ui.TextInput(
            label="Nové Jméno (opt.)",
            placeholder="nový-název",
            required=False,
            max_length=100
        )
        self.quest = discord.ui.TextInput(
            label="Cíl Výpravy (opt.)",
            placeholder="Vyhledat tajný chrám...",
            required=False,
            max_length=200
        )
        self.emoji = discord.ui.TextInput(
            label="Emblem (opt.)",
            placeholder="🦋",
            required=False,
            max_length=10
        )
        self.barva = discord.ui.TextInput(
            label="Barva Hex (opt.)",
            placeholder="FFAABB",
            required=False,
            max_length=7
        )

        self.add_item(self.new_name)
        self.add_item(self.quest)
        self.add_item(self.emoji)
        self.add_item(self.barva)

    async def on_submit(self, interaction: discord.Interaction):
        old_name = self.party_name
        new_name_input = self.new_name.value.strip().lower() or None
        new_quest = self.quest.value.strip() or None
        new_emoji = self.emoji.value.strip() or None
        new_color = self.barva.value.strip() or None

        party = self.party_db.get_party(old_name)
        if not party:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Družina Neexistuje", f"Družina **{old_name}** nebyla nalezena."),
                ephemeral=True
            )
            return

        if not self.party_db.is_leader(old_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Neoprávněný Přístup", "Pouze vůdce může měnit identitu."),
                ephemeral=True
            )
            return

        changes = []
        final_name = old_name

        # Přejmenování
        if new_name_input and new_name_input != old_name:
            if self.party_db.get_party(new_name_input):
                await interaction.response.send_message(
                    embed=create_error_embed("❌ Název Obsazen", f"Družina **{new_name_input}** už existuje."),
                    ephemeral=True
                )
                return

            old_thread_id = party.get("thread_id")
            if self.party_db.rename_party(old_name, new_name_input):
                if old_thread_id:
                    try:
                        thread = self.bot.get_channel(old_thread_id)
                        if thread:
                            new_party_data = self.party_db.get_party(new_name_input)
                            emoji = new_party_data.get("emoji") if new_party_data else ""
                            new_thread_name = f"{emoji} party-{new_name_input}".strip() if emoji else f"party-{new_name_input}"
                            await thread.edit(name=new_thread_name[:100])
                    except Exception:
                        pass
                changes.append(f"🏷️ Jméno: {old_name} → **{new_name_input}**")
                final_name = new_name_input
            else:
                await interaction.response.send_message(
                    embed=create_error_embed("❌ Chyba Přejmenování", "Nepodařilo se přejmenovat družinu."),
                    ephemeral=True
                )
                return

        # Barva
        if new_color:
            color_hex = self.cog._validate_hex_color(new_color)
            if not color_hex:
                await interaction.response.send_message(
                    embed=create_error_embed("❌ Neplatná Barva", "Hex kód jako `FFAABB` nebo `#FFAABB`."),
                    ephemeral=True
                )
                return
            self.party_db.set_color(final_name, color_hex)
            changes.append(f"🎨 Barva: #{color_hex}")

        # Emoji
        if new_emoji:
            self.party_db.set_emoji(final_name, new_emoji)
            await self.cog._update_thread_emoji(final_name)
            changes.append(f"📿 Emblem: {new_emoji}")

        # Cíl výpravy
        if new_quest:
            self.party_db.set_quest(final_name, new_quest)
            changes.append(f"🗺️ Cíl: {new_quest[:40]}")

        color_int = await self.cog._get_party_color(final_name)

        if changes:
            await interaction.response.send_message(
                embed=create_success_embed("⚔️ Identita Upravena", "\n".join(changes), color=color_int),
                ephemeral=True
            )
        else:
            embed = discord.Embed(
                title="ℹ️ Žádné Změny",
                description="Všechna pole byla prázdná — nic nezměněno.",
                color=color_int
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# PARTY COG
# ============================================================

class Party(commands.Cog):
    """Cog pro správu družin — SAO × Aurionis edition ⚔️"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.party_db = PartyManager()

    # ============================================================
    # HELPERS
    # ============================================================

    def _validate_hex_color(self, color_str: Optional[str]) -> Optional[str]:
        """Validuje a normalizuje hex barvu. Vrací hex bez '#' nebo None."""
        if not color_str:
            return None
        cleaned = color_str.lstrip("#").upper()
        try:
            if len(cleaned) == 6:
                int(cleaned, 16)
                return cleaned
        except Exception:
            pass
        return None

    async def _update_thread_emoji(self, party_name: str):
        """Aktualizuje název threadu s emoji prefixem."""
        party = self.party_db.get_party(party_name)
        if not party:
            return
        thread_id = party.get("thread_id")
        if not thread_id:
            return
        emoji = party.get("emoji")
        new_name = f"{emoji} party-{party_name}" if emoji else f"party-{party_name}"
        try:
            thread = self.bot.get_channel(thread_id)
            if thread:
                await thread.edit(name=new_name)
        except Exception:
            pass

    async def _get_party_color(self, party_name: Optional[str]) -> int:
        """Vrátí int barvu party nebo fallback na bot color."""
        if not party_name:
            return self.bot.color
        party = self.party_db.get_party(party_name)
        if not party or not party.get("color"):
            return self.bot.color
        try:
            return int(party.get("color"), 16)
        except Exception:
            return self.bot.color

    async def _add_to_thread(self, party_name: str, user: discord.Member):
        """Přidá uživatele do party threadu."""
        party = self.party_db.get_party(party_name)
        thread_id = party.get("thread_id") if party else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.add_user(user)
            except Exception:
                pass

    async def _remove_from_thread(self, party_name: str, user: discord.Member):
        """Odebere uživatele z party threadu."""
        party = self.party_db.get_party(party_name)
        thread_id = party.get("thread_id") if party else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.remove_user(user)
            except Exception:
                pass

    async def _create_party_thread(self, interaction: discord.Interaction, jmeno: str, emoji: Optional[str]) -> Optional[int]:
        """Vytvoří private thread pro party. Vrátí thread_id nebo None."""
        try:
            channel_name = self.bot.config.get("campfire_channel", "campfire")
            if interaction.guild:
                channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
                if channel:
                    party_emoji = emoji or ""
                    thread_name = f"{party_emoji} party-{jmeno}".strip() if party_emoji else f"party-{jmeno}"
                    thread = await channel.create_thread(
                        name=thread_name[:100],
                        type=discord.ChannelType.private_thread
                    )
                    await thread.add_user(interaction.user)
                    return thread.id
        except Exception:
            pass
        return None

    # ============================================================
    # LISTENERS
    # ============================================================

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """Vyčistí thread_id pokud byl kanál smazán manuálně."""
        try:
            parties = self.party_db.list_all_parties()
            for name, data in parties.items():
                if data.get("thread_id") == getattr(channel, "id", None):
                    self.party_db.remove_thread_id(name)
                    print(f"   ℹ️ Vymazáno thread_id pro {name} (kanál smazán).")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        """Handler pro smazané thready."""
        try:
            parties = self.party_db.list_all_parties()
            for name, data in parties.items():
                if data.get("thread_id") == thread.id:
                    self.party_db.remove_thread_id(name)
                    print(f"   ℹ️ Vymazáno thread_id pro {name} (thread smazán).")
        except Exception:
            pass

    # ============================================================
    # /party_create
    # ============================================================

    @app_commands.command(name="party_create", description="⚔️ Vytvoř novou družinu")
    @app_commands.describe(
        jmeno="Název nové družiny",
        quest="Cíl nebo popis výpravy",
        soukroma="Soukromá? (default: ne)",
        barva="Hex barva embedu (např. FF5500)",
        emoji="Emoji emblém"
    )
    async def party_create(
        self,
        interaction: discord.Interaction,
        jmeno: str,
        quest: Optional[str] = None,
        soukroma: Optional[bool] = None,
        barva: Optional[str] = None,
        emoji: Optional[str] = None,
    ):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        # Max 3 party
        user_parties = self.party_db.get_user_parties(user_id)
        if len(user_parties) >= 3:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Příliš Mnoho Družin",
                    "Jsi již ve třech družinách. Nejdřív jednu opusť!"
                ),
                ephemeral=True
            )
            return

        if self.party_db.get_party(jmeno):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Název Obsazen", f"Družina **{jmeno}** už existuje."),
                ephemeral=True
            )
            return

        quest = quest or "Putování neznámem..."
        is_private = soukroma or False
        self.party_db.create_party(jmeno, user_id, quest, is_private)

        if barva:
            color_hex = self._validate_hex_color(barva)
            if color_hex:
                self.party_db.set_color(jmeno, color_hex)

        if emoji:
            self.party_db.set_emoji(jmeno, emoji.strip())

        thread_id = await self._create_party_thread(interaction, jmeno, emoji)
        if thread_id:
            self.party_db.set_thread_id(jmeno, thread_id)

        privacy_text = "🔒 Soukromá" if is_private else "🔓 Veřejná"
        msg = f"Jsi vůdce. Status: {privacy_text}\nCíl: `{quest}`"
        if not thread_id:
            msg += "\n⚠️ Kanál 'campfire' nenalezen — thread nevytvořen"

        color_int = await self._get_party_color(jmeno)
        await interaction.response.send_message(
            embed=create_success_embed(f"⚔️ Družina {jmeno} Vytvořena!", msg, color=color_int)
        )

    # ============================================================
    # /party_join
    # ============================================================

    @app_commands.command(name="party_join", description="🛡️ Připoj se k existující družině")
    @app_commands.describe(jmeno="Název družiny (veřejné se autocompletují)")
    @app_commands.autocomplete(jmeno=public_party_autocomplete)
    async def party_join(self, interaction: discord.Interaction, jmeno: str):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        user_parties = self.party_db.get_user_parties(user_id)
        if len(user_parties) >= 3:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Příliš Mnoho Družin", "Jsi již ve třech družinách!"),
                ephemeral=True
            )
            return

        party_data = self.party_db.get_party(jmeno)
        if not party_data:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Družina Neexistuje", f"Družina **{jmeno}** nebyla nalezena."),
                ephemeral=True
            )
            return

        if jmeno in user_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Již Jsi Členem", f"Jsi už v **{jmeno}**."),
                ephemeral=True
            )
            return

        if party_data.get("is_private", False):
            if not self.party_db.is_on_whitelist(jmeno, user_id):
                await interaction.response.send_message(
                    embed=create_error_embed(
                        "❌ Soukromá Družina",
                        f"**{jmeno}** je soukromá. Potřebuješ pozvánku od vůdce!"
                    ),
                    ephemeral=True
                )
                return

        self.party_db.add_member(jmeno, user_id)
        await self._add_to_thread(jmeno, interaction.user)

        color_int = await self._get_party_color(jmeno)
        await interaction.response.send_message(
            embed=create_success_embed(
                f"🛡️ Vítej v {jmeno}!",
                f"Úspěšně jsi se připojil/a k **{jmeno}**.",
                color=color_int
            )
        )

    # ============================================================
    # /party_leave
    # ============================================================

    @app_commands.command(name="party_leave", description="🚶 Opusť jednu ze svých družin")
    @app_commands.describe(jmeno="Která družina? (autocompletují se tvoje)")
    @app_commands.autocomplete(jmeno=user_party_autocomplete)
    async def party_leave(self, interaction: discord.Interaction, jmeno: str):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        user_parties = self.party_db.get_user_parties(user_id)
        if jmeno not in user_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Téhle Družině", f"Nejsi členem **{jmeno}**."),
                ephemeral=True
            )
            return

        if self.party_db.is_leader(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Vůdce Nemůže Odejít",
                    "Nejdřív předej vedení (`/party_promote`) nebo rozpusť (`/party_disband`)."
                ),
                ephemeral=True
            )
            return

        self.party_db.remove_member(jmeno, user_id)
        await self._remove_from_thread(jmeno, interaction.user)

        await interaction.response.send_message(
            embed=create_success_embed("🚶 Odešel/a Jsi", f"Opustil/a jsi **{jmeno}**.")
        )

    # ============================================================
    # /party_disband
    # ============================================================

    @app_commands.command(name="party_disband", description="🔥 Rozpusť jednu ze svých družin (vůdce)")
    @app_commands.describe(jmeno="Která družina? (autocompletují se tvoje)")
    @app_commands.autocomplete(jmeno=user_party_autocomplete)
    async def party_disband(self, interaction: discord.Interaction, jmeno: str):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        user_parties = self.party_db.get_user_parties(user_id)
        if jmeno not in user_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Téhle Družině", f"Nejsi členem **{jmeno}**."),
                ephemeral=True
            )
            return

        if not self.party_db.is_leader(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", f"Pouze vůdce může rozpustit **{jmeno}**."),
                ephemeral=True
            )
            return

        party = self.party_db.get_party(jmeno)
        thread_id = party.get("thread_id") if party else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.delete()
            except Exception:
                pass

        self.party_db.delete_party(jmeno)

        await interaction.response.send_message(
            embed=create_success_embed(
                f"🔥 Družina {jmeno} Rozpuštěna",
                "Všichni členové byli propuštěni. Cesty se rozcházejí..."
            )
        )

    # ============================================================
    # /party_invite
    # ============================================================

    @app_commands.command(name="party_invite", description="✉️ Pozvi hráče do své družiny (vůdce)")
    @app_commands.describe(
        jmeno="Tvoja družina (autocompletují se tvoje)",
        clen="Hráč, kterého chceš pozvat"
    )
    @app_commands.autocomplete(jmeno=user_party_autocomplete)
    async def party_invite(
        self,
        interaction: discord.Interaction,
        jmeno: str,
        clen: discord.Member,
    ):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        # Validace PŘED deferem — tyto checky jsou rychlé (pouze DB lookup)
        user_parties = self.party_db.get_user_parties(user_id)
        if jmeno not in user_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Téhle Družině", f"Nejsi členem **{jmeno}**."),
                ephemeral=True
            )
            return

        if not self.party_db.is_leader(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Pouze vůdce může posílat pozvánky."),
                ephemeral=True
            )
            return

        if clen.id == user_id:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nemůžeš Pozvat Sebe", "Jsi už v družině!"),
                ephemeral=True
            )
            return

        clen_parties = self.party_db.get_user_parties(clen.id)

        if jmeno in clen_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Již Je Členem", f"{clen.mention} je už v **{jmeno}**."),
                ephemeral=True
            )
            return

        if len(clen_parties) >= 3:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Hráč Má Plno Družin",
                    f"{clen.mention} je již ve třech družinách."
                ),
                ephemeral=True
            )
            return

        if not self.party_db.can_invite(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Příliš Mnoho Pozvánek", "Max 3 pozvánky za den."),
                ephemeral=True
            )
            return

        # Defer PŘED DM odesláním — DM může trvat déle než 3s a Discord by vyhodil timeout
        await interaction.response.defer(ephemeral=True)

        self.party_db.add_to_whitelist(jmeno, clen.id)
        self.party_db.record_invite(jmeno, user_id)

        party_data = self.party_db.get_party(jmeno)
        try:
            invite_color = int(party_data.get("color"), 16) if party_data and party_data.get("color") else self.bot.color
        except Exception:
            invite_color = self.bot.color

        invite_embed = discord.Embed(
            title=f"⚔️ Pozvánka do Družiny **{jmeno}**!",
            description=f"{interaction.user.mention} tě pozval/a do své družiny ve světě Aurionis!",
            color=invite_color
        )
        invite_embed.add_field(name="🗺️ Cíl", value=f"`{party_data['quest']}`", inline=False)
        invite_embed.add_field(name="👥 Členů", value=str(len(party_data["members"])), inline=True)

        try:
            view = InviteAcceptView(self.bot, self.party_db, jmeno, clen.id)
            await clen.send(embed=invite_embed, view=view)
        except discord.Forbidden:
            # Rollback whitelist a invite záznam pokud DM selže
            self.party_db.remove_from_whitelist(jmeno, clen.id)
            await interaction.followup.send(
                embed=create_error_embed("❌ DM Zamčené", f"{clen.mention} má zamčené DM."),
                ephemeral=True
            )
            return

        await interaction.followup.send(
            embed=create_success_embed("✉️ Pozvánka Odeslána", f"Pozvánka doručena {clen.mention}."),
            ephemeral=True
        )

    # ============================================================
    # /party_kick
    # ============================================================

    @app_commands.command(name="party_kick", description="👢 Vyhoď člena z družiny (vůdce)")
    @app_commands.describe(
        jmeno="Tvoja družina (autocompletují se tvoje)",
        clen="Člen k vyhození (autocompletuje se po zadání jmeno)"
    )
    @app_commands.autocomplete(jmeno=user_party_autocomplete, clen=party_member_autocomplete)
    async def party_kick(
        self,
        interaction: discord.Interaction,
        jmeno: str,
        clen: str,  # str ID z autocomplete
    ):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        try:
            clen_id = int(clen)
        except ValueError:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Neplatný Člen", "Vyber člena z autocomplete nabídky."),
                ephemeral=True
            )
            return

        user_parties = self.party_db.get_user_parties(user_id)
        if jmeno not in user_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Téhle Družině", f"Nejsi členem **{jmeno}**."),
                ephemeral=True
            )
            return

        if not self.party_db.is_leader(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Pouze vůdce může vyhazovat členy."),
                ephemeral=True
            )
            return

        if clen_id == user_id:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nemůžeš Vyhodit Sebe", "Použij `/party_disband` pro rozpuštění."),
                ephemeral=True
            )
            return

        clen_parties = self.party_db.get_user_parties(clen_id)
        if jmeno not in clen_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Člen Není v Téhle Družině", f"Hráč není členem **{jmeno}**."),
                ephemeral=True
            )
            return

        self.party_db.remove_member(jmeno, clen_id)

        clen_member = interaction.guild.get_member(clen_id) if interaction.guild else None
        if clen_member:
            await self._remove_from_thread(jmeno, clen_member)

        await interaction.response.send_message(
            embed=create_success_embed("👢 Člen Vyhozen", f"<@{clen_id}> byl/a vyhozen/a z **{jmeno}**.")
        )

    # ============================================================
    # /party_promote
    # ============================================================

    @app_commands.command(name="party_promote", description="👑 Předej vedení družiny jinému členovi")
    @app_commands.describe(
        jmeno="Tvoja družina (autocompletují se tvoje)",
        clen="Nový vůdce (autocompletuje se po zadání jmeno)"
    )
    @app_commands.autocomplete(jmeno=user_party_autocomplete, clen=party_member_autocomplete)
    async def party_promote(
        self,
        interaction: discord.Interaction,
        jmeno: str,
        clen: str,  # str ID z autocomplete
    ):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        try:
            clen_id = int(clen)
        except ValueError:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Neplatný Člen", "Vyber člena z autocomplete nabídky."),
                ephemeral=True
            )
            return

        user_parties = self.party_db.get_user_parties(user_id)
        if jmeno not in user_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Téhle Družině", f"Nejsi členem **{jmeno}**."),
                ephemeral=True
            )
            return

        if not self.party_db.is_leader(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Pouze vůdce může předat vedení."),
                ephemeral=True
            )
            return

        if clen_id == user_id:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Jsi Již Vůdce", "Nemůžeš předat vedení sám/a sobě."),
                ephemeral=True
            )
            return

        clen_parties = self.party_db.get_user_parties(clen_id)
        if jmeno not in clen_parties:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Člen Není v Téhle Družině", f"Hráč není členem **{jmeno}**."),
                ephemeral=True
            )
            return

        self.party_db.set_leader(jmeno, clen_id)

        color_int = await self._get_party_color(jmeno)
        await interaction.response.send_message(
            embed=create_success_embed(
                "👑 Vedení Předáno",
                f"<@{clen_id}> je nyní novým vůdcem **{jmeno}**!",
                color=color_int
            )
        )

    # ============================================================
    # /party_list
    # ============================================================

    @app_commands.command(name="party_list", description="📜 Zobraz seznam všech družin")
    async def party_list(self, interaction: discord.Interaction):
        parties = self.party_db.list_all_parties()
        embed = create_parties_list_embed(parties, color=self.bot.color)
        await interaction.response.send_message(embed=embed)

    # ============================================================
    # /party_info
    # ============================================================

    @app_commands.command(name="party_info", description="🔍 Zobraz info o jedné ze svých družin")
    @app_commands.describe(jmeno="Která? (autocompletují se tvoje — nech prázdné pro první)")
    @app_commands.autocomplete(jmeno=user_party_autocomplete)
    async def party_info(self, interaction: discord.Interaction, jmeno: str = ""):
        """
        Zobrazí info o družině.
        Discord neumí Optional[str] s autocomplete bez 'not responding' — používáme str s default "".
        """
        user_id = interaction.user.id

        # Pokud nezadal jmeno, vezmi první jeho party
        if not jmeno:
            user_parties = self.party_db.get_user_parties(user_id)
            if not user_parties:
                await interaction.response.send_message(
                    embed=create_error_embed(
                        "❌ Nejsi v Žádné Družině",
                        "Připoj se pomocí `/party_join`!"
                    ),
                    ephemeral=True
                )
                return
            jmeno = user_parties[0]
        else:
            jmeno = jmeno.lower()

        party_data = self.party_db.get_party(jmeno)
        if not party_data:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Družina Neexistuje", f"Družina **{jmeno}** nebyla nalezena."),
                ephemeral=True
            )
            return

        party_emoji = party_data.get("emoji")
        try:
            party_color = int(party_data.get("color"), 16) if party_data.get("color") else self.bot.color
        except Exception:
            party_color = self.bot.color

        embed = create_party_embed(
            party_name=jmeno,
            quest=party_data["quest"],
            members=party_data["members"],
            leader_id=party_data["leader"],
            is_private=party_data.get("is_private", False),
            color=party_color,
            emoji=party_emoji
        )
        await interaction.response.send_message(embed=embed)

    # ============================================================
    # /party_set
    # ============================================================

    @app_commands.command(name="party_set", description="⚙️ Nastav identitu své družiny (vůdce)")
    @app_commands.describe(jmeno="Která? (autocompletují se tvoje)")
    @app_commands.autocomplete(jmeno=user_party_autocomplete)
    async def party_set(self, interaction: discord.Interaction, jmeno: str):
        jmeno = jmeno.lower()

        party = self.party_db.get_party(jmeno)
        if not party:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Družina Neexistuje", f"Družina **{jmeno}** nebyla nalezena."),
                ephemeral=True
            )
            return

        if not self.party_db.is_leader(jmeno, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Pouze vůdce může měnit identitu."),
                ephemeral=True
            )
            return

        modal = PartySetModal(self.bot, self.party_db, self, jmeno)
        await interaction.response.send_modal(modal)

    # ============================================================
    # /party_help
    # ============================================================

    @app_commands.command(name="party_help", description="📖 Nápověda k systému družin")
    async def party_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🐱 Arion — Průvodce Světem Aurionis",
            description=(
                "*Přátelé, ve světě Aurionis nikdo nechodí sám...*\n\n"
                "Můžeš být členem až **tří** různých družin zároveň!"
            ),
            color=self.bot.color
        )
        embed.add_field(
            name="📚 Příkazy",
            value=(
                "`/party_create` — Vytvoř novou družinu\n"
                "`/party_join` — Připoj se (veřejné se autocompletují)\n"
                "`/party_leave` — Opusť jednu ze svých\n"
                "`/party_disband` — Rozpusť svou (vůdce)\n"
                "`/party_invite` — Pozvi hráče (vůdce)\n"
                "`/party_kick` — Vyhoď člena (vůdce)\n"
                "`/party_promote` — Předej vedení (vůdce)\n"
                "`/party_set` — Nastavení identity (vůdce)\n"
                "`/party_list` — Všechny družiny\n"
                "`/party_info` — Detail tvé družiny\n"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 Tipy",
            value=(
                "🔓 Veřejné party se autocompletují při `/party_join`.\n"
                "🔒 Soukromé vyžadují pozvánku od vůdce.\n"
                "👥 Pro kick/promote zadej nejdřív jméno party, pak se autocompletují členové."
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="party_legacy",
        description="(Odstraněno) Použij /party_create, /party_join atd."
    )
    async def party_legacy(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=create_error_embed(
                "⚠️ Příkaz odstraněn",
                "Použij nové příkazy: `/party_create`, `/party_join`, `/party_leave` atd."
            ),
            ephemeral=True
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot):
    """Nainstaluje Party cog"""
    await bot.add_cog(Party(bot))