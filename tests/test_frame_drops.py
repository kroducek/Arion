import os
import tempfile
import unittest
from unittest.mock import patch
from src.database import db
from src.core.cards.frame_service import move_frame, frame_drop_chance
from src.core.cards.summon_reward import settle_opening
from src.utils.paths import CARDS_INVENTORY, CARDS_FRAMES, FRAMES_INVENTORY

class FrameDropTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=db.db_path()
        db.reset_for_tests(os.path.join(self.tmp.name,'test.db'))
        db.save_doc(os.path.basename(CARDS_FRAMES), [{'id':'riddler_frame','name':'Riddler'},{'id':'aurelion','name':'Aurelion'}])
        db.save_doc(os.path.basename(CARDS_INVENTORY), {'a':{'owner_id':'1','rarity':'common','frame':'aurelion'}})
        db.save_doc(os.path.basename(FRAMES_INVENTORY), {'1':[{'id':'riddler_frame'},{'id':'riddler_frame'}]})
        db.save_doc('cards_data.json',[{'id':1,'name':'Test','image':'hao.png'}])
        db.save_doc('cards_crates.json',{'1':{'basic':2}})
    def tearDown(self):
        db.reset_for_tests(self.old); self.tmp.cleanup()
    def test_swap_and_remove_preserve_copies(self):
        move_frame('1','a','riddler_frame')
        self.assertEqual([f['id'] for f in db.load_doc(os.path.basename(FRAMES_INVENTORY))['1']],['riddler_frame','aurelion'])
        move_frame('1','a',None)
        self.assertIsNone(db.load_doc(os.path.basename(CARDS_INVENTORY))['a']['frame'])
        self.assertEqual(len(db.load_doc(os.path.basename(FRAMES_INVENTORY))['1']),3)
        with self.assertRaises(ValueError): move_frame('1','a',None)
        with self.assertRaises(ValueError): move_frame('2','a','aurelion')
    def test_drop_commits_and_preview_does_not(self):
        with patch('src.core.cards.summon_reward.random.random',return_value=0):
            reward=settle_opening('1','basic',10)
            self.assertIn(reward.card['frame'],('aurelion','riddler_frame'))
            self.assertEqual(db.load_doc(os.path.basename(CARDS_INVENTORY))[reward.unique_id]['frame'],reward.card['frame'])
            before=db.load_doc(os.path.basename(CARDS_INVENTORY))
            settle_opening('1','basic',10,preview=True)
            self.assertEqual(db.load_doc(os.path.basename(CARDS_INVENTORY)),before)
    def test_chance_and_no_drop(self):
        self.assertEqual(frame_drop_chance(1),0.01)
        self.assertEqual(frame_drop_chance(10),0.02)
        with patch('src.core.cards.summon_reward.random.random',return_value=0.9):
            self.assertFalse(settle_opening('1','basic',1).card.get('frame'))
