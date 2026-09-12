"""Testy logu boje, undo a perkových buffů."""

import unittest

from src.logic import combat


def _combat(hp: int = 30, fur: int = 0) -> dict:
    return {
        "order": ["<@1>", "Goblin"],
        "stats": {"Goblin": {"hp": hp, "max_hp": 30, "def": 0, "fur": fur}},
        "round": 1,
    }


class TestCombatLog(unittest.TestCase):
    def _hit(self, state: dict, dmg: int, actor: str = "<@1>") -> dict:
        stat = state["stats"]["Goblin"]
        before = combat.stat_snapshot(stat)
        result = combat.apply_hit(stat, dmg)
        return combat.log_event(state, "attack", "Goblin", before,
                                combat.stat_snapshot(stat),
                                detail=result["change_str"], actor=actor)

    def test_event_records_before_after(self):
        state = _combat()
        event = self._hit(state, 7)
        self.assertEqual(event["before"]["hp"], 30)
        self.assertEqual(event["after"]["hp"], 23)
        self.assertEqual(event["id"], 1)
        self.assertEqual(len(state["log"]), 1)

    def test_ids_increment(self):
        state = _combat()
        self._hit(state, 1)
        self.assertEqual(self._hit(state, 1)["id"], 2)

    def test_log_is_capped(self):
        state = _combat(hp=999)
        for _ in range(combat.LOG_LIMIT + 10):
            self._hit(state, 0)
        self.assertEqual(len(state["log"]), combat.LOG_LIMIT)

    def test_undo_restores_hp_and_fury(self):
        state = _combat(fur=5)
        self._hit(state, 12)
        self.assertEqual(state["stats"]["Goblin"]["hp"], 23)
        event = combat.undo_last(state)
        self.assertIsNotNone(event)
        self.assertEqual(state["stats"]["Goblin"]["hp"], 30)
        self.assertEqual(state["stats"]["Goblin"]["fur"], 5)

    def test_undo_goes_backwards_once_each(self):
        state = _combat()
        self._hit(state, 5)
        self._hit(state, 10)
        combat.undo_last(state)
        self.assertEqual(state["stats"]["Goblin"]["hp"], 25)
        combat.undo_last(state)
        self.assertEqual(state["stats"]["Goblin"]["hp"], 30)
        self.assertIsNone(combat.undo_last(state))

    def test_undo_skips_removed_target(self):
        state = _combat()
        self._hit(state, 5)
        del state["stats"]["Goblin"]
        self.assertIsNone(combat.undo_last(state))

    def test_format_marks_undone(self):
        state = _combat()
        self._hit(state, 5)
        combat.undo_last(state)
        self.assertIn("~~", combat.format_log_event(state["log"][-1]))


class TestSummary(unittest.TestCase):
    def _state(self) -> dict:
        state = _combat()
        state["stats"]["<@1>"] = {"hp": 20, "max_hp": 20, "def": 0, "fur": 0}
        return state

    def _event(self, state, target, delta, actor=None):
        stat = state["stats"][target]
        before = combat.stat_snapshot(stat)
        stat["hp"] = max(0, stat["hp"] - delta)
        combat.log_event(state, "attack", target, before,
                         combat.stat_snapshot(stat), actor=actor)

    def test_tally_sorted_by_damage(self):
        state = self._state()
        self._event(state, "Goblin", 5, actor="<@1>")
        self._event(state, "Goblin", 7, actor="<@2>")
        self._event(state, "<@1>", 3, actor="Goblin")
        tally = dict(combat.damage_tally(state))
        self.assertEqual(tally["<@2>"]["dealt"], 7)
        self.assertEqual(tally["<@1>"], {"dealt": 5, "taken": 3, "healed": 0})
        self.assertEqual(combat.damage_tally(state)[0][0], "<@2>")

    def test_heal_counts_separately(self):
        state = self._state()
        self._event(state, "<@1>", 10, actor="Goblin")
        self._event(state, "<@1>", -6)
        tally = dict(combat.damage_tally(state))
        self.assertEqual(tally["<@1>"]["healed"], 6)
        self.assertEqual(tally["<@1>"]["taken"], 10)

    def test_undone_events_ignored(self):
        state = self._state()
        self._event(state, "Goblin", 9, actor="<@1>")
        combat.undo_last(state)
        self.assertEqual(combat.damage_tally(state), [])

    def test_wipeout_detects_dead_side(self):
        state = self._state()
        self.assertIsNone(combat.wipeout_side(state))
        state["stats"]["Goblin"]["hp"] = 0
        self.assertEqual(combat.wipeout_side(state), "npc")
        state["stats"]["<@1>"]["hp"] = 0
        self.assertEqual(combat.wipeout_side(state), "players")

    def test_no_wipeout_without_both_sides(self):
        state = _combat()
        state["stats"]["Goblin"]["hp"] = 0
        self.assertIsNone(combat.wipeout_side(state))

    def test_summary_embed_lists_fallen(self):
        state = self._state()
        self._event(state, "Goblin", 30, actor="<@1>")
        embed = combat.build_summary_embed(state, "Konec")
        self.assertIn("<@1>", embed.description)
        self.assertEqual(embed.fields[1].value, "Goblin")


class TestPerkBuffs(unittest.TestCase):
    def test_attack_scope_is_consumed(self):
        state = _combat()
        combat.add_perk_buff(state, "<@1>", "rana", "Těžká rána", "1d6")
        self.assertEqual(len(combat.take_attack_buffs(state, "<@1>")), 1)
        self.assertEqual(combat.take_attack_buffs(state, "<@1>"), [])

    def test_round_scope_survives_attack(self):
        state = _combat()
        combat.add_perk_buff(state, "<@1>", "zur", "Zuřivost", "2", scope="round")
        combat.take_attack_buffs(state, "<@1>")
        self.assertEqual(len(combat.take_attack_buffs(state, "<@1>")), 1)

    def test_clear_buffs_on_turn_end(self):
        state = _combat()
        combat.add_perk_buff(state, "<@1>", "zur", "Zuřivost", "2", scope="round")
        combat.clear_buffs(state, "<@1>")
        self.assertEqual(combat.take_attack_buffs(state, "<@1>"), [])

    def test_buffs_are_per_actor(self):
        state = _combat()
        combat.add_perk_buff(state, "<@1>", "rana", "Těžká rána", "1d6")
        self.assertEqual(combat.take_attack_buffs(state, "<@2>"), [])


if __name__ == "__main__":
    unittest.main()
