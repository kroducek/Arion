"""Testy SQLite vrstvy, migrace JSON → SQLite a ekonomiky nad ní."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest

from src.database import db
from src.utils import paths


class SqliteTestCase(unittest.TestCase):
    """Každý test běží nad vlastní dočasnou DB a vlastním DATA_DIR."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = self._tmp.name
        self._orig_data_dir = paths.DATA_DIR
        paths.DATA_DIR = self.data_dir
        db.reset_for_tests(os.path.join(self.data_dir, "test.db"))

    def tearDown(self):
        paths.DATA_DIR = self._orig_data_dir
        db.reset_for_tests(None)
        self._tmp.cleanup()

    def write_json(self, name: str, payload) -> str:
        path = os.path.join(self.data_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return path


class TestDocStore(SqliteTestCase):
    def test_save_and_load(self):
        db.save_doc("profiles.json", {"1:1": {"xp": 10}})
        self.assertEqual(db.load_doc("profiles.json"), {"1:1": {"xp": 10}})

    def test_missing_doc_returns_default(self):
        self.assertEqual(db.load_doc("nope.json"), {})
        self.assertEqual(db.load_doc("nope.json", default=[]), [])

    def test_update_doc_is_atomic_across_threads(self):
        db.save_doc("economy.json", {"1": 0})

        def worker():
            for _ in range(50):
                db.update_doc("economy.json", lambda d: d.update({"1": d["1"] + 1}))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(db.load_doc("economy.json")["1"], 200)

    def test_transaction_blocks_other_process(self):
        """Zápis z druhého procesu (bot vs. dnd) musí počkat, ne přepsat data."""
        db.save_doc("economy.json", {"1": 1})
        other = sqlite3.connect(db.db_path(), timeout=0, isolation_level=None)
        try:
            with db.transaction() as conn:
                conn.execute("SELECT data FROM docs WHERE name = 'economy.json'")
                with self.assertRaises(sqlite3.OperationalError):
                    other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()

    def test_snapshot_contains_data(self):
        db.save_doc("news.json", [{"title": "x"}])
        self.assertTrue(db.snapshot_bytes().startswith(b"SQLite format 3"))


class TestJsonUtilsRouting(SqliteTestCase):
    def test_data_dir_paths_go_to_db(self):
        from src.utils.json_utils import load_json, save_json

        target = os.path.join(self.data_dir, "quests.json")
        save_json(target, {"q1": {"name": "Test"}})

        self.assertFalse(os.path.exists(target), "data z DATA_DIR se nemají psát do souboru")
        self.assertEqual(load_json(target), {"q1": {"name": "Test"}})
        self.assertEqual(db.load_doc("quests.json"), {"q1": {"name": "Test"}})

    def test_paths_outside_data_dir_stay_files(self):
        from src.utils.json_utils import load_json, save_json

        with tempfile.TemporaryDirectory() as other:
            target = os.path.join(other, "library.json")
            save_json(target, {"a": 1})
            self.assertTrue(os.path.exists(target))
            self.assertEqual(load_json(target), {"a": 1})


class TestMigration(SqliteTestCase):
    def test_imports_json_and_is_idempotent(self):
        from src.database.migrate import run_migration

        self.write_json("profiles.json", {"1:1": {"xp": 5}})
        self.write_json("economy.json", {"1:1": 300})

        first = run_migration()
        self.assertIn("profiles.json", first["imported"])
        self.assertIn("economy.json", first["imported"])
        self.assertTrue(os.path.isdir(first["backup"]))

        # Bot mezitím data změní…
        db.save_doc("economy.json", {"1:1": 999})

        # …a druhý běh migrace je nesmí přepsat starým souborem.
        second = run_migration()
        self.assertEqual(second["imported"], [])
        self.assertEqual(db.load_doc("economy.json"), {"1:1": 999})

    def test_original_json_files_are_kept(self):
        from src.database.migrate import run_migration

        path = self.write_json("diaries.json", {"1:1": []})
        run_migration()
        self.assertTrue(os.path.exists(path))

    def test_corrupt_json_is_skipped(self):
        from src.database.migrate import run_migration

        with open(os.path.join(self.data_dir, "broken.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.write_json("news.json", [])

        result = run_migration()
        self.assertNotIn("broken.json", result["imported"])
        self.assertIn("news.json", result["imported"])

    def test_bootstrap_items_fills_defaults(self):
        paths.bootstrap_items()
        items = db.load_doc("items.json")
        for item_id in paths.DEFAULT_ITEMS:
            self.assertIn(item_id, items)


class TestEconomy(SqliteTestCase):
    def setUp(self):
        super().setUp()
        from src.logic import economy

        self.economy = economy
        # Cesty k měnám se počítají při importu — v testu je přesměrujeme na tmp.
        self._orig_files = dict(economy._CURRENCY_FILES)
        economy._CURRENCY_FILES.update({
            "gold": os.path.join(self.data_dir, "economy.json"),
            "silver": os.path.join(self.data_dir, "silver.json"),
            "stardust": os.path.join(self.data_dir, "stardust.json"),
        })

    def tearDown(self):
        self.economy._CURRENCY_FILES.update(self._orig_files)
        super().tearDown()

    def test_add_and_get(self):
        self.assertEqual(self.economy.add_balance(1, 100, "silver"), 100)
        self.assertEqual(self.economy.add_balance(1, -30, "silver"), 70)
        self.assertEqual(self.economy.get_balance(1, "silver"), 70)

    def test_spend_respects_balance(self):
        self.economy.set_balance(1, 50, "silver")
        self.assertFalse(self.economy.spend(1, 80, "silver"))
        self.assertEqual(self.economy.get_balance(1, "silver"), 50)
        self.assertTrue(self.economy.spend(1, 50, "silver"))
        self.assertEqual(self.economy.get_balance(1, "silver"), 0)

    def test_concurrent_add_does_not_lose_updates(self):
        self.economy.set_balance(7, 0, "silver")

        def worker():
            for _ in range(40):
                self.economy.add_balance(7, 1, "silver")

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.economy.get_balance(7, "silver"), 200)

    def test_transfer(self):
        self.economy.set_balance(1, 100, "silver")
        self.assertTrue(self.economy.transfer(1, 2, 40, "silver"))
        self.assertEqual(self.economy.get_balance(1, "silver"), 60)
        self.assertEqual(self.economy.get_balance(2, "silver"), 40)
        self.assertFalse(self.economy.transfer(1, 2, 1000, "silver"))


if __name__ == "__main__":
    unittest.main()
