import discord
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN_CARDS")

if not TOKEN:
    print("❌ DISCORD_TOKEN_CARDS nebyl nalezen v prostředí!")
    exit(1)

# ====== LOGGING ======
from src.utils.logger import configure_logging
configure_logging("ArionCARDS")
logger = logging.getLogger("ArionCARDS")

# ====== CONFIG Z ENV PROMĚNNÝCH ======
config = {
    "prefix":           os.getenv("PREFIX", "!"),
    "wiki_url":         os.getenv("WIKI_URL", "https://tvowiki.cz/aurionis"),
    "embed_color":      os.getenv("CARDS_EMBED_COLOR", "9B59B6"),
    "campfire_channel": os.getenv("CAMPFIRE_CHANNEL", "campfire"),
}

# ====== DATA ADRESÁŘ ======
from src.utils import paths as _paths
os.makedirs(_paths.DATA_DIR, exist_ok=True)
_paths.sync_default_data_files()

# JSON → SQLite: při prvním startu naimportuje existující data, pak už jen
# doplní nové defaultní klíče. Původní JSONy zůstávají jako záloha.
from src.database.migrate import run_migration as _run_migration
_run_migration()

_paths.bootstrap_items()

from src.utils.admin_gate import drop_admin_commands

CARDS_COGS = [
    "src.core.cards.cards",
    "src.core.cards.summon",
]

class ArionCARDS(commands.Bot):
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
        print("--- 🎮 Načítám ArionCARDS Cogs ---")

        # ── Migrace na multi-character (idempotentní; sdílený volume s ArionDND) ──
        #    Kdo z botů nastartuje dřív, ten překlopí gold uid→uid:1; druhý = no-op.
        #    Zavírá časové okno, kdyby ArionCARDS sáhl na gold před migrací z ArionDND.
        try:
            from src.database.migrate_chars import run_migration
            report = run_migration()
            logger.info(f"[characters] migrace: {report}")
            print(f"   🔁 migrace postav: {report}")
        except Exception as e:
            logger.exception(f"[characters] migrace selhala: {e}")
            print(f"   ❌ migrace postav selhala — viz log výše.")

        for cog in CARDS_COGS:
            try:
                await self.load_extension(cog)
                logger.info(f'✅ {cog} načten.')
                print(f'   ✅ {cog} načten.')
            except Exception as e:
                logger.exception(f'❌ {cog} selhal: {e}')
                print(f'   ❌ {cog} selhal — viz log výše.')

        # Karetní admin příkazy ze sdílených cogů patří ArionDM.
        dropped = drop_admin_commands(self)
        logger.info(f"[admin_gate] odebráno {len(dropped)} admin příkazů (má je ArionDM).")

        print("🔄 Synchronizuji slash commandy...")
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commandů.")
            print(f"✅ Synced {len(synced)} commandů.")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            print(f"⚠️ Command sync failed: {e}")

    async def on_ready(self):
        logger.info(f'🎮 ArionCARDS je online jako {self.user}')
        print(f'🎮 ArionCARDS je online jako {self.user}')

# ====== RUN ======
if __name__ == "__main__":
    bot = ArionCARDS()
    bot.run(TOKEN)