import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.database import db
from src.database.profiles import load_profiles, save_profiles
from src.logic.spirit_bond import change_bond
from src.logic import spirits


class BondTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/bond.db'
        db.reset_for_tests(self.path)
        save_profiles({'1:1': {'spirits': [dict(name='Vexx', rank=3, fury=100, fury_max=100, fury_cur=40, xp=22, element='ohen')]}})

    def tearDown(self):
        db.reset_for_tests(self.tmp.name + '/closed.db')
        self.tmp.cleanup()

    def start(self, channel=42, **kwargs):
        return change_bond(channel, 'start', profile_key='1:1', user_id=1, spirit_name='Vexx', **kwargs)

    def test_three_successes_persist_and_evolve_once(self):
        self.start()
        change_bond(42, 'success', interaction_id=1)
        db.reset_for_tests(self.path)
        self.assertEqual(change_bond(42, 'success', interaction_id=2)['successes'], 2)
        result = change_bond(42, 'success', interaction_id=3)
        self.assertEqual((result['old_maximum'], result['new_maximum']), (100, 200))
        spirit = load_profiles()['1:1']['spirits'][0]
        self.assertEqual((spirit['fury_cur'], spirit['fury_max'], spirit['rank'], spirit['xp']), (140, 200, 3, 22))
        with self.assertRaises(ValueError):
            change_bond(42, 'success')
        self.assertEqual(load_profiles()['1:1']['spirits'][0]['bond_evolutions'], 1)

    def test_custom_reward_and_invalid_override_does_not_advance(self):
        self.start()
        with self.assertRaises(ValueError):
            change_bond(42, 'success', new_maximum=250)
        change_bond(42, 'success')
        change_bond(42, 'success')
        with self.assertRaises(ValueError):
            change_bond(42, 'success', new_maximum=99)
        result = change_bond(42, 'success', new_maximum=250)
        self.assertEqual(result['new_maximum'], 250)
        self.assertEqual(load_profiles()['1:1']['spirits'][0]['fury_cur'], 190)

    def test_fail_cancels_and_new_start_resets(self):
        self.start()
        change_bond(42, 'success')
        change_bond(42, 'fail')
        self.assertEqual(load_profiles()['1:1']['spirits'][0]['fury_max'], 100)
        self.start()
        self.assertEqual(change_bond(42, 'success')['successes'], 1)

    def test_channel_and_spirit_conflicts_and_duplicate_interaction(self):
        self.start(interaction_id=10)
        with self.assertRaises(ValueError):
            self.start()
        with self.assertRaises(ValueError):
            self.start(channel=43)
        change_bond(42, 'success', interaction_id=11)
        with self.assertRaises(ValueError):
            change_bond(42, 'success', interaction_id=11)
        self.assertEqual(change_bond(42, 'success')['successes'], 2)

    def test_renamed_spirit_is_bound_by_id_and_deleted_spirit_can_be_cancelled(self):
        self.start()
        data = load_profiles()
        data['1:1']['spirits'][0]['name'] = 'New name'
        data['1:2'] = {'spirits': []}
        save_profiles(data)
        self.assertEqual(change_bond(42, 'success')['spirit_name'], 'New name')
        data = load_profiles()
        data['1:1']['spirits'] = []
        save_profiles(data)
        with self.assertRaises(ValueError):
            change_bond(42, 'success')
        change_bond(42, 'fail')
        self.assertEqual(load_profiles()['1:1']['spirit_bonds'], {})


class BondCommands(unittest.IsolatedAsyncioTestCase):
    async def test_permission_denial_does_not_change_state(self):
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(spirits, '_is_dm', return_value=False), patch('src.logic.spirit_bond.change_bond') as change:
            await spirits.Spirits(None)._bond_action(interaction, 'success')
            change.assert_not_called()
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])

    async def test_dm_message_is_a_single_quiet_line(self):
        interaction = SimpleNamespace(channel_id=42, id=100, response=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(spirits, '_is_dm', return_value=True), patch('src.logic.spirit_bond.change_bond', return_value=dict(user_id=1, spirit_name='Vexx', successes=1)):
            await spirits.Spirits(None)._bond_action(interaction, 'start')
        self.assertEqual(interaction.response.send_message.call_args.args[0], '-# <@1> se sbližuje s duchem Vexx.')

    async def test_bond_commands_only_exist_on_dm_tree(self):
        import discord
        from discord.ext import commands
        from src.utils.admin_gate import keep_only_admin, drop_admin_commands
        for admin in [False, True]:
            bot = commands.Bot(command_prefix='!', intents=discord.Intents.none())
            await bot.add_cog(spirits.Spirits(bot))
            (keep_only_admin if admin else drop_admin_commands)(bot)
            bond = bot.tree.get_command('duch').get_command('bond')
            self.assertEqual(bond is not None, admin)
            if admin:
                self.assertEqual({c.name for c in bond.commands}, {'start', 'success', 'fail'})
            await bot.close()
