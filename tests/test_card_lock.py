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
        self.inventory['abc']['locked'] = True
        with patch.object(cards, 'load_inventory', return_value=self.inventory), patch.object(cards, 'add_balance') as reward, patch.object(cards, 'save_json') as save:
            with self.assertRaises(cards.CardLockedError):
                cards.burn_card_by_id('1', 'abc')
            reward.assert_not_called()
            save.assert_not_called()
            self.assertIn('abc', self.inventory)
            self.inventory['abc']['locked'] = False
            cards.burn_card_by_id('1', 'abc')
            reward.assert_called_once()
            save.assert_called_once()
            self.assertNotIn('abc', self.inventory)

    def test_inventory_lock_marker(self):
        target = SimpleNamespace(display_name='Tester')
        plain = cards.build_inventory_embed(target, list(self.inventory.items()), 0)
        self.assertNotIn('🔒', plain.fields[0].name)
        self.inventory['abc']['locked'] = True
        locked = cards.build_inventory_embed(target, list(self.inventory.items()), 0)
        self.assertIn('🔒', locked.fields[0].name)
