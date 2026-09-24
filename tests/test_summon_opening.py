"""Summon accounting survives failed rendering and Discord delivery."""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.database import db
from src.core.cards.summon_reward import settle_opening, NoCrates, EmptyCardPool
from src.core.cards.summon import Summon, CRATES


class RewardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = db.db_path()
        db.reset_for_tests(os.path.join(self.tmp.name, 'test.db'))
        db.save_doc('cards_data.json', [{'id': 1, 'name': 'Test', 'image': 'missing.png'}])
        db.save_doc('cards_crates.json', {'1': {'basic': 1}})
        db.save_doc('summon_luck.json', {'1': {'clovers': 4}})

    def tearDown(self):
        db.reset_for_tests(self.old)
        self.tmp.cleanup()

    def snapshot(self):
        return {name: db.load_doc(name) for name in db.list_docs()}

    def test_jackpot_commits_card_crate_and_reset(self):
        reward = settle_opening('1', 'basic', 10)
        self.assertEqual((reward.card['rarity'], reward.card['quality']), ('legendary', 'shiny'))
        self.assertEqual(db.load_doc('cards_inventory.json')[reward.unique_id], reward.card)
        self.assertEqual(db.load_doc('cards_crates.json')['1']['basic'], 0)
        self.assertEqual(db.load_doc('summon_luck.json')['1']['clovers'], 0)
        with self.assertRaises(NoCrates):
            settle_opening('1', 'basic', 10)
        self.assertEqual(len(db.load_doc('cards_inventory.json')), 1)

    def test_preview_does_not_grant_a_real_card(self):
        before = self.snapshot()
        result = settle_opening('1', 'basic', 10, preview=True, forced_clovers=5)
        self.assertTrue(result.jackpot)
        self.assertEqual(before, self.snapshot())

    def test_empty_pool_does_not_consume_crate_or_luck(self):
        db.save_doc('cards_data.json', [])
        before = self.snapshot()
        with self.assertRaises(EmptyCardPool):
            settle_opening('1', 'basic', 10)
        self.assertEqual(before, self.snapshot())

    def test_failed_write_rolls_back_every_document(self):
        db.connect().execute("CREATE TRIGGER fail_inventory BEFORE INSERT ON docs WHEN NEW.name='cards_inventory.json' BEGIN SELECT RAISE(ABORT, 'test'); END")
        before = self.snapshot()
        with self.assertRaises(Exception):
            settle_opening('1', 'basic', 10)
        self.assertEqual(before, self.snapshot())

    def test_non_jackpot_keeps_luck_and_existing_inventory(self):
        db.save_doc('cards_inventory.json', {'old': {'card_id': 1, 'owner_id': '2', 'print_number': 7}})
        result = settle_opening('1', 'basic', 3)
        self.assertEqual(result.card['print_number'], 8)
        self.assertEqual(result.remaining_clovers, 4)
        self.assertIn('old', db.load_doc('cards_inventory.json'))

    def test_display_failure_never_refunds_committed_reward(self):
        async def run():
            message = SimpleNamespace(edit=AsyncMock(side_effect=RuntimeError('deleted')))
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=1, display_name='Tester', mention='@tester',
                                     display_avatar=SimpleNamespace(url='https://example.com/avatar.png')),
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock(return_value=message)),
                channel=None, filesize_limit=8 * 1024 * 1024,
            )
            # Extension-loading tests reimport the module; patch the class's
            # actual globals rather than a potentially newer module object.
            from unittest.mock import Mock
            render = Mock(side_effect=ValueError('render failed'))
            showcase = Mock(side_effect=ValueError('image missing'))
            achievement = AsyncMock(side_effect=RuntimeError('offline'))
            with patch.dict(Summon._run_opening.__globals__, {
                'render_opening': render, 'build_showcase_image': showcase,
                'check_collection_achievement': achievement,
            }):
                await Summon(None)._run_opening(interaction, 'basic', CRATES['basic'], forced_tickets=10)
            render.assert_called_once()
            showcase.assert_called_once()
            achievement.assert_awaited_once()
            self.assertEqual(interaction.followup.send.await_count, 2)
        asyncio.run(run())
        self.assertEqual(db.load_doc('cards_crates.json')['1']['basic'], 0)
        self.assertEqual(len(db.load_doc('cards_inventory.json')), 1)
        self.assertEqual(db.load_doc('summon_luck.json')['1']['clovers'], 0)


class LuckAnimationTests(unittest.TestCase):
    def test_tickets_fill_in_order_and_clover_appears_at_ten(self):
        async def run():
            message = SimpleNamespace(edit=AsyncMock())
            reward = SimpleNamespace(tickets=10, clovers_before=4, clovers=5, jackpot=True)
            with patch.object(asyncio, 'sleep', new=AsyncMock()):
                await Summon(None)._animate_luck(message, None, reward)
            calls = message.edit.await_args_list
            self.assertEqual(len(calls), 10)
            for count, call in enumerate(calls, 1):
                self.assertNotIn('attachments', call.kwargs)
                meters = call.kwargs['embeds'][1]
                self.assertEqual(meters.fields[0].value.count('🎟️'), count)
                self.assertEqual(meters.fields[1].value.count('🍀'), 5 if count == 10 else 4)
                self.assertEqual(bool(meters.description), count == 10)
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
