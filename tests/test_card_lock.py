import unittest
from types import SimpleNamespace
from unittest.mock import patch
from src.core.cards import cards


class CardLockTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {'abc': {'owner_id': '1', 'name': 'Hao', 'rarity': 'common', 'quality': 'normal'}}

    def test_toggle_and_ownership(self):
        with patch.object(cards, 'update_json', side_effect=lambda path, mutate: mutate(self.inventory)):
            self.assertTrue(cards.toggle_card_lock('1', 'abc'))
            with self.assertRaises(cards.NotCardOwnerError):
                cards.toggle_card_lock('2', 'abc')
            self.assertTrue(self.inventory['abc']['locked'])
            self.assertFalse(cards.toggle_card_lock('1', 'abc'))
            with self.assertRaises(cards.CardNotFoundError):
                cards.toggle_card_lock('1', 'missing')

    def test_locked_burn_has_no_side_effects_then_unlock_allows_burn(self):
        import os
        import tempfile
        from src.database import db
        self.inventory['abc']['locked'] = True
        old = db.db_path()
        with tempfile.TemporaryDirectory() as temp:
            try:
                db.reset_for_tests(os.path.join(temp, 'test.db'))
                db.save_doc('cards_inventory.json', self.inventory)
                with self.assertRaises(cards.CardLockedError):
                    cards.burn_card_by_id('1', 'abc')
                self.assertEqual(db.load_doc('cards_inventory.json'), self.inventory)
                self.assertFalse(db.load_doc('stardust.json'))
                cards.toggle_card_lock('1', 'abc')
                cards.burn_card_by_id('1', 'abc')
                self.assertNotIn('abc', db.load_doc('cards_inventory.json'))
                self.assertGreater(db.load_doc('stardust.json')['1'], 0)
            finally:
                db.reset_for_tests(old)

    def test_inventory_lock_marker(self):
        target = SimpleNamespace(display_name='Tester')
        plain = cards.build_inventory_embed(target, list(self.inventory.items()), 0)
        self.assertNotIn('🔒', plain.fields[0].name)
        self.inventory['abc']['locked'] = True
        locked = cards.build_inventory_embed(target, list(self.inventory.items()), 0)
        self.assertIn('🔒', locked.fields[0].name)
