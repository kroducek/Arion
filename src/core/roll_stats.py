import discord
from discord.ext import commands
from discord import app_commands
import json
import os

from src.utils.paths import ROLL_STATS as ROLL_STATS_FILE


# ── Datová vrstva ──────────────────────────────────────────────────────────────
#
# Formát:
# {
#   "guild_id": {
#     "user_id": {
#       "nat20":  int,
#       "nat1":   int,
#       "hits24": int,
#       "total":  int
#     }
#   }
# }

def load_stats() -> dict:
    if not os.path.exists(ROLL_STATS_FILE):
        return {}
    try:
        with open(ROLL_STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_stats(data: dict):
    try:
        with open(ROLL_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[roll_stats] Chyba při ukládání: {e}")

def record_roll(guild_id: int, user_id: int, *, nat20: bool, nat1: bool, hit24: bool, is_check: bool = False):
    """Zaznamená výsledek hodu pro daného hráče."""
    data = load_stats()
    gid  = str(guild_id)
    uid  = str(user_id)
    data.setdefault(gid, {}).setdefault(uid, {"nat20": 0, "nat1": 0, "hits24": 0, "total": 0, "checks": 0})
    s = data[gid][uid]
    s.setdefault("checks", 0)
    s["total"]  += 1
    if is_check: s["checks"] += 1
    if nat20:    s["nat20"]  += 1
    if nat1:     s["nat1"]   += 1
    if hit24:    s["hits24"] += 1
    save_stats(data)

def get_stats(guild_id: int, user_id: int) -> dict:
    data = load_stats()
    return data.get(str(guild_id), {}).get(str(user_id), {"nat20": 0, "nat1": 0, "hits24": 0, "total": 0})

def get_all_stats(guild_id: int) -> dict:
    return load_stats().get(str(guild_id), {})


# ── Cog ────────────────────────────────────────────────────────────────────────

class RollStatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="show_rolls", description="Zobraz statistiky hodů kostkami")
    @app_commands.describe(member="Hráč jehož statistiky chceš vidět (výchozí: ty)")
    async def show_rolls(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target   = member or interaction.user
        stats    = get_stats(interaction.guild.id, target.id)
        total    = stats["total"]
        nat20    = stats["nat20"]
        nat1     = stats["nat1"]
        hits24   = stats["hits24"]
        checks   = stats.get("checks", 0)
        rolls    = total - checks

        # Procentní šance
        def pct(n):
            if total == 0: return "—"
            return f"{n / total * 100:.1f} %"

        # Titulní řádek
        is_self = target.id == interaction.user.id
        if is_self:
            header = "Pššt.. jen pro tebe 🐾"
        else:
            header = f"Záznamy pro **{target.display_name}**"

        # Hodnocení nat1 / nat20 poměru
        if total == 0:
            verdict = "*Zatím žádný hod. Kostky čekají...*"
        elif nat20 > nat1 * 2:
            verdict = "*Hvězdy ti přejí. Nebo podvádíš.*"
        elif nat1 > nat20 * 2:
            verdict = "*Snad příště. Nebo ne.*"
        elif hits24 >= 3:
            verdict = "*Číslo 24... to není náhoda.*  👀"
        else:
            verdict = "*Průměrný osud. Nic víc, nic míň.*"

        # Easter egg řádek pro 24
        line_24 = ""
        if hits24 > 0:
            line_24 = f"\n**24**  🎲  `{hits24}×`   -# *...co to znamená?*"

        desc = (
            f"### 🐱  {header}\n"
            f"*Pššt.. nikomu neříkej, že tohle umím..*\n"
            f"\n"
            f"🎲  Celkem hodů: **{total}**   -# *(hody: {rolls}  ·  checky: {checks})*\n"
            f"\n"
            f"✨  Natural 20:  `{nat20}×`   -# *({pct(nat20)})*\n"
            f"💀  Natural 1:   `{nat1}×`   -# *({pct(nat1)})*"
            f"{line_24}\n"
            f"\n"
            f"-# {verdict}"
        )

        embed = discord.Embed(
            description=desc,
            color=0x2C2F33,
        )
        embed.set_footer(text="⭐ Aurionis")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RollStatsCog(bot))