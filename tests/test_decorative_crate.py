import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from src.database import db
from src.core.cards.summon import claim_daily_reward, DailyAlreadyClaimed, streak_bar, luck_embed
from src.core.cards.summon_reward import settle_opening, NoEligibleFrames

class DecorativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=db.db_path()
        db.reset_for_tests(os.path.join(self.tmp.name,'test.db'))
        self.now=datetime(2026,9,1,12,tzinfo=timezone.utc)
    def tearDown(self):
        db.reset_for_tests(self.old); self.tmp.cleanup()
    def test_two_weeks_and_duplicate_claim(self):
        for day in range(14):
            result=claim_daily_reward('1',self.now+timedelta(days=day))
            self.assertEqual(result[0],day+1)
            self.assertEqual(result[4],day in (6,13))
            with self.assertRaises(DailyAlreadyClaimed): claim_daily_reward('1',self.now+timedelta(days=day))
        self.assertEqual(db.load_doc('cards_crates.json')['1'],{'basic':15,'decorative':2})
        self.assertEqual(streak_bar(7),'🔥'*7)
        self.assertEqual(streak_bar(8),'🔥'+'▫️'*6)
        self.assertEqual(claim_daily_reward('1',self.now+timedelta(days=15))[0],1)
    def test_prague_midnight(self):
        claim_daily_reward('1',datetime(2026,9,1,21,59,tzinfo=timezone.utc))
        self.assertEqual(claim_daily_reward('1',datetime(2026,9,1,22,1,tzinfo=timezone.utc))[0],2)
    def test_guaranteed_drop_and_unavailable_frame_rollback(self):
        db.save_doc('cards_crates.json',{'1':{'decorative':2}})
        db.save_doc('cards_data.json',[{'id':1,'name':'Test','image':'hao.png'}])
        db.save_doc('cards_frames.json',[])
        with self.assertRaises(NoEligibleFrames): settle_opening('1','decorative',1)
        self.assertEqual(db.load_doc('cards_crates.json')['1']['decorative'],2)
        self.assertFalse(db.load_doc('cards_inventory.json'))
        db.save_doc('cards_frames.json',[{'id':'riddler_frame'}])
        with patch('src.core.cards.summon_reward.random.random',return_value=0.999):
            result=settle_opening('1','decorative',1)
        self.assertEqual(result.card['frame'],'riddler_frame')
        self.assertTrue(result.guaranteed_frame)
        self.assertEqual(db.load_doc('cards_crates.json')['1']['decorative'],1)
        self.assertIn('100 %',luck_embed(1,True).fields[1].value)
