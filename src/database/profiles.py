"""Jednotný přístup k profiles.json a items.json.

Dřív měl každý cog vlastní kopii `_load_profiles`/`_save_profiles`/`_pk`, takže
se opravy (např. fallback na nemigrované profily) musely dělat na deseti
místech. Cogy teď importují odsud.
"""
from src.database.characters import pkey
from src.utils.json_utils import load_json, save_json
from src.utils.paths import ITEMS, PROFILES


def load_profiles() -> dict:
    return load_json(PROFILES, default={})


def save_profiles(data: dict) -> None:
    save_json(PROFILES, data)


def profile_key(profiles: dict, uid) -> str:
    """Klíč profilu: pkey (uid:slot) když existuje, jinak holé uid (nemigrovaní)."""
    key = pkey(uid)
    return key if key in profiles else str(uid)


def load_items() -> dict:
    try:
        return load_json(ITEMS, default={})
    except Exception:
        return {}


def save_items(data: dict) -> None:
    save_json(ITEMS, data)
