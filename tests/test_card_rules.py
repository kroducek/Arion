import os
import tempfile
import unittest
from unittest.mock import patch

from src.core.cards.card_rules import (
    BASE_RARITY_WEIGHTS, QUALITY_WEIGHTS, RARITY_ORDER, QUALITY_ORDER,
    rarity_chances, roll_quality, migrate_qualities,
)
from src.database import db


class CardRulesTests(unittest.TestCase):
    def test_base_chances_match_requested_distribution(self):
        self.assertEqual(rarity_chances(1), {
            'common': 50, 'uncommon': 30, 'rare': 12.5,
            'epic': 5, 'legendary': 2, 'mythic': 0.5,
        })
        self.assertEqual(QUALITY_WEIGHTS, {
            'damaged': 10, 'poor': 20, 'normal': 40, 'excellent': 20, 'pristine': 10,
        })

    def test_tickets_increase_high_rarities_without_guaranteeing_them(self):
        previous = rarity_chances(1)
        for tickets in range(2, 11):
            current = rarity_chances(tickets)
            self.assertAlmostEqual(sum(current.values()), 100)
            for rarity in ('rare', 'epic', 'legendary', 'mythic'):
                self.assertGreater(current[rarity], previous[rarity])
            self.assertLess(current['mythic'], 1)
            previous = current
        self.assertEqual(rarity_chances(-10), rarity_chances(1))
        self.assertEqual(rarity_chances(99), rarity_chances(10))

    def test_quality_roll_uses_fixed_weights(self):
        with patch.object(roll_quality.__globals__['random'], 'choices', return_value=['poor']) as pick:
            self.assertEqual(roll_quality(), 'poor')
        self.assertEqual(pick.call_args.kwargs['weights'], [10, 20, 40, 20, 10])

    def test_album_ranking_includes_new_tiers(self):
        self.assertEqual(RARITY_ORDER, ['mythic', 'legendary', 'epic', 'rare', 'uncommon', 'common'])
        self.assertEqual(QUALITY_ORDER, ['pristine', 'excellent', 'normal', 'poor', 'damaged'])

    def test_migration_preserves_ownership_and_is_idempotent(self):
        old_path = db.db_path()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                db.reset_for_tests(os.path.join(tmp, 'test.db'))
                db.save_doc('cards_inventory.json', {
                    'a': {'owner_id': '1', 'quality': 'shiny', 'rarity': 'legendary'},
                    'b': {'owner_id': '2', 'quality': 'gold'},
                    'c': {'owner_id': '3', 'quality': 'normal'},
                })
                migrate_qualities()
                result = db.load_doc('cards_inventory.json')
                self.assertEqual(result['a'], {'owner_id': '1', 'quality': 'pristine',
                                               'rarity': 'legendary', 'legacy_quality': 'shiny'})
                self.assertEqual(result['b']['quality'], 'excellent')
                self.assertEqual(result['c'], {'owner_id': '3', 'quality': 'normal'})
                migrate_qualities()
                self.assertEqual(result, db.load_doc('cards_inventory.json'))
            finally:
                db.reset_for_tests(old_path)
