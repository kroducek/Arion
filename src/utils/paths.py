"""
Centrální definice cest k datovým souborům.
Všechny cogy importují cesty odsud — nikdy nepoužívají holé stringy jako "profiles.json".
"""
import os

# Kořen projektu (ArionBot/)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Složka s daty
DATA_DIR = os.path.join(ROOT, "src", "database", "data")


def data(filename: str) -> str:
    """Vrátí absolutní cestu k souboru ve složce database/data/."""
    return os.path.join(DATA_DIR, filename)


# ── Hráčská data ──────────────────────────────────────────────
PROFILES   = data("profiles.json")
ECONOMY    = data("economy.json")
DIARIES    = data("diaries.json")
ITEMS      = data("items.json")

# ── Herní stav ────────────────────────────────────────────────
RP_ROOMS      = data("rp_rooms.json")
QUESTS        = data("quests.json")
QUEST_LOG     = data("quest_log.json")
SHOP          = data("shop.json")
SHOPS         = data("shops.json")
PARTIES       = data("parties.json")
TOURNAMENT    = data("tournament.json")
COMBAT_STATE  = data("combat_state.json")

REPUTATION  = data("reputation.json")

# ── Statistiky ────────────────────────────────────────────────
TAKEDOWNS      = data("takedowns.json")
ROLL_STATS     = data("roll_stats.json")
DND_COUNTER    = data("dnd_counter.json")
KOSTKY_LB      = data("kostky_leaderboard.json")
KOSTKY_MAGIC   = data("kostky_magic_dice.json")
GUESS_SCORES       = data("guess_scores.json")
LIAR_SCORES        = data("liar_scores.json")
LIAR_SLOTS_SCORES  = data("liar_slots_scores.json")
LABYRINTH_SCORES   = data("labyrinth_scores.json")

# ── Příběhy / novinky ────────────────────────────────────────
NEWS        = data("news.json")
STORY_LIB   = data("story_library.json")

# ── Sběratelské karty ────────────────────────────────────────
CARDS_DIR   = os.path.join(ROOT, "src", "assets", "cards")
CARDS_DATA  = data("cards_data.json")
CARDS_INVENTORY = data("cards_inventory.json")
STORY_SAVE  = data("story_save.json")

# ── Assets ───────────────────────────────────────────────────
ASSETS_DIR  = os.path.join(ROOT, "src", "assets")
TAROT_DIR   = os.path.join(ASSETS_DIR, "tarot")
DICE_DIR    = os.path.join(ASSETS_DIR, "dice")
