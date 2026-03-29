"""
Thread-safe JSON load/save utility.
Každý soubor má vlastní threading.Lock — zabraňuje race conditions
při souběžných Discord příkazech.
"""
import json
import threading
from typing import Any

_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_meta:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def load_json(path: str, default: Any = None) -> Any:
    """Bezpečně načte JSON soubor. Vrátí `default` při chybě nebo chybějícím souboru."""
    lock = _get_lock(path)
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default if default is not None else {}


def save_json(path: str, data: Any) -> None:
    """Bezpečně uloží data do JSON souboru."""
    lock = _get_lock(path)
    with lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
