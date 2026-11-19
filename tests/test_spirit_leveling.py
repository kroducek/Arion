import unittest
from copy import deepcopy

from src.logic import furioku


class SpiritLevelingTests(unittest.TestCase):
    def make_profile(self):
        return {
            'main_spirit_id': 'main',
            'spirits': [
                dict(id='main', name='Main', rank=1, xp=0, total_xp=0,
                     xp_threshold=100, fury=100, fury_max=100, fury_cur=40),
                dict(id='other', name='Other', rank=4, xp=50, total_xp=1032,
                     xp_threshold=918, fury=200, fury_max=200, fury_cur=100),
            ],
        }

    def test_rank_up_boundaries_match_approved_table(self):
        costs = [3000, 9090, 17370, 27540, 39390, 52740,
                 67470, 83550, 100890, 119430, 139080, 159870]
        profile = self.make_profile()
        spirit = profile['spirits'][0]
        for rank, cost in enumerate(costs, start=1):
            with self.subTest(rank=rank):
                result = furioku.grant_xp(profile, cost - 1)
                self.assertFalse(result[0]['ranked_up'])
                self.assertEqual(spirit['rank'], rank)
                self.assertEqual(spirit['xp'], cost - 1)
                self.assertEqual(spirit['xp_threshold'], cost)

                result = furioku.grant_xp(profile, 1)
                self.assertTrue(result[0]['ranked_up'])
                self.assertEqual(spirit['rank'], rank + 1)
                self.assertEqual(spirit['xp'], 0)

    def test_bulk_reward_reaches_rank_12_and_keeps_remainder(self):
        profile = self.make_profile()
        result = furioku.grant_xp(profile, 659550 + 17)
        spirit, other = profile['spirits']
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['old_rank'], result[0]['new_rank']), (1, 12))
        self.assertEqual((spirit['rank'], spirit['xp'], spirit['total_xp']),
                         (12, 17, 659567))
        self.assertEqual(spirit['xp_threshold'], 159870)
        self.assertEqual((spirit['fury_max'], spirit['fury_cur']), (1151, 1091))
        self.assertEqual((other['rank'], other['xp'], other['total_xp']),
                         (4, 50, 1032))

    def test_existing_spirits_refresh_thresholds_without_resetting_progress(self):
        profile = self.make_profile()
        spirit = profile['spirits'][0]
        spirit.update(rank=12, xp=1234, total_xp=23219, xp_threshold=5329)
        previous = deepcopy(profile['spirits'])

        furioku.normalize(profile)
        for before, after, cost in zip(previous, profile['spirits'], (159870, 27540)):
            self.assertEqual(after, {**before, 'xp_threshold': cost})
        self.assertEqual(profile['main_spirit_id'], 'main')

        normalized = deepcopy(profile)
        furioku.normalize(profile)
        self.assertEqual(profile, normalized)
