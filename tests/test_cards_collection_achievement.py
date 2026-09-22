import unittest

from src.core.bot import cards
from src.core.dnd.achievements import ACHIEVEMENTS_DEF

CARDS_DB = [
    {"id": 1, "name": "Alice", "collection": "unworthy"},
    {"id": 2, "name": "Enel", "collection": "unworthy"},
    {"id": 3, "name": "Nyx", "collection": "chosen"},
    {"id": 4, "name": "Bez kolekce"},
]


def _inv(*owned: tuple) -> dict:
    return {
        f"c{i}": {"card_id": card_id, "owner_id": uid}
        for i, (uid, card_id) in enumerate(owned)
    }


class CompletedCollectionsTests(unittest.TestCase):
    def test_complete_collection_is_detected(self):
        inv = _inv(("1", 1), ("1", 2))
        self.assertEqual(cards.completed_collections("1", inv, CARDS_DB), ["unworthy"])

    def test_missing_card_means_incomplete(self):
        inv = _inv(("1", 1))
        self.assertEqual(cards.completed_collections("1", inv, CARDS_DB), [])

    def test_duplicates_do_not_complete_collection(self):
        inv = _inv(("1", 1), ("1", 1), ("1", 1))
        self.assertEqual(cards.completed_collections("1", inv, CARDS_DB), [])

    def test_cards_of_other_players_do_not_count(self):
        inv = _inv(("1", 1), ("2", 2))
        self.assertEqual(cards.completed_collections("1", inv, CARDS_DB), [])

    def test_single_card_collection_counts(self):
        inv = _inv(("1", 3))
        self.assertEqual(cards.completed_collections("1", inv, CARDS_DB), ["chosen"])

    def test_cards_without_collection_are_ignored(self):
        inv = _inv(("1", 4))
        self.assertEqual(cards.completed_collections("1", inv, CARDS_DB), [])


class AchievementDefinitionTests(unittest.TestCase):
    def test_achievement_is_defined(self):
        self.assertIn(cards.COLLECTION_ACHIEVEMENT, ACHIEVEMENTS_DEF)


if __name__ == "__main__":
    unittest.main()
