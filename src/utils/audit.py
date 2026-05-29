"""
Audit log — zaznamenává admin akce (give perk, quest, ekonomika...).
Ukládá do audit_log.json, max 500 záznamů (starší se oříznou).
Thread-safe s lockingem.
"""
import json
import os
import threading
from datetime import datetime, timezone

from src.utils.paths import data as _data
from src.utils.logger import get_logger

AUDIT_LOG = _data("audit_log.json")
MAX_ENTRIES = 500
_audit_lock = threading.Lock()

logger = get_logger("AuditLog")


def _load() -> list:
    """Thread-safely načte audit log. Vrátí [] na chybu."""
    try:
        if not os.path.exists(AUDIT_LOG):
            return []
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.error(f"Corrupt audit log JSON at {AUDIT_LOG}")
        return []
    except Exception as e:
        logger.error(f"Failed to load audit log: {e}")
        return []


def _save(entries: list):
    """Thread-safely uloží audit log."""
    try:
        dir_name = os.path.dirname(AUDIT_LOG)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(AUDIT_LOG, "w", encoding="utf-8") as f:
            json.dump(entries[-MAX_ENTRIES:], f, ensure_ascii=False, indent=2)
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
