import copy
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from src.database import db
from src.core.cards import print_ledger as ledger
from src.core.cards.cards import mint_cards, burn_card_by_id, burn_all_cards, CardLockedError
from src.core.cards.summon_reward import settle_opening

class PrintLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=db.db_path()
        db.reset_for_tests(os.path.join(self.tmp.name,'test.db'))
        db.save_doc('cards_data.json',[dict(id=1,name='Hao',image='hao.png',collection='chosen'),dict(id=2,name='Alice')])
        db.save_doc('cards_crates.json',{'1':{'basic':100}})
    def tearDown(self):
        db.reset_for_tests(self.old); self.tmp.cleanup()
    def mint(self,rarity='common',count=1):
        return mint_cards(1,rarity,'1',count,'admin')
    def test_sequence_ignores_rarity_quality_and_survives_all_burns(self):
        with patch('src.core.cards.cards.roll_quality',return_value='damaged'):
            ids,inv=self.mint()
        with patch('src.core.cards.cards.roll_quality',return_value='pristine'):
            ids2,inv=self.mint('mythic')
        self.assertEqual([inv[k]['print_number'] for k in ids+ids2],[1,2])
        burn_all_cards('1')
        db.save_doc('cards_data.json',[dict(id=1,name='Hao')])
        self.assertEqual(settle_opening('1','basic',1).card['print_number'],3)
        self.assertEqual(ledger.check(1,1)['status'],'destroyed')
    def test_restore_original_identity_no_counter_or_dust_change(self):
        ids,inv=self.mint('rare'); original=copy.deepcopy(inv[ids[0]])
        burn_card_by_id('1',ids[0]); wallet=db.load_doc('stardust.json')
        uid,card,kind=ledger.restore(1,1,'2','admin')
        self.assertEqual(uid,ids[0]); self.assertEqual(card['rarity'],original['rarity'])
        self.assertEqual(card['quality'],original['quality']); self.assertEqual(card['owner_id'],'2')
        self.assertEqual(db.load_doc('stardust.json'),wallet)
        self.assertEqual(ledger.counters()['1'],1)
        with self.assertRaises(ValueError): ledger.restore(1,1,'2','admin')
        with self.assertRaises(CardLockedError): burn_card_by_id('2',uid)
        self.assertEqual(ledger.check(1,1)['events'][-1]['kind'],'restored')
    def test_legacy_unknown_conflict_and_reconstruction(self):
        db.save_doc('cards_inventory.json',{'old':dict(card_id=1,print_number=8,owner_id='1',rarity='common',quality='normal')})
        self.assertFalse(ledger.migrate())
        self.assertEqual(ledger.check(1,4)['status'],'unknown')
        self.assertEqual(ledger.check(1,9)['status'],'never')
        with self.assertRaises(ValueError): ledger.restore(1,4,'1','admin')
        uid,card,kind=ledger.restore(1,4,'1','admin',rarity='rare',quality='normal')
        self.assertEqual(kind,'reconstructed'); self.assertEqual(ledger.counters()['1'],8)
        with self.assertRaises(ValueError): ledger.restore(1,20,'1','admin',rarity='rare',quality='normal')
        inv=db.load_doc('cards_inventory.json');inv['duplicate']=dict(inv['old']);db.save_doc('cards_inventory.json',inv)
        self.assertTrue(ledger.migrate()); self.assertEqual(ledger.check(1,8)['status'],'conflict')
        with self.assertRaises(ValueError): ledger.restore(1,8,'1','admin')
    def test_preview_and_failed_transaction_consume_no_print(self):
        preview=settle_opening('1','basic',1,preview=True)
        self.assertEqual(preview.card['print_number'],1)
        self.assertFalse(db.load_doc(ledger.LEDGER))
        with self.assertRaises(RuntimeError):
            with db.transaction() as conn:
                inv=ledger.read(conn,'cards_inventory.json')
                ledger.allocate(conn,inv,'x',dict(card_id=1))
                raise RuntimeError('rollback')
        self.assertEqual(self.mint()[1].popitem()[1]['print_number'],1)
    def test_concurrent_admin_and_summon_unique_prints(self):
        db.save_doc('cards_data.json',[dict(id=1,name='Hao')])
        def run(n):
            return self.mint()[1] if n%2 else settle_opening('1','basic',1)
        with ThreadPoolExecutor(max_workers=6) as pool: list(pool.map(run,range(20)))
        inv=db.load_doc('cards_inventory.json')
        self.assertEqual(sorted(c['print_number'] for c in inv.values()),list(range(1,21)))
    def test_admin_delete_records_snapshot_and_preserves_other_template(self):
        ids,inv=self.mint()
        other,inv=mint_cards(2,'common','1',1,'admin')
        ledger.destroy(ids[0],actor='admin')
        self.assertEqual(ledger.check(1,1)['events'][-1]['kind'],'admin_removed')
        self.assertEqual(ledger.check(2,1)['status'],'active')
        ids,inv=self.mint(); self.assertEqual(inv[ids[0]]['print_number'],2)

    def test_migration_does_not_modify_existing_cards_and_check_uses_current_owner(self):
        inv = {'legacy':dict(card_id=1,print_number=12,owner_id='1',rarity='rare',quality='normal',tags=['trade'])}
        db.save_doc('cards_inventory.json',inv)
        ledger.migrate(); ledger.migrate()
        self.assertEqual(db.load_doc('cards_inventory.json'),inv)
        self.assertEqual(len(ledger.check(1,12)['events']),1)
        inv['legacy']['owner_id']='2'
        db.save_doc('cards_inventory.json',inv)
        self.assertEqual(ledger.check(1,12)['card']['owner_id'],'2')
        ledger.destroy('legacy',actor='admin')
        self.assertEqual(ledger.check(1,12)['card']['owner_id'],'2')
        uid,card,kind=ledger.restore(1,12,'3','restorer')
        self.assertNotIn('tags',card)
        self.assertEqual(ledger.check(1,12)['events'][-1]['actor'],'restorer')
        ledger.destroy(uid,actor='admin')
        ledger.restore(1,12,'4','restorer2')
        self.assertEqual([e['kind'] for e in ledger.check(1,12)['events']],['legacy_import','admin_removed','restored','admin_removed','restored'])
        self.assertEqual(ledger.counters()['1'],12)
