import discord
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ DISCORD_TOKEN nebyl nalezen v prostředí!")
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
# Na Railway nastav env proměnnou DATA_DIR=/data (persistent volume)
# Lokálně se použije výchozí cesta src/database/data/
from src.utils import paths as _paths
_data_dir_override = os.getenv("DATA_DIR")
if _data_dir_override:
    _paths.DATA_DIR = _data_dir_override
    # Přepsat všechny cesty
    _paths.PROFILES         = _paths.data("profiles.json")
    _paths.ECONOMY          = _paths.data("economy.json")
    _paths.DIARIES          = _paths.data("diaries.json")
    _paths.ITEMS            = _paths.data("items.json")
    _paths.RP_ROOMS         = _paths.data("rp_rooms.json")
    _paths.QUESTS           = _paths.data("quests.json")
    _paths.QUEST_LOG        = _paths.data("quest_log.json")
    _paths.SHOP             = _paths.data("shop.json")
    _paths.PARTIES          = _paths.data("parties.json")
    _paths.TOURNAMENT       = _paths.data("tournament.json")
    _paths.COMBAT_STATE     = _paths.data("combat_state.json")
    _paths.REPUTATION       = _paths.data("reputation.json")
    _paths.TAKEDOWNS        = _paths.data("takedowns.json")
    _paths.ROLL_STATS       = _paths.data("roll_stats.json")
    _paths.DND_COUNTER      = _paths.data("dnd_counter.json")
    _paths.KOSTKY_LB        = _paths.data("kostky_leaderboard.json")
    _paths.KOSTKY_MAGIC     = _paths.data("kostky_magic_dice.json")
    _paths.GUESS_SCORES     = _paths.data("guess_scores.json")
    _paths.LIAR_SCORES       = _paths.data("liar_scores.json")
    _paths.LIAR_SLOTS_SCORES = _paths.data("liar_slots_scores.json")
    _paths.LABYRINTH_SCORES  = _paths.data("labyrinth_scores.json")
    _paths.NEWS             = _paths.data("news.json")
    _paths.STORY_LIB        = _paths.data("story_library.json")
    _paths.STORY_SAVE       = _paths.data("story_save.json")
    _paths.CARDS_DATA       = _paths.data("cards_data.json")
    _paths.CARDS_INVENTORY  = _paths.data("cards_inventory.json")

os.makedirs(_paths.DATA_DIR, exist_ok=True)

class ArionBot(commands.Bot):
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
        print("--- 🐾 Načítám Cogs ---")

        for folder, pkg in [('src/core', 'src.core'), ('src/logic', 'src.logic')]:
            if not os.path.isdir(folder):
                continue
            for filename in os.listdir(folder):
                if filename.endswith('.py') and not filename.startswith('_'):
                    try:
                        await self.load_extension(f'{pkg}.{filename[:-3]}')
                        print(f'   ✅ {filename} načten.')
                    except Exception:
                        logging.exception(f'[main] {filename} selhal')
                        print(f'   ❌ {filename} selhal — viz log výše.')

        print("🔄 Synchronizuji slash commandy...")
        synced = await self.tree.sync()
        print(f"✅ Synced {len(synced)} commandů.")

    async def on_ready(self):
        print(f'🚀 Arion je online jako {self.user}')

# ====== RUN ======
if __name__ == "__main__":
    bot = ArionBot()
    bot.run(TOKEN)