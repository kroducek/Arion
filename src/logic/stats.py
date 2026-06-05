import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import logging

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

from src.utils.paths import PROFILES as DATA_FILE, ITEMS as ITEMS_FILE
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger("Stats")

STAT_LABELS = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']

# XP caps pro každý level (index = level)
# Level 0 je startovní — hráč začíná zde po tutorialu
XP_CAPS = [
    100,    # Lvl 0  → 1
    500,    # Lvl I
    750,    # Lvl II
    1250,   # Lvl III
    2500,   # Lvl IV
    3500,   # Lvl V
    5000,   # Lvl VI
    7500,   # Lvl VII
    9000,   # Lvl VIII
    12500,  # Lvl IX  (+5 SP navíc)
    14500,  # Lvl X
    17500,  # Lvl XI
    21000,  # Lvl XII
]

# SP bonus na vybraných levelech  {level: bonus_sp}
SP_BONUS = {9: 5}

# Základní SP za levelup
SP_PER_LEVEL = 1

# Luck výchozí hodnota (procenta, 0–200, kde 100 = normál)
DEFAULT_LUCK = 100

# ══════════════════════════════════════════════════════════════════════════════
# EMOJI KONSTANTY  (synchronizováno s profile.py)
# ══════════════════════════════════════════════════════════════════════════════

HP_ON       = "<:hp:1490146344290222111>"
MN_ON       = "<:mana:1490148547427831981>"
HN_ON       = "<:hunger:1490169001890807928>"
FU_EMO      = "<:furioku:1490160933081972866>"
XP_EMO      = "<:xp:1490159053425348748>"
VLIV_EMO    = "<:vliv:1490162671969112085>"
SVETLO_EMO  = "<:svetlo:1490166284741120120>"
TEMNOTA_EMO = "<:temnota:1490166345516581034>"
ROVNO_EMO   = "<:rovnovaha:1490166409458749671>"

_SP_EMOJI = {"STR": "💪", "DEX": "🤸", "INS": "👁️", "INT": "🧠", "CHA": "✨", "WIS": "🔮"}

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS — profiles.json
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    return load_json(DATA_FILE)

def _save(data: dict):
    save_json(DATA_FILE, data)

def _profile(data: dict, uid: str) -> dict:
    """Vrátí profil hráče, inicializuje chybějící pole."""
    data.setdefault(uid, {})
    p = data[uid]
    p.setdefault("rank",         "F3")
    p.setdefault("level",        0)
    p.setdefault("xp",           0)
    p.setdefault("sp",           0)       # nerozdělené skill pointy
    p.setdefault("luck",         DEFAULT_LUCK)
    p.setdefault("stats",        {s: 1 for s in STAT_LABELS})
    return p

def _ensure_fields(p: dict) -> None:
    """Doplní výchozí hodnoty HP, hlad, mana, furioka atd. pokud chybí."""
    p.setdefault("hp_max",          50)
    p.setdefault("hp_cur",          p.get("hp_max", 50))
    p.setdefault("hunger_max",      10)
    p.setdefault("hunger_cur",      p.get("hunger_max", 10))
    p.setdefault("mana_max",        5)
    p.setdefault("mana_cur",        0)
    p.setdefault("fury_max",        0)
    p.setdefault("fury_cur",        0)
    p.setdefault("vliv_svetlo",     0)
    p.setdefault("vliv_temnota",    0)
    p.setdefault("vliv_rovnovaha",  0)
    p.setdefault("luck",            DEFAULT_LUCK)
    p.setdefault("level",           0)
    p.setdefault("xp",              0)
    p.setdefault("sp",              0)
    p.setdefault("stats",           {s: 1 for s in STAT_LABELS})

def _load_items_db() -> dict:
    try:
        return load_json(ITEMS_FILE, default={})
    except Exception:
        return {}

def _bar(cur: int, mx: int, width: int = 10) -> str:
    if mx <= 0:
        return "░" * width
    filled = round(max(0, min(cur, mx)) / mx * width)
    return "█" * filled + "░" * (width - filled)

def _compute_def(profile: dict, items_db: dict) -> int:
    equipment = profile.get("equipment", {})
    seen = set()
    total = 0
    for item_id in equipment.values():
        if item_id and item_id not in seen:
            seen.add(item_id)
            total += items_db.get(item_id, {}).get("def", 0)
    return total

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — volané z jiných cogů
# ══════════════════════════════════════════════════════════════════════════════

def get_xp_cap(level: int) -> int | None:
    """XP cap pro daný level. None = max level."""
    if level < len(XP_CAPS):
        return XP_CAPS[level]
    return None

def level_label(level: int) -> str:
    roman = ["0","I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII"]
    if level < len(roman):
        return f"Lvl {roman[level]}"
    return f"Lvl {level}"

def init_stats(user_id: int, base_stats: dict, sp: int = 0):
    """
    Inicializuje stats hráče při tutorialu.
    base_stats: dict {'STR': int, ...}
    sp: počet nerozdělených skill pointů
    """
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    p["stats"] = {s: base_stats.get(s, 1) for s in STAT_LABELS}
    p["level"] = 0
    p["xp"]    = 0
    p["sp"]    = sp
    p["luck"]  = DEFAULT_LUCK
    _save(data)

def add_xp(user_id: int, amount: int) -> dict:
    """
    Přidá XP hráči. Vrátí dict s informacemi o levelupu.
    Return: {'leveled_up': bool, 'new_level': int, 'sp_gained': int, 'xp': int, 'cap': int|None}
    """
    data   = _load()
    uid    = str(user_id)
    p      = _profile(data, uid)
    p["xp"] += amount

    leveled_up = False
    sp_gained  = 0
    new_level  = p["level"]

    cap = get_xp_cap(p["level"])
    while cap is not None and p["xp"] >= cap:
        p["xp"]    -= cap
        p["level"] += 1
        new_level   = p["level"]
        leveled_up  = True
        sp          = SP_PER_LEVEL + SP_BONUS.get(new_level, 0)
        sp_gained  += sp
        p["sp"]    += sp
        cap = get_xp_cap(p["level"])

    _save(data)
    return {
        "leveled_up": leveled_up,
        "new_level":  new_level,
        "sp_gained":  sp_gained,
        "xp":         p["xp"],
        "cap":        get_xp_cap(new_level),
    }

def get_stats(user_id: int) -> dict:
    """Vrátí stats dict hráče."""
    data = _load()
    p    = _profile(data, str(user_id))
    return p

def set_luck(user_id: int, value: int):
    """Nastaví luck hráče (0–200)."""
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    p["luck"] = max(0, min(200, value))
    _save(data)

def modify_luck(user_id: int, delta: int) -> int:
    """Upraví luck hráče o delta. Vrátí novou hodnotu."""
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    p["luck"] = max(0, min(200, p["luck"] + delta))
    _save(data)
    return p["luck"]

def spend_sp(user_id: int, stat: str, amount: int = 1) -> bool:
    """Utratí SP na daný stat. Vrátí True při úspěchu."""
    if stat not in STAT_LABELS:
        return False
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    if p["sp"] < amount:
        return False
    p["sp"]           -= amount
    p["stats"][stat]   = p["stats"].get(stat, 1) + amount
    _save(data)
    return True

# ══════════════════════════════════════════════════════════════════════════════
# QUICK SHEET — sestavení embedu
# ══════════════════════════════════════════════════════════════════════════════

def _build_quicksheet_embed(
    user: discord.User | discord.Member,
    p: dict,
    items_db: dict,
) -> discord.Embed:
    """Sestaví přehledný embed pro /stats quick sheet."""
    _ensure_fields(p)

    hp_cur     = p["hp_cur"];      hp_max     = p["hp_max"]
    mana_cur   = p["mana_cur"];    mana_max   = p["mana_max"]
    hunger_cur = p["hunger_cur"];  hunger_max = p["hunger_max"]
    fury_cur   = p["fury_cur"];    fury_max   = p["fury_max"]
    v_svetlo   = p["vliv_svetlo"]
    v_temnota  = p["vliv_temnota"]
    v_rovno    = p["vliv_rovnovaha"]
    level      = p["level"];  xp = p["xp"]; sp = p.get("sp", 0)
    luck       = p.get("luck", DEFAULT_LUCK)
    stats      = p.get("stats", {})
    total_def  = _compute_def(p, items_db)
    cap        = get_xp_cap(level)

    char_name = p.get("name", user.display_name)
    def_str   = f"  ·  🛡️ **{total_def}**" if total_def else ""
    xp_str    = f"*{xp} (MAX)*" if not cap else f"*{xp}/{cap}*"
    sp_str    = f"  ·  ⚡ **{sp} SP**" if sp > 0 else ""

    lines = []

    # ── Vitální stavy ─────────────────────────────────────────────────────────
    hp_bar     = _bar(hp_cur,     hp_max)
    mana_bar   = _bar(mana_cur,   mana_max)
    hunger_bar = _bar(hunger_cur, hunger_max)

    lines.append(f"{HP_ON} **Zdraví**  `{hp_bar}`  *{hp_cur} / {hp_max}*{def_str}")
    lines.append(f"{MN_ON} **Mana**  `{mana_bar}`  *{mana_cur} / {mana_max}*")
    lines.append(f"{HN_ON} **Hlad**  `{hunger_bar}`  *{hunger_cur} / {hunger_max}*")

    if fury_max > 0:
        fury_bar = _bar(fury_cur, fury_max)
        lines.append(f"{FU_EMO} **Furioka**  `{fury_bar}`  *{fury_cur} / {fury_max}*")
    else:
        lines.append(f"{FU_EMO} **Furioka**  *— žádný Vliv*")

    lines.append("")

    # ── Progres ───────────────────────────────────────────────────────────────
    xp_bar = _bar(xp, cap if cap else 1)
    lines.append(f"⭐ **{level_label(level)}**  ·  {XP_EMO} `{xp_bar}` {xp_str}{sp_str}")

    # Vliv (jen pokud má nějaký)
    if v_svetlo or v_temnota or v_rovno:
        lines.append(
            f"{VLIV_EMO}  {SVETLO_EMO} **{v_svetlo}**  ·  "
            f"{TEMNOTA_EMO} **{v_temnota}**  ·  "
            f"{ROVNO_EMO} **{v_rovno}**"
        )

    # Luck (jen pokud se liší od základu)
    if luck != DEFAULT_LUCK:
        if luck >= 130:   luck_icon = "🌟"
        elif luck >= 80:  luck_icon = "🍀"
        else:             luck_icon = "💔"
        lines.append(f"{luck_icon} *Štěstí {luck}%*")

    lines.append("")

    # ── Staty ─────────────────────────────────────────────────────────────────
    if stats:
        parts = [
            f"*{_SP_EMOJI.get(s, '')} {s}* **{stats.get(s, 1)}**"
            for s in STAT_LABELS
        ]
        lines.append("  ·  ".join(parts))

    embed = discord.Embed(
        title=f"📋  *{char_name}*  —  Quick Sheet",
        description="\n".join(lines),
        color=0x5865f2,
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Uprav svůj stav tlačítky níže  ·  Aurionis")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# ADJUST MODAL — zadání +číslo / -číslo
# ══════════════════════════════════════════════════════════════════════════════

class _AdjustModal(discord.ui.Modal):
    """Generický modal: hráč zadá +číslo nebo -číslo."""

    value_input = discord.ui.TextInput(
        label="Zadej změnu  (+číslo nebo -číslo)",
        placeholder="+5   nebo   -3",
        min_length=2,
        max_length=7,
    )

    def __init__(
        self,
        title: str,
        key_cur: str,
        key_max: str,
        user_id: int,
        allow_exceed_max: bool = False,
    ):
        super().__init__(title=title)
        self.key_cur         = key_cur
        self.key_max         = key_max
        self.user_id         = user_id
        self.allow_exceed_max = allow_exceed_max

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.value_input.value.strip()
        try:
            delta = int(raw)
        except ValueError:
            await interaction.response.send_message(
                f"❌ Neplatná hodnota `{raw}` — zadej např. `+5` nebo `-3`.",
                ephemeral=True,
            )
            return

        data = _load()
        uid  = str(self.user_id)
        p    = data.get(uid)
        if not p:
            await interaction.response.send_message("❌ Profil nenalezen.", ephemeral=True)
            return

        _ensure_fields(p)
        cur = p[self.key_cur]
        mx  = p[self.key_max]

        if self.allow_exceed_max:
            new_val = max(0, cur + delta)
        else:
            new_val = max(0, min(mx, cur + delta))

        p[self.key_cur] = new_val
        _save(data)

        items_db = _load_items_db()
        embed = _build_quicksheet_embed(interaction.user, p, items_db)
        await interaction.response.edit_message(
            embed=embed,
            view=QuickSheetView(self.user_id),
        )


# ══════════════════════════════════════════════════════════════════════════════
# QUICK SHEET VIEW — tlačítka
# ══════════════════════════════════════════════════════════════════════════════

class QuickSheetView(discord.ui.View):
    """Tlačítka pro úpravu vitálních hodnot v /stats quick sheetu."""

    def __init__(self, user_id: int):
        super().__init__(timeout=600)
        self.user_id = user_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ *Toto není tvůj quick sheet.*", ephemeral=True
            )
            return False
        return True

    # ── Řádek 0 ──────────────────────────────────────────────────────────────

    @discord.ui.button(label="❤️ HP", style=discord.ButtonStyle.red, row=0)
    async def btn_hp(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_modal(
            _AdjustModal("Upravit HP", "hp_cur", "hp_max", self.user_id)
        )

    @discord.ui.button(label="🔷 Mana", style=discord.ButtonStyle.blurple, row=0)
    async def btn_mana(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_modal(
            _AdjustModal("Upravit Manu", "mana_cur", "mana_max", self.user_id)
        )

    @discord.ui.button(label="🔥 Furioka", style=discord.ButtonStyle.grey, row=0)
    async def btn_fury(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_modal(
            _AdjustModal("Upravit Furioku", "fury_cur", "fury_max", self.user_id)
        )

    @discord.ui.button(label="🍖 Hlad", style=discord.ButtonStyle.green, row=0)
    async def btn_hunger(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_modal(
            _AdjustModal("Upravit Hlad", "hunger_cur", "hunger_max", self.user_id)
        )

    # ── Řádek 1 ──────────────────────────────────────────────────────────────

    @discord.ui.button(label="🔄 Obnovit", style=discord.ButtonStyle.grey, row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        data = _load()
        p    = data.get(str(self.user_id), {})
        _ensure_fields(p)
        items_db = _load_items_db()
        embed = _build_quicksheet_embed(interaction.user, p, items_db)
        await interaction.response.edit_message(embed=embed, view=QuickSheetView(self.user_id))


# ══════════════════════════════════════════════════════════════════════════════
# LEVELUP VIEW — hráč rozděluje SP po levelupu
# ══════════════════════════════════════════════════════════════════════════════

class SpendSPView(discord.ui.View):
    """Interaktivní view pro rozdělování SP — 6 tlačítek, 2 řádky."""

    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        for idx, stat in enumerate(STAT_LABELS):
            # Discord max 5 buttonů na řádek — prvních 5 v řádku 0, poslední v řádku 1
            row = 0 if idx < 5 else 1
            btn = discord.ui.Button(
                label=f"{_SP_EMOJI.get(stat, '')} {stat}",
                style=discord.ButtonStyle.blurple,
                row=row,
            )
            btn.callback = self._make_cb(stat)
            self.add_item(btn)

    def _make_cb(self, stat: str):
        async def cb(interaction: discord.Interaction):
            try:
                # Kontrola oprávnění
                if interaction.user.id != self.user_id:
                    await interaction.response.send_message(
                        "❌ Toto není tvůj výběr.", 
                        ephemeral=True
                    )
                    return

                # Načtení dat
                data = _load()
                uid  = str(self.user_id)
                p    = _profile(data, uid)

                # Kontrola SP
                if p["sp"] <= 0:
                    await interaction.response.send_message(
                        "❌ Nemáš žádné volné SP.",
                        ephemeral=True
                    )
                    return

                # Útrata SP
                p["sp"]          -= 1
                p["stats"][stat]  = p["stats"].get(stat, 1) + 1
                _save(data)
                
                remaining = p["sp"]
                new_val   = p["stats"][stat]

                # Vytvoření embedu
                embed = discord.Embed(
                    title="⚡ Skill Point utracen",
                    description=(
                        f"{_SP_EMOJI.get(stat, '')} **{stat}** zvýšen na **{new_val}**\n\n"
                        f"Zbývající SP: **{remaining}**"
                        + ("\n\n✅ *Vyber další stat.*" if remaining > 0 else "\n\n✅ *Všechny SP rozděleny!*")
                    ),
                    color=0x9b59b6,
                )

                # Odpověď s novou view (pokud zbývají SP)
                if remaining > 0:
                    await interaction.response.edit_message(
                        embed=embed,
                        view=SpendSPView(self.user_id),
                    )
                else:
                    # Poslední SP — nezobrazuj view
                    await interaction.response.edit_message(
                        embed=embed,
                        view=None,
                    )

            except discord.errors.NotFound:
                logger.warning(f"[SpendSPView] Message not found for user {self.user_id}")
            except Exception as e:
                logger.exception(f"[SpendSPView] Error in callback for stat {stat}: {e}")
                try:
                    await interaction.response.send_message(
                        f"❌ Chyba: {str(e)[:100]}",
                        ephemeral=True
                    )
                except:
                    pass

        return cb


# ══════════════════════════════════════════════════════════════════════════════
# COG — příkazy
# ══════════════════════════════════════════════════════════════════════════════

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /stats ────────────────────────────────────────────────────────────────

    @app_commands.command(name="stats", description="Tvůj quick sheet — stav postavy a tlačítka pro úpravu.")
    @app_commands.describe(member="Hráč (výchozí: ty) — při zobrazení jiného hráče bez tlačítek.")
    async def stats_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        try:
            target   = member or interaction.user
            data     = _load()
            uid      = str(target.id)

            if uid not in data:
                await interaction.response.send_message(
                    f"*{target.display_name} zatím nemá profil — musí projít tutoriálem.*",
                    ephemeral=True,
                )
                return

            p = data[uid]
            _ensure_fields(p)
            items_db = _load_items_db()
            embed    = _build_quicksheet_embed(target, p, items_db)

            # Vlastní quick sheet → ephemeral s tlačítky; cizí → bez tlačítek
            is_self = (member is None or member.id == interaction.user.id)
            if is_self:
                await interaction.response.send_message(
                    embed=embed,
                    view=QuickSheetView(interaction.user.id),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"[stats_cmd] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}",
                ephemeral=True,
            )

    # ── /sp ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="sp", description="Rozděl své skill pointy.")
    async def sp_cmd(self, interaction: discord.Interaction):
        try:
            data = _load()
            p    = _profile(data, str(interaction.user.id))
            sp   = p["sp"]

            if sp <= 0:
                await interaction.response.send_message(
                    "❌ Nemáš žádné volné skill pointy.", 
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title="⚡ Skill Pointy",
                description=(
                    f"Máš **{sp}** volných SP.\n\n"
                    "Klikni a vyber stat, který chceš zvýšit.\n"
                    f"-# Dostupné staty: {', '.join(STAT_LABELS)}"
                ),
                color=0x9b59b6,
            )
            await interaction.response.send_message(
                embed=embed,
                view=SpendSPView(user_id=interaction.user.id),
                ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"[sp_cmd] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}",
                ephemeral=True
            )

    # ── /luck ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="luck", description="Zobraz svůj aktuální Luck.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def luck_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        try:
            target = member or interaction.user
            data   = _load()
            p      = _profile(data, str(target.id))
            luck   = p["luck"]

            if luck >= 180:   desc = "🌟 Štěstěna se přímo usmívá"
            elif luck >= 130: desc = "📈 Příznivé okolnosti"
            elif luck >= 80:  desc = "⚖️ Stabilní vliv (Neutrální)"
            elif luck >= 40:  desc = "📉 Nepříznivé interference"
            else:             desc = "💀 Kritická nesouhra (Naprostá smůla)"

            bar_filled = round(luck / 10)
            bar = "█" * bar_filled + "░" * (20 - bar_filled)

            embed = discord.Embed(
                title=f"🍀 Štěstí — {target.display_name}",
                description=f"`{bar}` **{luck}%**\n\n{desc}",
                color=0xf1c40f,
            )
            embed.set_footer(text="⭐ Aurionis")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.exception(f"[luck_cmd] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}",
                ephemeral=True
            )

    # ── /admin-luck ───────────────────────────────────────────────────────────

    @app_commands.command(name="admin-luck", description="[Admin] Nastav nebo upravit Luck hráče.")
    @app_commands.describe(
        member="Hráč",
        operace="set = nastav přesnou hodnotu, add/remove = uprav o hodnotu",
        hodnota="Číslo (0–200 pro set, libovolné pro add/remove)",
    )
    @app_commands.choices(operace=[
        app_commands.Choice(name="set",    value="set"),
        app_commands.Choice(name="add",    value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_luck(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        operace: app_commands.Choice[str],
        hodnota: int,
    ):
        try:
            if operace.value == "set":
                set_luck(member.id, hodnota)
                new_luck = max(0, min(200, hodnota))
            elif operace.value == "add":
                new_luck = modify_luck(member.id, hodnota)
            else:
                new_luck = modify_luck(member.id, -hodnota)

            await interaction.response.send_message(
                f"✅ Luck hráče {member.mention} nastaven na **{new_luck}%**.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"[admin_luck] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}",
                ephemeral=True
            )

    # ── /admin-xp ─────────────────────────────────────────────────────────────

    @app_commands.command(name="admin-xp", description="[Admin] Přidej nebo odeber XP hráči.")
    @app_commands.describe(member="Hráč", amount="Množství XP (kladné = přidat, záporné = odebrat)")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_xp(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        try:
            if amount > 0:
                result = add_xp(member.id, amount)
                if result["leveled_up"]:
                    cap_str = f"/ {result['cap']}" if result["cap"] else "(MAX)"
                    embed = discord.Embed(
                        title="⬆️ Level Up!",
                        description=(
                            f"{member.mention} dosáhl/a **{level_label(result['new_level'])}**!\n\n"
                            f"XP: **{result['xp']}** {cap_str}\n"
                            f"Získané SP: **{result['sp_gained']}**"
                        ),
                        color=0xf1c40f,
                    )
                    await interaction.response.send_message(embed=embed)
                    # Upozornit hráče
                    try:
                        await interaction.followup.send(
                            content=member.mention,
                            embed=discord.Embed(
                                title="⬆️ Level Up!",
                                description=(
                                    f"Dosáhl/a jsi **{level_label(result['new_level'])}**!\n\n"
                                    f"Získal/a jsi **{result['sp_gained']} SP** — rozděl je přes `/sp`."
                                ),
                                color=0xf1c40f,
                            ),
                        )
                    except Exception as e:
                        logger.warning(f"[admin_xp] Failed to send followup: {e}")
                else:
                    cap_str = f"/ {result['cap']}" if result["cap"] else "(MAX)"
                    await interaction.response.send_message(
                        f"✅ {member.mention} získal/a **+{amount} XP**. "
                        f"Aktuálně: **{result['xp']}** {cap_str}",
                        ephemeral=True,
                    )
            else:
                # Odebrat XP
                data = _load()
                uid  = str(member.id)
                p    = _profile(data, uid)
                p["xp"] = max(0, p["xp"] + amount)
                _save(data)
                await interaction.response.send_message(
                    f"✅ {member.mention} ztratil/a **{abs(amount)} XP**. "
                    f"Aktuálně: **{p['xp']}**",
                    ephemeral=True,
                )
        except Exception as e:
            logger.exception(f"[admin_xp] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}",
                ephemeral=True
            )

    # ── /admin-stats ──────────────────────────────────────────────────────────

    @app_commands.command(name="admin-stats", description="[Admin] Nastav stat hráče přímo.")
    @app_commands.describe(
        member="Hráč",
        stat="Stat (STR/DEX/INS/INT/CHA/WIS)",
        hodnota="Nová hodnota",
    )
    @app_commands.choices(stat=[app_commands.Choice(name=s, value=s) for s in STAT_LABELS])
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_stats(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        stat: app_commands.Choice[str],
        hodnota: int,
    ):
        try:
            data = _load()
            uid  = str(member.id)
            p    = _profile(data, uid)
            p["stats"][stat.value] = max(1, hodnota)
            _save(data)
            await interaction.response.send_message(
                f"✅ **{stat.value}** hráče {member.mention} nastaven na **{hodnota}**.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"[admin_stats] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Stats(bot))