import discord
from discord.ext import commands
import json
import os
import re

# ── CONFIG ────────────────────────────────────────────────────────────────────

from src.utils.paths import DND_COUNTER as COUNTER_FILE
SNAJPY_ID    = 252489083899609089

DND_PATTERNS = [
    r"kdy\s+(bude\s+)?dnd",
    r"dal\s?bych\s+dnd",
    r"zahr[aá]l\s+bych\s+dnd",
    r"hrajeme\s+dnd",
    r"chci\s+dnd",
    r"dnd\s+dnes",
    r"dnd\s+dneska",
    r"budem\s+dnd",
    r"budeme\s+dnd",
    r"pl[aá]nujeme\s+dnd",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_counter() -> int:
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("count", 0)
        except Exception:
            return 0
    return 0

def save_counter(count: int):
    try:
        os.makedirs(os.path.dirname(COUNTER_FILE), exist_ok=True)
        with open(COUNTER_FILE, "w", encoding="utf-8") as f:
            json.dump({"count": count}, f)
    except Exception as e:
        print(f"[snajpycounter] Chyba při ukládání: {e}")

def is_dnd_message(content: str) -> bool:
    text = content.lower()
    return any(re.search(p, text) for p in DND_PATTERNS)

def flavor_text(count: int) -> str:
    milestones = {
        1:   "Začátek legendy... 🌱",
        5:   "Pět! Zlatý jubileum! 🥇",
        10:  "Desítka! Jsme v lore teď. 📜",
        25:  "25× ... trpělivost má meze. 😤",
        50:  "50× – zasluhuje achievement. 🏆",
        100: "100×. Legenda potvrzena. 👑",
    }
    if count in milestones:
        return milestones[count]
    if count % 10 == 0:
        return f"Další desítka! {count} je solidní číslo. 🎯"
    return "Arion si to zapsal... 🐾"

# ── Cog ───────────────────────────────────────────────────────────────────────

class SnajpyCounter(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.author.id != SNAJPY_ID:
            return
        if not is_dnd_message(message.content):
            return

        count = load_counter() + 1
        save_counter(count)

        embed = discord.Embed(color=0x7B2FBE)
        embed.add_field(
            name='🎲 "Kdy DnD?" counter',
            value=(
                f"**{message.author.display_name}** se zeptal(a) na DnD už\n"
                f"# {count}×"
            ),
            inline=False,
        )
        embed.set_footer(text=f"{flavor_text(count)}\n\n⭐ Aurionis")

        await message.reply(content="🐱", embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(SnajpyCounter(bot))