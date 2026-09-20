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


class TestSeedSync(unittest.TestCase):
    def test_manual_edit_survives_restart(self):
        seed  = {"info": "původní", "xp": "1000", "category": "side",
                 "parent_quest": None, "everyone": False}
        quest = dict(seed)
        q._sync_seed_fields(quest, seed)          # první start → jen otisk

        quest["xp"] = "5000"                      # admin upravil přes /quest edit
        q._sync_seed_fields(quest, seed)
        self.assertEqual(quest["xp"], "5000")

    def test_seed_change_reaches_untouched_field(self):
        seed  = {"info": "původní", "xp": "1000", "category": "side",
                 "parent_quest": None, "everyone": False}
        quest = dict(seed)
        q._sync_seed_fields(quest, seed)

        q._sync_seed_fields(quest, {**seed, "info": "nový popis"})
        self.assertEqual(quest["info"], "nový popis")

    def test_seed_change_does_not_beat_manual_edit(self):
        seed  = {"info": "původní", "xp": "1000", "category": "side",
                 "parent_quest": None, "everyone": False}
        quest = dict(seed)
        q._sync_seed_fields(quest, seed)

        quest["info"] = "ruční popis"
        q._sync_seed_fields(quest, {**seed, "info": "nový popis"})
        self.assertEqual(quest["info"], "ruční popis")


class TestBoardQuests(unittest.TestCase):
    def test_board_source_and_orphan_sides(self):
        quests = {
            "Volání hvězdy":  {"category": "main"},
            "Stíny v srdci":  {"category": "side", "parent_quest": "Volání hvězdy"},
            "Ztracený rodič": {"category": "side", "parent_quest": "Neexistuje"},
            "Krysy ve sklepě": {"category": "solo", "source": "board"},
            "Osobní výprava": {"category": "solo"},
        }
        board = q.board_quests(quests)
        self.assertEqual(set(board), {"Ztracený rodič", "Krysy ve sklepě"})


class TestEmbedFit(unittest.TestCase):
    def test_pages_split_on_length(self):
        blocks = ["x" * 2500] * 3
        pages  = q._pages(blocks, per_page=8)
        self.assertEqual([len(p) for p in pages], [1, 1, 1])

    def test_fit_description_notes_overflow(self):
        desc = q._fit_description(["x" * 2500] * 3)
        self.assertLessEqual(len(desc), 4096)
        self.assertIn("a dalších 2 questů", desc)


if __name__ == "__main__":
    unittest.main()
