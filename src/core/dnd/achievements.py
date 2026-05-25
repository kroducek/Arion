import discord
from discord.ext import commands
from discord import app_commands
import json
import os

from src.utils.paths import ACHIEVEMENTS, ACHIEVEMENT_DATA
from src.utils.json_utils import load_json, save_json

ARION_NAME = "Aurionis"

# ── Achievement definitions ───────────────────────────────────────────────────

ACHIEVEMENTS_DEF: dict[str, dict] = {
    "Vyvolený": {
        "emoji":       "🌟",
        "description": "Postoupil jsi do druhého kola turnaje hvězd.",
        "auto":        False,
        "rarity":      "Legendary",
    },
    "Strašný smolař": {
        "emoji":       "💀",
        "description": "Hodil jsi 3× za sebou nat 1. Smůla tě miluje.",
        "auto":        True,
        "rarity":      "Common",
    },
    "Šťastlivec": {
        "emoji":       "✨",
        "description": "Hodil jsi 3× za sebou nat 20. Nebo podvádíš.",
        "auto":        True,
        "rarity":      "Rare",
    },
    "Milovník kostek": {
        "emoji":       "🎲",
        "description": "Hodil jsi kostkou už 100 000×. Vážně.",
        "auto":        True,
        "rarity":      "Epic",
    },
    "Požehnaný osudem": {
        "emoji":       "🛡️",
        "description": "Přežil jsi souboj přesně s 1 HP.",
        "auto":        False,
        "rarity":      "Rare",
    },
    "Kočičí dlužník": {
        "emoji":       "🐾",
        "description": "Arion tě v minihrách obrala už o víc než 10 000 zlatých.",
        "auto":        True,
        "rarity":      "Common",
    },
    "Křest krví": {
        "emoji":       "⚔️",
        "description": "Vyhrál jsi svůj první duel v aréně.",
        "auto":        True,
        "rarity":      "Common",
    },
    "Neporazitelný": {
        "emoji":       "🏆",
        "description": "Vyhrál jsi 10 duelů v řadě bez jediné prohry.",
        "auto":        True,
        "rarity":      "Legendary",
    },
    "Vítej v Aurionisu": {
        "emoji":       "🌟",
        "description": "Dokončil jsi tutorial a vstoupil/a do světa Aurionisu.",
        "auto":        False,
        "rarity":      "Common",
    },
}

RARITY_COLOR = {
    "Common":    0x9B9B9B,
    "Rare":      0x4A90D9,
    "Epic":      0xA64AC9,
    "Legendary": 0xFFD700,
}

# ── Storage ───────────────────────────────────────────────────────────────────

def load_achievements() -> dict:
    """Thread-safe load achievements."""
    return load_json(ACHIEVEMENTS, default={})

def save_achievements(data: dict):
    """Thread-safe save achievements."""
    save_json(ACHIEVEMENTS, data)

def load_ach_data() -> dict:
    """Thread-safe load achievement tracking data."""
    return load_json(ACHIEVEMENT_DATA, default={})

def save_ach_data(data: dict):
    """Thread-safe save achievement tracking data."""
    save_json(ACHIEVEMENT_DATA, data)

def has_achievement(user_id: int, name: str) -> bool:
    return name in load_achievements().get(str(user_id), [])

def grant_achievement(user_id: int, name: str) -> bool:
    """Vrátí True pokud byl achievement nově udělen, False pokud ho hráč už měl."""
    data = load_achievements()
    uid  = str(user_id)
    data.setdefault(uid, [])
    if name in data[uid]:
        return False
    data[uid].append(name)
    save_achievements(data)
    return True

# ── Announce ──────────────────────────────────────────────────────────────────

async def announce_achievement(member: discord.Member, channel, name: str):
    ach   = ACHIEVEMENTS_DEF[name]
    color = RARITY_COLOR.get(ach["rarity"], 0xFFD700)
    embed = discord.Embed(
        title=f"{ach['emoji']}  Achievement odemčen!",
        description=f"### {name}\n*{ach['description']}*",
        color=color,
    )
    embed.add_field(name="Hráč",     value=member.mention, inline=True)
    embed.add_field(name="Vzácnost", value=ach["rarity"],  inline=True)
    embed.set_footer(text=f"⭐ {ARION_NAME}")
    try:
        await channel.send(embed=embed)
    except Exception:
        pass
    try:
        await member.send(embed=embed)
    except discord.Forbidden:
        pass

# ── Auto-check functions ──────────────────────────────────────────────────────

async def check_roll_achievements(guild_id: int, member: discord.Member, channel, stats: dict):
    """Voláno po každém hodu. stats = aktualizovaný stats dict hráče."""
    checks = [
        ("Strašný smolař", stats.get("streak_nat1", 0) >= 3),
        ("Šťastlivec",     stats.get("streak_nat20", 0) >= 3),
        ("Milovník kostek", stats.get("total", 0) >= 100_000),
    ]
    for name, condition in checks:
        if condition and not has_achievement(member.id, name):
            if grant_achievement(member.id, name):
                await announce_achievement(member, channel, name)

async def track_minigame_loss(user_id: int, amount: int, member: discord.Member, channel) -> None:
    """Voláno při prohře v minihrách. amount = kladné číslo (kolik zlatých hráč ztratil)."""
    data = load_ach_data()
    uid  = str(user_id)
    data.setdefault(uid, {})
    data[uid]["minigame_gold_lost"] = data[uid].get("minigame_gold_lost", 0) + amount
    save_ach_data(data)
    if data[uid]["minigame_gold_lost"] >= 10_000 and not has_achievement(user_id, "Kočičí dlužník"):
        if grant_achievement(user_id, "Kočičí dlužník"):
            await announce_achievement(member, channel, "Kočičí dlužník")

# ── Cog ───────────────────────────────────────────────────────────────────────

class AchievementsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    ach_group = app_commands.Group(name="achievement", description="Achievement systém")

    @app_commands.command(name="achievements", description="Zobraz získané achievementy")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def achievements_cmd(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        earned = load_achievements().get(str(target.id), [])

        lines = []
        for name, ach in ACHIEVEMENTS_DEF.items():
            if name in earned:
                lines.append(f"{ach['emoji']} **{name}** — *{ach['description']}*")
            else:
                lines.append(f"🔒 ~~{name}~~")

        is_self = target.id == interaction.user.id
        title   = "Tvoje achievementy" if is_self else f"Achievementy — {target.display_name}"

        desc = f"### 🏆 {title}\n\n" + "\n".join(lines)
        if not earned:
            desc += "\n\n-# *Zatím žádný achievement. Kostky čekají...*"
        else:
            desc += f"\n\n-# *Získáno: {len(earned)} / {len(ACHIEVEMENTS_DEF)}*"

        embed = discord.Embed(description=desc, color=0xFFD700)
        embed.set_footer(text=f"⭐ {ARION_NAME}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ach_group.command(name="done", description="Udělej achievement hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Název achievementu", member="Hráč")
    async def achievement_done(self, interaction: discord.Interaction, name: str, member: discord.Member):
        if name not in ACHIEVEMENTS_DEF:
            await interaction.response.send_message(f"Achievement **{name}** neexistuje.", ephemeral=True)
            return
        if grant_achievement(member.id, name):
            await interaction.response.send_message(f"✅ Achievement **{name}** udělen {member.mention}.", ephemeral=True)
            await announce_achievement(member, interaction.channel, name)
        else:
            await interaction.response.send_message(f"ℹ️ {member.mention} už má **{name}**.", ephemeral=True)

    @ach_group.command(name="remove", description="Odeber achievement hráči (admin)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Název achievementu", member="Hráč")
    async def achievement_remove(self, interaction: discord.Interaction, name: str, member: discord.Member):
        data = load_achievements()
        uid  = str(member.id)
        if name not in data.get(uid, []):
            await interaction.response.send_message(f"ℹ️ {member.mention} nemá **{name}**.", ephemeral=True)
            return
        data[uid].remove(name)
        save_achievements(data)
        await interaction.response.send_message(f"✅ Achievement **{name}** odebrán {member.mention}.", ephemeral=True)

    @achievement_done.autocomplete("name")
    @achievement_remove.autocomplete("name")
    async def ach_name_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=n, value=n)
            for n in ACHIEVEMENTS_DEF
            if current.lower() in n.lower()
        ][:25]


async def setup(bot):
    await bot.add_cog(AchievementsCog(bot))
