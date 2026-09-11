"""Načítání a ukládání herních dat.

Data z `DATA_DIR` (dřív JSON soubory) žijí v SQLite — viz `src.database.db`.
Rozhraní zůstalo stejné, takže cogy dál volají `load_json(PROFILES)` a nemusí
řešit, že pod tím je databáze. Cesty mimo `DATA_DIR` (repo defaulty, testovací
soubory) se pořád čtou a zapisují jako obyčejné soubory.
"""
import json
import os
import threading
from typing import Any

from src.utils import paths

_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()


def _get_lock(path: str) -> threading.Lock:
    with _locks_meta:
        if path not in _locks:
            _locks[path] = threading.Lock()
        return _locks[path]


def doc_name(path: str) -> str | None:
    """Název dokumentu v DB pro danou cestu, nebo None když jde o běžný soubor."""
    try:
        if os.path.dirname(os.path.abspath(path)) == os.path.abspath(paths.DATA_DIR):
            return os.path.basename(path)
    except Exception:
        pass
    return None


def load_json(path: str, default: Any = None) -> Any:
    """Bezpečně načte data. Vrátí `default` při chybě nebo chybějícím záznamu."""
    name = doc_name(path)
    if name is not None:
        from src.database import db
        return db.load_doc(name, default)

    lock = _get_lock(path)
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default if default is not None else {}


def save_json(path: str, data: Any) -> None:
    """Bezpečně uloží data. Zápis do DB je jedna transakce."""
    name = doc_name(path)
    if name is not None:
        from src.database import db
        db.save_doc(name, data)
        return

    lock = _get_lock(path)
    with lock:
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def update_json(path: str, mutate) -> Any:
    """Atomické read-modify-write: načti, změň, ulož v jedné transakci.

    Pro data v DB je to jediný bezpečný způsob, jak měnit záznam, na kterém
    může současně pracovat jiný příkaz.
    """
    name = doc_name(path)
    if name is not None:
        from src.database import db
        return db.update_doc(name, mutate)

    lock = _get_lock(path)
    with lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                current = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            current = {}
        result = mutate(current)
        new_data = current if result is None else result
        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        return new_data
