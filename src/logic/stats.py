import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

from src.utils.paths import PROFILES as DATA_FILE
from src.utils.json_utils import load_json, save_json

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

# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — volané z jiných cogů
# ══════════════════════════════════════════════════════════════════════════════

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
# LEVELUP VIEW — hráč rozděluje SP po levelupu
# ══════════════════════════════════════════════════════════════════════════════

class SpendSPView(discord.ui.View):
    """Ephemeral view pro rozdělení SP po levelupu."""

    def __init__(self, user_id: int, sp_to_spend: int):
        super().__init__(timeout=300)
        self.user_id     = user_id
        self.sp_to_spend = sp_to_spend

    @discord.ui.button(label="Rozdělit skill pointy", style=discord.ButtonStyle.primary, emoji="⚡")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Toto není tvůj levelup.", ephemeral=True)
            return
        await interaction.response.send_modal(SpendSPModal(user_id=self.user_id))


class SpendSPModal(discord.ui.Modal, title="Rozdělit Skill Pointy"):
    choice = discord.ui.TextInput(
        label="Stat (STR / DEX / INS / INT / CHA / WIS)",
        placeholder="Napiš název statu — např. STR",
        required=True,
        max_length=3,
    )

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        stat = self.choice.value.strip().upper()
        if stat not in STAT_LABELS:
            await interaction.response.send_message(
                f"❌ Neznámý stat `{stat}`. Použij: {', '.join(STAT_LABELS)}",
                ephemeral=True,
            )
            return

        data = _load()
        uid  = str(self.user_id)
        p    = _profile(data, uid)

        if p["sp"] <= 0:
            await interaction.response.send_message("Nemáš žádné volné skill pointy.", ephemeral=True)
            return

        p["sp"]         -= 1
        p["stats"][stat] = p["stats"].get(stat, 1) + 1
        _save(data)

        remaining = p["sp"]
        new_val   = p["stats"][stat]

        embed = discord.Embed(
            title="⚡  Skill Point utracen",
            description=(
                f"**{stat}** zvýšen na **{new_val}**.\n\n"
                f"Zbývající SP: **{remaining}**"
                + ("\n\n*Klikni znovu pro další SP.*" if remaining > 0 else "\n\n*Všechny SP rozděleny.*")
            ),
            color=0x9b59b6,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# COG — příkazy
# ══════════════════════════════════════════════════════════════════════════════

class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /stats ────────────────────────────────────────────────────────────────

    @app_commands.command(name="stats", description="Zobraz své staty, level a XP.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def stats_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        data   = _load()
        p      = _profile(data, str(target.id))

        level  = p["level"]
        xp     = p["xp"]
        cap    = get_xp_cap(level)
        sp     = p["sp"]
        luck   = p["luck"]
        stats  = p.get("stats", {})

        xp_bar = f"{xp} / {cap} XP" if cap else f"{xp} XP (MAX LEVEL)"

        stats_lines = "  ".join(f"**{s}** {stats.get(s, 1)}" for s in STAT_LABELS)

        embed = discord.Embed(
            title=f"📊  {target.display_name}",
            color=0x9b59b6,
        )
        embed.add_field(name="Level", value=f"**{level_label(level)}**", inline=True)
        embed.add_field(name="XP",    value=xp_bar,                      inline=True)
        if sp > 0:
            embed.add_field(name="⚡ Volné SP", value=str(sp),            inline=True)
        embed.add_field(name="Staty", value=stats_lines,                  inline=False)
        embed.add_field(name="Štěstí (LUCK)", value=f"{luck}%",           inline=True)
        embed.set_footer(text="⭐ Aurionis")

        await interaction.response.send_message(embed=embed, ephemeral=(member is None))

    # ── /sp ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="sp", description="Rozděl své skill pointy.")
    async def sp_cmd(self, interaction: discord.Interaction):
        data = _load()
        p    = _profile(data, str(interaction.user.id))
        sp   = p["sp"]

        if sp <= 0:
            await interaction.response.send_message(
                "Nemáš žádné volné skill pointy.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="⚡  Skill Pointy",
            description=(
                f"Máš **{sp}** volných SP.\n\n"
                "Klikni a vyber stat který chceš zvýšit.\n"
                f"-# Dostupné staty: {', '.join(STAT_LABELS)}"
            ),
            color=0x9b59b6,
        )
        await interaction.response.send_message(
            embed=embed,
            view=SpendSPView(user_id=interaction.user.id, sp_to_spend=sp),
            ephemeral=True,
        )

    # ── /luck ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="luck", description="Zobraz svůj aktuální Luck.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def luck_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
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
            title=f"🍀  Štěstí — {target.display_name}",
            description=f"`{bar}` **{luck}%**\n\n{desc}",
            color=0xf1c40f,
        )
        embed.set_footer(text="⭐ Aurionis")
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

    # ── /admin-xp ─────────────────────────────────────────────────────────────

    @app_commands.command(name="admin-xp", description="[Admin] Přidej nebo odeber XP hráči.")
    @app_commands.describe(member="Hráč", amount="Množství XP (kladné = přidat, záporné = odebrat)")
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_xp(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount > 0:
            result = add_xp(member.id, amount)
            if result["leveled_up"]:
                cap_str = f"/ {result['cap']}" if result["cap"] else "(MAX)"
                embed = discord.Embed(
                    title="⬆️  Level Up!",
                    description=(
                        f"{member.mention} dosáhl/a **{level_label(result['new_level'])}**!\n\n"
                        f"XP: **{result['xp']}** {cap_str}\n"
                        f"Získané SP: **{result['sp_gained']}**"
                    ),
                    color=0xf1c40f,
                )
                await interaction.response.send_message(embed=embed)
                # Upozornit hráče ephemeral
                try:
                    await interaction.followup.send(
                        content=member.mention,
                        embed=discord.Embed(
                            title="⬆️  Level Up!",
                            description=(
                                f"Dosáhl/a jsi **{level_label(result['new_level'])}**!\n\n"
                                f"Získal/a jsi **{result['sp_gained']} SP** — rozděl je přes `/sp`."
                            ),
                            color=0xf1c40f,
                        ),
                    )
                except Exception:
                    pass
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
        data = _load()
        uid  = str(member.id)
        p    = _profile(data, uid)
        p["stats"][stat.value] = max(1, hodnota)
        _save(data)
        await interaction.response.send_message(
            f"✅ **{stat.value}** hráče {member.mention} nastaven na **{hodnota}**.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Stats(bot))