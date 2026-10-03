"""Attack lifecycle tests against a real isolated SQLite database."""
import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from src.database import db
from src.logic import attack_flow as f, combat as c, furioku as energy
from src.logic import attack_ui as ui
from src.utils.paths import CHARACTERS
from src.utils.json_utils import save_json


def profile():
    p = dict(hp_cur=100, hp_max=100, mana_cur=20, mana_max=20,
             fury_cur=20, fury_max=20, spirits=[], stats={'DEX': 8},
             equipment={'hand_r': 'bow'}, inventory=[{'type': 'registered', 'id': 'arrow', 'qty': 5}])
    energy.normalize(p)
    p['furioka'].update(atk_amount=5, def_amount=4)
    return p


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = db.db_path()
        db.reset_for_tests(self.tmp.name + '/test.db')
        self.addCleanup(self.cleanup)
        db.save_doc(f.PROFILES_DOC, {'1:1': profile(), '2:1': profile()})
        db.save_doc(f.PERKS_DOC, {'1:1': {'perks': [energy.UTOK, energy.OBRANA]},
                                '2:1': {'perks': [energy.UTOK, energy.OBRANA, 'barrier'], 'cooldowns': {}}})
        state = dict(order=['<@1>', '<@2>', 'NPC'], locked=True, current_index=0, round=1,
            stats={actor:dict(hp=100, max_hp=100, fur=0, **{'def': 0}) for actor in ['<@1>', '<@2>', 'NPC']})
        db.save_doc(f.COMBAT, {'123': state})
        items = {'bow': {'name': 'Luk', 'dmg': '10+0', 'category': 'luky_kuše', 'mana_cost': 3},
                 'arrow': {'name': 'Šíp', 'category': c.AMMO_CATEGORY, 'dmg': '2+0'}}
        self.items = patch.object(c, '_load_items_db', return_value=items)
        self.items.start()
        self.addCleanup(self.items.stop)
        self.perks = patch('src.core.dnd.perks.load_perks', return_value={'barrier': {'cooldown_uses': 3}})
        self.perks.start()
        self.addCleanup(self.perks.stop)

    def cleanup(self):
        db.reset_for_tests(self.previous)
        self.tmp.cleanup()

    def state(self):
        return db.load_doc(f.COMBAT)['123']

    def profiles(self):
        return db.load_doc(f.PROFILES_DOC)

    def attack(self, **kwargs):
        return f.prepare(123, '<@1>', '<@2>', ammo='arrow', **kwargs)

    def ready(self, **kwargs):
        a = self.attack(**kwargs)
        return f.update_reaction(123, a['id'], 2, False, 'Uhnu stranou.')

    def test_hit_consumes_both_pools_and_undo_restores_everything(self):
        a = self.ready()
        f.confirm_cost(123, a['id'], True, mana=4, reaction=True, perk_id='barrier')
        result = f.resolve(123, a['id'], True, 'hit')
        self.assertEqual(self.profiles()['1:1']['fury_cur'], 15)
        self.assertEqual(self.profiles()['2:1']['fury_cur'], 16)
        self.assertEqual(self.profiles()['2:1']['hp_cur'], 87)  # 12 + 5 - 4
        self.assertEqual(self.profiles()['1:1']['mana_cur'], 17)
        self.assertEqual(self.profiles()['2:1']['mana_cur'], 16)
        self.assertNotIn(a['id'], self.state()['pending_attacks'])
        self.assertTrue(result['event']['resources']['flow'])
        self.assertIsNotNone(f.undo(123))
        for key in ['1:1', '2:1']:
            self.assertEqual(self.profiles()[key]['fury_cur'], 20)
            self.assertEqual(self.profiles()[key]['hp_cur'], 100)
            self.assertEqual(self.profiles()[key]['mana_cur'], 20)
        self.assertEqual(c._ammo_count(self.profiles()['1:1'], 'arrow'), 5)
        self.assertEqual(db.load_doc(f.PERKS_DOC)['2:1']['cooldowns'], {})
        self.assertEqual(self.state()['turn_state']['<@2>']['reaction'], 0)
        self.assertIsNone(f.undo(123))

    def test_override_includes_furioku_before_defense(self):
        a = self.ready()
        f.resolve(123, a['id'], True, 'hit', damage=10)
        self.assertEqual(self.profiles()['2:1']['hp_cur'], 94)  # 10 - 4, no extra 5
        self.assertEqual(self.profiles()['1:1']['fury_cur'], 15)

    def test_miss_keeps_furioku_but_pays_ammo_mana_and_defense(self):
        a = self.ready()
        f.confirm_cost(123, a['id'], True, mana=4, reaction=True)
        f.resolve(123, a['id'], True, 'miss')
        self.assertEqual(self.profiles()['1:1']['fury_cur'], 20)
        self.assertEqual(self.profiles()['1:1']['mana_cur'], 17)
        self.assertEqual(self.profiles()['2:1']['mana_cur'], 16)
        self.assertEqual(self.profiles()['2:1']['hp_cur'], 100)
        self.assertEqual(c._ammo_count(self.profiles()['1:1'], 'arrow'), 4)
        f.undo(123)
        self.assertEqual(c._ammo_count(self.profiles()['1:1'], 'arrow'), 5)
        self.assertEqual(self.profiles()['2:1']['mana_cur'], 20)

    def test_cancel_refund_choice(self):
        for refund in (False, True):
            a = self.attack()
            before = self.profiles()['2:1']['mana_cur']
            f.confirm_cost(123, a['id'], True, mana=2)
            f.resolve(123, a['id'], True, 'cancel', refund=refund)
            self.assertEqual(self.profiles()['2:1']['mana_cur'], before if refund else before-2)
            self.assertEqual(c._ammo_count(self.profiles()['1:1'], 'arrow'), 5)
            self.assertEqual(self.state()['turn_state']['<@1>']['attack'], 0)

    def test_already_paid_does_not_charge_or_refund(self):
        a = self.ready()
        f.confirm_cost(123, a['id'], True, mana=7, reaction=True, perk_id='barrier', already_paid=True)
        f.resolve(123, a['id'], True, 'miss')
        f.undo(123)
        self.assertEqual(self.profiles()['2:1']['mana_cur'], 20)
        self.assertEqual(db.load_doc(f.PERKS_DOC)['2:1']['cooldowns'], {})

    def test_double_resolve_concurrently_only_charges_once(self):
        a = self.ready()
        def run(_):
            try:
                return f.resolve(123, a['id'], True, 'hit')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.profiles()['1:1']['mana_cur'], 17)
        self.assertEqual(len(self.state()['log']), 1)

    def test_failure_rolls_back_all_documents(self):
        a = self.ready()
        before = [db.load_doc(d) for d in (f.COMBAT, f.PROFILES_DOC, f.PERKS_DOC)]
        with patch.object(c, 'apply_hit', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                f.resolve(123, a['id'], True, 'hit')
        self.assertEqual(before, [db.load_doc(d) for d in (f.COMBAT, f.PROFILES_DOC, f.PERKS_DOC)])

    def test_reaction_and_decision_permissions(self):
        a = self.attack()
        with self.assertRaises(ValueError):
            f.update_reaction(123, a['id'], 1, False, 'uhnu')
        with self.assertRaises(ValueError):
            f.resolve(123, a['id'], False, 'hit', bypass=True)
        with self.assertRaises(ValueError):
            f.request_roll(123, a['id'], False, 'cíl', '1d20')
        with self.assertRaises(ValueError):
            f.confirm_cost(123, a['id'], False, mana=3)
        with self.assertRaises(ValueError):
            f.resolve(123, a['id'], True, 'hit')
        f.resolve(123, a['id'], True, 'miss', bypass=True)

    def test_invalid_dice_does_not_spend_action(self):
        with self.assertRaises(ValueError):
            f.prepare(123, 'NPC', '<@1>', dm=True, force=True, npc_expr='invalid')
        self.assertNotIn('turn_state', self.state())

    def test_out_of_turn_locked_and_nonparticipant(self):
        with self.assertRaises(ValueError):
            f.prepare(123, '<@2>', '<@1>', ammo='arrow')
        with self.assertRaises(ValueError):
            f.prepare(123, '<@9>', '<@1>', dm=True, force=True)
        a = f.prepare(123, '<@2>', '<@1>', ammo='arrow', dm=True, force=True)
        self.assertEqual(a['attacker'], '<@2>')

    def test_roll_once_and_dm_reroll_preserves_first(self):
        a = self.ready()
        a = f.request_roll(123, a['id'], True, 'cíl', '1d20', ['DEX'], 'Úhyb')
        r = a['requests'][0]
        with patch('src.logic.dice.random.randint', return_value=11):
            _, rolled = f.submit_roll(123, a['id'], r['id'], 2)
        self.assertEqual(rolled['result']['total'], 11)
        self.assertEqual(rolled['result']['stats']['DEX'], 8)
        with self.assertRaises(ValueError):
            f.submit_roll(123, a['id'], r['id'], 2)
        a = f.request_roll(123, a['id'], True, 'cíl', '1d20', ['DEX'], reroll=r['id'])
        self.assertTrue(a['requests'][0]['superseded'])
        self.assertEqual(a['requests'][0]['result']['total'], 11)
        with self.assertRaises(ValueError):
            f.request_roll(123, a['id'], True, 'cíl', '1d20', reroll=r['id'])
        with self.assertRaises(ValueError):
            f.resolve(123, a['id'], True, 'hit')
        f.submit_roll(123, a['id'], a['requests'][-1]['id'], 2)
        f.resolve(123, a['id'], True, 'hit')
        self.assertEqual(len(self.state()['log'][0]['flow_attack']['requests']), 2)

    def test_restart_and_bound_character(self):
        a = self.ready()
        a = f.request_roll(123, a['id'], True, 'cíl', '1d20', ['DEX'])
        f.attach_message(123, a['id'], 77, 55)
        db.reset_for_tests(self.tmp.name + '/test.db')
        self.assertEqual(self.state()['pending_attacks'][a['id']]['message_id'], '77')
        save_json(CHARACTERS, {'2': {'active': '2'}})
        with self.assertRaises(ValueError):
            f.submit_roll(123, a['id'], a['requests'][0]['id'], 2)
        # DM resolution writes to the original bound character regardless of active slot.
        f.resolve(123, a['id'], True, 'hit', bypass=True)
        self.assertEqual(self.profiles()['2:1']['hp_cur'], 87)

    def test_roll_permissions_and_npc(self):
        a = self.ready()
        a = f.request_roll(123, a['id'], True, 'NPC', '1d20')
        r = a['requests'][0]
        with self.assertRaises(ValueError):
            f.submit_roll(123, a['id'], r['id'], 1)
        f.submit_roll(123, a['id'], r['id'], 99, dm=True)

    def test_cost_failure_rolls_back_mana(self):
        a = self.ready()
        f.transaction(123, lambda s,p,k: c.use_action(s, '<@2>', 'reaction'))
        with self.assertRaises(ValueError):
            f.confirm_cost(123, a['id'], True, mana=4, reaction=True)
        self.assertEqual(self.profiles()['2:1']['mana_cur'], 20)
        self.assertEqual(self.state()['pending_attacks'][a['id']]['costs'], [])

    def test_refund_does_not_reset_a_later_turn_reaction(self):
        a = self.ready()
        f.confirm_cost(123, a['id'], True, reaction=True)
        def next_turn(s,p,k):
            c.reset_turn(s, '<@2>', reaction=True)
            c.use_action(s, '<@2>', 'reaction')
        f.transaction(123, next_turn)
        f.resolve(123, a['id'], True, 'cancel', refund=True)
        self.assertEqual(self.state()['turn_state']['<@2>']['reaction'], 1)

    def test_new_turn_refreshes_only_that_actor(self):
        state = self.state()
        c.use_action(state, '<@1>', 'reaction')
        c.use_action(state, '<@2>', 'reaction')
        c.reset_turn(state, '<@1>', reaction=True)
        self.assertEqual(state['turn_state']['<@1>']['reaction'], 0)
        self.assertEqual(state['turn_state']['<@2>']['reaction'], 1)

    def test_two_requests_selection_does_not_roll(self):
        a = self.ready()
        for note in ['první', 'druhý']:
            f.request_roll(123, a['id'], True, 'cíl', '1d20', ['DEX'], note)
        self.assertEqual(len(f.available_rolls(123, 2, expr='1d20', attrs=['DEX'])), 2)
        self.assertEqual(f.available_rolls(123, 2, expr='1d6', attrs=['DEX']), [])

    def test_stale_tracker_save_does_not_resurrect_resolved_attack(self):
        a = self.ready()
        cog = c.CombatCog(None)
        f.resolve(123, a['id'], True, 'hit')
        # Another bot had loaded the old attack before the hit, and changes only a tracker setting.
        cog.active_combats[123]['auto_tick'] = False
        cog._save_state()
        self.assertNotIn(a['id'], self.state()['pending_attacks'])
        self.assertEqual(self.state()['stats']['<@2>']['hp'], 87)
        self.assertEqual(len(self.state()['log']), 1)
        self.assertFalse(self.state()['auto_tick'])

    def test_conflicting_stale_tracker_write_cannot_overwrite_hit(self):
        a = self.ready()
        cog = c.CombatCog(None)
        f.resolve(123, a['id'], True, 'hit')
        cog.active_combats[123]['stats']['<@2>']['hp'] = 99
        with self.assertRaises(ValueError):
            cog._save_state()
        self.assertEqual(self.state()['stats']['<@2>']['hp'], 87)

    def test_rune_delivery_without_nested_database_write(self):
        def add_rune(s,p,k):
            p['1:1']['inventory'].append(dict(type='registered', id='bow', runes=['jed_1']))
        f.transaction(123, add_rune)
        a = self.ready()
        self.assertIn(('jed', 'runa'), [tuple(x) for x in a['extra_statuses']])
        f.resolve(123, a['id'], True, 'hit')
        self.assertTrue(self.profiles()['2:1']['statuses'])
        f.undo(123)
        self.assertFalse(self.profiles()['2:1']['statuses'])

    def test_npc_attributes_are_persistent_and_used_when_rolling(self):
        a = self.ready()
        a = f.request_roll(123, a['id'], True, 'NPC', '1d20', ['DEX'])
        attrs = f.set_npc_stats(123, 'NPC', True, {'DEX': 4, 'STR': 7})
        self.assertEqual(attrs['DEX'], 4)
        db.reset_for_tests(self.tmp.name + '/test.db')
        with patch('src.logic.dice.random.randint', return_value=6):
            _, rolled = f.submit_roll(123, a['id'], a['requests'][0]['id'], 99, dm=True)
        self.assertEqual(rolled['result']['total'], 6)
        self.assertEqual(rolled['result']['stats']['DEX'], 4)
        f.set_npc_stats(123, 'NPC', True, {'DEX': 9})
        self.assertEqual(f.set_npc_stats(123, 'NPC', True, {})['STR'], 7)
        saved = self.state()['pending_attacks'][a['id']]['requests'][0]['result']
        self.assertEqual(saved['stats']['DEX'], 4)

    def test_npc_attributes_reject_players_invalid_values_and_non_dm(self):
        for actor, dm, values in [('<@1>', True, {'DEX': 4}), ('Missing', True, {'DEX': 4}),
                ('NPC', False, {'DEX': 4}), ('NPC', True, {'DEX': -1}), ('NPC', True, {'DEF': 4})]:
            with self.assertRaises(ValueError):
                f.set_npc_stats(123, actor, dm, values)
        self.assertEqual(f.set_npc_stats(123, 'NPC', True, {})['DEX'], 0)
        f.set_npc_stats(123, 'NPC', True, {'DEX': 0})
        self.assertEqual(self.profiles()['1:1']['stats']['DEX'], 8)

    def test_migration_does_not_double_reserve(self):
        a = self.attack()
        def old(s,p,k):
            legacy = s['pending_attacks'].pop(a['id'])
            legacy.pop('flow_version')
            s['pending_attacks']['77'] = legacy
        f.transaction(123, old)
        migrated = f.migrate_legacy(123, '77')
        self.assertEqual(migrated['id'], '77')
        self.assertEqual(c._ammo_count(self.profiles()['1:1'], 'arrow'), 4)
        f.resolve(123, '77', True, 'cancel')
        self.assertEqual(c._ammo_count(self.profiles()['1:1'], 'arrow'), 5)


class Routing(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_matches_do_not_roll_before_choice(self):
        i = SimpleNamespace(channel_id=123, user=SimpleNamespace(id=2, roles=[]),
                            response=SimpleNamespace(send_message=AsyncMock()))
        requests = [('a', dict(id=str(n), actor='<@2>', expr='1d20', attrs=['DEX'])) for n in range(2)]
        with patch.object(f, 'available_rolls', return_value=requests), patch.object(f, 'submit_roll') as submit:
            self.assertTrue(await ui.route_roll(i, '1d20', ['DEX']))
        submit.assert_not_called()
        self.assertIsInstance(i.response.send_message.call_args.kwargs['view'], ui.RollChoice)

    async def test_button_and_command_use_same_submission(self):
        i = SimpleNamespace(channel_id=123, user=SimpleNamespace(id=2, roles=[]))
        choices = [('a', dict(id='r', actor='<@2>', expr='1d20', attrs=['DEX']))]
        with patch.object(f, 'available_rolls', return_value=choices), patch.object(ui, 'perform_roll', new_callable=AsyncMock) as roll:
            await ui.route_roll(i, '1d20', ['DEX'])
            await ui.choose_roll(i, choices)
        self.assertEqual(roll.call_args_list[0], roll.call_args_list[1])

    async def test_unauthorized_modal_confirmation_cannot_apply(self):
        i = SimpleNamespace(user=SimpleNamespace(id=2, roles=[]), response=SimpleNamespace(is_done=lambda:False, send_message=AsyncMock()))
        view = ui.AttackView(object(), 123, data=dict(id='a', attacker='<@1>', target='<@2>', damage=4))
        with patch.object(f, 'resolve') as resolve:
            await view.decide(i, 'hit', damage=9, bypass=True)
        resolve.assert_not_called()


class DmPanel(unittest.IsolatedAsyncioTestCase):
    def data(self):
        return dict(id='a', flow_version=1, message_id='77', attacker='<@1>', target='<@2>',
                    damage=4, requests=[], reaction='', weapon_label='Meč')

    def interaction(self, dm=True):
        return SimpleNamespace(channel_id=123, message=SimpleNamespace(id=888),
            user=SimpleNamespace(id=9, roles=[SimpleNamespace(name='DM')] if dm else []),
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock(),
                                     edit_message=AsyncMock(), send_modal=AsyncMock()))

    async def test_lock_opens_ephemeral_admin_controls(self):
        public = ui.AttackView(object(), 123, data=self.data())
        self.assertEqual([b.label for b in public.children], ['Reakce', 'Hodit', 'DM'])
        i = self.interaction()
        with patch.object(public, 'fresh', new_callable=AsyncMock, return_value=public):
            await public.dm_panel.callback(i)
        sent = i.response.send_message.call_args.kwargs
        self.assertTrue(sent['ephemeral'])
        panel = sent['view']
        self.assertIsInstance(panel, ui.DmAttackView)
        self.assertEqual({b.label for b in panel.children},
                         {'Vyžádat hod', 'Náklady obrany', 'Přehodit', 'Zásah', 'Minutí', 'Upravit zásah', 'Zrušit'})
        self.assertTrue(panel.to_components())

    async def test_player_cannot_open_or_use_panel(self):
        public = ui.AttackView(object(), 123, data=self.data())
        i = self.interaction(dm=False)
        with patch.object(public, 'fresh', new_callable=AsyncMock) as fresh:
            await public.dm_panel.callback(i)
        fresh.assert_not_called()
        self.assertNotIn('view', i.response.send_message.call_args.kwargs)
        panel = ui.DmAttackView(object(), 123, data=self.data())
        self.assertFalse(await panel.interaction_check(i))
        with patch.object(f, 'resolve') as resolve:
            await panel.decide(i, 'hit', bypass=True)
        resolve.assert_not_called()

    async def test_private_modal_refresh_keeps_private_buttons_and_public_id(self):
        panel = ui.DmAttackView(object(), 123, data=self.data())
        i = self.interaction()
        with patch.object(db, 'load_doc', return_value={'123': {f.PENDING: {'a': self.data()}}}):
            fresh = await panel.fresh(i)
        self.assertIsInstance(fresh, ui.DmAttackView)
        self.assertEqual(fresh.message_id, '77')  # never bind to ephemeral message 888
        data = self.data()
        data['reaction'] = 'Bariéra'
        await fresh.refresh(i, data)
        edited = i.response.edit_message.call_args.kwargs
        self.assertIsInstance(edited['view'], ui.DmAttackView)
        self.assertIn('DM', edited['embed'].title)
        self.assertNotIn('DM', [b.label for b in edited['view'].children])
        self.assertEqual([b.label for b in ui.AttackView(object(), 123, data=data).children],
                         ['Reakce', 'Hodit', 'DM'])

    async def test_closed_attack_does_not_open_stale_panel(self):
        panel = ui.DmAttackView(object(), 123, data=self.data())
        i = self.interaction()
        with patch.object(db, 'load_doc', return_value={'123': {f.PENDING: {}}}):
            await panel.request.callback(i)
        i.response.send_modal.assert_not_called()
        i.response.send_message.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
