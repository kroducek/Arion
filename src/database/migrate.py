"""Jednorázový (a opakovatelně spustitelný) přesun JSON dat do SQLite.

Spouští se při startu bota. Co dělá:

1. Před prvním importem udělá kopii všech JSON souborů do
   `DATA_DIR/json_backup_<timestamp>/` — kdyby bylo potřeba se vrátit.
2. Každý `*.json` z DATA_DIR nahraje do tabulky `docs` pod svým názvem.
   Soubory, které v DB už jsou, přeskočí → migrace je idempotentní a data
   zapsaná botem po migraci nikdy nepřepíše starým souborem.
3. Doplní chybějící klíče z repozitářových defaultů (`DEFAULT_DATA_DIR`),
   což dřív dělal `sync_default_data_files` na úrovni souborů.

Původní JSON soubory se nemažou — zůstávají jako záloha.
"""
import json
import os
import shutil
from datetime import datetime, timezone

from src.database import db
from src.utils import paths
from src.utils.logger import get_logger

logger = get_logger("Migrate")

META_DOC = "_migration_meta"
SCHEMA_VERSION = 1

# Soubory, které nejsou herní data (statické knihovny se čtou přímo z repa).
SKIP_FILES = {"cards_frames.json"}


def _read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return json.loads(content) if content else None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Přeskakuji {os.path.basename(path)}: {exc}")
        return None


def _backup_json_files(data_dir: str) -> str | None:
    files = [f for f in os.listdir(data_dir) if f.endswith(".json")]
    if not files:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = os.path.join(data_dir, f"json_backup_{stamp}")
    os.makedirs(target, exist_ok=True)
    for name in files:
        try:
            shutil.copy2(os.path.join(data_dir, name), os.path.join(target, name))
        except OSError as exc:
            logger.warning(f"Zálohu {name} se nepodařilo vytvořit: {exc}")
    return target


def _merge_defaults(defaults_dir: str) -> int:
    """Doplní do DB klíče, které přibyly v repozitářových defaultech."""
    if not os.path.isdir(defaults_dir):
        return 0
    merged = 0
    for name in sorted(os.listdir(defaults_dir)):
        if not name.endswith(".json") or name in SKIP_FILES:
            continue
        src_data = _read_json_file(os.path.join(defaults_dir, name))
        if not isinstance(src_data, dict) or not src_data:
            continue
        current = db.load_doc(name, default=None)
        if not isinstance(current, dict):
            continue
        missing = {k: v for k, v in src_data.items() if k not in current}
        if missing:
            current.update(missing)
            db.save_doc(name, current)
            merged += len(missing)
    return merged


def run_migration() -> dict:
    """Nahraje chybějící JSON data do SQLite. Vrací souhrn pro log."""
    data_dir = paths.DATA_DIR
    os.makedirs(data_dir, exist_ok=True)
    db.connect()

    meta = db.load_doc(META_DOC, default={})
    first_run = not meta.get("migrated_at")

    json_files = sorted(f for f in os.listdir(data_dir) if f.endswith(".json"))
    pending = [f for f in json_files if f not in SKIP_FILES and not db.doc_exists(f)]

    backup_dir = None
    if pending and first_run:
        backup_dir = _backup_json_files(data_dir)

    imported = []
    for name in pending:
        payload = _read_json_file(os.path.join(data_dir, name))
        if payload is None:
            continue
        db.save_doc(name, payload)
        imported.append(name)

    merged = _merge_defaults(paths.DEFAULT_DATA_DIR)

    meta.update({
        "schema_version": SCHEMA_VERSION,
        "migrated_at": meta.get("migrated_at") or datetime.now(timezone.utc).isoformat(),
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "imported_files": sorted(set(meta.get("imported_files", [])) | set(imported)),
    })
    if backup_dir:
        meta["json_backup"] = backup_dir
    db.save_doc(META_DOC, meta)

    summary = {
        "db": db.db_path(),
        "imported": imported,
        "merged_default_keys": merged,
        "backup": backup_dir,
    }
    if imported:
        logger.info(f"SQLite: naimportováno {len(imported)} souborů ({', '.join(imported)})")
    if backup_dir:
        logger.info(f"SQLite: záloha JSONů v {backup_dir}")
    if merged:
        logger.info(f"SQLite: doplněno {merged} chybějících defaultních klíčů")
    return summary
