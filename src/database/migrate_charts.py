"""
migrate_chars.py — jednorázová, IDEMPOTENTNÍ migrace na multi-character klíče.

Cesta: src/database/migrate_chars.py

Re-klíčuje  uid → uid:1  v per-postava souborech a založí characters.json.
Bezpečné spustit opakovaně — už zmigrované klíče (obsahují ':') přeskočí.

MIGRUJE:
  profiles.json      plochý {uid:{...}}        → {uid:1:{...}}   (vč. memories/stats/inv/equip)
  economy.json       plochý {uid:int}          → {uid:1:int}     (gold)
  diaries.json       plochý {uid:[...]}        → {uid:1:[...]}
  player_perks.json  plochý {uid:{...}}        → {uid:1:{...}}
  reputation.json    {gid:{players:{uid:..}}}  → vnitřní uid → uid:1

NESAHÁ:  silver, stardust, achievements, guilds, parties, roll_stats,
         quest_log (list), takedowns (počítadlo), minihry — účtové/listové/globální.

characters.json:  pro každý uid z profiles založí slot "1" se jménem z profilu
                  (profile['name'], fallback 'Postava 1').

KOLIZE (existuje uid i uid:1 zároveň): bare klíč se NEPŘEPÍŠE ani nesmaže —
nechá se být a započítá se do 'conflicts', ať se nic neztratí. V čisté migraci
(data ještě nezmigrovaná) ke kolizím nedojde.
"""
import time
from src.utils.paths import (
    PROFILES, ECONOMY, DIARIES, PLAYER_PERKS, REPUTATION, CHARACTERS,
)
from src.utils.json_utils import load_json, save_json

DEFAULT_SLOT = "1"


# ══════════════════════════════════════════════════════════════════════════════
# Čisté funkce (bez I/O) — testovatelné
# ══════════════════════════════════════════════════════════════════════════════

def _is_bare_uid(k) -> bool:
    """Holé Discord uid = jen číslice (žádné ':')."""
    return isinstance(k, str) and k.isdigit()


def rekey_flat_dict(data: dict, slot: str = DEFAULT_SLOT):
    """
    Plochý {uid: X} → {uid:slot: X}. Idempotentní, nedestruktivní při kolizi.
    Vrací (new_data, migrated, conflicts).
    """
    if not isinstance(data, dict):
        return data, 0, 0
    migrated = conflicts = 0
    for k in list(data.keys()):
        if not _is_bare_uid(k):
            continue                      # už zmigrované (uid:1) nebo nečíselné → nech
        newk = f"{k}:{slot}"
        if newk in data:
            conflicts += 1                # uid i uid:slot existují → nesahat
            continue
        data[newk] = data.pop(k)
        migrated += 1
    return data, migrated, conflicts


def rekey_reputation_dict(data: dict, slot: str = DEFAULT_SLOT):
    """
    {gid: {players: {uid: ...}}} → vnitřní uid → uid:slot. Idempotentní.
    Vrací (new_data, migrated, conflicts).
    """
    if not isinstance(data, dict):
        return data, 0, 0
    migrated = conflicts = 0
    for gid, gdata in data.items():
        if not isinstance(gdata, dict):
            continue
        players = gdata.get("players")
        if not isinstance(players, dict):
            continue
        for k in list(players.keys()):
            if not _is_bare_uid(k):
                continue
            newk = f"{k}:{slot}"
            if newk in players:
                conflicts += 1
                continue
            players[newk] = players.pop(k)
            migrated += 1
    return data, migrated, conflicts


def build_characters_dict(chars: dict, profiles: dict, slot: str = DEFAULT_SLOT):
    """
    Pro každý klíč v profiles (už ve tvaru 'uid:slot' nebo holé 'uid') založí
    v characters.json záznam postavy se jménem z profilu. Idempotentní.
    Vrací (new_chars, created).
    """
    if not isinstance(chars, dict):
        chars = {}
    created = 0
    for pk, prof in (profiles or {}).items():
        if ":" in str(pk):
            uid, s = str(pk).split(":", 1)
        else:
            uid, s = str(pk), slot
        rec = chars.setdefault(uid, {"active": s, "chars": {}})
        rec.setdefault("active", s)
        rec.setdefault("chars", {})
        if s not in rec["chars"]:
            name = ""
            if isinstance(prof, dict):
                name = (prof.get("name") or "").strip()
            rec["chars"][s] = {
                "name": name or f"Postava {s}",
                "created_at": int(time.time()),
            }
            created += 1
    return chars, created


# ══════════════════════════════════════════════════════════════════════════════
# I/O wrappery
# ══════════════════════════════════════════════════════════════════════════════

def _migrate_flat(path) -> tuple:
    data = load_json(path, default={})
    data, migrated, conflicts = rekey_flat_dict(data)
    if migrated:
        save_json(path, data)
    return migrated, conflicts


def _migrate_reputation() -> tuple:
    data = load_json(REPUTATION, default={})
    data, migrated, conflicts = rekey_reputation_dict(data)
    if migrated:
        save_json(REPUTATION, data)
    return migrated, conflicts


def _build_characters() -> int:
    chars    = load_json(CHARACTERS, default={})
    profiles = load_json(PROFILES, default={})
    chars, created = build_characters_dict(chars, profiles)
    if created:
        save_json(CHARACTERS, chars)
    return created


def run_migration() -> dict:
    """Spustí celou migraci. Idempotentní. Vrátí report počtů."""
    report = {}
    for name, path in (("profiles", PROFILES), ("economy", ECONOMY),
                       ("diaries", DIARIES), ("player_perks", PLAYER_PERKS)):
        migrated, conflicts = _migrate_flat(path)
        report[name] = {"migrated": migrated, "conflicts": conflicts}

    migrated, conflicts = _migrate_reputation()
    report["reputation"] = {"migrated": migrated, "conflicts": conflicts}

    # characters.json se staví AŽ po překlíčování profiles (čte už uid:slot klíče)
    report["characters_created"] = _build_characters()
    return report