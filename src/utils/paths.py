"""
Centrální definice cest k datovým souborům.
Všechny cogy importují cesty odsud — nikdy nepoužívají holé stringy jako "profiles.json".
"""
import os
import json
import shutil

# Kořen projektu (ArionBot/)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Složka s daty — přepíše se env var DATA_DIR (Railway volume: /data)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(ROOT, "src", "database", "data"))
DEFAULT_DATA_DIR = os.path.join(ROOT, "src", "database", "data")


def sync_default_data_files() -> None:
    """Zajistí, že v přepsaném DATA_DIR jsou defaultní JSON soubory a chybějící entry."""
    if os.path.abspath(DATA_DIR) == os.path.abspath(DEFAULT_DATA_DIR):
        return
    if not os.path.exists(DEFAULT_DATA_DIR):
        return
    os.makedirs(DATA_DIR, exist_ok=True)

    for filename in os.listdir(DEFAULT_DATA_DIR):
        src_path = os.path.join(DEFAULT_DATA_DIR, filename)
        dst_path = os.path.join(DATA_DIR, filename)

        if not os.path.isfile(src_path):
            continue

        if not os.path.exists(dst_path):
            shutil.copy2(src_path, dst_path)
            continue

        if not filename.endswith(".json"):
            continue

        try:
            with open(src_path, "r", encoding="utf-8") as f:
                src_data = json.load(f)
            with open(dst_path, "r", encoding="utf-8") as f:
                dst_data = json.load(f)
        except Exception:
            continue

        if not isinstance(src_data, dict) or not isinstance(dst_data, dict):
            continue

        changed = False
        for key, value in src_data.items():
            if key not in dst_data:
                dst_data[key] = value
                changed = True

        if changed:
            with open(dst_path, "w", encoding="utf-8") as f:
                json.dump(dst_data, f, ensure_ascii=False, indent=2)


# ── Definice systémových položek (musí být dostupné v každém prostředí) ────
DEFAULT_ITEMS = {
    "brasna": {
        "name": "Brašna",
        "category": "příslušenství",
        "slot": "belt",
        "stackable": False,
        "consumable": False,
        "desc": "Malá brašna na pás — zvyšuje nositele na inventáře"
    },
    "kozena_tunika": {
        "name": "Kožená tunika",
        "category": "armor",
        "slot": "chest",
        "stackable": False,
        "consumable": False,
        "def": 5,
        "desc": "Jednoduchá kožená zbroj"
    },
    "ocelovy_kyrys": {
        "name": "Ocelový kýrys",
        "category": "armor",
        "slot": "chest",
        "stackable": False,
        "consumable": False,
        "def": 8,
        "requires": {"STR": 3},
        "desc": "Robustní ocelová zbroj"
    },
    "magicka_roba": {
        "name": "Magická roba",
        "category": "armor",
        "slot": "chest",
        "stackable": False,
        "consumable": False,
        "def": 3,
        "mana": 5,
        "desc": "Roba plná kouzelné energie"
    },
    "bojova_hul": {
        "name": "Bojová hůl",
        "category": "zbraně",
        "slot": "hand_l",
        "hand_type": "two",
        "stackable": False,
        "consumable": False,
        "atk": 14,
        "desc": "Obouruční hůl bojového mnicha"
    },
    "magicka_hulka": {
        "name": "Magická hůlka",
        "category": "zbraně",
        "slot": "hand_l",
        "stackable": False,
        "consumable": False,
        "atk": 5,
        "mana": 3,
        "desc": "Hůlka pro seslávání kouzel"
    },
    "sipky_10x": {
        "name": "Šípky (10x)",
        "category": "náboje",
        "slot": None,
        "stackable": True,
        "consumable": True,
        "desc": "Balíček 10 obyčejných šípů"
    },
    "ogniva_runa": {
        "name": "Ohnivá runa",
        "category": "zbraně",
        "slot": "hand_l",
        "stackable": False,
        "consumable": False,
        "atk": 18,
        "desc": "Runa ohnivé magie — 🔥"
    },
    "ledova_runa": {
        "name": "Ledová runa",
        "category": "zbraně",
        "slot": "hand_l",
        "stackable": False,
        "consumable": False,
        "atk": 18,
        "desc": "Runa ledové magie — ❄️"
    },
    "uzdravovaci_runa": {
        "name": "Uzdravovací runa",
        "category": "zbraně",
        "slot": "hand_l",
        "stackable": False,
        "consumable": False,
        "atk": 0,
        "desc": "Runa uzdravovací magie — 💚"
    },
    "lektvar_zivota": {
        "name": "Léktvár života",
        "category": "consumable",
        "slot": None,
        "stackable": True,
        "consumable": True,
        "desc": "Obnoví 10 HP"
    },
    "lektvar_many": {
        "name": "Léktvár many",
        "category": "consumable",
        "slot": None,
        "stackable": True,
        "consumable": True,
        "desc": "Obnoví 10 many"
    },
}


def bootstrap_items() -> None:
    """Zajistí, že items.json obsahuje všechny systémové položky potřebné pro loadouty."""
    items_file = data("items.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    
    try:
        if os.path.exists(items_file):
            with open(items_file, "r", encoding="utf-8") as f:
                items = json.load(f)
        else:
            items = {}
    except Exception:
        items = {}
    
    changed = False
    for item_id, item_def in DEFAULT_ITEMS.items():
        if item_id not in items:
            items[item_id] = item_def
            changed = True
    
    if changed or not os.path.exists(items_file):
        try:
            with open(items_file, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


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
DUEL_SCORES        = data("duel_scores.json")

# ── Příběhy / novinky ────────────────────────────────────────
NEWS        = data("news.json")
STORY_LIB   = data("story_library.json")

# ── Sběratelské karty ────────────────────────────────────────
CARDS_DIR   = os.path.join(ROOT, "src", "assets", "cards")
FRAMES_DIR  = os.path.join(ROOT, "src", "assets", "frames")
CARDS_DATA  = data("cards_data.json")
CARDS_INVENTORY = data("cards_inventory.json")
CARDS_FRAMES = data("cards_frames.json")
FRAMES_INVENTORY = data("frames_inventory.json")
STORY_SAVE  = data("story_save.json")

# ── Assets ───────────────────────────────────────────────────
ASSETS_DIR  = os.path.join(ROOT, "src", "assets")
TAROT_DIR   = os.path.join(ASSETS_DIR, "tarot")
DICE_DIR    = os.path.join(ASSETS_DIR, "dice")

# ── Achievementy ─────────────────────────────────────────────
ACHIEVEMENTS      = data("achievements.json")
ACHIEVEMENT_DATA  = data("achievement_data.json")

# ── Perky ─────────────────────────────────────────────────────
PERKS        = data("perks.json")
PLAYER_PERKS = data("player_perks.json")

# ── Bot state ────────────────────────────────────────────────
TUTORIAL_MSG = data("tutorial_msg.json")

# ── Tierlistry ───────────────────────────────────────────────
TIERLISTS = data("tierlists.json")