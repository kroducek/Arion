"""
characters.py — registr postav + resolver aktivní postavy (multi-character systém).

Cesta: src/database/characters.py
POZOR: přidej do src/utils/paths.py konstantu:
       CHARACTERS = data("characters.json")

═══════════════════════════════════════════════════════════════════════════════
characters.json
{
  "<uid>": {
    "active": "1",
    "chars": {
      "1": {"name": "Kaiser", "created_at": 1710000000},
      "2": {"name": "Vexx",   "created_at": 1710000100}
    }
  }
}
═══════════════════════════════════════════════════════════════════════════════

KLÍČOVÁNÍ DAT:
  • Per-postava soubory (profiles, economy-gold, diaries, player_perks,
    quest_log, reputation-inner, takedowns, combat_state) se klíčují přes
    pkey(uid) → "<uid>:<slot>".
  • Účtové soubory (silver, stardust, achievements, guilds, parties,
    roll_stats, minihry) zůstávají na holém str(uid) — NESAHAT.

Resolver vrací slot "1" i pro hráče bez záznamu, takže per-postava data
mají vždy tvar "<uid>:<slot>" (po migraci legacy data sedí na "<uid>:1").
"""
import time
from src.utils.paths import CHARACTERS
from src.utils.json_utils import load_json, save_json

# Max počet postav na účet (zatím 2 — lze později zvednout).
MAX_CHARS = 2

# Délkový limit jména postavy.
MAX_NAME_LEN = 32


# ══════════════════════════════════════════════════════════════════════════════
# Interní práce se souborem
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    return load_json(CHARACTERS, default={})

def _save(data: dict):
    save_json(CHARACTERS, data)


# ══════════════════════════════════════════════════════════════════════════════
# RESOLVER  (tohle importují všechny per-postava moduly)
# ══════════════════════════════════════════════════════════════════════════════

def get_active_slot(uid) -> str:
    """Slot aktivní postavy ('1'/'2'). Default '1' i bez záznamu."""
    rec = _load().get(str(uid))
    if not rec:
        return "1"
    return str(rec.get("active", "1"))

def pkey(uid) -> str:
    """
    Datový klíč AKTIVNÍ postavy: '<uid>:<slot>'.
    Tohle nahrazuje str(uid) na všech per-postava místech.
    """
    return f"{uid}:{get_active_slot(uid)}"

def ckey(uid, slot) -> str:
    """Datový klíč KONKRÉTNÍHO slotu (pro onboarding nové postavy / purge)."""
    return f"{uid}:{slot}"


# ══════════════════════════════════════════════════════════════════════════════
# Dotazy
# ══════════════════════════════════════════════════════════════════════════════

def get_record(uid) -> dict | None:
    return _load().get(str(uid))

def list_chars(uid) -> dict:
    """Vrátí {slot: {name, created_at}} pro daný účet (může být prázdné)."""
    rec = _load().get(str(uid))
    return rec.get("chars", {}) if rec else {}

def get_char(uid, slot) -> dict | None:
    return list_chars(uid).get(str(slot))

def char_count(uid) -> int:
    return len(list_chars(uid))

def has_characters(uid) -> bool:
    return bool(list_chars(uid))

def active_name(uid) -> str | None:
    """Jméno aktivní postavy — pro přejmenování v guild/party rosteru."""
    rec = _load().get(str(uid))
    if not rec:
        return None
    slot = str(rec.get("active", "1"))
    ch = rec.get("chars", {}).get(slot)
    return ch.get("name") if ch else None


# ══════════════════════════════════════════════════════════════════════════════
# Mutace
# ══════════════════════════════════════════════════════════════════════════════

def _next_slot(chars: dict) -> str | None:
    """Nejnižší volný slot 1..MAX_CHARS, nebo None když je plno."""
    for i in range(1, MAX_CHARS + 1):
        if str(i) not in chars:
            return str(i)
    return None

def create_char(uid, name: str, make_active: bool = True) -> str | None:
    """
    Vytvoří novou postavu. Vrátí slot ('1'/'2') nebo None když je účet plný.
    Pokud make_active (nebo je to první postava), rovnou ji nastaví jako aktivní
    — díky tomu onboarding zapisuje do nového slotu.
    """
    data = _load()
    u = str(uid)
    rec = data.setdefault(u, {"active": "1", "chars": {}})
    slot = _next_slot(rec["chars"])
    if slot is None:
        return None
    rec["chars"][slot] = {
        "name": name.strip()[:MAX_NAME_LEN] or f"Postava {slot}",
        "created_at": int(time.time()),
    }
    if make_active or len(rec["chars"]) == 1:
        rec["active"] = slot
    _save(data)
    return slot

def ensure_active(uid, name: str = None) -> str:
    """
    Zajistí, že účet má aspoň jednu postavu, a vrátí aktivní slot.
    - First-timer (žádný záznam): založí slot '1' (jméno z onboardingu) a nastaví aktivní.
    - Existující záznam + zadané jméno: přejmenuje AKTIVNÍ postavu.
    Volá onboarding, aby i nově vytvořená postava měla záznam v characters.json.
    """
    data = _load()
    u = str(uid)
    rec = data.get(u)
    if not rec or not rec.get("chars"):
        slot = "1"
        nm = (name or "").strip()[:MAX_NAME_LEN] or "Postava 1"
        data[u] = {"active": slot, "chars": {slot: {"name": nm, "created_at": int(time.time())}}}
        _save(data)
        return slot
    slot = str(rec.get("active", "1"))
    if name:
        rec.setdefault("chars", {}).setdefault(slot, {"created_at": int(time.time())})
        rec["chars"][slot]["name"] = name.strip()[:MAX_NAME_LEN] or rec["chars"][slot].get("name", f"Postava {slot}")
        _save(data)
    return slot


def switch_char(uid, slot) -> bool:
    """Přepne aktivní postavu. False když slot neexistuje."""
    data = _load()
    rec = data.get(str(uid))
    slot = str(slot)
    if not rec or slot not in rec.get("chars", {}):
        return False
    rec["active"] = slot
    _save(data)
    return True

def rename_char(uid, slot, name: str) -> bool:
    data = _load()
    rec = data.get(str(uid))
    slot = str(slot)
    if not rec or slot not in rec.get("chars", {}):
        return False
    rec["chars"][slot]["name"] = name.strip()[:MAX_NAME_LEN] or f"Postava {slot}"
    _save(data)
    return True

def delete_char(uid, slot) -> bool:
    """
    Smaže slot z REGISTRU. Pravidlo: musí zůstat aspoň 1 postava.
    Pokud mažeš aktivní, přepne se na nějakou zbývající.

    POZOR: tohle maže jen záznam v characters.json. Vlastní data postavy
    (profil/gold/deník/perky/questy/reputaci na klíči '<uid>:<slot>') musí
    smazat volající (cog), aby nevznikla osiřelá data — viz purge ve fázi 4.
    """
    data = _load()
    rec = data.get(str(uid))
    slot = str(slot)
    if not rec:
        return False
    chars = rec.get("chars", {})
    if slot not in chars:
        return False
    if len(chars) <= 1:
        return False  # min. 1 postava musí zůstat
    del chars[slot]
    if str(rec.get("active")) == slot:
        rec["active"] = next(iter(chars.keys()))
    _save(data)
    return True