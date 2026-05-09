"""
Audit log — zaznamenává admin akce (give perk, quest, ekonomika...).
Ukládá do audit_log.json, max 500 záznamů (starší se oříznou).
"""
import json
import os
from datetime import datetime

from src.utils.paths import data as _data

AUDIT_LOG = _data("audit_log.json")
MAX_ENTRIES = 500


def _load() -> list:
    if not os.path.exists(AUDIT_LOG):
        return []
    try:
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(entries: list):
    with open(AUDIT_LOG, "w", encoding="utf-8") as f:
        json.dump(entries[-MAX_ENTRIES:], f, ensure_ascii=False, indent=2)


def log_action(action: str, actor: str, target: str, detail: str = ""):
    """
    action — krátký typ akce, např. "perk_give", "quest_give", "perk_remove"
    actor  — Discord jméno admina
    target — na koho/co se akce vztahuje (hráč / název questu / perk ID)
    detail — volitelný doplněk (perk_id, xp, počet hráčů…)
    """
    entries = _load()
    entries.append({
        "ts":     datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "action": action,
        "actor":  actor,
        "target": target,
        "detail": detail,
    })
    _save(entries)


def get_recent(n: int = 30) -> list:
    return _load()[-n:]
