"""
Guilds Cog - Správa guild
SAO × Aurionis edition 🏰

Guildy jsou STÁLÉ a EXKLUZIVNÍ (1 guilda na hráče), se 3 hodnostmi:
    👑 guildmaster → 🛡️ officer → ⚔️ member

Umístění: src/core/dnd/guilds.py
Datová vrstva: src/database/guild.py (GuildManager)
"""
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List

from src.database.guild import GuildManager
from src.utils.embeds import (
    create_error_embed,
    create_success_embed,
    create_guild_embed,
    create_guilds_list_embed,
)

# Odznaky režimu náboru (pro hlášky)
RECRUITMENT_LABELS = {
    "open": "🟢 Otevřená",
    "apply": "🟡 Na přihlášku",
    "closed": "🔴 Uzavřená",
}

RECRUITMENT_CHOICES = [
    app_commands.Choice(name="🟢 Otevřená (kdokoli vstoupí)", value="open"),
    app_commands.Choice(name="🟡 Na přihlášku (schvaluje officer)", value="apply"),
    app_commands.Choice(name="🔴 Uzavřená (jen na pozvánku)", value="closed"),
]


# ============================================================
# AUTOCOMPLETE HELPERS
# ============================================================

def _get_cog(interaction: discord.Interaction) -> Optional["Guilds"]:
    return interaction.client.get_cog("Guilds")


async def open_guild_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Guildy s otevřeným náborem (pro /guild_join)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guilds = cog.guild_db.list_all_guilds()
        cur = (current or "").lower()
        return [
            app_commands.Choice(name=name, value=name)
            for name, data in guilds.items()
            if data.get("recruitment", "open") == "open" and cur in name
        ][:25]
    except Exception:
        return []


async def apply_guild_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Guildy v režimu 'apply' (pro /guild_apply)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guilds = cog.guild_db.list_all_guilds()
        cur = (current or "").lower()
        return [
            app_commands.Choice(name=name, value=name)
            for name, data in guilds.items()
            if data.get("recruitment", "open") == "apply" and cur in name
        ][:25]
    except Exception:
        return []


async def any_guild_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Všechny guildy (pro /guild_info cizí guildy)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guilds = cog.guild_db.list_all_guilds()
        cur = (current or "").lower()
        return [app_commands.Choice(name=n, value=n) for n in guilds if cur in n][:25]
    except Exception:
        return []


def _member_choices(interaction, member_ids, current: str):
    """Pomocník — z member_ids udělá Choice(display_name, str(id)), kromě autora."""
    cur = (current or "").lower()
    choices = []
    for mid in member_ids:
        if mid == interaction.user.id:
            continue
        member = interaction.guild.get_member(mid) if interaction.guild else None
        display = member.display_name if member else str(mid)
        if cur in display.lower():
            choices.append(app_commands.Choice(name=display, value=str(mid)))
    return choices[:25]


async def my_member_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Členové MÉ guildy (kromě mě) — pro kick/transfer."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guild_name = cog.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            return []
        guild = cog.guild_db.get_guild(guild_name)
        return _member_choices(interaction, guild.get("members", []), current)
    except Exception:
        return []


async def my_promotable_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Členové MÉ guildy, kteří NEjsou officeři (pro /guild_promote)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guild_name = cog.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            return []
        guild = cog.guild_db.get_guild(guild_name)
        officers = guild.get("officers", [])
        gm = guild.get("guildmaster")
        plain = [m for m in guild.get("members", []) if m not in officers and m != gm]
        return _member_choices(interaction, plain, current)
    except Exception:
        return []


async def my_officer_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Officeři MÉ guildy (pro /guild_demote)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guild_name = cog.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            return []
        guild = cog.guild_db.get_guild(guild_name)
        return _member_choices(interaction, guild.get("officers", []), current)
    except Exception:
        return []


async def my_applicant_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Čekající žadatelé do MÉ guildy (pro /guild_accept, /guild_deny)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        guild_name = cog.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            return []
        apps = cog.guild_db.list_applications(guild_name)
        return _member_choices(interaction, apps, current)
    except Exception:
        return []


async def my_pending_apps_autocomplete(interaction, current: str) -> List[app_commands.Choice[str]]:
    """Guildy, kam má hráč čekající přihlášku (pro /guild_withdraw)."""
    try:
        cog = _get_cog(interaction)
        if not cog:
            return []
        uid = interaction.user.id
        cur = (current or "").lower()
        guilds = cog.guild_db.list_all_guilds()
        return [
            app_commands.Choice(name=n, value=n)
            for n, d in guilds.items()
            if uid in d.get("applications", []) and cur in n
        ][:25]
    except Exception:
        return []


# ============================================================
# INVITE ACCEPT VIEW (DM pozvánka)
# ============================================================

class GuildInviteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"gi:(?P<action>a|d):(?P<user>\d+):(?P<guild>.+)",
):
    """
    Persistentní tlačítko pozvánky do guildy.

    Stav (guilda + komu) je zakódovaný v custom_id, takže tlačítka
    fungují i po restartu bota (na rozdíl od klasického View s timeoutem).
    Registruje se přes bot.add_dynamic_items(GuildInviteButton) v cog_load.
    Vyžaduje discord.py >= 2.4.
    """

    def __init__(self, action: str, user_id: int, guild_name: str):
        self.action = action
        self.user_id = user_id
        self.guild_name = guild_name
        is_accept = action == "a"
        super().__init__(
            discord.ui.Button(
                label="Přijmout" if is_accept else "Zamítnout",
                style=discord.ButtonStyle.green if is_accept else discord.ButtonStyle.red,
                emoji="✅" if is_accept else "✖️",
                custom_id=f"gi:{action}:{user_id}:{guild_name}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["user"]), match["guild"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Guilds")
        if not cog:
            await interaction.response.send_message("⚠️ Guild systém není načtený.", ephemeral=True)
            return
        db = cog.guild_db

        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Toto není pro tebe!", ephemeral=True)
            return

        # Zamítnutí
        if self.action == "d":
            db.remove_from_whitelist(self.guild_name, self.user_id)
            await interaction.response.edit_message(
                content="✖️ Pozvánku jsi odmítl/a.", embed=None, view=None
            )
            return

        # Přijetí — exkluzivita
        current = db.get_user_guild(self.user_id)
        if current:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Už Jsi v Guildě",
                    f"Jsi členem **{current}**. Nejdřív ji opusť (`/guild_leave`)."
                ),
                ephemeral=True,
            )
            return

        if not db.get_guild(self.guild_name):
            await interaction.response.edit_message(
                content="⚠️ Tahle guilda už neexistuje.", embed=None, view=None
            )
            return

        if db.is_full(self.guild_name):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Je Plná", f"**{self.guild_name}** dosáhla kapacity."),
                ephemeral=True,
            )
            return

        if not db.add_member(self.guild_name, self.user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nepodařilo Se", "Vstup do guildy selhal."),
                ephemeral=True,
            )
            return

        # Přidat do threadu
        guild = db.get_guild(self.guild_name)
        thread_id = guild.get("thread_id") if guild else None
        if thread_id:
            try:
                thread = cog.bot.get_channel(thread_id)
                if thread:
                    await thread.add_user(interaction.user)
            except Exception:
                pass

        await interaction.response.edit_message(
            content=f"🏰 Vítej v **{self.guild_name}**! Přijal/a jsi pozvánku.",
            embed=None,
            view=None,
        )


def build_guild_invite_view(user_id: int, guild_name: str) -> discord.ui.View:
    """Sestaví View se dvěma persistentními tlačítky pozvánky."""
    view = discord.ui.View(timeout=None)
    view.add_item(GuildInviteButton("a", user_id, guild_name))
    view.add_item(GuildInviteButton("d", user_id, guild_name))
    return view


# ============================================================
# CONFIRM VIEW (potvrzení nevratných akcí)
# ============================================================

class ConfirmView(discord.ui.View):
    """Jednoduché potvrzení 'Opravdu?' pro nevratné akce."""

    def __init__(self, author_id: int, confirm_label: str = "Ano, opravdu",
                 confirm_style: discord.ButtonStyle = discord.ButtonStyle.danger):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value: Optional[bool] = None
        self.confirm.label = confirm_label
        self.confirm.style = confirm_style

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Toto není pro tebe!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ano, opravdu", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(content="⏳ Provádím…", embed=None, view=None)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="✖️ Zrušeno.", embed=None, view=None)

    async def on_timeout(self):
        self.value = False


# ============================================================
# GUILD SET MODAL (identita)
# ============================================================

class GuildSetModal(discord.ui.Modal, title="🏰 Nastavit Identitu Guildy"):
    """Modal pro úpravu identity guildy (vůdce)."""

    def __init__(self, bot, guild_db: GuildManager, cog: "Guilds", guild_name: str):
        super().__init__()
        self.bot = bot
        self.guild_db = guild_db
        self.cog = cog
        self.guild_name = guild_name

        self.new_name = discord.ui.TextInput(label="Nové jméno (opt.)", required=False, max_length=100)
        self.tag = discord.ui.TextInput(label="Tag / zkratka (opt.)", placeholder="AUR", required=False, max_length=5)
        self.motto = discord.ui.TextInput(label="Motto (opt.)", required=False, max_length=200)
        self.emoji = discord.ui.TextInput(label="Emblem (opt.)", placeholder="🏰", required=False, max_length=10)
        self.barva = discord.ui.TextInput(label="Barva hex (opt.)", placeholder="FFAABB", required=False, max_length=7)

        for item in (self.new_name, self.tag, self.motto, self.emoji, self.barva):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        old_name = self.guild_name
        guild = self.guild_db.get_guild(old_name)
        if not guild:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Neexistuje", f"**{old_name}** nebyla nalezena."),
                ephemeral=True
            )
            return

        if not self.guild_db.is_guildmaster(old_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Pouze vůdce může měnit identitu."),
                ephemeral=True
            )
            return

        changes = []
        final_name = old_name

        # Přejmenování
        new_name_input = self.new_name.value.strip().lower() or None
        if new_name_input and new_name_input != old_name:
            if self.guild_db.get_guild(new_name_input):
                await interaction.response.send_message(
                    embed=create_error_embed("❌ Název Obsazen", f"**{new_name_input}** už existuje."),
                    ephemeral=True
                )
                return
            old_thread_id = guild.get("thread_id")
            if self.guild_db.rename_guild(old_name, new_name_input):
                final_name = new_name_input
                changes.append(f"🏷️ Jméno: {old_name} → **{new_name_input}**")
                if old_thread_id:
                    try:
                        thread = self.bot.get_channel(old_thread_id)
                        if thread:
                            gd = self.guild_db.get_guild(new_name_input)
                            emoji = gd.get("emoji") if gd else ""
                            tn = f"{emoji} guild-{new_name_input}".strip() if emoji else f"guild-{new_name_input}"
                            await thread.edit(name=tn[:100])
                    except Exception:
                        pass

        # Tag
        if self.tag.value.strip():
            self.guild_db.set_tag(final_name, self.tag.value.strip())
            changes.append(f"🔖 Tag: [{self.tag.value.strip().upper()}]")

        # Barva
        if self.barva.value.strip():
            color_hex = self.cog._validate_hex_color(self.barva.value.strip())
            if not color_hex:
                await interaction.response.send_message(
                    embed=create_error_embed("❌ Neplatná Barva", "Hex jako `FFAABB`."),
                    ephemeral=True
                )
                return
            self.guild_db.set_color(final_name, color_hex)
            changes.append(f"🎨 Barva: #{color_hex}")

        # Emoji
        if self.emoji.value.strip():
            self.guild_db.set_emoji(final_name, self.emoji.value.strip())
            await self.cog._update_thread_emoji(final_name)
            changes.append(f"📿 Emblem: {self.emoji.value.strip()}")

        # Motto
        if self.motto.value.strip():
            self.guild_db.set_quest(final_name, self.motto.value.strip())
            changes.append(f"🗺️ Motto: {self.motto.value.strip()[:40]}")

        color_int = await self.cog._get_guild_color(final_name)
        if changes:
            await interaction.response.send_message(
                embed=create_success_embed("🏰 Identita Upravena", "\n".join(changes), color=color_int),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=create_error_embed("ℹ️ Žádné Změny", "Všechna pole byla prázdná."),
                ephemeral=True
            )


# ============================================================
# GUILDS COG
# ============================================================

class Guilds(commands.Cog):
    """Cog pro správu guild — SAO × Aurionis edition 🏰"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_db = GuildManager()

    async def cog_load(self):
        # Registrace persistentních tlačítek pozvánek (přežijí restart bota).
        try:
            self.bot.add_dynamic_items(GuildInviteButton)
        except AttributeError:
            # discord.py < 2.4 — DynamicItem není dostupný; pozvánky pak
            # nepřežijí restart, ale jinak fungují.
            pass

    # ============================================================
    # HELPERS
    # ============================================================

    def _validate_hex_color(self, color_str: Optional[str]) -> Optional[str]:
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

    async def _get_guild_color(self, guild_name: Optional[str]) -> int:
        if not guild_name:
            return self.bot.color
        guild = self.guild_db.get_guild(guild_name)
        if not guild or not guild.get("color"):
            return self.bot.color
        try:
            return int(guild.get("color"), 16)
        except Exception:
            return self.bot.color

    async def _update_thread_emoji(self, guild_name: str):
        guild = self.guild_db.get_guild(guild_name)
        if not guild or not guild.get("thread_id"):
            return
        emoji = guild.get("emoji")
        new_name = f"{emoji} guild-{guild_name}" if emoji else f"guild-{guild_name}"
        try:
            thread = self.bot.get_channel(guild["thread_id"])
            if thread:
                await thread.edit(name=new_name[:100])
        except Exception:
            pass

    async def _add_to_thread(self, guild_name: str, user: discord.Member):
        guild = self.guild_db.get_guild(guild_name)
        thread_id = guild.get("thread_id") if guild else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.add_user(user)
            except Exception:
                pass

    async def _remove_from_thread(self, guild_name: str, user: discord.Member):
        guild = self.guild_db.get_guild(guild_name)
        thread_id = guild.get("thread_id") if guild else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.remove_user(user)
            except Exception:
                pass

    async def _create_guild_thread(self, interaction, guild_name: str, emoji: Optional[str]) -> Optional[int]:
        try:
            channel_name = self.bot.config.get("campfire_channel", "campfire")
            if interaction.guild:
                channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
                if channel:
                    pref = emoji or ""
                    tn = f"{pref} guild-{guild_name}".strip() if pref else f"guild-{guild_name}"
                    thread = await channel.create_thread(name=tn[:100], type=discord.ChannelType.private_thread)
                    await thread.add_user(interaction.user)
                    return thread.id
        except Exception:
            pass
        return None

    async def _resolve_member_id(self, interaction, clen: str) -> Optional[int]:
        try:
            return int(clen)
        except (ValueError, TypeError):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Neplatný Člen", "Vyber člena z autocomplete nabídky."),
                ephemeral=True
            )
            return None

    async def _notify_officers(self, guild_name: str, embed: discord.Embed):
        """Pošle embed do guild threadu (notifikace officerům)."""
        guild = self.guild_db.get_guild(guild_name)
        thread_id = guild.get("thread_id") if guild else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.send(embed=embed)
            except Exception:
                pass

    # ============================================================
    # LISTENERS — úklid thread_id
    # ============================================================

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        try:
            for name, data in self.guild_db.list_all_guilds().items():
                if data.get("thread_id") == getattr(channel, "id", None):
                    self.guild_db.remove_thread_id(name)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        try:
            for name, data in self.guild_db.list_all_guilds().items():
                if data.get("thread_id") == thread.id:
                    self.guild_db.remove_thread_id(name)
        except Exception:
            pass

    # ============================================================
    # /guild_create
    # ============================================================

    @app_commands.command(name="guild_create", description="🏰 Založ novou guildu (staneš se vůdcem)")
    @app_commands.describe(
        jmeno="Název guildy",
        motto="Motto / cíl guildy",
        tag="Zkratka (2–5 znaků, zobrazí se jako [TAG])",
        nabor="Režim náboru (default: otevřená)",
        barva="Hex barva embedu (např. FF5500)",
        emoji="Emoji emblém",
    )
    @app_commands.choices(nabor=RECRUITMENT_CHOICES)
    async def guild_create(
        self,
        interaction: discord.Interaction,
        jmeno: str,
        motto: Optional[str] = None,
        tag: Optional[str] = None,
        nabor: Optional[app_commands.Choice[str]] = None,
        barva: Optional[str] = None,
        emoji: Optional[str] = None,
    ):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        # Exkluzivita
        current = self.guild_db.get_user_guild(user_id)
        if current:
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Už Jsi v Guildě",
                    f"Jsi členem **{current}**. Guilda je na celý život (no, skoro) — nejdřív ji opusť."
                ),
                ephemeral=True
            )
            return

        if self.guild_db.get_guild(jmeno):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Název Obsazen", f"Guilda **{jmeno}** už existuje."),
                ephemeral=True
            )
            return

        motto = motto or "Společně silnější..."
        recruitment = nabor.value if nabor else "open"

        if not self.guild_db.create_guild(jmeno, user_id, motto, tag=tag, recruitment=recruitment):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nepodařilo Se", "Založení guildy selhalo."),
                ephemeral=True
            )
            return

        if barva:
            color_hex = self._validate_hex_color(barva)
            if color_hex:
                self.guild_db.set_color(jmeno, color_hex)
        if emoji:
            self.guild_db.set_emoji(jmeno, emoji.strip())

        thread_id = await self._create_guild_thread(interaction, jmeno, emoji)
        if thread_id:
            self.guild_db.set_thread_id(jmeno, thread_id)

        msg = f"Jsi 👑 vůdce. Nábor: {RECRUITMENT_LABELS.get(recruitment)}\nMotto: `{motto}`"
        if not thread_id:
            msg += "\n⚠️ Kanál 'campfire' nenalezen — thread nevytvořen."

        color_int = await self._get_guild_color(jmeno)
        await interaction.response.send_message(
            embed=create_success_embed(f"🏰 Guilda {jmeno} Založena!", msg, color=color_int)
        )

    # ============================================================
    # /guild_join
    # ============================================================

    @app_commands.command(name="guild_join", description="🛡️ Vstup do otevřené guildy")
    @app_commands.describe(jmeno="Název guildy (otevřené se autocompletují)")
    @app_commands.autocomplete(jmeno=open_guild_autocomplete)
    async def guild_join(self, interaction: discord.Interaction, jmeno: str):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        current = self.guild_db.get_user_guild(user_id)
        if current:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Už Jsi v Guildě", f"Jsi členem **{current}**. Nejdřív ji opusť."),
                ephemeral=True
            )
            return

        guild = self.guild_db.get_guild(jmeno)
        if not guild:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Neexistuje", f"**{jmeno}** nebyla nalezena."),
                ephemeral=True
            )
            return

        if self.guild_db.is_full(jmeno):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Je Plná", f"**{jmeno}** dosáhla kapacity."),
                ephemeral=True
            )
            return

        recruitment = guild.get("recruitment", "open")
        on_wl = self.guild_db.is_on_whitelist(jmeno, user_id)

        if recruitment == "apply" and not on_wl:
            await interaction.response.send_message(
                embed=create_error_embed("🟡 Na Přihlášku", f"**{jmeno}** přijímá přes `/guild_apply`."),
                ephemeral=True
            )
            return
        if recruitment == "closed" and not on_wl:
            await interaction.response.send_message(
                embed=create_error_embed("🔴 Uzavřená Guilda", f"**{jmeno}** přijímá jen na pozvánku od officera."),
                ephemeral=True
            )
            return

        if not self.guild_db.add_member(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nepodařilo Se", "Vstup selhal."),
                ephemeral=True
            )
            return

        await self._add_to_thread(jmeno, interaction.user)
        color_int = await self._get_guild_color(jmeno)
        await interaction.response.send_message(
            embed=create_success_embed(f"🛡️ Vítej v {jmeno}!", f"Připojil/a ses k **{jmeno}**.", color=color_int)
        )

    # ============================================================
    # /guild_apply
    # ============================================================

    @app_commands.command(name="guild_apply", description="📝 Podej přihlášku do guildy (režim na přihlášku)")
    @app_commands.describe(jmeno="Název guildy (na přihlášku se autocompletují)")
    @app_commands.autocomplete(jmeno=apply_guild_autocomplete)
    async def guild_apply(self, interaction: discord.Interaction, jmeno: str):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        current = self.guild_db.get_user_guild(user_id)
        if current:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Už Jsi v Guildě", f"Jsi členem **{current}**."),
                ephemeral=True
            )
            return

        guild = self.guild_db.get_guild(jmeno)
        if not guild:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Neexistuje", f"**{jmeno}** nebyla nalezena."),
                ephemeral=True
            )
            return

        if guild.get("recruitment", "open") != "apply":
            await interaction.response.send_message(
                embed=create_error_embed("ℹ️ Nepřijímá Přihlášky", f"**{jmeno}** není v režimu na přihlášku."),
                ephemeral=True
            )
            return

        if self.guild_db.is_applicant(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("ℹ️ Už Máš Přihlášku", f"Tvá přihláška do **{jmeno}** čeká na schválení."),
                ephemeral=True
            )
            return

        if not self.guild_db.add_application(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nepodařilo Se", "Přihlášku se nepodařilo podat."),
                ephemeral=True
            )
            return

        # Notifikace do threadu
        notify = discord.Embed(
            title="📝 Nová Přihláška",
            description=f"{interaction.user.mention} se hlásí do guildy.\nSchval přes `/guild_accept` nebo zamítni `/guild_deny`.",
            color=await self._get_guild_color(jmeno),
        )
        await self._notify_officers(jmeno, notify)

        await interaction.response.send_message(
            embed=create_success_embed(
                "📝 Přihláška Odeslána",
                f"Tvá přihláška do **{jmeno}** čeká na schválení.\n\n"
                f"💡 *Kdyby sis to rozmyslel/a, můžeš ji stáhnout přes* `/guild_withdraw`."
            ),
            ephemeral=True
        )

    # ============================================================
    # /guild_withdraw
    # ============================================================

    @app_commands.command(name="guild_withdraw", description="↩️ Stáhni svou čekající přihlášku do guildy")
    @app_commands.describe(jmeno="Guilda, kam jsi se hlásil (autocompletuje se)")
    @app_commands.autocomplete(jmeno=my_pending_apps_autocomplete)
    async def guild_withdraw(self, interaction: discord.Interaction, jmeno: str):
        user_id = interaction.user.id
        jmeno = jmeno.lower()

        if not self.guild_db.is_applicant(jmeno, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("ℹ️ Žádná Přihláška", f"Do **{jmeno}** nemáš čekající přihlášku."),
                ephemeral=True
            )
            return

        self.guild_db.remove_application(jmeno, user_id)
        await interaction.response.send_message(
            embed=create_success_embed("↩️ Přihláška Stažena", f"Tvá přihláška do **{jmeno}** byla zrušena."),
            ephemeral=True
        )

    # ============================================================
    # /guild_applications  (officer+)
    # ============================================================

    @app_commands.command(name="guild_applications", description="📋 Zobraz čekající přihlášky (officer+)")
    async def guild_applications(self, interaction: discord.Interaction):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."),
                ephemeral=True
            )
            return

        if not self.guild_db.is_officer_or_above(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nedostatečná Hodnost", "Jen officer nebo vůdce vidí přihlášky."),
                ephemeral=True
            )
            return

        apps = self.guild_db.list_applications(guild_name)
        if not apps:
            await interaction.response.send_message(
                embed=create_success_embed("📋 Přihlášky", "Žádné čekající přihlášky.", color=self.bot.color),
                ephemeral=True
            )
            return

        lines = "\n".join(f"• <@{uid}> — `/guild_accept` nebo `/guild_deny`" for uid in apps)
        embed = discord.Embed(title=f"📋 Přihlášky do {guild_name}", description=lines, color=self.bot.color)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ============================================================
    # /guild_accept  (officer+)
    # ============================================================

    @app_commands.command(name="guild_accept", description="✅ Schval přihlášku do guildy (officer+)")
    @app_commands.describe(clen="Žadatel (autocompletuje se)")
    @app_commands.autocomplete(clen=my_applicant_autocomplete)
    async def guild_accept(self, interaction: discord.Interaction, clen: str):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return
        if not self.guild_db.is_officer_or_above(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nedostatečná Hodnost", "Jen officer/vůdce schvaluje přihlášky."), ephemeral=True)
            return

        clen_id = await self._resolve_member_id(interaction, clen)
        if clen_id is None:
            return

        if not self.guild_db.is_applicant(guild_name, clen_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Žádná Přihláška", "Tento hráč nemá čekající přihlášku."), ephemeral=True)
            return

        if self.guild_db.get_user_guild(clen_id):
            self.guild_db.remove_application(guild_name, clen_id)
            await interaction.response.send_message(
                embed=create_error_embed("❌ Už Je v Guildě", "Žadatel mezitím vstoupil jinam — přihláška zrušena."), ephemeral=True)
            return

        if self.guild_db.is_full(guild_name):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Je Plná", "Nelze přijmout — kapacita."), ephemeral=True)
            return

        self.guild_db.add_member(guild_name, clen_id)  # odebere i přihlášku
        member = interaction.guild.get_member(clen_id) if interaction.guild else None
        if member:
            await self._add_to_thread(guild_name, member)

        color_int = await self._get_guild_color(guild_name)
        await interaction.response.send_message(
            embed=create_success_embed("✅ Přihláška Schválena", f"<@{clen_id}> je nyní členem **{guild_name}**!", color=color_int)
        )

    # ============================================================
    # /guild_deny  (officer+)
    # ============================================================

    @app_commands.command(name="guild_deny", description="✖️ Zamítni přihlášku do guildy (officer+)")
    @app_commands.describe(clen="Žadatel (autocompletuje se)")
    @app_commands.autocomplete(clen=my_applicant_autocomplete)
    async def guild_deny(self, interaction: discord.Interaction, clen: str):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return
        if not self.guild_db.is_officer_or_above(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nedostatečná Hodnost", "Jen officer/vůdce zamítá přihlášky."), ephemeral=True)
            return

        clen_id = await self._resolve_member_id(interaction, clen)
        if clen_id is None:
            return

        if not self.guild_db.remove_application(guild_name, clen_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Žádná Přihláška", "Tento hráč nemá čekající přihlášku."), ephemeral=True)
            return

        await interaction.response.send_message(
            embed=create_success_embed("✖️ Přihláška Zamítnuta", f"Přihláška <@{clen_id}> byla zamítnuta.")
        )

    # ============================================================
    # /guild_leave
    # ============================================================

    @app_commands.command(name="guild_leave", description="🚶 Opusť svou guildu")
    async def guild_leave(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return

        if self.guild_db.is_guildmaster(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed(
                    "❌ Vůdce Nemůže Odejít",
                    "Nejdřív předej vedení (`/guild_transfer`) nebo guildu rozpusť (`/guild_disband`)."
                ),
                ephemeral=True
            )
            return

        self.guild_db.remove_member(guild_name, user_id)
        await self._remove_from_thread(guild_name, interaction.user)
        await interaction.response.send_message(
            embed=create_success_embed("🚶 Odešel/a Jsi", f"Opustil/a jsi **{guild_name}**.")
        )

    # ============================================================
    # /guild_disband  (vůdce)
    # ============================================================

    @app_commands.command(name="guild_disband", description="🔥 Rozpusť svou guildu (jen vůdce)")
    async def guild_disband(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return
        if not self.guild_db.is_guildmaster(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce může guildu rozpustit."), ephemeral=True)
            return

        # Potvrzení — nevratná akce
        count = self.guild_db.member_count(guild_name)
        confirm_embed = create_error_embed(
            "⚠️ Opravdu Rozpustit?",
            f"Guilda **{guild_name}** ({count} členů) bude **nenávratně smazána** včetně threadu.\n"
            f"Tuto akci nelze vrátit zpět."
        )
        view = ConfirmView(user_id, confirm_label="Ano, rozpustit")
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)
        await view.wait()
        if view.value is not True:
            return

        guild = self.guild_db.get_guild(guild_name)
        thread_id = guild.get("thread_id") if guild else None
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.delete()
            except Exception:
                pass

        self.guild_db.delete_guild(guild_name)
        await interaction.followup.send(
            embed=create_success_embed(f"🔥 Guilda {guild_name} Rozpuštěna", "Všichni členové byli propuštěni.")
        )

    # ============================================================
    # /guild_invite  (officer+)
    # ============================================================

    @app_commands.command(name="guild_invite", description="✉️ Pozvi hráče do své guildy (officer+)")
    @app_commands.describe(clen="Hráč, kterého chceš pozvat")
    async def guild_invite(self, interaction: discord.Interaction, clen: discord.Member):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return
        if not self.guild_db.is_officer_or_above(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nedostatečná Hodnost", "Jen officer/vůdce posílá pozvánky."), ephemeral=True)
            return
        if clen.id == user_id:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nemůžeš Pozvat Sebe", "Jsi už v guildě!"), ephemeral=True)
            return

        other = self.guild_db.get_user_guild(clen.id)
        if other:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Hráč Už Má Guildu", f"{clen.mention} je v **{other}**."), ephemeral=True)
            return
        if self.guild_db.is_full(guild_name):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Je Plná", "Nemáš místo pro dalšího člena."), ephemeral=True)
            return
        if not self.guild_db.can_invite(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Příliš Mnoho Pozvánek", "Max 3 pozvánky za den."), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        self.guild_db.add_to_whitelist(guild_name, clen.id)
        self.guild_db.record_invite(guild_name, user_id)

        guild = self.guild_db.get_guild(guild_name)
        invite_color = await self._get_guild_color(guild_name)
        invite_embed = discord.Embed(
            title=f"🏰 Pozvánka do Guildy **{guild_name}**!",
            description=f"{interaction.user.mention} tě zve do své guildy v Aurionisu!",
            color=invite_color,
        )
        invite_embed.add_field(name="🗺️ Motto", value=f"`{guild['quest']}`", inline=False)
        invite_embed.add_field(name="👥 Členů", value=f"{len(guild['members'])}/{guild.get('capacity', 50)}", inline=True)

        try:
            view = build_guild_invite_view(clen.id, guild_name)
            await clen.send(embed=invite_embed, view=view)
        except discord.Forbidden:
            self.guild_db.remove_from_whitelist(guild_name, clen.id)
            await interaction.followup.send(
                embed=create_error_embed("❌ DM Zamčené", f"{clen.mention} má zamčené DM."), ephemeral=True)
            return

        await interaction.followup.send(
            embed=create_success_embed("✉️ Pozvánka Odeslána", f"Pozvánka doručena {clen.mention}."), ephemeral=True)

    # ============================================================
    # /guild_kick  (officer+ na členy, vůdce na kohokoli)
    # ============================================================

    @app_commands.command(name="guild_kick", description="👢 Vyhoď člena z guildy (officer+)")
    @app_commands.describe(clen="Člen k vyhození (autocompletuje se)")
    @app_commands.autocomplete(clen=my_member_autocomplete)
    async def guild_kick(self, interaction: discord.Interaction, clen: str):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return
        if not self.guild_db.is_officer_or_above(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nedostatečná Hodnost", "Jen officer/vůdce vyhazuje členy."), ephemeral=True)
            return

        clen_id = await self._resolve_member_id(interaction, clen)
        if clen_id is None:
            return
        if clen_id == user_id:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nemůžeš Vyhodit Sebe", "Použij `/guild_leave` nebo `/guild_disband`."), ephemeral=True)
            return
        if not self.guild_db.is_user_in_guild(guild_name, clen_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Není Členem", "Tento hráč není v tvé guildě."), ephemeral=True)
            return

        target_rank = self.guild_db.get_rank(guild_name, clen_id)
        actor_is_gm = self.guild_db.is_guildmaster(guild_name, user_id)

        # Officer smí vyhazovat jen řadové členy, ne jiné officery/vůdce
        if not actor_is_gm and target_rank in ("officer", "guildmaster"):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nedostatečná Hodnost", "Officer může vyhodit jen řadové členy. Na officera musí vůdce."),
                ephemeral=True
            )
            return

        self.guild_db.remove_member(guild_name, clen_id)
        member = interaction.guild.get_member(clen_id) if interaction.guild else None
        if member:
            await self._remove_from_thread(guild_name, member)

        await interaction.response.send_message(
            embed=create_success_embed("👢 Člen Vyhozen", f"<@{clen_id}> byl/a vyhozen/a z **{guild_name}**.")
        )

    # ============================================================
    # /guild_promote  (vůdce — člen → officer)
    # ============================================================

    @app_commands.command(name="guild_promote", description="🛡️ Povyš člena na officera (jen vůdce)")
    @app_commands.describe(clen="Člen k povýšení (autocompletuje se)")
    @app_commands.autocomplete(clen=my_promotable_autocomplete)
    async def guild_promote(self, interaction: discord.Interaction, clen: str):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name or not self.guild_db.is_guildmaster(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce povyšuje na officera."), ephemeral=True)
            return

        clen_id = await self._resolve_member_id(interaction, clen)
        if clen_id is None:
            return
        if not self.guild_db.promote_to_officer(guild_name, clen_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nepodařilo Se", "Hráč není člen, nebo už je officer/vůdce."), ephemeral=True)
            return

        color_int = await self._get_guild_color(guild_name)
        await interaction.response.send_message(
            embed=create_success_embed("🛡️ Nový Officer", f"<@{clen_id}> je nyní officer **{guild_name}**!", color=color_int)
        )

    # ============================================================
    # /guild_demote  (vůdce — officer → člen)
    # ============================================================

    @app_commands.command(name="guild_demote", description="⬇️ Sesaď officera na člena (jen vůdce)")
    @app_commands.describe(clen="Officer k sesazení (autocompletuje se)")
    @app_commands.autocomplete(clen=my_officer_autocomplete)
    async def guild_demote(self, interaction: discord.Interaction, clen: str):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name or not self.guild_db.is_guildmaster(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce sesazuje officery."), ephemeral=True)
            return

        clen_id = await self._resolve_member_id(interaction, clen)
        if clen_id is None:
            return
        if not self.guild_db.demote_to_member(guild_name, clen_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nepodařilo Se", "Tento hráč není officer."), ephemeral=True)
            return

        await interaction.response.send_message(
            embed=create_success_embed("⬇️ Officer Sesazen", f"<@{clen_id}> je opět řadový člen **{guild_name}**.")
        )

    # ============================================================
    # /guild_transfer  (vůdce — předání vedení)
    # ============================================================

    @app_commands.command(name="guild_transfer", description="👑 Předej vedení guildy jinému členovi (jen vůdce)")
    @app_commands.describe(clen="Nový vůdce (autocompletuje se)")
    @app_commands.autocomplete(clen=my_member_autocomplete)
    async def guild_transfer(self, interaction: discord.Interaction, clen: str):
        user_id = interaction.user.id
        guild_name = self.guild_db.get_user_guild(user_id)
        if not guild_name or not self.guild_db.is_guildmaster(guild_name, user_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce může předat vedení."), ephemeral=True)
            return

        clen_id = await self._resolve_member_id(interaction, clen)
        if clen_id is None:
            return
        if clen_id == user_id:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Jsi Již Vůdce", "Nemůžeš předat vedení sám/a sobě."), ephemeral=True)
            return
        if not self.guild_db.is_user_in_guild(guild_name, clen_id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Není Členem", "Hráč není v tvé guildě."), ephemeral=True)
            return

        # Potvrzení — předání vedení
        confirm_embed = create_error_embed(
            "⚠️ Předat Vedení?",
            f"Vedení **{guild_name}** přejde na <@{clen_id}>.\n"
            f"Ty klesneš na 🛡️ officera. Pokračovat?"
        )
        view = ConfirmView(user_id, confirm_label="Ano, předat", confirm_style=discord.ButtonStyle.primary)
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)
        await view.wait()
        if view.value is not True:
            return

        self.guild_db.set_guildmaster(guild_name, clen_id)  # starý vůdce → officer
        color_int = await self._get_guild_color(guild_name)
        await interaction.followup.send(
            embed=create_success_embed("👑 Vedení Předáno", f"<@{clen_id}> je nový vůdce **{guild_name}**! (Ty jsi teď officer.)", color=color_int)
        )

    # ============================================================
    # /guild_set  (vůdce — identita)
    # ============================================================

    @app_commands.command(name="guild_set", description="⚙️ Nastav identitu své guildy (jen vůdce)")
    async def guild_set(self, interaction: discord.Interaction):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi v Guildě", "Nejsi členem žádné guildy."), ephemeral=True)
            return
        if not self.guild_db.is_guildmaster(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce mění identitu."), ephemeral=True)
            return
        await interaction.response.send_modal(GuildSetModal(self.bot, self.guild_db, self, guild_name))

    # ============================================================
    # /guild_recruitment  (vůdce — režim náboru)
    # ============================================================

    @app_commands.command(name="guild_recruitment", description="🚪 Změň režim náboru guildy (jen vůdce)")
    @app_commands.describe(rezim="Otevřená / na přihlášku / uzavřená")
    @app_commands.choices(rezim=RECRUITMENT_CHOICES)
    async def guild_recruitment(self, interaction: discord.Interaction, rezim: app_commands.Choice[str]):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name or not self.guild_db.is_guildmaster(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce mění režim náboru."), ephemeral=True)
            return
        self.guild_db.set_recruitment(guild_name, rezim.value)
        await interaction.response.send_message(
            embed=create_success_embed("🚪 Nábor Změněn", f"**{guild_name}**: {RECRUITMENT_LABELS.get(rezim.value)}")
        )

    # ============================================================
    # /guild_capacity  (vůdce — kapacita)
    # ============================================================

    @app_commands.command(name="guild_capacity", description="👥 Nastav maximální počet členů (jen vůdce)")
    @app_commands.describe(max="Maximální počet členů (1–250)")
    async def guild_capacity(self, interaction: discord.Interaction, max: int):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name or not self.guild_db.is_guildmaster(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce mění kapacitu."), ephemeral=True)
            return
        if max < 1 or max > 250:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Neplatná Hodnota", "Kapacita musí být 1–250."), ephemeral=True)
            return
        current_count = self.guild_db.member_count(guild_name)
        if max < current_count:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Příliš Málo", f"Guilda už má {current_count} členů."), ephemeral=True)
            return
        self.guild_db.set_capacity(guild_name, max)
        await interaction.response.send_message(
            embed=create_success_embed("👥 Kapacita Nastavena", f"**{guild_name}**: max {max} členů.")
        )

    # ============================================================
    # /guild_describe  (vůdce — popis / lore)
    # ============================================================

    @app_commands.command(name="guild_describe", description="📖 Nastav popis / lore guildy (jen vůdce)")
    @app_commands.describe(text="Popis guildy (prázdné = smazat)")
    async def guild_describe(self, interaction: discord.Interaction, text: str = ""):
        guild_name = self.guild_db.get_user_guild(interaction.user.id)
        if not guild_name or not self.guild_db.is_guildmaster(guild_name, interaction.user.id):
            await interaction.response.send_message(
                embed=create_error_embed("❌ Nejsi Vůdce", "Jen vůdce mění popis."), ephemeral=True)
            return
        self.guild_db.set_description(guild_name, text.strip())
        await interaction.response.send_message(
            embed=create_success_embed("📖 Popis Upraven", "Popis guildy byl aktualizován." if text.strip() else "Popis byl smazán.")
        )

    # ============================================================
    # /guild_list
    # ============================================================

    @app_commands.command(name="guild_list", description="📜 Zobraz seznam všech guild")
    async def guild_list(self, interaction: discord.Interaction):
        guilds = self.guild_db.list_all_guilds()
        embed = create_guilds_list_embed(guilds, color=self.bot.color)
        await interaction.response.send_message(embed=embed)

    # ============================================================
    # /guild_info
    # ============================================================

    @app_commands.command(name="guild_info", description="🔍 Zobraz info o guildě (nech prázdné pro svou)")
    @app_commands.describe(jmeno="Která guilda? (prázdné = tvoje)")
    @app_commands.autocomplete(jmeno=any_guild_autocomplete)
    async def guild_info(self, interaction: discord.Interaction, jmeno: str = ""):
        if not jmeno:
            jmeno = self.guild_db.get_user_guild(interaction.user.id)
            if not jmeno:
                await interaction.response.send_message(
                    embed=create_error_embed("❌ Nejsi v Guildě", "Připoj se přes `/guild_join` nebo zadej jméno."),
                    ephemeral=True
                )
                return
        else:
            jmeno = jmeno.lower()

        guild = self.guild_db.get_guild(jmeno)
        if not guild:
            await interaction.response.send_message(
                embed=create_error_embed("❌ Guilda Neexistuje", f"**{jmeno}** nebyla nalezena."), ephemeral=True)
            return

        try:
            color = int(guild.get("color"), 16) if guild.get("color") else self.bot.color
        except Exception:
            color = self.bot.color

        embed = create_guild_embed(
            guild_name=jmeno,
            quest=guild["quest"],
            members=guild["members"],
            guildmaster_id=guild["guildmaster"],
            officers=guild.get("officers", []),
            tag=guild.get("tag"),
            description=guild.get("description"),
            recruitment=guild.get("recruitment", "open"),
            capacity=guild.get("capacity", 50),
            color=color,
            emoji=guild.get("emoji"),
        )
        await interaction.response.send_message(embed=embed)

    # ============================================================
    # /guild_help
    # ============================================================

    @app_commands.command(name="guild_help", description="📖 Nápověda k systému guild")
    async def guild_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏰 Arion — Guildy Aurionisu",
            description="*Guilda je tvůj stálý domov. Můžeš být jen v **jedné** — vyber moudře.*",
            color=self.bot.color,
        )
        embed.add_field(
            name="🧭 Pro každého",
            value=(
                "`/guild_create` — Založ guildu\n"
                "`/guild_join` — Vstup do otevřené\n"
                "`/guild_apply` — Podej přihlášku\n"
                "`/guild_withdraw` — Stáhni přihlášku\n"
                "`/guild_leave` — Opusť guildu\n"
                "`/guild_list` — Všechny guildy\n"
                "`/guild_info` — Detail guildy\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️ Officer+",
            value=(
                "`/guild_invite` — Pozvi hráče\n"
                "`/guild_applications` — Čekající přihlášky\n"
                "`/guild_accept` / `/guild_deny` — Schval/zamítni\n"
                "`/guild_kick` — Vyhoď řadového člena\n"
            ),
            inline=False,
        )
        embed.add_field(
            name="👑 Jen vůdce",
            value=(
                "`/guild_promote` / `/guild_demote` — Officeři\n"
                "`/guild_transfer` — Předej vedení\n"
                "`/guild_set` — Identita (jméno, tag, motto, emoji, barva)\n"
                "`/guild_recruitment` — Režim náboru\n"
                "`/guild_capacity` — Kapacita\n"
                "`/guild_describe` — Popis / lore\n"
                "`/guild_disband` — Rozpusť guildu\n"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot):
    """Nainstaluje Guilds cog"""
    await bot.add_cog(Guilds(bot))