import discord
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN_BOT")

if not TOKEN:
    print("❌ DISCORD_TOKEN_BOT nebyl nalezen v prostředí!")
    exit(1)

# ====== LOGGING ======
logging.basicConfig(level=logging.INFO)

# ====== CONFIG Z ENV PROMĚNNÝCH ======
config = {
    "prefix":           os.getenv("PREFIX", "!"),
    "wiki_url":         os.getenv("WIKI_URL", "https://tvowiki.cz/aurionis"),
    "embed_color":      os.getenv("EMBED_COLOR", "FFD700"),
    "campfire_channel": os.getenv("CAMPFIRE_CHANNEL", "campfire"),
}

# ====== DATA ADRESÁŘ ======
from src.utils import paths as _paths
_data_dir_override = os.getenv("DATA_DIR")
if _data_dir_override:
    _paths.DATA_DIR = _data_dir_override
    _paths.ECONOMY           = _paths.data("economy.json")
    _paths.KOSTKY_LB         = _paths.data("kostky_leaderboard.json")
    _paths.KOSTKY_MAGIC      = _paths.data("kostky_magic_dice.json")
    _paths.GUESS_SCORES      = _paths.data("guess_scores.json")
    _paths.LIAR_SCORES       = _paths.data("liar_scores.json")
    _paths.LIAR_SLOTS_SCORES = _paths.data("liar_slots_scores.json")
    _paths.LABYRINTH_SCORES  = _paths.data("labyrinth_scores.json")
    _paths.NEWS              = _paths.data("news.json")
    _paths.STORY_LIB         = _paths.data("story_library.json")
    _paths.STORY_SAVE        = _paths.data("story_save.json")
    _paths.CARDS_DATA        = _paths.data("cards_data.json")
    _paths.CARDS_INVENTORY   = _paths.data("cards_inventory.json")
    _paths.CARDS_FRAMES      = _paths.data("cards_frames.json")
    _paths.FRAMES_INVENTORY  = _paths.data("frames_inventory.json")
    _paths.SHOP              = _paths.data("shop.json")

os.makedirs(_paths.DATA_DIR, exist_ok=True)

BOT_COGS = [
    # Minihry & karty
    "src.core.bot.cards",
    "src.core.bot.guess",
    "src.core.bot.kostky",
    "src.core.bot.liar_dice",
    "src.core.bot.liar_slots",
    "src.core.bot.gallows",
    "src.core.bot.tarot",
    "src.core.bot.minigames_hub",
    # Labyrinth (balíček)
    "src.core.bot.labyrinth",
    # Utility
    "src.core.bot.countdown",
    "src.core.bot.voice",
    "src.core.bot.poll",
    "src.core.bot.news",
    "src.core.bot.story",
    # Sdílená logika
    "src.logic.economy",
    "src.logic.radio",
]

class ArionBOT(commands.Bot):
    def __init__(self):
        self.config = config

        try:
            self.color = int(self.config['embed_color'], 16)
        except Exception:
            print("⚠️ Neplatná barva v configu, používám fallback.")
            self.color = 0xFF0000

        self.wiki_url = self.config['wiki_url']

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config['prefix'],
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        print("--- 🎮 Načítám ArionBOT Cogs ---")

        for cog in BOT_COGS:
            try:
                await self.load_extension(cog)
                print(f'   ✅ {cog} načten.')
            except Exception:
                logging.exception(f'[main_bot] {cog} selhal')
                print(f'   ❌ {cog} selhal — viz log výše.')

        print("🔄 Synchronizuji slash commandy...")
        synced = await self.tree.sync()
        print(f"✅ Synced {len(synced)} commandů.")

    async def on_ready(self):
        print(f'🎮 ArionBOT je online jako {self.user}')

# ====== RUN ======
if __name__ == "__main__":
    bot = ArionBOT()
    bot.run(TOKEN)
