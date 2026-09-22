"""ArionDM — vypravěčský bot s admin příkazy.

Běží jako třetí proces vedle ArionDND a ArionBOT a sdílí s nimi stejný
`DATA_DIR` (SQLite ve WAL módu), takže vidí úplně stejná data. Rozdíl je jen
v tom, že admin příkazy jsou registrované pod touhle aplikací — na serverech,
kde ArionDM není, nejdou vyvolat.

Migrace dat (`src.database.migrate`, `src.database.migrate_chars`) se tady
záměrně nespouští — o ty se starají ArionDND a ArionBOT.
"""
import discord
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN_DM")

if not TOKEN:
    print("❌ DISCORD_TOKEN_DM nebyl nalezen v prostředí!")
    exit(1)

# ====== LOGGING ======
from src.utils.logger import configure_logging
configure_logging("ArionDM")
logger = logging.getLogger("ArionDM")

# ====== CONFIG Z ENV PROMĚNNÝCH ======
config = {
    "prefix":           os.getenv("PREFIX", "!"),
    "wiki_url":         os.getenv("WIKI_URL", "https://tvowiki.cz/aurionis"),
    "embed_color":      os.getenv("DM_EMBED_COLOR", "C0392B"),
    "campfire_channel": os.getenv("CAMPFIRE_CHANNEL", "campfire"),
}

# ====== DATA ADRESÁŘ ======
# `paths` si `DATA_DIR` čte z prostředí sám při importu, takže tady stačí
# ověřit, že složka existuje — data jsou stejná jako u ArionDND a ArionBOT.
from src.utils import paths as _paths

os.makedirs(_paths.DATA_DIR, exist_ok=True)

from src.utils.admin_gate import SHARED_COGS, drop_listeners, keep_only_admin

# Cogy, které patří výhradně ArionDM.
DM_COGS = [
    "src.core.dm.board",
    "src.core.dm.lore",
    "src.core.dm.backup",
    "src.core.dm.diary_admin",
    "src.core.dm.news_admin",
    "src.core.dm.aurionis_admin",
]

# `SHARED_COGS` (admin_gate) načítá i ArionDND — tady z nich po startu zůstanou
# jen příkazy označené `@admin_only()` / `@mark_admin`.


class ArionDM(commands.Bot):
    def __init__(self):
        self.config = config

        try:
            self.color = int(self.config['embed_color'], 16)
        except Exception:
            print("⚠️ Neplatná barva v configu, používám fallback.")
            self.color = 0xC0392B

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
        print("--- 🎲 Načítám ArionDM Cogs ---")

        for cog in DM_COGS + SHARED_COGS:
            try:
                await self.load_extension(cog)
                logger.info(f'✅ {cog} načten.')
                print(f'   ✅ {cog} načten.')
            except Exception as e:
                logger.exception(f'❌ {cog} selhal: {e}')
                print(f'   ❌ {cog} selhal — viz log výše.')

        # Ze sdílených cogů si nech jen admin příkazy a vypni jejich listenery,
        # ať na stejnou událost nereagují dva boti naráz.
        dropped = keep_only_admin(self)
        drop_listeners(self)
        logger.info(f"[admin_gate] odebráno {len(dropped)} hráčských příkazů.")

        print("🔄 Synchronizuji slash commandy...")
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commandů.")
            print(f"✅ Synced {len(synced)} commandů.")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            print(f"⚠️ Command sync failed: {e}")

    async def on_ready(self):
        logger.info(f'🎲 ArionDM je online jako {self.user}')
        print(f'🎲 ArionDM je online jako {self.user}')


# ====== RUN ======
if __name__ == "__main__":
    bot = ArionDM()
    bot.run(TOKEN)
