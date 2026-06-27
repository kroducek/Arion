import discord
import os
import logging
from discord.ext import commands
from dotenv import load_dotenv

# ====== LOAD ENV ======
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN_DND")

if not TOKEN:
    print("❌ DISCORD_TOKEN_DND nebyl nalezen v prostředí!")
    exit(1)

# ====== LOGGING ======
from src.utils.logger import configure_logging
configure_logging("ArionDND")
logger = logging.getLogger("ArionDND")

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
    _paths.ROLL_STATS        = _paths.data("roll_stats.json")
    _paths.DND_COUNTER       = _paths.data("dnd_counter.json")
    _paths.TUTORIAL_MSG      = _paths.data("tutorial_msg.json")
    _paths.PERKS             = _paths.data("perks.json")
    _paths.PLAYER_PERKS      = _paths.data("player_perks.json")
    _paths.ACHIEVEMENTS      = _paths.data("achievements.json")
    _paths.ACHIEVEMENT_DATA  = _paths.data("achievement_data.json")

os.makedirs(_paths.DATA_DIR, exist_ok=True)
_paths.sync_default_data_files()
_paths.bootstrap_items()

DND_COGS = [
    # D&D core
    "src.core.dnd.aurionis",
    "src.core.dnd.party",
    "src.core.dnd.quests",
    "src.core.dnd.roll_stats",
    "src.core.dnd.takedown",
    "src.core.dnd.diary",
    "src.core.dnd.snajpycounter",
    "src.core.dnd.achievements",
    "src.core.dnd.perks",
    "src.core.dnd.blacksmith",
    "src.core.dnd.character",
    
    # D&D logika / postavy
    "src.logic.profile",
    "src.logic.profile_render",
    "src.logic.stats",
    "src.logic.combat",
    "src.logic.inventory",
    "src.logic.onboard",
    "src.logic.roll",
    "src.logic.rpmanage",
    "src.logic.memory",
    "src.logic.reputation",
    "src.logic.economy",
    "src.logic.spirits",
]

class ArionDND(commands.Bot):
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
        print("--- ⚔️ Načítám ArionDND Cogs ---")

        # ── Migrace na multi-character systém (idempotentní, jednorázová) ──
        #    Překlopí legacy data uid → uid:1. Bezpečné spouštět při každém startu.
        try:
            from src.database.migrate_chars import run_migration
            report = run_migration()
            logger.info(f"[characters] migrace: {report}")
            print(f"   🔁 migrace postav: {report}")
        except Exception as e:
            logger.exception(f"[characters] migrace selhala: {e}")
            print(f"   ❌ migrace postav selhala — viz log výše.")

        for cog in DND_COGS:
            try:
                await self.load_extension(cog)
                logger.info(f'✅ {cog} načten.')
                print(f'   ✅ {cog} načten.')
            except Exception as e:
                logger.exception(f'❌ {cog} selhal: {e}')
                print(f'   ❌ {cog} selhal — viz log výše.')

        from src.logic.onboard import TutorialWarningView
        self.add_view(TutorialWarningView())

        print("🔄 Synchronizuji slash commandy...")
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commandů.")
            print(f"✅ Synced {len(synced)} commandů.")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
            print(f"⚠️ Command sync failed: {e}")

    async def on_ready(self):
        logger.info(f'⚔️ ArionDND je online jako {self.user}')
        print(f'⚔️ ArionDND je online jako {self.user}')

# ====== RUN ======
if __name__ == "__main__":
    bot = ArionDND()
    bot.run(TOKEN)