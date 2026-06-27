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
import datetime

logger = logging.getLogger("Stats")

# Maximální počet záznamů v XP logu na hráče (FIFO ring buffer)
XP_LOG_MAX_PER_USER = 50

STAT_LABELS = ['STR', 'DEX', 'INS', 'INT', 'CHA', 'WIS']
SKILL_LABELS = ['Síla', 'Obratnost', 'Magie', 'Výdrž']  # SP skilly (požadavky na výzbroj)
START_AP = 5   # body do atributů na startu (tutoriál)
START_SP = 0   # body do skillů na startu

# XP caps pro každý level (index = level)
# Level 0 je startovní — hráč začíná zde po tutorialu
XP_CAPS = [
    100,          # Lvl 0  → I
    500,          # Lvl I
    750,          # Lvl II
    1_250,        # Lvl III
    2_500,        # Lvl IV
    3_500,        # Lvl V
    5_000,        # Lvl VI
    7_500,        # Lvl VII
    9_000,        # Lvl VIII
    12_500,       # Lvl IX   (+5 SP navíc)
    14_500,       # Lvl X
    17_500,       # Lvl XI
    21_000,       # Lvl XII
    25_000,       # Lvl XIII
    30_000,       # Lvl XIV
    36_000,       # Lvl XV
    43_000,       # Lvl XVI
    51_000,       # Lvl XVII
    60_000,       # Lvl XVIII
    71_000,       # Lvl XIX
    84_000,       # Lvl XX
    99_000,       # Lvl 21
    115_000,      # Lvl 22
    135_000,      # Lvl 23
    160_000,      # Lvl 24
    190_000,      # Lvl 25
    225_000,      # Lvl 26
    265_000,      # Lvl 27
    310_000,      # Lvl 28
    365_000,      # Lvl 29
    430_000,      # Lvl 30
    505_000,      # Lvl 31
    595_000,      # Lvl 32
    700_000,      # Lvl 33
    825_000,      # Lvl 34
    970_000,      # Lvl 35
    1_150_000,    # Lvl 36
    1_350_000,    # Lvl 37
    1_600_000,    # Lvl 38
    1_900_000,    # Lvl 39
    2_250_000,    # Lvl 40
    2_650_000,    # Lvl 41
    3_100_000,    # Lvl 42
    3_650_000,    # Lvl 43
    4_300_000,    # Lvl 44
    5_050_000,    # Lvl 45
    5_950_000,    # Lvl 46
    7_000_000,    # Lvl 47
    8_250_000,    # Lvl 48
    9_700_000,    # Lvl 49
    11_500_000,   # Lvl 50
    13_500_000,   # Lvl 51
    16_000_000,   # Lvl 52
    19_000_000,   # Lvl 53
    22_500_000,   # Lvl 54
    26_500_000,   # Lvl 55
    31_000_000,   # Lvl 56
    36_500_000,   # Lvl 57
    43_000_000,   # Lvl 58
    50_500_000,   # Lvl 59
    59_500_000,   # Lvl 60
    70_000_000,   # Lvl 61
    82_500_000,   # Lvl 62
    97_000_000,   # Lvl 63
    114_000_000,  # Lvl 64
    134_000_000,  # Lvl 65
    158_000_000,  # Lvl 66
    186_000_000,  # Lvl 67
    219_000_000,  # Lvl 68
    258_000_000,  # Lvl 69
    304_000_000,  # Lvl 70
    358_000_000,  # Lvl 71
    422_000_000,  # Lvl 72
    498_000_000,  # Lvl 73
    588_000_000,  # Lvl 74
    694_000_000,  # Lvl 75
    819_000_000,  # Lvl 76
    966_000_000,  # Lvl 77
    1_139_000_000, # Lvl 78
    1_343_000_000, # Lvl 79  (MAX)
]

# SP bonus na vybraných levelech  {level: bonus_sp}
SP_BONUS = {9: 5, 20: 3, 40: 5, 60: 5, 79: 10}

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
_SKILL_EMOJI = {"Síla": "⚔️", "Obratnost": "🌀", "Magie": "🪄", "Výdrž": "🛡️"}

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
    p.setdefault("sp",           0)       # nerozdělené skill pointy (skilly)
    p.setdefault("ap",           0)       # nerozdělené attribute pointy
    p.setdefault("luck",         DEFAULT_LUCK)
    p.setdefault("stats",        {s: 1 for s in STAT_LABELS})
    p.setdefault("skills",       {s: 0 for s in SKILL_LABELS})
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
    p.setdefault("statuses", [])
    p.setdefault("vliv_svetlo",     0)
    p.setdefault("vliv_temnota",    0)
    p.setdefault("vliv_rovnovaha",  0)
    p.setdefault("luck",            DEFAULT_LUCK)
    p.setdefault("level",           0)
    p.setdefault("xp",              0)
    p.setdefault("sp",              0)
    p.setdefault("ap",              0)
    p.setdefault("stats",           {s: 1 for s in STAT_LABELS})
    p.setdefault("skills",          {s: 0 for s in SKILL_LABELS})

def _load_items_db() -> dict:
    try:
        return load_json(ITEMS_FILE, default={})
    except Exception:
        return {}

# ══════════════════════════════════════════════════════════════════════════════
# XP LOG — persistentní log v profiles.json pod klíčem "xp_log"
# Každý záznam: {"ts": ISO str, "delta": int, "level_before": int,
#                "level_after": int, "reason": str}
# ══════════════════════════════════════════════════════════════════════════════

def _append_xp_log(p: dict, delta: int, level_before: int,
                   level_after: int, reason: str = "") -> None:
    """Přidá záznam do XP logu hráče (FIFO, max XP_LOG_MAX_PER_USER záznamů)."""
    entry = {
        "ts":           datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "delta":        delta,
        "level_before": level_before,
        "level_after":  level_after,
        "reason":       reason,
    }
    log = p.setdefault("xp_log", [])
    log.append(entry)
    # FIFO — zahoď nejstarší pokud přesáhne limit
    if len(log) > XP_LOG_MAX_PER_USER:
        p["xp_log"] = log[-XP_LOG_MAX_PER_USER:]


def get_xp_log(user_id: int) -> list[dict]:
    """Vrátí XP log hráče (od nejnovějšího)."""
    data = _load()
    p    = _profile(data, str(user_id))
    return list(reversed(p.get("xp_log", [])))


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


def level_rewards(level: int) -> tuple[int, int]:
    """Body získané za DOSAŽENÍ daného levelu → (sp, ap).
    SP (hojnější — skilly+perky) = (sudý level) + 3×(násobek 5)
    AP (vzácnější — 6 atributů)  = (lichý level) + (násobek 10)."""
    sp = (1 if level % 2 == 0 else 0) + (3 if level % 5 == 0 else 0)
    ap = (1 if level % 2 == 1 else 0) + (1 if level % 10 == 0 else 0)
    return sp, ap


def attr_cap(level: int) -> int:
    """Max BONUS na jeden atribut nad základ (base 1) podle tieru levelu.
    ≤19 → +5,  ≤39 → +10.  Nad 40 zatím beze změny (TBD)."""
    if level <= 19:
        return 5
    if level <= 39:
        return 10
    return 10

def level_label(level: int) -> str:
    roman = [
        "0","I","II","III","IV","V","VI","VII","VIII","IX","X",
        "XI","XII","XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX",
    ]
    if level < len(roman):
        return f"Lvl {roman[level]}"
    return f"Lvl {level}"

def init_stats(user_id: int, base_stats: dict, sp: int = 0, ap: int = 0):
    """
    Inicializuje stats hráče při tutorialu.
    base_stats: dict {'STR': int, ...}
    sp: nerozdělené skill pointy (skilly),  ap: nerozdělené attribute pointy
    """
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    p["stats"]  = {s: base_stats.get(s, 1) for s in STAT_LABELS}
    p["skills"] = {s: 0 for s in SKILL_LABELS}
    p["level"]  = 0
    p["xp"]     = 0
    p["sp"]     = sp
    p["ap"]     = ap
    p["luck"]   = DEFAULT_LUCK
    _save(data)

def add_xp(user_id: int, amount: int, reason: str = "") -> dict:
    """
    Přidá XP hráči. Vrátí dict s informacemi o levelupu.
    Return: {'leveled_up': bool, 'levels_gained': int, 'new_level': int,
             'sp_gained': int, 'xp': int, 'cap': int|None}
    Záporné amount je tiše ignorováno — pro odebrání XP použij remove_xp().
    reason: volitelný popis (zobrazí se v /xp-log), např. "Quest: Stíny minulosti"
    """
    if amount <= 0:
        p = _profile(_load(), str(user_id))
        return {
            "leveled_up":    False,
            "levels_gained": 0,
            "new_level":     p["level"],
            "sp_gained":     0,
            "ap_gained":     0,
            "xp":            p["xp"],
            "cap":           get_xp_cap(p["level"]),
        }

    data          = _load()
    uid           = str(user_id)
    p             = _profile(data, uid)
    level_before  = p["level"]
    p["xp"]       = max(0, p["xp"] + amount)

    leveled_up    = False
    sp_gained     = 0
    ap_gained     = 0
    levels_gained = 0
    new_level     = p["level"]

    cap = get_xp_cap(p["level"])
    while cap is not None and p["xp"] >= cap:
        p["xp"]    -= cap
        p["level"] += 1
        new_level   = p["level"]
        leveled_up  = True
        levels_gained += 1
        lsp, lap    = level_rewards(new_level)
        sp_gained  += lsp
        ap_gained  += lap
        p["sp"]    += lsp
        p["ap"]     = p.get("ap", 0) + lap
        cap = get_xp_cap(p["level"])

    _append_xp_log(p, amount, level_before, new_level, reason)
    _save(data)
    return {
        "leveled_up":    leveled_up,
        "levels_gained": levels_gained,
        "new_level":     new_level,
        "sp_gained":     sp_gained,
        "ap_gained":     ap_gained,
        "xp":            p["xp"],
        "cap":           get_xp_cap(new_level),
    }


def remove_xp(user_id: int, amount: int, reason: str = "") -> dict:
    """
    Odebere XP hráči. XP neklesne pod 0, level se nesníží.
    Return: {'new_xp': int, 'level': int, 'cap': int|None}
    reason: volitelný popis (zobrazí se v /xp-log)
    """
    if amount <= 0:
        raise ValueError("amount musí být kladné číslo")
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    level_before  = p["level"]
    p["xp"]       = max(0, p["xp"] - amount)
    _append_xp_log(p, -amount, level_before, p["level"], reason)
    _save(data)
    return {
        "new_xp": p["xp"],
        "level":  p["level"],
        "cap":    get_xp_cap(p["level"]),
    }

def get_stats(user_id: int) -> dict:
    """Vrátí stats dict hráče (vždy s plně inicializovanými poli)."""
    data = _load()
    p    = _profile(data, str(user_id))
    _ensure_fields(p)
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

def spend_ap(user_id: int, attr: str, amount: int = 1) -> bool:
    """Utratí AP na atribut (STR/DEX/...). Hlídá tier strop. True při úspěchu."""
    if attr not in STAT_LABELS:
        return False
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    if p.get("ap", 0) < amount:
        return False
    cur = p["stats"].get(attr, 1)
    # strop: hodnota atributu nesmí přesáhnout 1 + attr_cap(level)
    if (cur + amount) - 1 > attr_cap(p.get("level", 0)):
        return False
    p["ap"]           = p.get("ap", 0) - amount
    p["stats"][attr]  = cur + amount
    _save(data)
    return True

def spend_sp(user_id: int, skill: str, amount: int = 1) -> bool:
    """Utratí SP na skill (Síla/Obratnost/Magie/Výdrž). True při úspěchu."""
    if skill not in SKILL_LABELS:
        return False
    data = _load()
    uid  = str(user_id)
    p    = _profile(data, uid)
    if p.get("sp", 0) < amount:
        return False
    p.setdefault("skills", {s: 0 for s in SKILL_LABELS})
    p["sp"]            = p.get("sp", 0) - amount
    p["skills"][skill] = p["skills"].get(skill, 0) + amount
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
    ap         = p.get("ap", 0)
    skills     = p.get("skills", {})
    luck       = p.get("luck", DEFAULT_LUCK)
    stats      = p.get("stats", {})
    total_def  = _compute_def(p, items_db)
    cap        = get_xp_cap(level)

    char_name = p.get("name", user.display_name)
    def_str   = f"  ·  🛡️ **{total_def}**" if total_def else ""
    xp_str    = f"*{xp} (MAX)*" if not cap else f"*{xp}/{cap}*"
    pts = []
    if ap > 0: pts.append(f"🎯 **{ap} AP**")
    if sp > 0: pts.append(f"⚡ **{sp} SP**")
    sp_str    = ("  ·  " + "  ·  ".join(pts)) if pts else ""

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

    # ── Skilly (jen pokud do nich něco šlo) ───────────────────────────────────
    if skills and any(skills.get(s, 0) for s in SKILL_LABELS):
        sparts = [
            f"*{_SKILL_EMOJI.get(s, '')} {s}* **{skills.get(s, 0)}**"
            for s in SKILL_LABELS
        ]
        lines.append("  ·  ".join(sparts))

    # ── Aktivní statusy ───────────────────────────────────────────────────────
    active_statuses = p.get("statuses") or []
    if active_statuses:
        try:
            from src.core.dnd.blacksmith import describe_statuses
            st_desc = describe_statuses(p)
        except Exception:
            st_desc = ""
        if st_desc:
            lines.append("")
            lines.append("🩸 **Aktivní statusy**")
            lines.append(st_desc)

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
        # Bezpečnostní kontrola — jen vlastník může upravovat svůj profil
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "❌ *Nemůžeš upravovat cizí profil.*", ephemeral=True
            )
            return

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

    @discord.ui.button(label="🩹 Vyléčit statusy", style=discord.ButtonStyle.green, row=1)
    async def btn_cure(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        data = _load()
        p    = data.get(str(self.user_id), {})
        _ensure_fields(p)
        if not (p.get("statuses") or []):
            return await interaction.response.send_message("✨ Žádné aktivní statusy.", ephemeral=True)
        try:
            from src.core.dnd.blacksmith import describe_statuses
            desc = describe_statuses(p)
        except Exception:
            desc = ""
        await interaction.response.send_message(
            f"🩹 **Vyléčit statusy** — vyber typ léčení:\n{desc}",
            view=_CureView(self.user_id), ephemeral=True)


class _CureView(discord.ui.View):
    """Volba typu léčení statusů (fyzické/magické/vše)."""
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    async def _cure(self, interaction: discord.Interaction, cure_type: str):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Není tvoje.", ephemeral=True)
        try:
            from src.core.dnd.blacksmith import cure_statuses
        except Exception:
            return await interaction.response.send_message("❌ Status engine nedostupný.", ephemeral=True)
        data = _load()
        p    = data.get(str(self.user_id), {})
        _ensure_fields(p)
        if cure_type == "vse":
            removed = [s.get("status") for s in p.get("statuses", [])]
            p["statuses"] = []
        else:
            removed = cure_statuses(p, cure_type)
        _save(data)
        await interaction.response.edit_message(
            content=f"🩹 Sundáno: {', '.join(removed) if removed else 'nic'}.", view=None)

    @discord.ui.button(label="Fyzické", style=discord.ButtonStyle.primary)
    async def cure_fyz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._cure(interaction, "fyzické")

    @discord.ui.button(label="Magické", style=discord.ButtonStyle.primary)
    async def cure_mag(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._cure(interaction, "magické")

    @discord.ui.button(label="Vše", style=discord.ButtonStyle.secondary)
    async def cure_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._cure(interaction, "vse")


# ══════════════════════════════════════════════════════════════════════════════
# LEVELUP VIEW — hráč rozděluje SP po levelupu
# ══════════════════════════════════════════════════════════════════════════════

class StatPointView(discord.ui.View):
    """Rozdávání bodů s přepínačem: Atributy (AP) ↔ Skilly (SP)."""

    def __init__(self, user_id: int, mode: str = "ap"):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.mode    = mode if mode in ("ap", "sp") else "ap"
        targets = STAT_LABELS if self.mode == "ap" else SKILL_LABELS
        emo     = _SP_EMOJI   if self.mode == "ap" else _SKILL_EMOJI
        for idx, name in enumerate(targets):
            row = 0 if idx < 5 else 1
            btn = discord.ui.Button(
                label=f"{emo.get(name, '')} {name}",
                style=discord.ButtonStyle.blurple,
                row=row,
            )
            btn.callback = self._make_cb(name)
            self.add_item(btn)
        # přepínač režimu
        other = "Skilly (SP)" if self.mode == "ap" else "Atributy (AP)"
        tbtn = discord.ui.Button(label=f"🔁 {other}", style=discord.ButtonStyle.secondary, row=2)
        tbtn.callback = self._toggle
        self.add_item(tbtn)

    def _header(self, p: dict) -> discord.Embed:
        ap = p.get("ap", 0); sp = p.get("sp", 0); lvl = p.get("level", 0)
        if self.mode == "ap":
            title = "🎯 Attribute Pointy"
            body  = (
                f"Máš **{ap}** volných 🎯 AP.\n\n"
                "Klikni na atribut, který chceš zvýšit (+1 atribut = +1 k hodům).\n"
                f"-# Strop na lvl {lvl}: max **+{attr_cap(lvl)}** na jeden atribut."
            )
        else:
            title = "⚡ Skill Pointy"
            body  = (
                f"Máš **{sp}** volných ⚡ SP.\n\n"
                "Klikni na skill, který chceš zvýšit.\n"
                f"-# Skilly: {', '.join(SKILL_LABELS)}"
            )
        e = discord.Embed(title=title, description=body, color=0x9b59b6)
        e.set_footer(text=f"🎯 {ap} AP  ·  ⚡ {sp} SP")
        return e

    async def _toggle(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Toto není tvůj výběr.", ephemeral=True)
            return
        new_mode = "sp" if self.mode == "ap" else "ap"
        p    = _profile(_load(), str(self.user_id))
        view = StatPointView(self.user_id, mode=new_mode)
        await interaction.response.edit_message(embed=view._header(p), view=view)

    def _make_cb(self, name: str):
        async def cb(interaction: discord.Interaction):
            try:
                if interaction.user.id != self.user_id:
                    await interaction.response.send_message("❌ Toto není tvůj výběr.", ephemeral=True)
                    return
                if self.mode == "ap":
                    if not spend_ap(self.user_id, name, 1):
                        p = _profile(_load(), str(self.user_id))
                        lvl = p.get("level", 0)
                        if p.get("ap", 0) <= 0:
                            msg = "❌ Nemáš žádné volné AP."
                        else:
                            msg = f"❌ **{name}** je na stropu (+{attr_cap(lvl)} na lvl {lvl})."
                        await interaction.response.send_message(msg, ephemeral=True)
                        return
                else:
                    if not spend_sp(self.user_id, name, 1):
                        await interaction.response.send_message("❌ Nemáš žádné volné SP.", ephemeral=True)
                        return
                p = _profile(_load(), str(self.user_id))
                if self.mode == "ap":
                    new_val = p.get("stats", {}).get(name, 1)
                else:
                    new_val = p.get("skills", {}).get(name, 0)
                view  = StatPointView(self.user_id, mode=self.mode)
                embed = view._header(p)
                embed.description = f"✅ **{name}** → **{new_val}**\n\n" + embed.description
                await interaction.response.edit_message(embed=embed, view=view)
            except discord.errors.NotFound:
                logger.warning(f"[StatPointView] Message not found for user {self.user_id}")
            except Exception as e:
                logger.exception(f"[StatPointView] Error for {name}: {e}")
                try:
                    await interaction.response.send_message(f"❌ Chyba: {str(e)[:100]}", ephemeral=True)
                except Exception:
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

    # ── /staty ────────────────────────────────────────────────────────────────

    @app_commands.command(name="staty", description="Rozděl své body — atributy (AP) a skilly (SP).")
    async def staty_cmd(self, interaction: discord.Interaction):
        try:
            data = _load()
            p    = _profile(data, str(interaction.user.id))
            ap = p.get("ap", 0); sp = p.get("sp", 0)
            if ap <= 0 and sp <= 0:
                await interaction.response.send_message(
                    "❌ Nemáš žádné volné body (AP ani SP).", ephemeral=True
                )
                return
            mode = "ap" if ap > 0 else "sp"
            view = StatPointView(interaction.user.id, mode=mode)
            await interaction.response.send_message(
                embed=view._header(p), view=view, ephemeral=True
            )
        except Exception as e:
            logger.exception(f"[staty_cmd] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}", ephemeral=True
            )

    # ── /reset-stats ──────────────────────────────────────────────────────────

    @app_commands.command(name="reset-stats", description="[Admin] Vynuluje rozdané staty/skilly a vrátí body dle levelu.")
    @app_commands.describe(member="Hráč (výchozí: všichni)")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_stats_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        try:
            data    = _load()
            targets = [str(member.id)] if member else list(data.keys())
            n = 0
            for uid in targets:
                if uid not in data:
                    continue
                p   = _profile(data, uid)
                lvl = p.get("level", 0)
                tot_sp = START_SP
                tot_ap = START_AP
                for L in range(1, lvl + 1):
                    s, a = level_rewards(L)
                    tot_sp += s; tot_ap += a
                p["stats"]  = {s: 1 for s in STAT_LABELS}
                p["skills"] = {s: 0 for s in SKILL_LABELS}
                p["ap"] = tot_ap
                p["sp"] = tot_sp
                n += 1
            _save(data)
            scope = member.mention if member else f"**{n}** hráč(ů)"
            await interaction.response.send_message(
                f"♻️ Reset hotov pro {scope}.\nAtributy→1, skilly→0, body vráceny dle levelu "
                "(rozdej znovu přes /staty).",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"[reset_stats] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}", ephemeral=True
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

            bar_filled = min(20, round(luck / 10))
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
    @app_commands.describe(
        member="Hráč",
        amount="Množství XP (kladné = přidat, záporné = odebrat)",
        reason="Důvod (zobrazí se v /xp-log hráče)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_xp(self, interaction: discord.Interaction, member: discord.Member,
                       amount: int, reason: str = ""):
        try:
            if amount > 0:
                result = add_xp(member.id, amount, reason=reason)
                if result["leveled_up"]:
                    cap_str = f"/ {result['cap']:,}" if result["cap"] else "(MAX)"
                    levels_str = (
                        f"  *(+{result['levels_gained']} levelů)*"
                        if result["levels_gained"] > 1 else ""
                    )
                    embed = discord.Embed(
                        title="⬆️ Level Up!",
                        description=(
                            f"{member.mention} dosáhl/a **{level_label(result['new_level'])}**!{levels_str}\n\n"
                            f"XP: **{result['xp']:,}** {cap_str}\n"
                            f"Získané body: 🎯 **{result['ap_gained']} AP**  ·  ⚡ **{result['sp_gained']} SP**"
                        ),
                        color=0xf1c40f,
                    )
                    await interaction.response.send_message(
                        content=member.mention, embed=embed
                    )
                else:
                    cap_str = f"/ {result['cap']:,}" if result["cap"] else "(MAX)"
                    await interaction.response.send_message(
                        f"✅ {member.mention} získal/a **+{amount:,} XP**. "
                        f"Aktuálně: **{result['xp']:,}** {cap_str}",
                        ephemeral=True,
                    )
            elif amount < 0:
                result = remove_xp(member.id, abs(amount), reason=reason)
                cap_str = f"/ {result['cap']:,}" if result["cap"] else "(MAX)"
                await interaction.response.send_message(
                    f"✅ {member.mention} ztratil/a **{abs(amount):,} XP**. "
                    f"Aktuálně: **{result['new_xp']:,}** {cap_str}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "❌ Zadej nenulové množství XP.", ephemeral=True
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


    # ── /xp-log ───────────────────────────────────────────────────────────────

    @app_commands.command(name="xp-log", description="Zobraz historii XP změn.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def xp_log_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        try:
            target   = member or interaction.user
            is_self  = (member is None or member.id == interaction.user.id)
            is_admin = interaction.user.guild_permissions.administrator

            # Cizí log může vidět jen admin
            if not is_self and not is_admin:
                await interaction.response.send_message(
                    "❌ Nemáš oprávnění zobrazit XP log jiného hráče.", ephemeral=True
                )
                return

            log = get_xp_log(target.id)  # od nejnovějšího
            if not log:
                await interaction.response.send_message(
                    f"*{target.display_name} ještě nemá žádné záznamy v XP logu.*",
                    ephemeral=True,
                )
                return

            lines = []
            for entry in log[:20]:  # max 20 zobrazených
                delta      = entry["delta"]
                sign       = "+" if delta >= 0 else ""
                lvl_before = entry["level_before"]
                lvl_after  = entry["level_after"]
                ts         = entry["ts"][:16].replace("T", " ")  # "YYYY-MM-DD HH:MM"
                reason     = entry.get("reason", "")

                lvl_str = (
                    f"  ⬆️ {level_label(lvl_before)} → **{level_label(lvl_after)}**"
                    if lvl_after != lvl_before else ""
                )
                reason_str = f"  *{reason}*" if reason else ""
                icon       = "📈" if delta >= 0 else "📉"
                lines.append(
                    f"{icon} `{ts}` **{sign}{delta:,} XP**{lvl_str}{reason_str}"
                )

            data  = _load()
            p     = _profile(data, str(target.id))
            level = p["level"]
            xp    = p["xp"]
            cap   = get_xp_cap(level)
            cap_str = f"/ {cap:,}" if cap else "(MAX)"

            embed = discord.Embed(
                title=f"📜 XP Log — {target.display_name}",
                description="\n".join(lines),
                color=0x3498db,
            )
            embed.set_footer(
                text=f"{level_label(level)}  ·  {xp:,} {cap_str} XP  ·  "
                     f"zobrazeno {min(len(log), 20)} / {len(log)} záznamů"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.exception(f"[xp_log_cmd] Error: {e}")
            await interaction.response.send_message(
                f"❌ Chyba: {str(e)[:100]}", ephemeral=True
            )

    # ── /xp-leaderboard ───────────────────────────────────────────────────────

    @app_commands.command(name="xp-leaderboard", description="Žebříček hráčů podle levelu a XP.")
    async def xp_leaderboard_cmd(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=False)

            data = _load()
            if not data:
                await interaction.followup.send("*Žádní hráči ještě nemají profil.*")
                return

            # Seřadit: primárně level desc, sekundárně xp desc
            entries = []
            for uid, p in data.items():
                if not isinstance(p, dict):
                    continue
                level = p.get("level", 0)
                xp    = p.get("xp", 0)
                entries.append((uid, level, xp))

            entries.sort(key=lambda x: (x[1], x[2]), reverse=True)
            top = entries[:15]

            # Resolve Discord member names
            guild      = interaction.guild
            lines      = []
            medals     = {1: "🥇", 2: "🥈", 3: "🥉"}
            caller_uid = str(interaction.user.id)
            caller_pos = next(
                (i + 1 for i, (uid, *_) in enumerate(entries) if uid == caller_uid),
                None,
            )

            for rank, (uid, level, xp) in enumerate(top, 1):
                medal = medals.get(rank, f"`#{rank}`")
                cap   = get_xp_cap(level)
                cap_str = f"/ {cap:,}" if cap else "(MAX)"

                try:
                    member = guild.get_member(int(uid)) or await guild.fetch_member(int(uid))
                    name   = member.display_name
                except Exception:
                    name = f"*Hráč {uid[-4:]}*"

                bold_open  = "**" if uid == caller_uid else ""
                bold_close = "**" if uid == caller_uid else ""
                lines.append(
                    f"{medal}  {bold_open}{name}{bold_close}  —  "
                    f"{level_label(level)}  ·  {xp:,} {cap_str} XP"
                )

            footer_parts = [f"Celkem hráčů: {len(entries)}"]
            if caller_pos and caller_pos > 15:
                footer_parts.append(f"Tvoje pozice: #{caller_pos}")

            embed = discord.Embed(
                title="🏆 XP Žebříček",
                description="\n".join(lines) if lines else "*Žádná data.*",

                color=0xf1c40f,
            )
            embed.set_footer(text="  ·  ".join(footer_parts) + "  ·  Aurionis")
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.exception(f"[xp_leaderboard_cmd] Error: {e}")
            await interaction.followup.send(
                f"❌ Chyba: {str(e)[:100]}"
            )


async def setup(bot):
    await bot.add_cog(Stats(bot))