"""SQLite backend pro všechna herní data.

Data žijí v jednom souboru (`DATA_DIR/arion.db`) ve dvou vrstvách:

* `docs`     — dokumentové úložiště, které nahradilo JSON soubory. Klíč je
               původní název souboru ("profiles.json"), hodnota celý JSON.
               Zápis je jedna transakce, takže soubor nikdy nezůstane půlku
               zapsaný a dva souběžné příkazy se neprobijí navzájem.
Souběžné změny jednoho dokumentu (přičtení goldu, zápis profilu) se dělají
přes `update_doc`, které načte, změní a uloží v jedné transakci — tím mizí
race condition, kvůli které dřív dva příkazy naráz přepsaly jeden druhého.

`load_doc`/`save_doc` používá `src.utils.json_utils`, takže volající kód
zůstává stejný jako za časů JSON souborů.
"""
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from typing import Any, Callable

from src.utils import paths

_db_path_override: str | None = os.environ.get("ARION_DB")


def db_path() -> str:
    """Cesta k DB — `ARION_DB`, jinak `arion.db` v DATA_DIR (Railway volume)."""
    return _db_path_override or os.path.join(paths.DATA_DIR, "arion.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    name       TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()


def connect() -> sqlite3.Connection:
    """Vrátí (a při prvním volání vytvoří) sdílené spojení s inicializovaným schématem."""
    global _conn
    with _lock:
        if _conn is None:
            path = db_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            # isolation_level=None → transakce si řídíme sami (BEGIN IMMEDIATE),
            # jinak by SELECT běžel mimo transakci a dva procesy (bot + dnd)
            # by si navzájem přepsaly změny.
            conn = sqlite3.connect(path, check_same_thread=False, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
            _conn = conn
        return _conn


@contextmanager
def transaction():
    """Zápisová transakce — zámek drží od prvního čtení až po commit.

    `BEGIN IMMEDIATE` zabere zápisový zámek hned, takže read-modify-write
    uvnitř je atomický i mezi procesy (bot a dnd běží odděleně).
    """
    conn = connect()
    with _lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def reset_for_tests(path: str) -> None:
    """Přepne spojení na jinou databázi (používají testy)."""
    global _conn, _db_path_override
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _db_path_override = path


# ── Dokumenty (bývalé JSON soubory) ───────────────────────────────────────────

def load_doc(name: str, default: Any = None) -> Any:
    conn = connect()
    with _lock:
        row = conn.execute("SELECT data FROM docs WHERE name = ?", (name,)).fetchone()
    if row is None:
        return {} if default is None else default
    try:
        return json.loads(row["data"])
    except json.JSONDecodeError:
        return {} if default is None else default


def save_doc(name: str, data: Any) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO docs (name, data, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (name, payload),
        )


def update_doc(name: str, mutate: Callable[[Any], Any], default: Any = None) -> Any:
    """Atomické read-modify-write nad jedním dokumentem.

    `mutate` dostane načtená data, může je změnit na místě a případně vrátit
    novou hodnotu. Celé se to odehraje v jedné transakci, takže souběžné
    příkazy si navzájem nepřepíšou změny.
    """
    with transaction() as conn:
        row = conn.execute("SELECT data FROM docs WHERE name = ?", (name,)).fetchone()
        current = json.loads(row["data"]) if row else ({} if default is None else default)
        result = mutate(current)
        new_data = current if result is None else result
        conn.execute(
            "INSERT INTO docs (name, data, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(name) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (name, json.dumps(new_data, ensure_ascii=False)),
        )
        return new_data


def doc_exists(name: str) -> bool:
    conn = connect()
    with _lock:
        return conn.execute("SELECT 1 FROM docs WHERE name = ?", (name,)).fetchone() is not None


def snapshot_bytes() -> bytes:
    """Konzistentní kopie celé databáze (pro /backup_data).

    Kopírovat `arion.db` za běhu není bezpečné (WAL), proto se používá
    `sqlite3.Connection.backup`, který drží snapshot v jedné transakci.
    """
    source = connect()
    with tempfile.TemporaryDirectory() as tmp:
        target_path = os.path.join(tmp, "snapshot.db")
        with _lock:
            target = sqlite3.connect(target_path)
            try:
                source.backup(target)
            finally:
                target.close()
        with open(target_path, "rb") as f:
            return f.read()


def list_docs() -> list[str]:
    conn = connect()
    with _lock:
        return [r["name"] for r in conn.execute("SELECT name FROM docs ORDER BY name")]
