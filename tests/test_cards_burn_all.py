import os
import tempfile
import unittest
from src.database import db
from src.core.cards.cards import burn_all_cards, calculate_dust
from src.utils.paths import CARDS_INVENTORY, STARDUST, PROFILES


class BurnAllTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = db.db_path()
        db.reset_for_tests(os.path.join(self.tmp.name, 'test.db'))
        self.inv = {'a': {'owner_id': '1', 'rarity': 'rare', 'quality': 'pristine'},
                    'b': {'owner_id': '1', 'locked': True}, 'c': {'owner_id': '2'}}
        db.save_doc(os.path.basename(CARDS_INVENTORY), self.inv)
        db.save_doc(os.path.basename(STARDUST), {'1': 10})
        db.save_doc(os.path.basename(PROFILES), {'1': {'active_card_id': 'a'}})

    def tearDown(self):
        db.reset_for_tests(self.old)
        self.tmp.cleanup()

    def test_burn_preserves_locks_other_owners_and_cannot_reward_twice(self):
        dust = calculate_dust('rare', 'pristine')
        self.assertEqual(burn_all_cards('1'), {'count': 1, 'protected': 1, 'dust': dust})
        self.assertEqual(db.load_doc(os.path.basename(CARDS_INVENTORY)), {k:v for k,v in self.inv.items() if k != 'a'})
        self.assertEqual(db.load_doc(os.path.basename(STARDUST)), {'1': 10 + dust})
        self.assertIsNone(db.load_doc(os.path.basename(PROFILES))['1']['active_card_id'])
        self.assertEqual(burn_all_cards('1'), {'count': 0, 'protected': 1, 'dust': 0})
        self.assertEqual(burn_all_cards('nobody'), {'count': 0, 'protected': 0, 'dust': 0})
        self.assertEqual(db.load_doc(os.path.basename(STARDUST)), {'1': 10 + dust})

    def test_invalid_wallet_rolls_back_deletion_and_profile(self):
        db.save_doc(os.path.basename(STARDUST), {'1': 'invalid'})
        with self.assertRaises(ValueError):
            burn_all_cards('1')
        self.assertEqual(db.load_doc(os.path.basename(CARDS_INVENTORY)), self.inv)
        self.assertEqual(db.load_doc(os.path.basename(PROFILES))['1']['active_card_id'], 'a')
