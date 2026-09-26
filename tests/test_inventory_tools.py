import copy
import unittest
from src.core.cards.inventory_tools import edit_tags, select_cards


class InventoryToolsTests(unittest.TestCase):
    def setUp(self):
        self.inv = {
            'a': dict(owner_id='1', name='Hádankář', collection='jesters', rarity='rare', quality='poor', print_number=5, created_at='2026-01-01', locked=True, tags=['trade'], frame='burned'),
            'b': dict(owner_id='1', name='Alice', collection='queen', rarity='mythic', quality='pristine', print_number=2, created_at='2026-02-01'),
            'c': dict(owner_id='2', name='Hádankář', tags=['trade']),
        }

    def test_combined_filters_and_ownership(self):
        result = select_cards(self.inv, '1', character='hadankar', collection='jesters', rarity='rare', quality='poor', frame='burned', locked=True, tag='TRADE')
        self.assertEqual([k for k,c in result], ['a'])
        self.assertEqual(select_cards(self.inv, '1', tag='trade', locked=False), [])
        self.assertEqual([k for k,c in select_cards(self.inv, '1', frame='none')], ['b'])

    def test_sort_modes(self):
        for mode in ('print', 'newest', 'rarity', 'quality'):
            self.assertEqual([k for k,c in select_cards(self.inv, '1', sort=mode)], ['b', 'a'])
        self.assertEqual([k for k,c in select_cards(self.inv, '1', sort='oldest')], ['a', 'b'])

    def test_bulk_tags_are_validated_before_mutation(self):
        before = copy.deepcopy(self.inv)
        with self.assertRaises(ValueError):
            edit_tags(self.inv, '1', ['a', 'c'], 'favorite')
        self.assertEqual(self.inv, before)
        edit_tags(self.inv, '1', ['a', 'b', 'a'], ' OBLÍBENÉ ')
        edit_tags(self.inv, '1', ['a', 'b'], 'oblíbené')
        self.assertEqual(self.inv['a']['tags'], ['trade', 'oblíbené'])
        self.assertTrue(self.inv['a']['locked'])
        self.assertNotIn('locked', self.inv['b'])
        edit_tags(self.inv, '1', ['a', 'b'], 'oblíbené', remove=True)
        self.assertEqual(self.inv['a']['tags'], ['trade'])
        self.assertEqual(self.inv['b']['tags'], [])

    def test_limits(self):
        for tag in ('', 'x'*25, 'a b', '@everyone'):
            with self.assertRaises(ValueError): edit_tags(self.inv, '1', ['a'], tag)
        self.inv['a']['tags'] = [str(n) for n in range(8)]
        with self.assertRaises(ValueError): edit_tags(self.inv, '1', ['b','a'], 'new')
        self.assertNotIn('tags', self.inv['b'])
