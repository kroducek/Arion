"""
Audit log — zaznamenává admin akce (give perk, quest, ekonomika...).
Ukládá do audit_log.json, max 500 záznamů (starší se oříznou).
Thread-safe s lockingem.
"""
import os
import threading
from datetime import datetime, timezone

from src.utils.json_utils import load_json, save_json
from src.utils.paths import data as _data
from src.utils.logger import get_logger

AUDIT_LOG = _data("audit_log.json")
MAX_ENTRIES = 500
_audit_lock = threading.Lock()

logger = get_logger("AuditLog")


def _load() -> list:
    """Thread-safely načte audit log. Vrátí [] na chybu."""
    try:
        data = load_json(AUDIT_LOG, default=[])
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Failed to load audit log: {e}")
        return []


def _save(entries: list):
    """Thread-safely uloží audit log."""
    try:
        save_json(AUDIT_LOG, entries[-MAX_ENTRIES:])
    except Exception as e:
        logger.error(f"Failed to save audit log: {e}")


def log_action(action: str, actor: str, target: str, detail: str = ""):
    """
    Log admin akci. Thread-safe.
    action — krátký typ akce, např. "perk_give", "quest_give", "perk_remove"
    actor  — Discord jméno admina
    target — na koho/co se akce vztahuje (hráč / název questu / perk ID)
    detail — volitelný doplněk (perk_id, xp, počet hráčů…)
    """
    with _audit_lock:
        try:
            entries = _load()
            entries.append({
                "ts":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "action": action,
                "actor":  actor,
                "target": target,
                "detail": detail,
            })
            _save(entries)
        except Exception as e:
            logger.error(f"Failed to log action '{action}': {e}")


def get_recent(n: int = 30) -> list:
    """Thread-safely vrátí posledních n záznamů."""
    with _audit_lock:
        try:
            entries = _load()
            return entries[-n:] if entries else []
        except Exception as e:
            logger.error(f"Failed to get recent audit logs: {e}")
            return []
