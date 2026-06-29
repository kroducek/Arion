import re
import discord
import logging
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.utils.paths import PROFILES as PROFILES_FILE, ITEMS as ITEMS_FILE
from src.utils.json_utils import load_json, save_json
from src.database.characters import pkey

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

EQUIPMENT_SLOTS = [
    "hand_l", "hand_r",
    "helmet", "armor", "gloves", "kalhoty", "boots", "cloak", "belt",
    "ring_1", "ring_2",
    "amulet_1",
]

SLOT_LABELS = {
    "hand_l":   "Zbraň L",
    "hand_r":   "Zbraň P",
    "helmet":   "Hlava",
    "armor":    "Zbroj",
    "gloves":   "Rukavice",
    "kalhoty":  "Kalhoty",
    "boots":    "Boty",
    "cloak":    "Plášť",
    "belt":     "Opasek",
    "ring_1":   "Prsten 1",
    "ring_2":   "Prsten 2",
    "amulet_1": "Amulet",
}

SLOT_EMOJIS = {
    "hand_l":   "🗡️",
    "hand_r":   "🗡️",
    "helmet":   "🪖",
    "armor":    "🛡️",
    "gloves":   "🧤",
    "kalhoty":  "👖",
    "boots":    "👢",
    "cloak":    "🧥",
    "belt":     "🪢",
    "ring_1":   "💍",
    "ring_2":   "💍",
    "amulet_1": "📿",
}

CATEGORIES = [
    "dýky", "jednoruční", "obouruční", "luky_kuše",
    "střelné", "náboje", "hůlky_hole",
    "runy_krystaly", "svitky", "speciální",
    "brnění", "amulety", "prsteny", "pásky",
    "jídlo", "lektvary", "unikátní", "ostatní",
]

# Široké skupiny pro automatické řazení v inventáři/úložištích.
# (emoji, nadpis, [jemné kategorie patřící do skupiny]) — pořadí = pořadí zobrazení.
CATEGORY_GROUPS = [
    ("⚔️", "Zbraně",     ["dýky", "jednoruční", "obouruční", "luky_kuše", "střelné", "hůlky_hole"]),
    ("🎯", "Munice",      ["náboje"]),
    ("🛡️", "Zbroje",     ["brnění", "pásky"]),
    ("💍", "Doplňky",     ["amulety", "prsteny"]),
    ("📜", "Magie",       ["runy_krystaly", "svitky"]),
    ("🍖", "Spotřební",   ["jídlo", "lektvary"]),
    ("✨", "Speciální",   ["speciální", "unikátní"]),
    ("📦", "Ostatní",     ["ostatní"]),
]
# Rychlá mapa: jemná kategorie → index skupiny (pro řazení).
_CAT_TO_GROUP = {cat: gi for gi, (_e, _l, cats) in enumerate(CATEGORY_GROUPS) for cat in cats}
_OSTATNI_GROUP = len(CATEGORY_GROUPS) - 1  # fallback skupina pro neznámé/volné itemy

# Sloty které zabírá full_set item
FULL_SET_SLOTS = ["helmet", "armor", "boots", "cloak", "belt"]

# Mapování require klíčů Vlivu na pole profilu
VLIV_REQUIRES = {
    "TEMNOTA":   "vliv_temnota",
    "SVETLO":    "vliv_svetlo",
    "ROVNOVAHA": "vliv_rovnovaha",
}

# Mapování skill require klíčů (ASCII) → klíče v profile["skills"]
SKILL_REQUIRES = {
    "SILA":      "Síla",
    "OBRATNOST": "Obratnost",
    "MAGIE":     "Magie",
    "VYDRZ":     "Výdrž",
}


def _req_have(profile: dict, key: str) -> int:
    """Aktuální hodnota hráče pro require/bonus klíč (atribut / Vliv / skill)."""
    if not profile:
        return 0
    if key in VLIV_REQUIRES:
        return profile.get(VLIV_REQUIRES[key], 0)
    if key in SKILL_REQUIRES:
        return profile.get("skills", {}).get(SKILL_REQUIRES[key], 0)
    return profile.get("stats", {}).get(key, 0)

# Kategorie dostupné v /use
USE_CATEGORIES = ["jídlo", "lektvary", "svitky", "ostatní"]

DM_ROLE_NAME = "DM"
EMBED_COLOR  = 0x2b2d31
PAGE_SIZE    = 15
BOH_ITEM_ID  = "bag_of_holding"
BOH_COLOR    = 0x6B4226   # hnědá — barva pytle
TOULEC_ITEM_ID = "toulec"   # storage item na munici (DM ho vytvoří/dá hráči)

# ── Storage systém ────────────────────────────────────────────────────────────
BASE_INV_SLOTS = 10                                  # základní sloty (+ STR)
WEIGHTLESS_CATEGORIES = ["jídlo", "lektvary", "náboje"]  # nezabírají sloty

# Vizuál pro storage embed dle item kategorie / typu
STORAGE_VISUALS = {
    "inventory":     {"emoji": "🎒", "label": "Inventář",        "color": EMBED_COLOR},
    "bag_of_holding":{"emoji": "👜", "label": "Bag of Holding",  "color": BOH_COLOR},
    "toulec":        {"emoji": "🏹", "label": "Toulec",          "color": 0x7a5230},
    "_default":      {"emoji": "📦", "label": "Úložiště",        "color": 0x5a6b3b},
}

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load_profiles() -> dict:
    return load_json(PROFILES_FILE, default={})

def _save_profiles(data: dict) -> None:
    save_json(PROFILES_FILE, data)

def _load_items() -> dict:
    return load_json(ITEMS_FILE, default={})

def _save_items(data: dict) -> None:
    save_json(ITEMS_FILE, data)

def _pk(profiles: dict, uid) -> str:
    """Klíč profilu: pkey (uid:slot) když existuje, jinak holé uid (nemigrovaní)."""
    k = pkey(uid)
    return k if k in profiles else str(uid)


def _get_profile(uid: int) -> dict | None:
    profiles = _load_profiles()
    return profiles.get(_pk(profiles, uid))

def _default_equipment() -> dict:
    return {slot: None for slot in EQUIPMENT_SLOTS}

def _link_inventory(profile: dict) -> list:
    """Sjednotí profile['inventory'] a storages['inventory'] na JEDEN živý list.

    Po uložení/načtení z JSONu se tato dvě pole rozpojí (JSON neumí sdílené
    reference). Část příkazů píše do profile['inventory'], zobrazení čte
    storages['inventory'] → přidané itemy se nezobrazovaly. profile['inventory']
    je vždy nejčerstvější (žádný příkaz nepíše do storages['inventory'], aniž by
    ho přes _ensure_storage zároveň přelinkoval), takže ho bereme za zdroj pravdy.
    """
    profile.setdefault("storages", {})
    legacy = profile.get("inventory")
    if not isinstance(legacy, list):
        legacy = profile["storages"].get("inventory")
        if not isinstance(legacy, list):
            legacy = []
    profile["storages"]["inventory"] = legacy   # kanonický zdroj pro zobrazení
    profile["inventory"] = legacy               # živá reference pro zpětnou kompatibilitu
    return legacy


def _ensure_inv_fields(profile: dict) -> dict:
    """Zajistí že profil má všechna potřebná pole inventáře."""
    _link_inventory(profile)
    profile.setdefault("notes", [])
    profile.setdefault("equipment", {})
    profile.setdefault("ring_slots", 2)
    profile["amulet_slots"] = 1   # jediný amulet slot
    # Zajisti že všechny sloty existují (i v případě starého/částečného profilu)
    for s in ["hand_l", "hand_r", "helmet", "armor",
              "gloves", "kalhoty", "boots", "cloak", "belt"]:
        profile["equipment"].setdefault(s, None)
    for i in range(1, profile["ring_slots"] + 1):
        profile["equipment"].setdefault(f"ring_{i}", None)
    profile["equipment"].setdefault("amulet_1", None)
    # Migrace: zrušený ammo slot — munice teď žije v Toulci, ukazatel jen zahoď
    profile["equipment"].pop("ammo", None)
    # Migrace: zrušené sloty wrists/headwear — případné itemy vrať do inventáře
    for dead in ("wrists", "headwear"):
        gone = profile["equipment"].pop(dead, None)
        if gone:
            _add_to_inventory(profile["inventory"], gone, 1)
    # Migrace: zrušené druhé+ amulet sloty — případné itemy vrať do inventáře
    for key in [k for k in list(profile["equipment"])
                if k.startswith("amulet_") and k != "amulet_1"]:
        extra = profile["equipment"].pop(key, None)
        if extra:
            _add_to_inventory(profile["inventory"], extra, 1)
    # Vitální pole — nutná pro /use efekty
    profile.setdefault("hp_max",     50)
    profile.setdefault("hp_cur",     profile.get("hp_max", 50))
    profile.setdefault("hunger_max", 10)
    profile.setdefault("hunger_cur", profile.get("hunger_max", 10))
    profile.setdefault("mana_max",   5)
    profile.setdefault("mana_cur",   0)
    profile.setdefault("fury_max",   0)
    profile.setdefault("fury_cur",   0)
    return profile

def _ensure_boh_field(profile: dict) -> None:
    """Zajistí že profil má BoH storage (zpětná kompatibilita)."""
    _migrate_storages(profile)
    profile.setdefault("storages", {}).setdefault("bag_of_holding", [])
    profile["bag_of_holding"] = profile["storages"]["bag_of_holding"]
    profile.setdefault("storage_notes", {}).setdefault("bag_of_holding", [])
    profile["boh_notes"] = profile["storage_notes"]["bag_of_holding"]


def _inv_notes(profile: dict) -> list:
    """Jediný zdroj pravdy pro inventářové poznámky.

    Zobrazení (`/inv`) čte ze `storage_notes['inventory']`, ale staré zápisy
    šly do `profile['notes']`. Po JSON round-tripu se z toho stala dvě nezávislá
    pole → přidané poznámky se nezobrazovaly. Tahle funkce obě pole sjednotí na
    jeden živý list a vrátí ho (stejný princip jako `_ensure_boh_field` u BoH).
    """
    sn     = profile.setdefault("storage_notes", {})
    legacy = profile.get("notes")
    legacy = legacy if isinstance(legacy, list) else []
    canon  = sn.get("inventory")

    if not isinstance(canon, list):
        # první inicializace — převezmi staré pole
        canon = list(legacy)
    elif legacy and legacy != canon:
        # historický bug: zápisy šly do profile['notes'], čtení z canon.
        # Pravdivá data jsou v legacy → sjednoť na ně.
        canon = list(legacy)

    sn["inventory"] = canon
    profile["notes"] = canon          # živá reference pro zpětnou kompatibilitu
    return canon


def _has_boh(profile: dict) -> bool:
    """True pokud hráč vlastní Bag of Holding (v inventáři nebo equipnutý)."""
    return _owns_storage_item(profile, BOH_ITEM_ID)


# ══════════════════════════════════════════════════════════════════════════════
# STORAGE SYSTÉM
# ══════════════════════════════════════════════════════════════════════════════

def _migrate_storages(profile: dict) -> None:
    """Převede starý inventory/bag_of_holding do profile['storages']."""
    profile.setdefault("storages", {})
    profile.setdefault("storage_notes", {})

    storages = profile["storages"]
    # Inventář: jeden živý list (profile['inventory'] == storages['inventory'])
    _link_inventory(profile)
    if "bag_of_holding" not in storages and profile.get("bag_of_holding"):
        storages["bag_of_holding"] = profile.get("bag_of_holding", [])

    # Notes migrace
    notes = profile["storage_notes"]
    notes.setdefault("inventory", profile.get("notes", []))
    if profile.get("boh_notes"):
        notes.setdefault("bag_of_holding", profile.get("boh_notes", []))

    # Drž zpětnou kompatibilitu — bag_of_holding je živá reference
    if "bag_of_holding" in storages:
        profile["bag_of_holding"] = storages["bag_of_holding"]


def _is_storage_item(item_id: str, items_db: dict) -> bool:
    """True pokud je item v DB označen jako storage (má pole 'storage')."""
    return isinstance(items_db.get(item_id, {}).get("storage"), dict)


def _storage_capacity(storage_key: str, profile: dict, items_db: dict) -> int | None:
    """Vrátí kapacitu storage. None = unlimited."""
    if storage_key == "inventory":
        return BASE_INV_SLOTS + profile.get("stats", {}).get("STR", 0)
    cap = items_db.get(storage_key, {}).get("storage", {}).get("capacity")
    return cap  # None = unlimited (BoH)


def _entry_slot_cost(entry: dict, items_db: dict) -> int:
    """Kolik slotů zabírá daný entry (qty se počítá; lehké kategorie = 0)."""
    if entry.get("type") != "registered":
        return 0   # free/custom položky slot nezabírají
    db_item = items_db.get(entry["id"], {})
    if db_item.get("category") in WEIGHTLESS_CATEGORIES:
        return 0
    return entry.get("qty", 1)


def _count_slots(storage: list, items_db: dict) -> int:
    """Spočítá obsazené sloty v daném storage."""
    return sum(_entry_slot_cost(e, items_db) for e in storage)


def _owns_storage_item(profile: dict, item_id: str) -> bool:
    """True pokud hráč vlastní daný item (v jakémkoliv storage nebo equipnutý)."""
    for stor in profile.get("storages", {}).values():
        for entry in stor:
            if entry.get("type") == "registered" and entry.get("id") == item_id:
                return True
    return any(v == item_id for v in profile.get("equipment", {}).values())


def _available_storages(profile: dict, items_db: dict) -> list[str]:
    """Vrátí seznam storage klíčů které hráč může používat (inventory + vlastněné storage itemy, vč. Toulce)."""
    keys = ["inventory"]
    seen = {"inventory"}
    # Projdi všechny itemy které hráč má a najdi storage typy
    for stor in profile.get("storages", {}).values():
        for entry in stor:
            if entry.get("type") == "registered":
                iid = entry["id"]
                if iid not in seen and _is_storage_item(iid, items_db):
                    keys.append(iid)
                    seen.add(iid)
    # Equipnuté storage itemy (např. BoH na pásku)
    for v in profile.get("equipment", {}).values():
        if v and v not in seen and _is_storage_item(v, items_db):
            keys.append(v)
            seen.add(v)
    return keys


def _ensure_storage(profile: dict, storage_key: str) -> list:
    """Vrátí (a vytvoří) storage list pro daný klíč."""
    profile.setdefault("storages", {})
    profile["storages"].setdefault(storage_key, [])
    if storage_key == "inventory":
        profile["inventory"] = profile["storages"]["inventory"]
    return profile["storages"][storage_key]


def _drop_storage(profile: dict, item_id: str) -> None:
    """Smaže storage instanci i s obsahem (když hráč ztratí batoh/brašnu)."""
    profile.get("storages", {}).pop(item_id, None)
    profile.get("storage_notes", {}).pop(item_id, None)


def _storage_visual(storage_key: str, items_db: dict) -> dict:
    """Vrátí emoji/label/color pro storage embed."""
    if storage_key in STORAGE_VISUALS:
        return STORAGE_VISUALS[storage_key]
    db_item = items_db.get(storage_key, {})
    return {
        "emoji": db_item.get("storage", {}).get("emoji", "📦"),
        "label": db_item.get("name", storage_key),
        "color": STORAGE_VISUALS["_default"]["color"],
    }


def _sort_ammo_to_toulec(profile: dict, items_db: dict) -> bool:
    """Přesune veškerou munici (kategorie 'náboje') z inventáře do Toulce.

    Toulec je storage item (id 'toulec'). Auto-sort proběhne JEN když ho hráč
    vlastní — jinak munice zůstane v inventáři. Vrací True pokud se něco přesunulo.
    """
    if not _owns_storage_item(profile, TOULEC_ITEM_ID):
        return False
    inv = profile.setdefault("storages", {}).setdefault("inventory", [])
    profile["inventory"] = inv  # drž živou referenci
    moved = False
    remaining = []
    for entry in inv:
        is_ammo = (entry.get("type") == "registered"
                   and items_db.get(entry.get("id"), {}).get("category") == "náboje")
        if is_ammo:
            toulec = profile["storages"].setdefault(TOULEC_ITEM_ID, [])
            _add_to_inventory(toulec, entry["id"], entry.get("qty", 1))
            moved = True
        else:
            remaining.append(entry)
    if moved:
        inv[:] = remaining  # uprav in-place, ať zůstane živá reference
    return moved


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_requires(raw: str) -> dict[str, int]:
    """Parsuje string 'STR:2 INS:1 CHA:3' na dict {stat: hodnota}."""
    result = {}
    for part in raw.replace(",", " ").split():
        if ":" in part:
            k, _, v = part.partition(":")
            try:
                result[k.upper()] = int(v)
            except ValueError:
                pass
    return result


# Klíče pro requires / stat_bonus (staty + Vliv) — pro autocomplete.
REQUIRE_KEYS = ["STR", "DEX", "CON", "INT", "WIS", "CHA", "INS",
                "SILA", "OBRATNOST", "MAGIE", "VYDRZ",
                "SVETLO", "TEMNOTA", "ROVNOVAHA"]

_ATK_TOKEN_RE = re.compile(r"^\d+(d\d+)?$", re.IGNORECASE)

def _valid_attack(expr: str) -> bool:
    """True pro číslo, kostky nebo jejich součet: 12, 1d8, 4d6, 2d6+1d4."""
    expr = expr.replace(" ", "")
    if not expr:
        return False
    return all(_ATK_TOKEN_RE.match(tok) for tok in expr.split("+"))


async def _ac_requires(interaction: discord.Interaction, current: str):
    """Autocomplete pro requires/stat_bonus — postupně nabízí klíče (staty + Vliv)."""
    parts = current.split()
    # Pokud poslední token je rozepsaný klíč (bez ':'), doplň ho; jinak nabídni další.
    if parts and ":" not in parts[-1]:
        prefix = " ".join(parts[:-1])
        frag   = parts[-1].upper()
        base   = (prefix + " ") if prefix else ""
        keys   = [k for k in REQUIRE_KEYS if k.startswith(frag)] or REQUIRE_KEYS
    else:
        base = (current + " ") if current.strip() else ""
        keys = REQUIRE_KEYS
    out = []
    for k in keys:
        val = f"{base}{k}:"
        out.append(app_commands.Choice(name=val[:100], value=val[:100]))
    return out[:25]

def _find_inv_entry(inventory: list, item_key: str) -> dict | None:
    """Najde položku v inventáři dle ID (registrovaný) nebo jména (volný — legacy)."""
    key = item_key.lower()
    for entry in inventory:
        if entry["type"] == "registered" and entry["id"].lower() == key:
            return entry
        if entry["type"] == "free" and entry.get("name", "").lower() == key:
            return entry
    return None

def _add_to_inventory(inventory: list, item_id: str, qty: int) -> None:
    """Přidá nebo navýší registrovaný item v inventáři."""
    entry = _find_inv_entry(inventory, item_id)
    if entry and entry["type"] == "registered":
        entry["qty"] = entry.get("qty", 1) + qty
    else:
        inventory.append({"type": "registered", "id": item_id, "qty": qty})

def _remove_from_inventory(inventory: list, item_key: str, qty: int) -> bool:
    """Odebere qty kusů. Vrátí True pokud se povedlo."""
    entry = _find_inv_entry(inventory, item_key)
    if not entry or entry.get("qty", 1) < qty:
        return False
    entry["qty"] -= qty
    if entry["qty"] <= 0:
        inventory.remove(entry)
    return True

def _item_display_name(entry: dict, items_db: dict) -> str:
    if entry["type"] == "registered":
        db_item = items_db.get(entry["id"])
        return db_item["name"] if db_item else f"[{entry['id']}]"
    return entry.get("name", "?")

def _parse_modifiers(db_item: dict) -> str:
    """Vrátí inline modifikátory z DMG řádku jako emoji string: '💧4', '🔥5', '🧪3' atd."""
    desc = db_item.get("desc", "")
    dmg_line = ""
    for line in desc.split("\n"):
        if line.upper().startswith("DMG:"):
            dmg_line = line
            break
    if not dmg_line:
        return ""
    parts = []
    m = re.search(r"krv[aá]cení\s*\(1d(\d+)", dmg_line, re.IGNORECASE)
    if m:
        parts.append(f"🩸{m.group(1)}")
    elif re.search(r"krv[aá]cení", dmg_line, re.IGNORECASE):
        parts.append("🩸")
    m = re.search(r"1d(\d+)\s*(?:burn|fire)", dmg_line, re.IGNORECASE)
    if m:
        parts.append(f"🔥{m.group(1)}")
    m = re.search(r"otráv[eě]n[íi]\s*\(1d(\d+)", dmg_line, re.IGNORECASE)
    if m:
        parts.append(f"🧪{m.group(1)}")
    return " ".join(parts)

def _active_ring_slots(profile: dict) -> list[str]:
    return [f"ring_{i+1}" for i in range(profile.get("ring_slots", 2))]

def _active_amulet_slots(profile: dict) -> list[str]:
    return ["amulet_1"]   # jeden pevný amulet slot

def _active_slots(profile: dict) -> list[str]:
    base = ["hand_l", "hand_r", "helmet", "armor",
            "gloves", "kalhoty", "boots", "cloak", "belt"]
    return base + _active_ring_slots(profile) + _active_amulet_slots(profile)


async def _check_full_equip(member, channel, profile: dict) -> None:
    """Bezpečně zkontroluje achievement 'Naplno vyzbrojený!' (plná výbava).

    Chybu LOGUJE (ne tiše spolkne), aby šlo diagnostikovat — a nikdy neshodí
    příkaz, který ji volá.
    """
    try:
        from src.core.dnd.achievements import check_full_equip_achievement
        await check_full_equip_achievement(
            member, channel, profile["equipment"], _active_slots(profile))
    except Exception:
        logger.exception("check_full_equip_achievement selhal (achievement 'Naplno vyzbrojený!')")

# ══════════════════════════════════════════════════════════════════════════════
# EQUIPMENT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _format_bonus(bonus: dict) -> str:
    """Vrátí lidsky čitelný popis equip_bonus pro zprávu. Prázdný string pokud žádný."""
    if not bonus:
        return ""
    parts = []
    for key, val in bonus.items():
        sign = "+" if val >= 0 else ""
        if key.startswith("vliv_"):
            label = key.replace("vliv_", "").capitalize()
            parts.append(f"{sign}{val} {label}")
        elif key == "mana_max":
            parts.append(f"{sign}{val} 🔷 max mana")
        elif key == "hp_max":
            parts.append(f"{sign}{val} ❤️ max HP")
        elif key == "hunger_max":
            parts.append(f"{sign}{val} 🍖 max hlad")
        elif key in SKILL_REQUIRES:
            parts.append(f"{sign}{val} {SKILL_REQUIRES[key]}")
        else:
            parts.append(f"{sign}{val} {key}")
    return "  ·  ".join(parts)


def _recalc_fury_from_vliv(profile: dict) -> None:
    """Přepočítá fury_max podle celkového Vlivu (1 Vliv = 5 fury_max)."""
    total   = (profile.get("vliv_svetlo", 0)
               + profile.get("vliv_temnota", 0)
               + profile.get("vliv_rovnovaha", 0))
    new_max = total * 5
    old_max = profile.get("fury_max", 0)
    delta   = new_max - old_max
    profile["fury_max"] = new_max
    profile["fury_cur"] = max(0, min(new_max, profile.get("fury_cur", 0) + delta))


def _apply_equip_bonus(profile: dict, bonus: dict) -> None:
    """Aplikuje equip_bonus na profil (při equipu)."""
    if not bonus:
        return
    vliv_changed = False
    stats = profile.setdefault("stats", {})
    for key, val in bonus.items():
        if key.startswith("vliv_"):
            profile[key] = profile.get(key, 0) + val
            vliv_changed = True
        elif key in ("mana_max", "hp_max", "hunger_max"):
            profile[key] = profile.get(key, 0) + val
        elif key in SKILL_REQUIRES:
            sk = profile.setdefault("skills", {})
            sk[SKILL_REQUIRES[key]] = sk.get(SKILL_REQUIRES[key], 0) + val
        else:
            stats[key] = stats.get(key, 0) + val
    if vliv_changed:
        _recalc_fury_from_vliv(profile)


def _remove_equip_bonus(profile: dict, bonus: dict) -> None:
    """Odstraní equip_bonus z profilu (při unequipu)."""
    if not bonus:
        return
    vliv_changed = False
    stats = profile.setdefault("stats", {})
    for key, val in bonus.items():
        if key.startswith("vliv_"):
            profile[key] = max(0, profile.get(key, 0) - val)
            vliv_changed = True
        elif key in ("mana_max", "hp_max", "hunger_max"):
            profile[key] = max(0, profile.get(key, 0) - val)
        elif key in SKILL_REQUIRES:
            sk = profile.setdefault("skills", {})
            sk[SKILL_REQUIRES[key]] = max(0, sk.get(SKILL_REQUIRES[key], 0) - val)
        else:
            stats[key] = max(0, stats.get(key, 0) - val)
    if vliv_changed:
        _recalc_fury_from_vliv(profile)


def _equip_item(profile: dict, item_id: str, preferred_slot: str | None,
                items_db: dict, user_id: str | None = None) -> tuple[bool, str]:
    _ensure_inv_fields(profile)
    db_item = items_db.get(item_id)
    if not db_item:
        return False, f"Item `{item_id}` není v databázi."

    slot_target = db_item.get("slot")
    if not slot_target:
        return False, f"**{db_item['name']}** nelze equipnout."
    # Backwards-compat: "weapon" byl legacy slot value, normalizuj na "hand_l"
    if slot_target == "weapon":
        slot_target = "hand_l"

    inventory = profile["inventory"]
    equipment = profile["equipment"]

    entry = _find_inv_entry(inventory, item_id)
    if not entry:
        return False, f"**{db_item['name']}** nemáš v inventáři."

    # ── Kontrola požadavků (včetně Vlivu) ────────────────────────────────────
    requires = db_item.get("requires", {})
    failed = []
    for stat, needed in requires.items():
        have = _req_have(profile, stat)
        if have < needed:
            failed.append((stat, needed, have))
    if failed:
        reqs = ", ".join(f"**{stat}** {needed} (máš {have})" for stat, needed, have in failed)
        return False, f"**{db_item['name']}** — nesplněné požadavky: {reqs}."

    req_perk = db_item.get("required_perk")
    if req_perk and user_id:
        try:
            from src.core.dnd.perks import load_player_perks, load_perks
            owned_perks = load_player_perks().get(user_id, {}).get("perks", [])
            if req_perk not in owned_perks:
                perk_name = load_perks().get(req_perk, {}).get("name", req_perk)
                return False, f"**{db_item['name']}** vyžaduje perk **{perk_name}**."
        except Exception:
            pass

    hand_type   = db_item.get("hand_type")
    equip_bonus = db_item.get("equip_bonus", {})

    # ── Full set ──────────────────────────────────────────────────────────────
    if slot_target == "full_set":
        freed = []
        seen  = set()
        for s in FULL_SET_SLOTS:
            old = equipment.get(s)
            if old and old not in seen:
                _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
                _add_to_inventory(inventory, old, 1)
                freed.append(old)
                seen.add(old)
            equipment[s] = item_id
        _remove_from_inventory(inventory, item_id, 1)
        _apply_equip_bonus(profile, equip_bonus)
        msg = f"Equipoval jsi **{db_item['name']}** (full set)."
        if freed:
            freed_names = [items_db[i]["name"] if i in items_db else i for i in freed]
            msg += f"\nUvolněno: {', '.join(freed_names)} → vráceno do inventáře."
        bonus_str = _format_bonus(equip_bonus)
        if bonus_str:
            msg += f"\n✨ Bonus: {bonus_str}"
        return True, msg

    # ── Obouruční zbraň ───────────────────────────────────────────────────────
    if slot_target == "hand_l" and hand_type == "two":
        freed = []
        seen  = set()
        for s in ("hand_l", "hand_r"):
            old = equipment.get(s)
            if old and old not in seen:
                _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
                _add_to_inventory(inventory, old, 1)
                freed.append(old)
                seen.add(old)
            equipment[s] = None
        equipment["hand_l"] = item_id
        equipment["hand_r"] = item_id  # marker — oba ukazují na stejný item
        _remove_from_inventory(inventory, item_id, 1)
        _apply_equip_bonus(profile, equip_bonus)
        msg = f"Equipoval jsi **{db_item['name']}** (obouruční)."
        if freed:
            freed_names = [items_db[i]["name"] if i in items_db else i for i in freed]
            msg += f"\nUvolněno: {', '.join(freed_names)} → vráceno do inventáře."
        bonus_str = _format_bonus(equip_bonus)
        if bonus_str:
            msg += f"\n✨ Bonus: {bonus_str}"
        return True, msg

    # ── Jednoruční zbraň ──────────────────────────────────────────────────────
    if slot_target == "hand_l" and hand_type == "one":
        if preferred_slot in ("hand_l", "hand_r"):
            target_slot = preferred_slot
        else:
            target_slot = next(
                (s for s in ("hand_l", "hand_r") if not equipment.get(s)),
                "hand_l"
            )
        old = equipment.get(target_slot)
        freed_msg = ""
        if old:
            if equipment.get("hand_l") == equipment.get("hand_r") == old:
                equipment["hand_l"] = None
                equipment["hand_r"] = None
            _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
            _add_to_inventory(inventory, old, 1)
            old_name  = items_db[old]["name"] if old in items_db else old
            freed_msg = f"\nUvolněno: {old_name} → vráceno do inventáře."
        equipment[target_slot] = item_id
        _remove_from_inventory(inventory, item_id, 1)
        _apply_equip_bonus(profile, equip_bonus)
        slot_label = SLOT_LABELS.get(target_slot, target_slot)
        bonus_str  = _format_bonus(equip_bonus)
        bonus_line = f"\n✨ Bonus: {bonus_str}" if bonus_str else ""
        return True, f"Equipoval jsi **{db_item['name']}** do slotu **{slot_label}**.{freed_msg}{bonus_line}"

    # ── Prsteny / amulety ─────────────────────────────────────────────────────
    if slot_target in ("ring", "amulet"):
        active = _active_ring_slots(profile) if slot_target == "ring" else _active_amulet_slots(profile)
        if preferred_slot and preferred_slot in active:
            target_slot = preferred_slot
        else:
            target_slot = next((s for s in active if not equipment.get(s)), active[0])
    else:
        # Přímý slot (helmet, armor, boots, cloak, belt, hand_l bez hand_type)
        target_slot = slot_target
        if target_slot not in profile["equipment"]:
            return False, f"Slot `{target_slot}` neexistuje."

    old = equipment.get(target_slot)
    freed_msg = ""
    if old:
        _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
        _add_to_inventory(inventory, old, 1)
        old_name  = items_db[old]["name"] if old in items_db else old
        freed_msg = f"\nUvolněno: {old_name} → vráceno do inventáře."

    equipment[target_slot] = item_id
    _remove_from_inventory(inventory, item_id, 1)
    _apply_equip_bonus(profile, equip_bonus)
    slot_label = SLOT_LABELS.get(target_slot, target_slot)
    bonus_str  = _format_bonus(equip_bonus)
    bonus_line = f"\n✨ Bonus: {bonus_str}" if bonus_str else ""
    return True, f"Equipoval jsi **{db_item['name']}** ({slot_label}).{freed_msg}{bonus_line}"


def _unequip_slot(profile: dict, slot: str, items_db: dict) -> tuple[bool, str]:
    _ensure_inv_fields(profile)
    equipment = profile["equipment"]
    item_id   = equipment.get(slot)

    if not item_id:
        return False, f"Slot **{SLOT_LABELS.get(slot, slot)}** je prázdný."

    db_item     = items_db.get(item_id, {})
    name        = db_item.get("name", item_id)
    hand_type   = db_item.get("hand_type")
    slot_type   = db_item.get("slot")
    equip_bonus = db_item.get("equip_bonus", {})

    _remove_equip_bonus(profile, equip_bonus)

    if slot_type == "full_set":
        for s in FULL_SET_SLOTS:
            if equipment.get(s) == item_id:
                equipment[s] = None
    elif hand_type == "two" and slot in ("hand_l", "hand_r"):
        equipment["hand_l"] = None
        equipment["hand_r"] = None
    else:
        equipment[slot] = None

    _add_to_inventory(profile["inventory"], item_id, 1)
    return True, f"Sundal jsi **{name}** → vráceno do inventáře."

# ══════════════════════════════════════════════════════════════════════════════
# EMBED BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_equip_embed(profile: dict, member: discord.Member,
                       items_db: dict) -> discord.Embed:
    """Embed zobrazující equipment + přehled dostupných úložišť (úvod /inv)."""
    _ensure_inv_fields(profile)
    _migrate_storages(profile)
    equipment = profile["equipment"]

    embed = discord.Embed(color=EMBED_COLOR)
    embed.set_author(name=f"{member.display_name} — ⚔️ Výbava",
                     icon_url=member.display_avatar.url)

    equip_lines = []
    total_def   = 0
    seen_items  = set()
    for slot in _active_slots(profile):
        label   = SLOT_LABELS.get(slot, slot)
        emoji   = SLOT_EMOJIS.get(slot, "▪️")
        item_id = equipment.get(slot)
        if not item_id:
            equip_lines.append(f"{emoji} **{label}**  —")
        else:
            if slot == "hand_r" and equipment.get("hand_l") == item_id:
                continue
            db_item  = items_db.get(item_id) or {}
            name     = db_item.get("name", f"[{item_id}]")
            suffix   = "  *(obouruční)*" if db_item.get("hand_type") == "two" else ""
            def_val  = db_item.get("def", 0)
            atk_val  = db_item.get("atk", 0)
            mods     = _parse_modifiers(db_item)
            stat_str = ""
            if atk_val: stat_str += f"  ⚔️{atk_val}"
            if mods:    stat_str += f"  {mods}"
            if def_val: stat_str += f"  🛡️{def_val}"
            if item_id not in seen_items:
                total_def += def_val
                seen_items.add(item_id)
            equip_lines.append(f"{emoji} **{label}**  {name}{suffix}{stat_str}")

    totals_str = f"  ·  🛡️ DEF celkem: **{total_def}**" if total_def else ""
    embed.add_field(name=f"⚔️  Equipment{totals_str}",
                    value="\n".join(equip_lines) or "—", inline=False)

    stor_lines = []
    for skey in _available_storages(profile, items_db):
        visual  = _storage_visual(skey, items_db)
        stor    = profile.get("storages", {}).get(skey, [])
        cap     = _storage_capacity(skey, profile, items_db)
        used    = _count_slots(stor, items_db)
        cap_str = "∞" if cap is None else f"{used}/{cap}"
        stor_lines.append(f"{visual['emoji']} **{visual['label']}**  `[{cap_str}]`")
    embed.add_field(name="🎒  Úložiště",
                    value="\n".join(stor_lines) + "\n-# Vyber tlačítkem níže.",
                    inline=False)

    embed.set_footer(text="🪶 = lehký předmět (nezabírá slot)  ·  Aurionis")
    return embed


def _build_inspect_embed(item_id: str, items_db: dict,
                         profile: dict | None = None) -> discord.Embed | None:
    item = items_db.get(item_id)
    if not item:
        return None

    hand_label = {"one": "Jednoruční", "two": "Obouruční"}.get(item.get("hand_type", ""), "")
    slot_label = SLOT_LABELS.get(item.get("slot", ""), item.get("slot", ""))

    tags = []
    if hand_label:
        tags.append(hand_label)
    if item.get("atk"):             tags.append(f"⚔️ ATK {item['atk']}")
    if item.get("def"):             tags.append(f"🛡️ DEF {item['def']}")
    if item.get("hunger_restore"):  tags.append(f"🍖 +{item['hunger_restore']} hlad")
    if item.get("hp_restore"):      tags.append(f"❤️ +{item['hp_restore']} HP")
    if item.get("mana_restore"):    tags.append(f"🔷 +{item['mana_restore']} mana")
    if item.get("mana_cost"):       tags.append(f"🔷 -{item['mana_cost']} mana (cena)")
    if item.get("consumable"):      tags.append("consumable")
    if item.get("stackable"):       tags.append("stackable")

    desc_parts = []
    if item.get("category"):
        desc_parts.append(f"-# {item['category']}")
    if tags:
        desc_parts.append(f"-# {' · '.join(tags)}")
    if item.get("desc"):
        desc_parts.append(f"\n{item['desc']}")

    # ── Požadavky ─────────────────────────────────────────────────────────────
    requires = item.get("requires", {})
    if requires:
        req_lines = []
        for stat, needed in requires.items():
            have  = _req_have(profile, stat) if profile else 0
            label = SKILL_REQUIRES.get(stat, stat)
            icon  = "✅" if have >= needed else "❌"
            line  = f"{icon} **{label}** {needed}"
            if profile:
                line += f"  *(máš {have})*"
            req_lines.append(line)
        desc_parts.append("\n**Požadavky:**\n" + "\n".join(req_lines))

    req_perk = item.get("required_perk")
    if req_perk:
        try:
            from src.core.dnd.perks import load_perks
            perk_name = load_perks().get(req_perk, {}).get("name", req_perk)
        except Exception:
            perk_name = req_perk
        desc_parts.append(f"\n**Potřebný perk:** ⚔️ **{perk_name}**\n-# `{req_perk}`")

    embed = discord.Embed(
        title=item["name"],
        description="\n".join(desc_parts) if desc_parts else "—",
        color=EMBED_COLOR,
    )
    embed.set_footer(text=f"ID: {item_id}  ·  slot: {slot_label or '—'}")
    return embed


def _entry_line(entry: dict, items_db: dict) -> tuple[int, str]:
    """Vrátí (index_skupiny, vykreslený_řádek) pro jeden předmět."""
    name    = _item_display_name(entry, items_db)
    qty     = entry.get("qty", 1)
    qty_str = f" ×{qty}" if qty > 1 else ""
    if entry.get("type") == "registered":
        db_item = items_db.get(entry["id"], {})
        cat     = db_item.get("category", "")
        light   = " 🪶" if cat in WEIGHTLESS_CATEGORIES else ""
        gi      = _CAT_TO_GROUP.get(cat, _OSTATNI_GROUP)
        return gi, f"▸ **{name}**{qty_str}{light}"
    return _OSTATNI_GROUP, f"▸ {name}{qty_str}"


def _render_storage_lines(storage: list, items_db: dict) -> list[str]:
    """Řádky předmětů seskupené a seřazené podle širokých kategorií (bez stránkování)."""
    buckets: dict[int, list[str]] = {}
    for entry in storage:
        gi, line = _entry_line(entry, items_db)
        buckets.setdefault(gi, []).append(line)
    lines: list[str] = []
    for gi, (emoji, label, _cats) in enumerate(CATEGORY_GROUPS):
        items = buckets.get(gi)
        if not items:
            continue
        items.sort(key=str.lower)
        lines.append(f"**{emoji} {label}**")
        lines.extend(items)
    return lines


def _paginate_storage(storage: list, items_db: dict,
                      page_size: int = PAGE_SIZE) -> list[dict]:
    """Group-aware stránkování úložiště.

    Vrací list stránek: [{"lines": [...], "entries": [abs_idx, ...]}].
    Skupiny nepřetékají — nadpis zůstává se svými předměty na stejné stránce.
    Skupina delší než stránka se rozdělí a nadpis se zopakuje s '(pokr.)'.
    `entries` drží absolutní indexy do `storage` pro detail-dropdown.
    """
    buckets: dict[int, list[tuple[int, str]]] = {}
    for abs_idx, entry in enumerate(storage):
        gi, line = _entry_line(entry, items_db)
        buckets.setdefault(gi, []).append((abs_idx, line))

    ordered: list[tuple[str, list[tuple[int, str]]]] = []
    for gi, (emoji, label, _cats) in enumerate(CATEGORY_GROUPS):
        items = buckets.get(gi)
        if not items:
            continue
        items.sort(key=lambda t: t[1].lower())
        ordered.append((f"**{emoji} {label}**", items))

    pages: list[dict] = []
    cur = {"lines": [], "entries": []}
    cur_count = 0

    def flush():
        nonlocal cur, cur_count
        if cur["lines"]:
            pages.append(cur)
        cur = {"lines": [], "entries": []}
        cur_count = 0

    for header, items in ordered:
        # Skupina delší než stránka → rozděl, nadpis opakuj s "(pokr.)"
        if len(items) > page_size:
            if cur_count:
                flush()
            for ci in range(0, len(items), page_size):
                chunk = items[ci:ci + page_size]
                cur["lines"].append(header if ci == 0 else f"{header} *(pokr.)*")
                for abs_idx, line in chunk:
                    cur["lines"].append(line)
                    cur["entries"].append(abs_idx)
                cur_count = len(chunk)
                flush()
            continue
        # Skupina se vejde celá — když se nevejde na současnou stránku, začni novou
        if cur_count and cur_count + len(items) > page_size:
            flush()
        cur["lines"].append(header)
        for abs_idx, line in items:
            cur["lines"].append(line)
            cur["entries"].append(abs_idx)
        cur_count += len(items)
    flush()
    return pages or [{"lines": [], "entries": []}]


def _build_storage_embed(profile: dict, member: discord.Member, items_db: dict,
                         storage_key: str, page: int = 0) -> tuple[discord.Embed, int]:
    """Univerzální embed pro libovolný storage (inventory, BoH, batoh, brašna…)."""
    storage = _ensure_storage(profile, storage_key)
    if storage_key == "inventory":
        notes = _inv_notes(profile)   # sjednocený zdroj pravdy (viz fix bugu s poznámkami)
    else:
        notes = profile.setdefault("storage_notes", {}).setdefault(storage_key, [])
    visual  = _storage_visual(storage_key, items_db)
    cap     = _storage_capacity(storage_key, profile, items_db)
    used    = _count_slots(storage, items_db)
    cap_str = "∞" if cap is None else f"{used}/{cap}"

    embed = discord.Embed(color=visual["color"])
    embed.set_author(
        name=f"{member.display_name} — {visual['emoji']} {visual['label']}  [{cap_str}]",
        icon_url=member.display_avatar.url,
    )

    pages_data  = _paginate_storage(storage, items_db)
    total_pages = len(pages_data)
    page        = max(0, min(page, total_pages - 1))
    chunk       = pages_data[page]["lines"]
    embed.description = "\n".join(chunk) if chunk else "*Prázdné...*"

    if notes:
        note_lines = [f"`{i+1}.` {n}" for i, n in enumerate(notes)]
        notes_val  = "\n".join(note_lines[:20])
        if len(notes) > 20:
            notes_val += f"\n*... a {len(notes) - 20} dalších*"
        embed.add_field(name="📝 Ostatní", value=notes_val, inline=False)

    cap_footer = "∞ neomezeno" if cap is None else f"{used}/{cap} slotů"
    embed.set_footer(text=f"{visual['emoji']} {visual['label']}  ·  {cap_footer}  ·  Strana {page + 1}/{total_pages}")
    return embed, total_pages


def _build_item_detail_embed(entry: dict, items_db: dict) -> discord.Embed:
    """Plný detail jednoho předmětu (pro select v inventáři)."""
    if entry["type"] != "registered":
        # Free / custom item — jen jméno
        return discord.Embed(
            title=entry.get("name", "?"),
            description="*Volný předmět bez databázového záznamu.*",
            color=EMBED_COLOR,
        )

    iid     = entry["id"]
    db_item = items_db.get(iid, {})
    name    = db_item.get("name", f"[{iid}]")
    qty     = entry.get("qty", 1)

    embed = discord.Embed(title=name, color=EMBED_COLOR)

    # Lore / popis
    lore = db_item.get("lore_drop")
    desc = db_item.get("desc")
    if desc:
        embed.description = desc
    elif lore:
        embed.description = f"*{lore}*"

    # Statistiky
    stat_lines = []
    cat = db_item.get("category")
    if cat:
        stat_lines.append(f"📦 Kategorie: **{cat}**")
    if qty > 1:
        stat_lines.append(f"🔢 Množství: **{qty}**")
    slot = db_item.get("slot")
    if slot:
        slot_label = SLOT_LABELS.get(slot, slot)
        ht = db_item.get("hand_type")
        ht_str = "  *(obouruční)*" if ht == "two" else ("  *(jednoruční)*" if ht == "one" else "")
        stat_lines.append(f"📍 Slot: **{slot_label}**{ht_str}")
    if db_item.get("atk"):
        stat_lines.append(f"⚔️ Útok: **{db_item['atk']}**")
    if db_item.get("def"):
        stat_lines.append(f"🛡️ Obrana: **{db_item['def']}**")
    mods = _parse_modifiers(db_item)
    if mods:
        stat_lines.append(f"✨ Efekty: {mods}")
    for key, label in [("hp_restore", "❤️ Obnova HP"), ("mana_restore", "🔷 Obnova many"),
                       ("hunger_restore", "🍖 Obnova hladu"), ("mana_cost", "🔷 Cena many")]:
        if db_item.get(key):
            stat_lines.append(f"{label}: **{db_item[key]}**")
    if db_item.get("stackable"):
        stat_lines.append("📚 Stackovatelné")
    if db_item.get("consumable"):
        stat_lines.append("🍽️ Spotřebuje se při použití")

    storage = db_item.get("storage")
    if isinstance(storage, dict):
        scap = storage.get("capacity")
        scap_str = "∞ neomezené" if scap is None else f"{scap} slotů"
        stat_lines.append(f"{storage.get('emoji', '📦')} Úložiště: **{scap_str}**")

    if stat_lines:
        embed.add_field(name="Vlastnosti", value="\n".join(stat_lines), inline=False)

    # Runy vyryté na TÉTO instanci itemu (mimo databázi — viz blacksmith.py)
    runes = entry.get("runes")
    if isinstance(runes, list) and runes:
        try:
            from src.core.dnd.blacksmith import load_runes
            reg = load_runes()
        except Exception:
            reg = {}
        rune_lines = []
        for rid in runes:
            r = reg.get(rid, {})
            emoji = r.get("emoji", "🔹")
            nm    = r.get("name", rid)
            dmg   = f"  +{r['bonus_dmg']} dmg" if r.get("bonus_dmg") else ""
            rune_lines.append(f"{emoji} **{nm}**{dmg} — {r.get('desc', '—')}")
        embed.add_field(name="🔮 Runy", value="\n".join(rune_lines), inline=False)

    # Požadavky
    req = db_item.get("requires")
    if req:
        req_str = "  ·  ".join(f"{k} {v}" for k, v in req.items())
        embed.add_field(name="📋 Požadavky", value=req_str, inline=False)

    eb = db_item.get("equip_bonus")
    if eb:
        bonus_str = _format_bonus(eb)
        if bonus_str:
            embed.add_field(name="🌟 Bonus při equipu", value=bonus_str, inline=False)

    rp = db_item.get("required_perk")
    if rp:
        embed.add_field(name="🔒 Vyžaduje perk", value=rp, inline=False)

    embed.set_footer(text=f"ID: {iid}")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

# ══════════════════════════════════════════════════════════════════════════════
# AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

async def _ac_database_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    cur = current.lower()
    return [
        app_commands.Choice(name=v["name"], value=k)
        for k, v in items_db.items()
        if cur in k.lower() or cur in v["name"].lower()
    ][:25]


async def _ac_vyzboj_perk(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        from src.core.dnd.perks import load_perks
        perks = load_perks()
        cur   = current.lower()
        return [
            app_commands.Choice(name=f"{p['name']} ({pid})", value=pid)
            for pid, p in perks.items()
            if p.get("group") == "Výzbroj"
            and (cur in pid.lower() or cur in p.get("name", "").lower())
        ][:25]
    except Exception:
        return []


async def _ac_inventory_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur     = current.lower()
    choices = []
    for entry in profile["inventory"]:
        name = _item_display_name(entry, items_db)
        key  = entry["id"] if entry["type"] == "registered" else entry.get("name", "")
        if cur in name.lower() or cur in key.lower():
            choices.append(app_commands.Choice(name=name, value=key))
    return choices[:25]


async def _ac_ammo_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete pro munici v Toulci/inventáři (kategorie 'náboje' — i throwable jako granáty)."""
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur      = current.lower()
    storages = profile.get("storages", {})
    pool     = list(storages.get("toulec", [])) + list(profile.get("inventory", []))
    seen     = set()
    choices  = []
    for entry in pool:
        if entry.get("type") != "registered":
            continue
        iid = entry["id"]
        if iid in seen:
            continue
        db_item = items_db.get(iid, {})
        if db_item.get("category") != "náboje":
            continue
        name = _item_display_name(entry, items_db)
        if cur in name.lower() or cur in iid.lower():
            choices.append(app_commands.Choice(name=name, value=iid))
            seen.add(iid)
    return choices[:25]


async def _ac_equipped_slot(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    profile = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    equipment = profile["equipment"]
    cur       = current.lower()
    choices   = []
    seen      = set()
    for slot in _active_slots(profile):
        item_id = equipment.get(slot)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        label = SLOT_LABELS.get(slot, slot)
        if cur in label.lower() or cur in slot.lower():
            choices.append(app_commands.Choice(name=label, value=slot))
    return choices[:25]


async def _ac_equippable_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur     = current.lower()
    choices = []
    for entry in profile["inventory"]:
        if entry["type"] != "registered":
            continue
        db_item = items_db.get(entry["id"])
        if not db_item or not db_item.get("slot"):
            continue
        name = db_item["name"]
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(name=name, value=entry["id"]))
    return choices[:25]


async def _ac_consumable_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur     = current.lower()
    choices = []
    for entry in profile["inventory"]:
        if entry["type"] != "registered":
            continue
        db_item = items_db.get(entry["id"])
        if not db_item or not db_item.get("consumable"):
            continue
        name = db_item["name"]
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(name=name, value=entry["id"]))
    return choices[:25]

async def _ac_use_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete pro /use — filtruje consumable itemy, volitelně podle kategorie."""
    items_db  = _load_items()
    profile   = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur      = current.lower()
    kategorie = getattr(interaction.namespace, "kategorie", None)

    # "ostatní" = vše consumable co není jídlo/lektvary/svitky
    _other = {"jídlo", "lektvary", "svitky"}

    choices = []
    for entry in profile["inventory"]:
        if entry["type"] != "registered":
            continue
        db_item = items_db.get(entry["id"])
        if not db_item or not db_item.get("consumable"):
            continue
        cat = db_item.get("category", "")
        if kategorie and kategorie != "ostatní" and cat != kategorie:
            continue
        if kategorie == "ostatní" and cat in _other:
            continue
        name = db_item["name"]
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(name=name, value=entry["id"]))
    return choices[:25]


async def _ac_storage_key(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete pro dostupné storage hráče (inventory, BoH, batoh…)."""
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _migrate_storages(profile)
    cur     = current.lower()
    choices = []
    for skey in _available_storages(profile, items_db):
        visual = _storage_visual(skey, items_db)
        label  = f"{visual['emoji']} {visual['label']}"
        if cur in label.lower() or cur in skey.lower():
            choices.append(app_commands.Choice(name=label, value=skey))
    return choices[:25]


def _make_ac_storage_items(param_name: str):
    """Factory — autocomplete pro itemy v storage zvoleném v jiném parametru."""
    async def _ac(interaction: discord.Interaction, current: str):
        items_db = _load_items()
        profile  = _get_profile(interaction.user.id)
        if not profile:
            return []
        _migrate_storages(profile)
        # Zjisti hodnotu zdrojového storage z již vyplněných parametrů
        skey = None
        for opt in (interaction.data.get("options") or []):
            for sub in opt.get("options", [opt]):
                if sub.get("name") == param_name:
                    skey = sub.get("value")
        if skey is None:
            skey = "inventory"
        stor    = profile.get("storages", {}).get(skey, [])
        cur     = current.lower()
        choices = []
        for entry in stor:
            name = _item_display_name(entry, items_db)
            key  = entry["id"] if entry["type"] == "registered" else entry.get("name", "")
            if cur in name.lower() or cur in key.lower():
                choices.append(app_commands.Choice(name=name, value=key))
        return choices[:25]
    return _ac


async def _ac_equip_slot(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Kontextový autocomplete pro slot v /equip — závisí na zvoleném itemu."""
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    item_id  = getattr(interaction.namespace, "item", None)

    db_item = items_db.get(item_id) if item_id else None
    if not db_item:
        return []

    slot_target = db_item.get("slot")
    if not slot_target:
        return []

    equipment = {}
    if profile:
        _ensure_inv_fields(profile)
        equipment = profile["equipment"]

    cur = current.lower()

    def _slot_choice(slot_key: str) -> app_commands.Choice[str]:
        label    = SLOT_LABELS.get(slot_key, slot_key)
        occupied = equipment.get(slot_key)
        if occupied:
            occ_name = items_db.get(occupied, {}).get("name", occupied)
            display  = f"{label}  [{occ_name}]"
        else:
            display  = f"{label}  [volný]"
        return app_commands.Choice(name=display, value=slot_key)

    choices = []
    if slot_target == "weapon":
        for s in ("hand_l", "hand_r"):
            if not cur or cur in SLOT_LABELS[s].lower() or cur in s:
                choices.append(_slot_choice(s))

    elif slot_target == "ring":
        active = _active_ring_slots(profile) if profile else ["ring_1", "ring_2"]
        for s in active:
            if not cur or cur in SLOT_LABELS.get(s, s).lower() or cur in s:
                choices.append(_slot_choice(s))

    elif slot_target == "amulet":
        active = _active_amulet_slots(profile) if profile else ["amulet_1"]
        for s in active:
            if not cur or cur in SLOT_LABELS.get(s, s).lower() or cur in s:
                choices.append(_slot_choice(s))

    else:
        # Přímý slot (helmet, armor, boots, cloak, belt) — jen jeden, ale ukáž ho
        choices.append(_slot_choice(slot_target))

    return choices[:25]

# ══════════════════════════════════════════════════════════════════════════════
# STRÁNKOVÁNÍ VIEW
# ══════════════════════════════════════════════════════════════════════════════

class InvPageView(discord.ui.View):
    """Univerzální view — equip embed + tlačítka pro každý dostupný storage."""

    def __init__(self, profile: dict, member: discord.Member, items_db: dict,
                 start_storage: str = "inventory"):
        super().__init__(timeout=180)
        self.profile  = profile
        self.member   = member
        self.items_db = items_db
        self.storages = _available_storages(profile, items_db)
        self.active   = start_storage if start_storage in self.storages else "inventory"
        self.page     = 0
        self.pages    = 1
        self._build_storage_buttons()
        self._rebuild_item_select()

    def _build_storage_buttons(self):
        """Přidá tlačítko pro každý dostupný storage (row 1+)."""
        # Smaž stará storage tlačítka
        for item in [c for c in self.children if getattr(c, "custom_id", "").startswith("stor_")]:
            self.remove_item(item)
        for i, skey in enumerate(self.storages):
            visual = _storage_visual(skey, self.items_db)
            is_active = (skey == self.active)
            btn = discord.ui.Button(
                label=f"{visual['emoji']} {visual['label']}",
                style=discord.ButtonStyle.success if is_active else discord.ButtonStyle.secondary,
                custom_id=f"stor_{skey}",
                row=2 + (i // 5),
            )
            btn.callback = self._make_storage_callback(skey)
            self.add_item(btn)

    def _rebuild_item_select(self):
        """Naplní dropdown itemy z aktuální stránky (sladěno s group-aware stránkováním)."""
        # Smaž starý select
        for item in [c for c in self.children if getattr(c, "custom_id", "") == "item_detail_select"]:
            self.remove_item(item)

        storage    = self.profile.get("storages", {}).get(self.active, [])
        pages_data = _paginate_storage(storage, self.items_db)
        page       = max(0, min(self.page, len(pages_data) - 1))
        entry_idxs = pages_data[page]["entries"]
        if not entry_idxs:
            return

        options = []
        for abs_idx in entry_idxs:
            entry = storage[abs_idx]
            name  = _item_display_name(entry, self.items_db)
            qty   = entry.get("qty", 1)
            label = (name if qty <= 1 else f"{name} ×{qty}")[:100]
            cat   = ""
            if entry.get("type") == "registered":
                cat = self.items_db.get(entry["id"], {}).get("category", "")
            options.append(discord.SelectOption(
                label=label,
                value=str(abs_idx),        # absolutní index v storage
                description=cat[:100] if cat else None,
            ))

        select = discord.ui.Select(
            placeholder="📋 Zobrazit detail předmětu…",
            options=options[:25],
            custom_id="item_detail_select",
            row=1,
        )
        select.callback = self._item_select_callback
        self.add_item(select)

    async def _item_select_callback(self, interaction: discord.Interaction):
        # Najdi vybraný index
        try:
            sel_idx = int(interaction.data["values"][0])
        except (KeyError, ValueError, IndexError):
            await interaction.response.send_message("*Nelze načíst předmět.*", ephemeral=True)
            return
        storage = self.profile.get("storages", {}).get(self.active, [])
        if sel_idx >= len(storage):
            await interaction.response.send_message("*Předmět už není v úložišti.*", ephemeral=True)
            return
        embed = _build_item_detail_embed(storage[sel_idx], self.items_db)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _make_storage_callback(self, storage_key: str):
        async def callback(interaction: discord.Interaction):
            self.active = storage_key
            self.page   = 0
            self._build_storage_buttons()
            await self._refresh(interaction)
        return callback

    def _update_nav(self):
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page >= self.pages - 1)

    async def _refresh(self, interaction: discord.Interaction):
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, self.member.id))
        if profile:
            _ensure_inv_fields(profile)
            _migrate_storages(profile)
            self.profile  = profile
            self.storages = _available_storages(profile, self.items_db)
            if self.active not in self.storages:
                self.active = "inventory"

        embed, pages = _build_storage_embed(
            self.profile, self.member, self.items_db, self.active, self.page)
        self.pages = pages
        self._update_nav()
        self._rebuild_item_select()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self._refresh(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self._refresh(interaction)

    @discord.ui.button(label="⚔️ Výbava", style=discord.ButtonStyle.primary, row=0)
    async def equip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Vrátí zpět na úvodní equip embed."""
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, self.member.id))
        if profile:
            _ensure_inv_fields(profile)
            _migrate_storages(profile)
            self.profile  = profile
            self.storages = _available_storages(profile, self.items_db)
        self.active = "inventory"
        self.page   = 0
        self._build_storage_buttons()
        # Odeber item select — na equip přehledu nedává smysl
        for item in [c for c in self.children if getattr(c, "custom_id", "") == "item_detail_select"]:
            self.remove_item(item)
        embed = _build_equip_embed(self.profile, self.member, self.items_db)
        await interaction.response.edit_message(embed=embed, view=self)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Inventory(commands.Cog):
    inv_db       = app_commands.Group(name="inv-db",       description="[DM] Správa databáze itemů")
    inv_admin    = app_commands.Group(name="inv-admin",    description="[DM] Admin operace s inventářem")
    inv_note     = app_commands.Group(name="inv-note",     description="Poznámky v inventáři (sekce Ostatní)")
    inv_boh_note = app_commands.Group(name="boh-note", description="Poznámky v Bag of Holding (sekce Ostatní)")

    def __init__(self, bot):
        self.bot = bot

    # ── /inv ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="inv", description="Zobrazí equipment a úložiště.")
    @app_commands.describe(member="Hráč (výchozí: ty).")
    async def inv(self, interaction: discord.Interaction,
                  member: Optional[discord.Member] = None):
        await interaction.response.defer()
        target   = member or interaction.user
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, target.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{target.display_name}** nemá profil.", ephemeral=True)
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)
        items_db = _load_items()
        if _sort_ammo_to_toulec(profile, items_db):
            _save_profiles(profiles)

        # Otevři rovnou inventář (se select dropdownem); equip je dostupný tlačítkem
        view = InvPageView(profile, target, items_db, start_storage="inventory")
        embed, pages = _build_storage_embed(profile, target, items_db, "inventory", 0)
        view.pages = pages
        view._update_nav()
        await interaction.followup.send(embed=embed, view=view)

        # Achievement: plná výbava — záchytný trigger při zobrazení vlastního inv.
        if target.id == interaction.user.id:
            await _check_full_equip(interaction.user, interaction.channel, profile)

    # ── /inv-note add ─────────────────────────────────────────────────────────
    @inv_note.command(name="add",
                      description="Přidá poznámku do sekce Ostatní (věci mimo databázi).")
    @app_commands.describe(text="Text poznámky — předmět, nález, informace...")
    async def inv_note_add(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil. Nejdřív `/start`.")
            return
        _ensure_inv_fields(profile)
        notes = _inv_notes(profile)
        notes.append(text)
        line_num = len(notes)
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Přidáno jako řádek **{line_num}**: *{text}*")

    # ── /inv-note edit ────────────────────────────────────────────────────────
    @inv_note.command(name="edit",
                      description="Upraví poznámku v sekci Ostatní dle čísla řádku.")
    @app_commands.describe(
        cislo="Číslo řádku (viz /inv → Ostatní).",
        text="Nový text.",
    )
    async def inv_note_edit(self, interaction: discord.Interaction,
                            cislo: int, text: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        notes = _inv_notes(profile)
        if cislo < 1 or cislo > len(notes):
            await interaction.followup.send(
                f"❌ Řádek {cislo} neexistuje. Máš {len(notes)} poznámek.")
            return
        old          = notes[cislo - 1]
        notes[cislo - 1] = text
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Řádek **{cislo}** upraven.\n~~{old}~~ → *{text}*")

    # ── /inv-note remove ──────────────────────────────────────────────────────
    @inv_note.command(name="remove",
                      description="Odebere poznámku z Ostatní dle čísla řádku.")
    @app_commands.describe(cislo="Číslo řádku (viz /inv → Ostatní).")
    async def inv_note_remove(self, interaction: discord.Interaction, cislo: int):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        notes = _inv_notes(profile)
        if cislo < 1 or cislo > len(notes):
            await interaction.followup.send(
                f"❌ Řádek {cislo} neexistuje. Máš {len(notes)} poznámek.")
            return
        removed = notes.pop(cislo - 1)
        _save_profiles(profiles)
        await interaction.followup.send(f"✅ Odebráno řádek **{cislo}**: ~~{removed}~~")

    # ── /inv-remove ───────────────────────────────────────────────────────────
    @app_commands.command(name="inv-remove",
                          description="Odebere registrovaný item z vlastního inventáře.")
    @app_commands.describe(
        item="Název nebo ID itemu.",
        qty="Množství (výchozí: 1).",
    )
    @app_commands.autocomplete(item=_ac_inventory_item)
    async def inv_remove(self, interaction: discord.Interaction,
                         item: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        ok = _remove_from_inventory(profile["inventory"], item, qty)
        if not ok:
            await interaction.followup.send(
                f"❌ Nemáš dost kusů **{item}** v inventáři.")
            return
        _save_profiles(profiles)
        await interaction.followup.send(f"✅ Odebráno: **{item}** ×{qty}.")

    # ── /inv-give ─────────────────────────────────────────────────────────────
    @app_commands.command(name="inv-give", description="Pošle registrovaný item jinému hráči.")
    @app_commands.describe(
        member="Příjemce.",
        item="Název nebo ID itemu.",
        qty="Množství (výchozí: 1).",
    )
    @app_commands.autocomplete(item=_ac_inventory_item)
    async def inv_give(self, interaction: discord.Interaction,
                       member: discord.Member, item: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if member.id == interaction.user.id:
            await interaction.followup.send("❌ Nemůžeš posílat sám sobě.")
            return
        profiles = _load_profiles()
        giver_p  = profiles.get(_pk(profiles, interaction.user.id))
        recvr_p  = profiles.get(_pk(profiles, member.id))
        if not giver_p:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        if not recvr_p:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(giver_p)
        _ensure_inv_fields(recvr_p)
        items_db = _load_items()

        entry = _find_inv_entry(giver_p["inventory"], item)
        if not entry:
            await interaction.followup.send(f"❌ **{item}** nemáš v inventáři.")
            return

        ok = _remove_from_inventory(giver_p["inventory"], item, qty)
        if not ok:
            await interaction.followup.send(f"❌ Nemáš dost kusů **{item}**.")
            return

        name = _item_display_name(entry, items_db)
        if entry["type"] == "registered":
            _add_to_inventory(recvr_p["inventory"], entry["id"], qty)
            _sort_ammo_to_toulec(recvr_p, items_db)   # munice příjemci rovnou do Toulce
        else:
            # Legacy volný item — přidej jako poznámku
            recvr_notes = _inv_notes(recvr_p)
            for _ in range(qty):
                recvr_notes.append(entry.get("name", item))

        _save_profiles(profiles)
        qty_str = f" ×{qty}" if qty > 1 else ""
        await interaction.followup.send(
            f"✅ Předal jsi **{name}**{qty_str} → **{member.display_name}**.")

    # ── /inv-use ──────────────────────────────────────────────────────────────
    @app_commands.command(name="inv-use", description="Použije consumable item.")
    @app_commands.describe(item="Consumable item z inventáře.")
    @app_commands.autocomplete(item=_ac_consumable_item)
    async def inv_use(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.", ephemeral=True)
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        db_item  = items_db.get(item)
        if not db_item:
            await interaction.followup.send(
                "❌ Tento item není v databázi.", ephemeral=True)
            return
        if not db_item.get("consumable"):
            await interaction.followup.send(
                f"❌ **{db_item['name']}** není consumable.", ephemeral=True)
            return
        entry = _find_inv_entry(profile["inventory"], item)
        if not entry:
            await interaction.followup.send(
                f"❌ **{db_item['name']}** nemáš v inventáři.", ephemeral=True)
            return

        # ── Zkontroluj mana_cost před použitím ───────────────────────────────
        mana_cost = db_item.get("mana_cost", 0)
        if mana_cost:
            mana_cur = profile.get("mana_cur", profile.get("mana_max", 20))
            if mana_cur < mana_cost:
                await interaction.followup.send(
                    f"❌ Nemáš dost many. Potřebuješ **{mana_cost}** 🔷, máš **{mana_cur}**.",
                    ephemeral=True,
                )
                return

        _remove_from_inventory(profile["inventory"], item, 1)

        # ── Aplikuj efekty ────────────────────────────────────────────────────
        effects = []

        if mana_cost:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            new = max(0, cur - mana_cost)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (-{mana_cost})")

        hunger_restore = db_item.get("hunger_restore", 0)
        if hunger_restore:
            cur = profile.get("hunger_cur", 0)
            máx = profile.get("hunger_max", 10)
            new = min(cur + hunger_restore, máx)
            profile["hunger_cur"] = new
            effects.append(f"🍖 Hlad `{cur}` → `{new}` (+{new - cur})")

        hp_restore = db_item.get("hp_restore", 0)
        if hp_restore:
            cur = profile.get("hp_cur", 0)
            máx = profile.get("hp_max", 50)
            new = min(cur + hp_restore, máx)
            profile["hp_cur"] = new
            effects.append(f"❤️ HP `{cur}` → `{new}` (+{new - cur})")

        mana_restore = db_item.get("mana_restore", 0)
        if mana_restore:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            máx = profile.get("mana_max", 20)
            new = min(cur + mana_restore, máx)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (+{new - cur})")

        _save_profiles(profiles)

        effect_str = "\n".join(effects) if effects else ""
        use_text = db_item.get("lore_drop") or db_item.get("desc", "…")
        embed = discord.Embed(
            title=f"✨ {db_item['name']}",
            description=f"*{use_text}*" + (f"\n\n{effect_str}" if effect_str else ""),
            color=0xf0a500,
        )
        embed.set_footer(text=f"{interaction.user.display_name}  ·  item použit a odebrán")
        await interaction.followup.send(embed=embed)

    # ── /use ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="use", description="Použij consumable item ze svého inventáře.")
    @app_commands.describe(
        kategorie="Filtruj typ itemu (výchozí: vše).",
        item="Item k použití.",
    )
    @app_commands.choices(kategorie=[
        app_commands.Choice(name=c, value=c) for c in USE_CATEGORIES
    ])
    @app_commands.autocomplete(item=_ac_use_item)
    async def use_cmd(
        self,
        interaction: discord.Interaction,
        item: str,
        kategorie: Optional[app_commands.Choice[str]] = None,
    ):
        """Stejná logika jako /inv-use, ale s filtrovaným autocomplete."""
        await interaction.response.defer()
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.", ephemeral=True)
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        db_item  = items_db.get(item)
        if not db_item:
            await interaction.followup.send("❌ Tento item není v databázi.", ephemeral=True)
            return
        if not db_item.get("consumable"):
            await interaction.followup.send(
                f"❌ **{db_item['name']}** není consumable.", ephemeral=True)
            return
        entry = _find_inv_entry(profile["inventory"], item)
        if not entry:
            await interaction.followup.send(
                f"❌ **{db_item['name']}** nemáš v inventáři.", ephemeral=True)
            return

        mana_cost = db_item.get("mana_cost", 0)
        if mana_cost:
            mana_cur = profile.get("mana_cur", profile.get("mana_max", 20))
            if mana_cur < mana_cost:
                await interaction.followup.send(
                    f"❌ Nemáš dost many. Potřebuješ **{mana_cost}** 🔷, máš **{mana_cur}**.",
                    ephemeral=True,
                )
                return

        _remove_from_inventory(profile["inventory"], item, 1)
        effects = []

        if mana_cost:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            new = max(0, cur - mana_cost)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (-{mana_cost})")

        if db_item.get("hunger_restore", 0):
            cur = profile.get("hunger_cur", 0)
            máx = profile.get("hunger_max", 10)
            new = min(cur + db_item["hunger_restore"], máx)
            profile["hunger_cur"] = new
            effects.append(f"🍖 Hlad `{cur}` → `{new}` (+{new - cur})")

        if db_item.get("hp_restore", 0):
            cur = profile.get("hp_cur", 0)
            máx = profile.get("hp_max", 50)
            new = min(cur + db_item["hp_restore"], máx)
            profile["hp_cur"] = new
            effects.append(f"❤️ HP `{cur}` → `{new}` (+{new - cur})")

        if db_item.get("mana_restore", 0):
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            máx = profile.get("mana_max", 20)
            new = min(cur + db_item["mana_restore"], máx)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (+{new - cur})")

        _save_profiles(profiles)
        effect_str = "\n".join(effects) if effects else ""
        use_text = db_item.get("lore_drop") or db_item.get("desc", "…")
        embed = discord.Embed(
            title=f"✨ {db_item['name']}",
            description=f"*{use_text}*" + (f"\n\n{effect_str}" if effect_str else ""),
            color=0xf0a500,
        )
        embed.set_footer(text=f"{interaction.user.display_name}  ·  item použit a odebrán")
        await interaction.followup.send(embed=embed)

    # ── /inv-inspect ──────────────────────────────────────────────────────────
    @app_commands.command(name="inv-inspect",
                          description="Zobrazí detail registrovaného itemu.")
    @app_commands.describe(item="ID nebo název itemu.")
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_inspect(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer(ephemeral=True)
        items_db = _load_items()
        profile  = _get_profile(interaction.user.id)
        embed    = _build_inspect_embed(item, items_db, profile)
        if not embed:
            await interaction.followup.send(
                f"❌ Item `{item}` není v databázi.")
            return
        await interaction.followup.send(embed=embed)

    # ── /equip ────────────────────────────────────────────────────────────────
    @app_commands.command(name="equip", description="Equipne item ze svého inventáře.")
    @app_commands.describe(
        item="Item k equipnutí.",
        slot="Slot (volitelné — pro prsteny/amulety/zbraně).",
    )
    @app_commands.autocomplete(item=_ac_equippable_item, slot=_ac_equip_slot)
    async def equip(self, interaction: discord.Interaction,
                    item: str, slot: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        ok, msg  = _equip_item(profile, item, slot, items_db, str(interaction.user.id))
        if ok:
            _save_profiles(profiles)
            # Achievement: plná výbava (všechny sloty obsazené)
            await _check_full_equip(interaction.user, interaction.channel, profile)
        await interaction.followup.send(f"{'✅' if ok else '❌'} {msg}")

    # ── /unequip ──────────────────────────────────────────────────────────────
    @app_commands.command(name="unequip", description="Sundá item ze slotu.")
    @app_commands.describe(slot="Slot k uvolnění.")
    @app_commands.autocomplete(slot=_ac_equipped_slot)
    async def unequip(self, interaction: discord.Interaction, slot: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        if slot not in profile["equipment"]:
            await interaction.followup.send(
                f"❌ Slot `{slot}` neexistuje nebo není aktivní.")
            return
        items_db = _load_items()
        ok, msg  = _unequip_slot(profile, slot, items_db)
        if ok:
            _save_profiles(profiles)
        await interaction.followup.send(f"{'✅' if ok else '❌'} {msg}")

    @app_commands.command(
        name="inv-ammo",
        description="Uprav počet munice v Toulci (např. −1 po výstřelu).")
    @app_commands.describe(
        item="Munice z Toulce.",
        number="Změna počtu: záporné odebere (−1 po výstřelu), kladné přidá.",
    )
    @app_commands.autocomplete(item=_ac_ammo_item)
    async def inv_ammo(self, interaction: discord.Interaction,
                       item: str, number: int = -1):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil. Nejdřív `/start`.")
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        _sort_ammo_to_toulec(profile, items_db)   # munice do Toulce (pokud ho hráč má)
        # Munice je v Toulci (pokud ho vlastní), jinak zůstává v inventáři
        if _owns_storage_item(profile, TOULEC_ITEM_ID):
            store = profile.setdefault("storages", {}).setdefault(TOULEC_ITEM_ID, [])
        else:
            store = profile["inventory"]

        if items_db.get(item, {}).get("category") != "náboje":
            nm = items_db.get(item, {}).get("name", item)
            await interaction.followup.send(f"❌ **{nm}** není munice (kategorie *náboje*).")
            return

        def _count() -> int:
            return sum(e.get("qty", 1) for e in store
                       if e.get("type") == "registered" and e.get("id") == item)

        have = _count()
        if have <= 0:
            nm = items_db.get(item, {}).get("name", item)
            await interaction.followup.send(f"❌ **{nm}** nemáš.")
            return

        if number < 0:
            _remove_from_inventory(store, item, min(have, -number))
        elif number > 0:
            _add_to_inventory(store, item, number)

        have_after = _count()
        _save_profiles(profiles)
        name  = items_db.get(item, {}).get("name", item)
        if have_after <= 0:
            await interaction.followup.send(f"🏹 **{name}** došla — odebrána z Toulce.")
        else:
            delta = f"−{abs(number)}" if number < 0 else f"+{number}"
            await interaction.followup.send(f"🏹 **{name}**  ×{have_after}  ({delta})")

    # ══════════════════════════════════════════════════════════════════════════
    # DATABASE COMMANDY (DM only)
    # ══════════════════════════════════════════════════════════════════════════

    @inv_db.command(name="add", description="[DM] Přidá item do databáze.")
    @app_commands.describe(
        item_id="Konzolové ID (snake_case, např. mec_ocisty).",
        name="Zobrazované jméno.",
        category="Kategorie itemu.",
        slot="Kam lze equipnout (prázdné = nelze).",
        hand_type="Jednoruční / obouruční (jen pro zbraně).",
        atk="Útočná hodnota — číslo nebo kostky (12, 1d8, 4d6, 2d6+1d4).",
        defense="Obranná hodnota (např. 3).",
        hunger_restore="Kolik hladu obnoví při použití.",
        hp_restore="Kolik HP obnoví při použití (lektvary života).",
        mana_restore="Kolik many obnoví při použití (lektvary many).",
        mana_cost="Kolik many spotřebuje při použití (svitky, kouzla).",
        requires="Požadavky na staty (např. STR:2 INS:1 CHA:3).",
        stackable="Lze stackovat (výchozí: False).",
        consumable="Po použití se zničí (výchozí: False).",
        hp_bonus="Bonus k max HP při equipu (trvalý dokud equipnuto).",
        mana_bonus="Bonus k max maně při equipu (trvalý dokud equipnuto).",
        stat_bonus="Bonusy ke statům při equipu, např. STR:3 DEX:1 (0 = odebrat).",
        desc="Popis, lore, perky — volný text.",
        lore_drop="Narativní hláška zobrazená při použití itemu (místo desc).",
        required_perk="Perk nutný pro equipnutí (autocomplete: Výzbroj perky).",
        storage_capacity="Pokud je item úložiště: počet slotů (0 = neúložiště, -1 = neomezeno jako BoH).",
        storage_emoji="Emoji úložiště zobrazené na tlačítku /inv (např. 🎒).",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES],
        slot=[
            app_commands.Choice(name="Zbraň",     value="weapon"),
            app_commands.Choice(name="Hlava",     value="helmet"),
            app_commands.Choice(name="Zbroj",     value="armor"),
            app_commands.Choice(name="Rukavice",  value="gloves"),
            app_commands.Choice(name="Kalhoty",   value="kalhoty"),
            app_commands.Choice(name="Boty",      value="boots"),
            app_commands.Choice(name="Plášť",     value="cloak"),
            app_commands.Choice(name="Opasek",    value="belt"),
            app_commands.Choice(name="Prsten",    value="ring"),
            app_commands.Choice(name="Amulet",    value="amulet"),
            app_commands.Choice(name="—",         value="none"),
        ],
        hand_type=[
            app_commands.Choice(name="Jednoruční", value="one"),
            app_commands.Choice(name="Obouruční",  value="two"),
        ],
    )
    @app_commands.autocomplete(required_perk=_ac_vyzboj_perk,
                               requires=_ac_requires, stat_bonus=_ac_requires)
    async def inv_db_add(
        self, interaction: discord.Interaction,
        item_id: str, name: str, category: str,
        slot: str = "none", hand_type: Optional[str] = None,
        atk: str = "", defense: int = 0,
        hunger_restore: int = 0, hp_restore: int = 0,
        mana_restore: int = 0, mana_cost: int = 0,
        requires: Optional[str] = None,
        stackable: bool = False, consumable: bool = False,
        hp_bonus: Optional[int] = None, mana_bonus: Optional[int] = None,
        stat_bonus: Optional[str] = None,
        desc: Optional[str] = None,
        lore_drop: Optional[str] = None,
        required_perk: Optional[str] = None,
        storage_capacity: int = 0,
        storage_emoji: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM může spravovat databázi.")
            return
        item_id  = item_id.lower().replace(" ", "_")
        items_db = _load_items()
        if item_id in items_db:
            await interaction.followup.send(
                f"❌ Item `{item_id}` již existuje. Použij `/inv-db edit`.")
            return
        # "weapon" je display alias pro "hand_l" — normalizuj před uložením
        resolved_slot = None if slot == "none" else ("hand_l" if slot == "weapon" else slot)
        item: dict = {
            "name":       name,
            "category":   category,
            "slot":       resolved_slot,
            "stackable":  stackable,
            "consumable": consumable,
        }
        if hand_type:          item["hand_type"]      = hand_type
        if atk:
            atk = atk.strip()
            if not _valid_attack(atk):
                await interaction.followup.send(
                    "❌ Neplatná útočná hodnota. Použij číslo nebo kostky "
                    "(např. `12`, `1d8`, `4d6`, `2d6+1d4`).")
                return
            item["atk"] = atk
        if defense > 0:        item["def"]            = defense
        if hunger_restore > 0: item["hunger_restore"] = hunger_restore
        if hp_restore > 0:     item["hp_restore"]     = hp_restore
        if mana_restore > 0:   item["mana_restore"]   = mana_restore
        if mana_cost > 0:      item["mana_cost"]      = mana_cost
        if desc:               item["desc"]           = desc
        if lore_drop:          item["lore_drop"]      = lore_drop
        if requires:
            req_dict = _parse_requires(requires)
            if req_dict:       item["requires"]       = req_dict
        equip_bonus: dict = {}
        if hp_bonus:   equip_bonus["hp_max"]   = hp_bonus
        if mana_bonus: equip_bonus["mana_max"] = mana_bonus
        if stat_bonus:
            for k, v in _parse_requires(stat_bonus).items():
                if v != 0:
                    # SVETLO/TEMNOTA/ROVNOVAHA → vliv_*, ostatní = staty
                    equip_bonus[VLIV_REQUIRES.get(k, k)] = v
        if equip_bonus:    item["equip_bonus"]    = equip_bonus
        if required_perk:  item["required_perk"]  = required_perk
        # Storage item — capacity 0 = běžný item, -1 = unlimited (BoH styl)
        if storage_capacity != 0:
            storage_def: dict = {"capacity": None if storage_capacity < 0 else storage_capacity}
            if storage_emoji:
                storage_def["emoji"] = storage_emoji
            item["storage"] = storage_def
        items_db[item_id] = item
        _save_items(items_db)
        storage_note = ""
        if storage_capacity != 0:
            cap_str = "neomezené ∞" if storage_capacity < 0 else f"{storage_capacity} slotů"
            storage_note = f"\n📦 Úložiště: {cap_str}"
        await interaction.followup.send(
            f"✅ Item **{name}** (`{item_id}`) přidán do databáze.{storage_note}")

    @inv_db.command(name="edit", description="[DM] Upraví existující item v databázi.")
    @app_commands.describe(
        item_id="ID itemu k úpravě.",
        name="Nové jméno (prázdné = beze změny).",
        category="Nová kategorie (prázdné = beze změny).",
        slot="Nový equip slot (prázdné = beze změny).",
        hand_type="Jednoruční/obouruční, nebo — pro odebrání (prázdné = beze změny).",
        desc="Nový popis (prázdné = beze změny).",
        atk="Útočná hodnota — číslo/kostky (např. 4d6); prázdné=beze změny, 0=odebrat.",
        defense="Nová obranná hodnota (0 = odebrat).",
        hunger_restore="Obnova hladu při použití (0 = odebrat).",
        hp_restore="Obnova HP při použití (0 = odebrat).",
        mana_restore="Obnova many při použití (0 = odebrat).",
        mana_cost="Cena v maně při použití (0 = odebrat).",
        requires="Nové požadavky (např. STR:2 INS:1 · prázdné = beze změny).",
        consumable="Změnit consumable příznak.",
        stackable="Změnit stackable příznak.",
        hp_bonus="Bonus k max HP při equipu (0 = odebrat).",
        mana_bonus="Bonus k max maně při equipu (0 = odebrat).",
        stat_bonus="Bonusy ke statům při equipu, např. STR:3 DEX:1 (stat:0 = odebrat).",
        lore_drop="Narativní hláška při použití (prázdné = beze změny · 'clear' = odebrat).",
        required_perk="Perk nutný pro equipnutí ('clear' = odebrat).",
        storage_capacity="Úložiště: počet slotů (0 = beze změny, -1 = ∞, 'clear' přes storage_clear).",
        storage_emoji="Emoji úložiště na tlačítku /inv.",
        storage_clear="Odebere storage vlastnost (item přestane být úložiště).",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES],
        slot=[
            app_commands.Choice(name="Zbraň",              value="weapon"),
            app_commands.Choice(name="Hlava",              value="helmet"),
            app_commands.Choice(name="Zbroj",              value="armor"),
            app_commands.Choice(name="Rukavice",           value="gloves"),
            app_commands.Choice(name="Kalhoty",            value="kalhoty"),
            app_commands.Choice(name="Boty",               value="boots"),
            app_commands.Choice(name="Plášť",              value="cloak"),
            app_commands.Choice(name="Opasek",             value="belt"),
            app_commands.Choice(name="Prsten",             value="ring"),
            app_commands.Choice(name="Amulet",             value="amulet"),
            app_commands.Choice(name="— (nelze equipnout)", value="none"),
        ],
        hand_type=[
            app_commands.Choice(name="Jednoruční",  value="one"),
            app_commands.Choice(name="Obouruční",   value="two"),
            app_commands.Choice(name="— (odebrat)", value="clear"),
        ],
    )
    @app_commands.autocomplete(item_id=_ac_database_item, required_perk=_ac_vyzboj_perk,
                               requires=_ac_requires, stat_bonus=_ac_requires)
    async def inv_db_edit(
        self, interaction: discord.Interaction,
        item_id: str,
        name: Optional[str] = None,
        category: Optional[str] = None,
        slot: Optional[str] = None,
        hand_type: Optional[str] = None,
        desc: Optional[str] = None,
        lore_drop: Optional[str] = None,
        atk: Optional[str] = None,
        defense: Optional[int] = None,
        hunger_restore: Optional[int] = None,
        hp_restore: Optional[int] = None,
        mana_restore: Optional[int] = None,
        mana_cost: Optional[int] = None,
        requires: Optional[str] = None,
        consumable: Optional[bool] = None,
        stackable: Optional[bool] = None,
        hp_bonus: Optional[int] = None,
        mana_bonus: Optional[int] = None,
        stat_bonus: Optional[str] = None,
        required_perk: Optional[str] = None,
        storage_capacity: Optional[int] = None,
        storage_emoji: Optional[str] = None,
        storage_clear: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM může spravovat databázi.")
            return
        items_db = _load_items()
        item     = items_db.get(item_id)
        if not item:
            await interaction.followup.send(f"❌ Item `{item_id}` neexistuje.")
            return
        if name       is not None: item["name"]       = name
        if category   is not None: item["category"]   = category
        if slot       is not None:
            # "weapon" je alias pro "hand_l", "none" = nelze equipnout
            item["slot"] = None if slot == "none" else ("hand_l" if slot == "weapon" else slot)
        if hand_type  is not None:
            if hand_type == "clear": item.pop("hand_type", None)
            else:                    item["hand_type"] = hand_type
        if desc       is not None: item["desc"]       = desc
        if lore_drop  is not None:
            if lore_drop.lower() == "clear": item.pop("lore_drop", None)
            else:                            item["lore_drop"] = lore_drop
        if consumable is not None: item["consumable"] = consumable
        if stackable  is not None: item["stackable"]  = stackable
        if atk is not None:
            atk = atk.strip()
            if atk in ("", "0", "clear"):
                item.pop("atk", None)
            elif _valid_attack(atk):
                item["atk"] = atk
            else:
                await interaction.followup.send(
                    "❌ Neplatná útočná hodnota. Použij číslo nebo kostky "
                    "(např. `12`, `1d8`, `4d6`).")
                return
        if defense is not None:
            if defense > 0: item["def"] = defense
            else:           item.pop("def", None)

        for key, val in [
            ("hunger_restore", hunger_restore),
            ("hp_restore",     hp_restore),
            ("mana_restore",   mana_restore),
            ("mana_cost",      mana_cost),
        ]:
            if val is not None:
                if val > 0: item[key] = val
                else:       item.pop(key, None)

        if requires is not None:
            req_dict = _parse_requires(requires)
            if req_dict: item["requires"] = req_dict
            else:        item.pop("requires", None)
        if hp_bonus is not None or mana_bonus is not None or stat_bonus is not None:
            eb = item.setdefault("equip_bonus", {})
            if hp_bonus is not None:
                if hp_bonus != 0: eb["hp_max"]   = hp_bonus
                else:             eb.pop("hp_max", None)
            if mana_bonus is not None:
                if mana_bonus != 0: eb["mana_max"] = mana_bonus
                else:               eb.pop("mana_max", None)
            if stat_bonus is not None:
                for k, v in _parse_requires(stat_bonus).items():
                    bk = VLIV_REQUIRES.get(k, k)   # SVETLO/TEMNOTA/ROVNOVAHA → vliv_*
                    if v != 0: eb[bk] = v
                    else:      eb.pop(bk, None)
            if not eb:
                item.pop("equip_bonus", None)
        if required_perk is not None:
            if required_perk.lower() == "clear": item.pop("required_perk", None)
            else:                                 item["required_perk"] = required_perk
        # Storage vlastnost
        if storage_clear:
            item.pop("storage", None)
        elif storage_capacity is not None or storage_emoji is not None:
            stor = item.setdefault("storage", {"capacity": 0})
            if storage_capacity is not None:
                stor["capacity"] = None if storage_capacity < 0 else storage_capacity
            if storage_emoji is not None:
                stor["emoji"] = storage_emoji
        _save_items(items_db)
        await interaction.followup.send(
            f"✅ Item **{item['name']}** (`{item_id}`) upraven.")

    @inv_db.command(name="remove", description="[DM] Odebere item z databáze.")
    @app_commands.describe(item_id="ID itemu k odebrání.")
    @app_commands.autocomplete(item_id=_ac_database_item)
    async def inv_db_remove(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM může spravovat databázi.")
            return
        items_db = _load_items()
        item = items_db.pop(item_id, None)
        if not item:
            await interaction.followup.send(f"❌ Item `{item_id}` neexistuje.")
            return
        _save_items(items_db)
        await interaction.followup.send(f"🗑️ Item **{item['name']}** (`{item_id}`) odebrán z databáze.")

    @inv_db.command(name="find", description="Prohledá databázi itemů.")
    @app_commands.describe(query="Název nebo ID itemu.")
    @app_commands.autocomplete(query=_ac_database_item)
    async def inv_db_find(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)
        items_db = _load_items()
        profile  = _get_profile(interaction.user.id)
        embed    = _build_inspect_embed(query, items_db, profile)
        if not embed:
            await interaction.followup.send(f"❌ Item `{query}` není v databázi.")
            return
        await interaction.followup.send(embed=embed)

    @inv_db.command(name="list", description="Vypíše všechny itemy v databázi.")
    @app_commands.describe(category="Filtr dle kategorie (volitelné).")
    @app_commands.choices(category=[
        app_commands.Choice(name=c, value=c) for c in CATEGORIES
    ])
    async def inv_db_list(self, interaction: discord.Interaction,
                          category: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        items_db = _load_items()
        filtered = {
            k: v for k, v in items_db.items()
            if not category or v.get("category") == category
        }
        if not filtered:
            await interaction.followup.send("Žádné itemy v databázi.")
            return

        by_cat: dict[str, list] = {}
        for k, v in filtered.items():
            cat = v.get("category", "ostatní")
            by_cat.setdefault(cat, []).append((k, v))

        embed = discord.Embed(title="📖  Databáze itemů", color=EMBED_COLOR)
        for cat, items in by_cat.items():
            lines = []
            for iid, iv in items:
                tags = []
                if iv.get("consumable"): tags.append("consumable")
                if iv.get("stackable"):  tags.append("stackable")
                tag_str = f"  *{', '.join(tags)}*" if tags else ""
                lines.append(f"**{iv['name']}**  `{iid}`{tag_str}")
            embed.add_field(name=cat, value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # STORAGE — univerzální přesun (hráč)
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="storage-move",
                          description="Přesune item mezi úložišti (inventář, BoH, batoh…).")
    @app_commands.describe(
        odkud="Zdrojové úložiště.",
        item="Item ze zdrojového úložiště.",
        kam="Cílové úložiště.",
        qty="Množství (výchozí: 1).",
    )
    @app_commands.autocomplete(odkud=_ac_storage_key, kam=_ac_storage_key,
                               item=_make_ac_storage_items("odkud"))
    async def storage_move(self, interaction: discord.Interaction,
                           odkud: str, item: str, kam: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)
        items_db = _load_items()

        avail = _available_storages(profile, items_db)
        if odkud not in avail or kam not in avail:
            await interaction.followup.send("❌ Neplatné úložiště.")
            return
        if odkud == kam:
            await interaction.followup.send("❌ Zdroj a cíl jsou stejné.")
            return

        src = _ensure_storage(profile, odkud)
        dst = _ensure_storage(profile, kam)

        # Ověř kapacitu cíle (jen pro itemy které zabírají sloty)
        src_entry = _find_inv_entry(src, item)
        if not src_entry or src_entry.get("qty", 1) < qty:
            await interaction.followup.send(f"❌ Nemáš dost kusů **{item}** v `{odkud}`.")
            return

        slot_cost = _entry_slot_cost({"type": "registered", "id": item, "qty": qty}, items_db) \
            if src_entry["type"] == "registered" else 0
        cap = _storage_capacity(kam, profile, items_db)
        if cap is not None and slot_cost > 0:
            if _count_slots(dst, items_db) + slot_cost > cap:
                visual = _storage_visual(kam, items_db)
                await interaction.followup.send(
                    f"❌ **{visual['label']}** nemá dost místa "
                    f"({_count_slots(dst, items_db)}/{cap}, potřebuješ +{slot_cost}).")
                return

        # Přesun
        key = src_entry["id"] if src_entry["type"] == "registered" else src_entry.get("name", item)
        if src_entry["type"] == "registered":
            _remove_from_inventory(src, key, qty)
            _add_to_inventory(dst, key, qty)
        else:
            src.remove(src_entry)
            dst.append(src_entry)

        _save_profiles(profiles)
        name    = items_db.get(key, {}).get("name", key)
        v_from  = _storage_visual(odkud, items_db)
        v_to    = _storage_visual(kam, items_db)
        qty_str = f" ×{qty}" if qty > 1 else ""
        await interaction.followup.send(
            f"✅ **{name}**{qty_str} přesunuto: {v_from['emoji']} {v_from['label']} → {v_to['emoji']} {v_to['label']}.")

    # ══════════════════════════════════════════════════════════════════════════
    # BAG OF HOLDING — hráčské příkazy
    # ══════════════════════════════════════════════════════════════════════════

    @inv_boh_note.command(name="add",
                          description="Přidá poznámku do sekce Ostatní v Bag of Holding.")
    @app_commands.describe(text="Text poznámky — předmět, nález, informace...")
    async def inv_boh_note_add(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_boh_field(profile)
        if not _has_boh(profile):
            await interaction.followup.send("❌ Nevlastníš **Bag of Holding**.")
            return
        profile["boh_notes"].append(text)
        line_num = len(profile["boh_notes"])
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Přidáno do 👜 BoH jako řádek **{line_num}**: *{text}*")

    @inv_boh_note.command(name="edit",
                          description="Upraví poznámku v sekci Ostatní Bag of Holding.")
    @app_commands.describe(cislo="Číslo řádku (viz /inv → BoH → Ostatní).", text="Nový text.")
    async def inv_boh_note_edit(self, interaction: discord.Interaction,
                                cislo: int, text: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_boh_field(profile)
        notes = profile["boh_notes"]
        if cislo < 1 or cislo > len(notes):
            await interaction.followup.send(
                f"❌ Řádek {cislo} neexistuje. Máš {len(notes)} poznámek v BoH.")
            return
        old              = notes[cislo - 1]
        notes[cislo - 1] = text
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ BoH řádek **{cislo}** upraven.\n~~{old}~~ → *{text}*")

    @inv_boh_note.command(name="remove",
                          description="Odebere poznámku ze sekce Ostatní Bag of Holding.")
    @app_commands.describe(cislo="Číslo řádku (viz /inv → BoH → Ostatní).")
    async def inv_boh_note_remove(self, interaction: discord.Interaction, cislo: int):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_boh_field(profile)
        notes = profile["boh_notes"]
        if cislo < 1 or cislo > len(notes):
            await interaction.followup.send(
                f"❌ Řádek {cislo} neexistuje. Máš {len(notes)} poznámek v BoH.")
            return
        removed = notes.pop(cislo - 1)
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ BoH řádek **{cislo}** odebrán: ~~{removed}~~")

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN COMMANDY (DM only)
    # ══════════════════════════════════════════════════════════════════════════

    @inv_admin.command(name="add", description="[DM] Přidá item hráči.")
    @app_commands.describe(
        member="Hráč.",
        item="ID registrovaného itemu nebo volný text (půjde do Ostatní).",
        qty="Množství.",
        note="Přepíše text poznámky pro volné itemy.",
    )
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_admin_add(self, interaction: discord.Interaction,
                            member: discord.Member, item: str,
                            qty: int = 1, note: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        items_db  = _load_items()
        if item in items_db:
            name = items_db[item]["name"]
            _add_to_inventory(profile["inventory"], item, qty)
        else:
            # Volný item → do sekce Ostatní jako poznámka
            name      = note or item
            inv_notes = _inv_notes(profile)
            for _ in range(qty):
                inv_notes.append(name)
        _sort_ammo_to_toulec(profile, items_db)   # munice rovnou do Toulce
        _save_profiles(profiles)
        qty_str = f" ×{qty}" if qty > 1 else ""
        await interaction.followup.send(
            f"✅ Přidáno **{name}**{qty_str} → **{member.display_name}**.")

    @inv_admin.command(name="remove", description="[DM] Odebere registrovaný item hráči.")
    @app_commands.describe(member="Hráč.", item="Název nebo ID.", qty="Množství.")
    async def inv_admin_remove(self, interaction: discord.Interaction,
                               member: discord.Member, item: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        ok = _remove_from_inventory(profile["inventory"], item, qty)
        if not ok:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá dost kusů **{item}**.")
            return
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Odebráno **{item}** ×{qty} od **{member.display_name}**.")

    @inv_admin.command(name="slots", description="[DM] Nastaví počet prstenových slotů hráči.")
    @app_commands.describe(
        member="Hráč.",
        slot_type="ring (amulet je teď pevně jeden).",
        count="Počet slotů (1–6).",
    )
    @app_commands.choices(slot_type=[
        app_commands.Choice(name="Prsteny", value="ring"),
    ])
    async def inv_admin_slots(self, interaction: discord.Interaction,
                              member: discord.Member, slot_type: str, count: int):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if slot_type != "ring":
            await interaction.followup.send("❌ Nastavovat lze jen prstenové sloty (amulet je pevně jeden).")
            return
        if count < 1 or count > 6:
            await interaction.followup.send("❌ Počet slotů musí být 1–6.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        profile["ring_slots"] = count
        for i in range(1, count + 1):
            profile["equipment"].setdefault(f"ring_{i}", None)
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ **{member.display_name}** má teď {count}× prsten slot.")


    @inv_admin.command(name="storage-remove",
                       description="[DM] Odebere item z konkrétního úložiště hráče.")
    @app_commands.describe(
        member="Hráč.",
        item="ID itemu.",
        storage="Úložiště (id storage itemu nebo 'inventory'/'bag_of_holding').",
        qty="Množství.",
    )
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_admin_storage_remove(self, interaction: discord.Interaction,
                                       member: discord.Member, item: str,
                                       storage: str = "inventory", qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)
        items_db = _load_items()

        avail = _available_storages(profile, items_db)
        if storage not in avail:
            await interaction.followup.send(
                f"❌ Hráč nemá úložiště `{storage}`. Dostupná: {', '.join(avail)}")
            return

        target = _ensure_storage(profile, storage)
        ok = _remove_from_inventory(target, item, qty)
        if not ok:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá dost kusů **{item}** v `{storage}`.")
            return
        _save_profiles(profiles)
        visual = _storage_visual(storage, items_db)
        name   = items_db.get(item, {}).get("name", item)
        await interaction.followup.send(
            f"✅ Odebráno **{name}** ×{qty} z {visual['emoji']} {visual['label']} — **{member.display_name}**.")

    @inv_admin.command(name="storage-move",
                       description="[DM] Přesune item mezi úložišti hráče (inventář, BoH, batoh…).")
    @app_commands.describe(
        member="Hráč.",
        odkud="Zdrojové úložiště.",
        item="ID itemu ze zdroje.",
        kam="Cílové úložiště.",
        qty="Množství.",
    )
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_admin_storage_move(self, interaction: discord.Interaction,
                                     member: discord.Member, odkud: str,
                                     item: str, kam: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)
        items_db = _load_items()

        avail = _available_storages(profile, items_db)
        if odkud not in avail or kam not in avail:
            await interaction.followup.send(
                f"❌ Neplatné úložiště. Dostupná: {', '.join(avail)}")
            return
        if odkud == kam:
            await interaction.followup.send("❌ Zdroj a cíl jsou stejné.")
            return

        src = _ensure_storage(profile, odkud)
        dst = _ensure_storage(profile, kam)

        src_entry = _find_inv_entry(src, item)
        if not src_entry or src_entry.get("qty", 1) < qty:
            await interaction.followup.send(
                f"❌ Hráč nemá dost kusů **{item}** v `{odkud}`.")
            return

        slot_cost = _entry_slot_cost({"type": "registered", "id": item, "qty": qty}, items_db) \
            if src_entry["type"] == "registered" else 0
        cap = _storage_capacity(kam, profile, items_db)
        if cap is not None and slot_cost > 0:
            if _count_slots(dst, items_db) + slot_cost > cap:
                visual = _storage_visual(kam, items_db)
                await interaction.followup.send(
                    f"❌ **{visual['label']}** nemá dost místa "
                    f"({_count_slots(dst, items_db)}/{cap}, potřebuješ +{slot_cost}).")
                return

        key = src_entry["id"] if src_entry["type"] == "registered" else src_entry.get("name", item)
        if src_entry["type"] == "registered":
            _remove_from_inventory(src, key, qty)
            _add_to_inventory(dst, key, qty)
        else:
            src.remove(src_entry)
            dst.append(src_entry)

        _save_profiles(profiles)
        name    = items_db.get(key, {}).get("name", key)
        v_from  = _storage_visual(odkud, items_db)
        v_to    = _storage_visual(kam, items_db)
        qty_str = f" ×{qty}" if qty > 1 else ""
        await interaction.followup.send(
            f"✅ **{name}**{qty_str} přesunuto: {v_from['emoji']} {v_from['label']} → "
            f"{v_to['emoji']} {v_to['label']} — **{member.display_name}**.")

    # ══════════════════════════════════════════════════════════════════════════
    # STORAGE — admin
    # ══════════════════════════════════════════════════════════════════════════

    @inv_admin.command(name="storage-give",
                       description="[DM] Dá hráči úložný item (batoh, brašnu, BoH…).")
    @app_commands.describe(member="Hráč.", storage_item="ID storage itemu z databáze.")
    @app_commands.autocomplete(storage_item=_ac_database_item)
    async def inv_admin_storage_give(self, interaction: discord.Interaction,
                                     member: discord.Member, storage_item: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        items_db = _load_items()
        if not _is_storage_item(storage_item, items_db):
            await interaction.followup.send(
                f"❌ `{storage_item}` není storage item (chybí pole `storage` v DB).")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)

        if _owns_storage_item(profile, storage_item):
            await interaction.followup.send(
                f"❌ **{member.display_name}** už tento storage vlastní (1 kus od typu).")
            return

        # Přidej item do inventáře a založ jeho storage
        _add_to_inventory(profile["inventory"], storage_item, 1)
        _ensure_storage(profile, storage_item)
        _save_profiles(profiles)

        visual = _storage_visual(storage_item, items_db)
        cap    = _storage_capacity(storage_item, profile, items_db)
        cap_str = "∞" if cap is None else str(cap)
        await interaction.followup.send(
            f"✅ **{member.display_name}** dostal {visual['emoji']} **{visual['label']}** "
            f"(kapacita: {cap_str}). Úložiště je připraveno.")

    @inv_admin.command(name="storage-add",
                       description="[DM] Přidá item přímo do konkrétního úložiště hráče.")
    @app_commands.describe(
        member="Hráč.",
        item="ID itemu z databáze.",
        storage="Cílové úložiště (id storage itemu nebo 'inventory'/'bag_of_holding').",
        qty="Množství.",
    )
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_admin_storage_add(self, interaction: discord.Interaction,
                                    member: discord.Member, item: str,
                                    storage: str = "inventory", qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)
        items_db = _load_items()
        if item not in items_db:
            await interaction.followup.send(f"❌ Item `{item}` není v databázi.")
            return

        avail = _available_storages(profile, items_db)
        if storage not in avail:
            await interaction.followup.send(
                f"❌ Hráč nemá úložiště `{storage}`. Dostupná: {', '.join(avail)}")
            return

        target_stor = _ensure_storage(profile, storage)

        # Kapacita
        slot_cost = _entry_slot_cost({"type": "registered", "id": item, "qty": qty}, items_db)
        cap = _storage_capacity(storage, profile, items_db)
        if cap is not None and slot_cost > 0:
            if _count_slots(target_stor, items_db) + slot_cost > cap:
                await interaction.followup.send(
                    f"❌ Úložiště je plné ({_count_slots(target_stor, items_db)}/{cap}).")
                return

        _add_to_inventory(target_stor, item, qty)
        _save_profiles(profiles)
        visual = _storage_visual(storage, items_db)
        name   = items_db[item]["name"]
        await interaction.followup.send(
            f"✅ Přidáno **{name}** ×{qty} do {visual['emoji']} {visual['label']} — **{member.display_name}**.")

    @inv_admin.command(name="storage-drop",
                       description="[DM] Odebere hráči storage item i s obsahem.")
    @app_commands.describe(member="Hráč.", storage_item="ID storage itemu.")
    @app_commands.autocomplete(storage_item=_ac_database_item)
    async def inv_admin_storage_drop(self, interaction: discord.Interaction,
                                     member: discord.Member, storage_item: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        _migrate_storages(profile)
        items_db = _load_items()

        # Odeber item ze všech storage + smaž jeho storage instanci s obsahem
        for stor in profile["storages"].values():
            _remove_from_inventory(stor, storage_item, 999)
        for slot, v in profile.get("equipment", {}).items():
            if v == storage_item:
                profile["equipment"][slot] = None
        _drop_storage(profile, storage_item)
        _save_profiles(profiles)

        visual = _storage_visual(storage_item, items_db)
        await interaction.followup.send(
            f"🗑️ **{member.display_name}** ztratil {visual['emoji']} **{visual['label']}** "
            f"i s celým obsahem.")


async def setup(bot):
    await bot.add_cog(Inventory(bot))