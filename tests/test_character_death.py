import os
import tempfile
import unittest
from unittest.mock import patch

from src.database import db, deaths


class CharacterDeathTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.old_db = db._db_path_override
        self.path = os.path.join(directory.name, "arion.db")
        db.reset_for_tests(self.path)
        self.addCleanup(db.reset_for_tests, self.old_db)
        db.save_doc(deaths.CHARACTERS, {
            "123": {"active": "2", "chars": {"1": {"name": "A"}, "2": {"name": "B"}}},
        })
        db.save_doc(deaths.PROFILES, {"123:1": {"hp_cur": 10}, "123:2": {"hp_cur": 5}})
        db.save_doc(deaths.COMBAT, {"42": {"stats": {"<@123>": {"profile_key": "123:2", "hp": 0}}}})

    def kill(self, at=1000):
        with patch.object(deaths.time, "time", return_value=at), deaths.in_channel(42):
            db.update_documents([deaths.PROFILES], lambda docs:
                                docs[deaths.PROFILES]["123:2"].update(hp_cur=0))
        return deaths.pending_deaths()["123:2"]

    def test_saved_deadline_and_revival_apply_to_original_slot(self):
        death = self.kill()
        self.assertEqual((death["channel_id"], death["deadline"]), (42, 1600))
        self.assertEqual(self.kill(at=1100), death)
        db.reset_for_tests(self.path)
        registry = db.load_doc(deaths.CHARACTERS)
        registry["123"]["active"] = "1"
        db.save_doc(deaths.CHARACTERS, registry)
        with patch.object(deaths.time, "time", return_value=1599):
            self.assertIsNone(deaths.resolve("123:2", death["id"], "expire"))
            self.assertEqual(deaths.resolve("123:2", death["id"], "revive"), "revived")
        self.assertEqual(db.load_doc(deaths.PROFILES), {"123:1": {"hp_cur": 10}, "123:2": {"hp_cur": 1}})
        self.assertEqual(db.load_doc(deaths.COMBAT)["42"]["stats"]["<@123>"]["hp"], 1)
        self.assertIsNone(deaths.resolve("123:2", death["id"], "delete"))

    def test_expiration_can_delete_the_last_character(self):
        self.assertIsNotNone(deaths.delete_character(123, "1"))
        death = self.kill()
        db.save_doc("diaries.json", {"123:2": {"entries": ["Ahoj"]}})
        with patch.object(deaths.time, "time", return_value=1600):
            self.assertEqual(deaths.resolve("123:2", death["id"], "revive"), "expired")
        for doc in (deaths.CHARACTERS, deaths.PROFILES, "diaries.json", deaths.DEATHS):
            self.assertEqual(db.load_doc(doc), {})
        self.assertEqual(db.load_doc(deaths.COMBAT)["42"]["stats"], {})

    def test_old_buttons_cannot_delete_a_reused_slot(self):
        old = self.kill()
        self.assertIsNotNone(deaths.delete_character(123, "2"))
        db.save_doc(deaths.PROFILES, {"123:2": {"hp_cur": 5}})
        new = self.kill()
        with patch.object(deaths.time, "time", return_value=1001):
            self.assertIsNone(deaths.resolve("123:2", old["id"], "delete"))
            self.assertEqual(deaths.resolve("123:2", new["id"], "delete"), "deleted")
        self.assertEqual(db.load_doc(deaths.CHARACTERS)["123"]["active"], "1")
