import unittest
from unittest.mock import patch

from src.database import characters as ch
from src.core.dnd import quests as q

REGISTRY = {
    "42": {
        "active": "2",
        "chars": {
            "1": {"name": "Erith", "created_at": 0},
            "2": {"name": "Enel", "created_at": 0},
        },
    }
}


class TestParseXp(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(q._parse_xp("160 000"), 160000)
        self.assertEqual(q._parse_xp("1,500"), 1500)
        self.assertEqual(q._parse_xp("2 500 XP"), 2500)
        self.assertEqual(q._parse_xp("35\u00a0000"), 35000)
        self.assertEqual(q._parse_xp(12000), 12000)
        self.assertEqual(q._parse_xp(None), 0)
        self.assertEqual(q._parse_xp("hodně"), 0)

    def test_warning_only_for_unparseable(self):
        self.assertEqual(q._xp_warning("160 000"), "")
        self.assertEqual(q._xp_warning(None), "")
        self.assertIn("nejde přečíst", q._xp_warning("hodně"))


class TestQuestSlots(unittest.TestCase):
    def setUp(self):
        p = patch.object(ch, "_load", lambda: REGISTRY)
        p.start()
        self.addCleanup(p.stop)

    def test_remember_and_read_slot(self):
        quest = {"members": [42]}
        self.assertEqual(q._remember_slot(quest, 42), "2")
        self.assertEqual(quest["member_slots"], {"42": "2"})
        # Přepnutí aktivní postavy už quest neovlivní
        with ch.use_slot(42, "1"):
            self.assertEqual(q._quest_slot(quest, 42), "2")

    def test_legacy_quest_falls_back_to_active(self):
        self.assertEqual(q._quest_slot({"members": [42]}, 42), "2")

    def test_diary_key(self):
        self.assertEqual(q._diary_key(42, "2"), "42:2")


class TestDiaryMigration(unittest.TestCase):
    def test_merges_legacy_keys_into_first_character(self):
        stored = {
            "42": [{"text": "starý quest", "pinned": False, "tag": "📜"}],
            "42:1": [{"text": "tutoriál", "pinned": False, "tag": None}],
            "7": [{"text": "sólo", "pinned": False, "tag": "📜"}],
        }
        with patch.object(q, "load_diaries", lambda: stored), \
             patch.object(q, "save_diaries", lambda d: stored.update(d)):
            q._migrate_diaries()
        self.assertNotIn("42", stored)
        self.assertEqual([e["text"] for e in stored["42:1"]], ["tutoriál", "starý quest"])
        self.assertEqual([e["text"] for e in stored["7:1"]], ["sólo"])

    def test_no_duplicates_on_repeated_run(self):
        stored = {"42": [{"text": "quest", "pinned": False, "tag": "📜"}]}
        with patch.object(q, "load_diaries", lambda: stored), \
             patch.object(q, "save_diaries", lambda d: stored.update(d)):
            q._migrate_diaries()
            q._migrate_diaries()
        self.assertEqual(len(stored["42:1"]), 1)


class TestMemberMentions(unittest.TestCase):
    def test_duplicate_mention_counts_once(self):
        class Member:
            def __init__(self, mid):
                self.id = mid

        class Guild:
            def get_member(self, mid):
                return Member(mid)

        ids = q._parse_member_mentions("<@42> <@42> <@7>", Guild())
        self.assertEqual(ids, [42, 7])


if __name__ == "__main__":
    unittest.main()
