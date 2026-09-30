"""Resource lifecycle: migration, multiple spirits, rest, XP, combat and undo."""
import copy
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

from src.logic import furioku as e, spirits, combat, stats, profile
from src.database import db
from src.database.profiles import load_profiles, save_profiles

PERKS = [e.UTOK, e.OBRANA, e.JEDNOTA]


def player():
    p = dict(hp_cur=100, hp_max=100, fury_cur=10, fury_max=20,
             spirits=[dict(name='A', rank=1, fury=40, element='ohen', description='original', xp=50, total_xp=50),
                      dict(name='B', rank=1, fury=60, element='ohen')], equipped_spirit_idx=0)
    e.normalize(p)
    p['equipped_spirit_ids'] = [s['id'] for s in p['spirits']]
    p['furioka'].update(spirit_ids=list(p['equipped_spirit_ids']), atk_amount=15, def_amount=30)
    return p


class Rules(unittest.TestCase):
    def test_legacy_migration_is_stable_and_preserves_equipped(self):
        p = dict(spirits=[dict(name='Old', rank=2, fury=80)], equipped_spirit_idx=0,
                 furioka=dict(use_spirit=True))
        e.normalize(p)
        before = copy.deepcopy(p)
        e.normalize(p)
        self.assertEqual(p, before)
        self.assertEqual(e.pool(p, PERKS), 80)
        self.assertEqual(p['spirits'][0]['fury_cur'], 80)

    def test_unlock_is_permanent_and_not_granted_by_empty_profile(self):
        p = {}
        e.normalize(p)
        self.assertFalse(p.get('furioku_unlocked'))
        p['vliv_svetlo'] = 1
        e.recalc(p)
        p['vliv_svetlo'] = 0
        e.recalc(p)
        self.assertTrue(p['furioku_unlocked'])

    def test_defense_respects_reservation_perks_and_spirit_order(self):
        p = player()
        self.assertEqual(e.absorb(p, 50, []), (50, 0))
        self.assertEqual(e.absorb(p, 50, PERKS), (20, 30))
        self.assertEqual(p['fury_cur'], 0)
        self.assertEqual([s['fury_cur'] for s in p['spirits']], [20, 60])
        self.assertEqual([s['fury_max'] for s in p['spirits']], [40, 60])
        self.assertEqual(e.attack(p, PERKS), 15)
        self.assertEqual(e.attack(p, PERKS), 0)

    def test_disconnect_does_not_refill_and_cannot_double_allocate(self):
        p = player()
        e.attack(p, PERKS)
        p['equipped_spirit_ids'] = []
        e.normalize(p)
        self.assertEqual(e.pool(p, PERKS), 0)
        self.assertEqual(e.bonuses(p, PERKS), (0, 0))
        p['equipped_spirit_ids'] = [s['id'] for s in p['spirits']]
        p['furioka']['spirit_ids'] = list(p['equipped_spirit_ids'])
        self.assertEqual(e.pool(p, PERKS), 95)

    def test_rest_recovers_unequipped_spirits_too(self):
        p = player()
        p['spirits'][0]['fury_cur'] = 0
        p['spirits'][1]['fury_cur'] = 10
        p['equipped_spirit_ids'] = []
        profile._rest_heal(p, .5)
        self.assertEqual(p['fury_cur'], 20)
        self.assertEqual([s['fury_cur'] for s in p['spirits']], [20, 40])

    def test_xp_goes_to_each_equipped_spirit_and_can_gain_multiple_ranks(self):
        p = player()
        result = e.grant_xp(p, 1000)
        self.assertTrue(all(r['new_rank'] >= 3 for r in result))
        self.assertEqual([s['total_xp'] for s in p['spirits']], [1050, 1000])
        p['equipped_spirit_ids'] = []
        self.assertEqual(e.grant_xp(p, 100), [])

    def test_breeding_preserves_identity_xp_element_and_equipment(self):
        for roll in [0, .999]:
            p = player()
            survivor = p['spirits'][0]
            original_id = survivor['id']
            with patch.object(spirits.random, 'random', return_value=roll):
                spirits.breed_spirits(p, 0, 1)
            self.assertEqual(len(p['spirits']), 1)
            self.assertIs(p['spirits'][0], survivor)
            self.assertEqual(survivor['id'], original_id)
            self.assertEqual(survivor['description'], 'original')
            self.assertEqual(survivor['element'], 'ohen')
            self.assertEqual(survivor['xp'], 50)
            self.assertEqual(p['equipped_spirit_ids'], [original_id])
            self.assertGreater(survivor['fury_max'], 40)

    def test_equipment_recalc_preserves_dm_bonus(self):
        from src.logic.inventory import _recalc_fury_from_vliv
        p = dict(vliv_svetlo=2, fury_max_bonus=50, fury_max=55, fury_cur=30)
        _recalc_fury_from_vliv(p)
        self.assertEqual((p['fury_max'], p['fury_cur']), (60, 35))


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db.reset_for_tests(self.temp.name + '/test.db')
        save_profiles({'1:1': player()})
        self.perks = patch('src.logic.spirits._owned_perks', return_value=PERKS)
        self.perks.start()
        self.c = dict(stats={'<@1>': dict(hp=100, max_hp=100, fur=10, **{'def': 5}),
                             'NPC': dict(hp=100, max_hp=100, fur=0, **{'def': 0})})
        combat._refresh_energy(self.c)

    def tearDown(self):
        self.perks.stop()
        db.reset_for_tests(self.temp.name + '/closed.db')
        self.temp.cleanup()

    def test_damage_writeback_reload_and_undo_restore_spirit_energy(self):
        stat = self.c['stats']['<@1>']
        before = combat.stat_snapshot(stat)
        combat.apply_hit(stat, 50)
        combat.log_event(self.c, 'attack', '<@1>', before, combat.stat_snapshot(stat))
        combat._writeback_player_state(1, stat)
        combat._refresh_energy(self.c)
        self.assertEqual(stat['hp'], 85)
        self.assertEqual(stat['energy']['spirits'][0]['fury_cur'], 20)
        self.assertEqual(load_profiles()['1:1']['fury_cur'], 0)
        combat.undo_last(self.c)
        combat._writeback_player_state(1, stat)
        combat._refresh_energy(self.c)
        self.assertEqual(stat['hp'], 100)
        self.assertEqual(stat['energy']['spirits'][0]['fury_cur'], 40)
        self.assertEqual(stat['energy']['furioka']['def_amount'], 30)

    def test_attack_consumes_once_and_undo_refunds_attacker(self):
        stat = self.c['stats']['NPC']
        resources = {'uid': 1}
        before = combat.stat_snapshot(stat)
        amount = combat._attack_energy(self.c, '<@1>', resources)
        combat.apply_hit(stat, 10 + amount)
        combat.log_event(self.c, 'attack', 'NPC', before, combat.stat_snapshot(stat), actor='<@1>', resources=resources)
        combat._writeback_attack(self.c, '<@1>', resources)
        self.assertEqual(stat['hp'], 75)
        self.assertEqual(load_profiles()['1:1']['spirits'][0]['fury_cur'], 35)
        event = combat.undo_last(self.c)
        combat.refund_resources(event)
        combat._refresh_energy(self.c)
        self.assertEqual(load_profiles()['1:1']['fury_cur'], 10)
        self.assertEqual(self.c['stats']['<@1>']['energy']['furioka']['atk_amount'], 15)

    def test_no_aura_means_no_automatic_shield_even_for_status_damage(self):
        self.c['stats']['<@1>']['energy_perks'] = []
        combat.apply_status_dmg(self.c['stats']['<@1>'], 20)
        self.assertEqual(self.c['stats']['<@1>']['hp'], 80)
        self.assertEqual(self.c['stats']['<@1>']['energy']['fury_cur'], 10)

    def test_admin_xp_path_rewards_all_equipped_spirits(self):
        result = stats.add_xp(1, 100)
        p = load_profiles()['1:1']
        self.assertEqual([s['total_xp'] for s in p['spirits']], [150, 100])
        self.assertEqual(len(result['spirits']), 2)

    def test_bound_character_not_current_slot_receives_writeback(self):
        p = load_profiles()
        p['1:2'] = player()
        save_profiles(p)
        stat = self.c['stats']['<@1>']
        combat.apply_hit(stat, 50)
        with patch.object(combat, '_pk', return_value='1:2'):
            combat._writeback_player_state(1, stat)
        self.assertEqual(load_profiles()['1:1']['fury_cur'], 0)
        self.assertEqual(load_profiles()['1:2']['fury_cur'], 10)


class Commands(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_hit_and_miss_through_real_combat_mutation(self):
        for hit in [False, True]:
            with tempfile.TemporaryDirectory() as directory:
                db.reset_for_tests(directory + '/test.db')
                save_profiles({'1:1': player()})
                with patch('src.logic.spirits._owned_perks', return_value=PERKS):
                    cog = combat.CombatCog(None)
                    cog.active_combats[123] = dict(stats={
                        '<@1>': dict(hp=100, max_hp=100, fur=10),
                        'NPC': dict(hp=100, max_hp=100, fur=0)}, order=['<@1>', 'NPC'])
                    cog._save_state()
                    cog._consume_weapon = lambda *args, **kwargs: {}
                    cog.check_wipeout = AsyncMock()
                    view = combat.AttackView(cog, 123, '<@1>', 1, 'NPC', 10, None,
                                             resources={'uid': 1})
                    view._replace_with_console = AsyncMock()
                    interaction = SimpleNamespace(channel=None,
                        response=SimpleNamespace(send_message=AsyncMock()))
                    if hit:
                        await view.resolve_hit(interaction, 10)
                        await view.resolve_hit(interaction, 10)  # duplicate confirmation
                    else:
                        view._ensure_state = AsyncMock(return_value=True)
                        view._may_resolve = lambda _: True
                        await view.miss.callback(interaction)
                    cog.reload_state()
                    p = load_profiles()['1:1']
                    self.assertEqual(p['fury_cur'], 0 if hit else 10)
                    self.assertEqual(p['furioka']['atk_amount'], 0 if hit else 15)
                    self.assertEqual(cog.active_combats[123]['stats']['NPC']['hp'], 75 if hit else 100)
                db.reset_for_tests(directory + '/closed.db')

    async def test_locked_command_only_displays_question_marks(self):
        interaction = SimpleNamespace(user=SimpleNamespace(id=1), response=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(spirits, '_load', return_value={}):
            await spirits.Spirits.furioku.callback(spirits.Spirits(None), interaction)
        interaction.response.send_message.assert_awaited_once_with('?????????', ephemeral=True)

    async def test_player_and_admin_command_split(self):
        from discord.ext import commands
        import discord
        from src.utils.admin_gate import drop_admin_commands, keep_only_admin
        for admin in [False, True]:
            bot = commands.Bot(command_prefix='!', intents=discord.Intents.none())
            await bot.add_cog(spirits.Spirits(bot))
            (keep_only_admin if admin else drop_admin_commands)(bot)
            self.assertEqual(bot.tree.get_command('furioku') is None, admin)
            duch = bot.tree.get_command('duch')
            self.assertEqual(duch.get_command('xp') is not None, admin)
            self.assertEqual(duch.get_command('equip') is None, admin)
            await bot.close()
