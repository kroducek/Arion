"""Testy combat updatu: kostky, damage itemů, zásah, pojistka akcí, consumables."""

import random
import unittest

from src.logic.dice import DiceError, item_damage_expr, roll_expr


class TestDice(unittest.TestCase):
    def test_flat_number(self):
        self.assertEqual(roll_expr("5").total, 5)

    def test_range(self):
        rng = random.Random(1)
        for _ in range(50):
            result = roll_expr("2d6+3", rng)
            self.assertTrue(5 <= result.total <= 15)

    def test_minus(self):
        rng = random.Random(2)
        result = roll_expr("1d1-1", rng)
        self.assertEqual(result.total, 0)

    def test_nat20(self):
        rng = random.Random(0)
        results = [roll_expr("1d20", rng) for _ in range(200)]
        self.assertTrue(all(r.is_d20 for r in results))
        self.assertTrue(any(r.nat20 for r in results))
        self.assertTrue(any(r.nat1 for r in results))

    def test_invalid(self):
        for expr in ("", "abc", "1d20 + neco", "d20"):
            with self.assertRaises(DiceError):
                roll_expr(expr)

    def test_limits(self):
        with self.assertRaises(DiceError):
            roll_expr("200d6")
        with self.assertRaises(DiceError):
            roll_expr("1d5000")


class TestItemDamage(unittest.TestCase):
    def test_explicit_field(self):
        self.assertEqual(item_damage_expr({"dmg": "1d8+2"}), "1d8+2")

    def test_from_desc(self):
        item = {"desc": "Krásný meč.\nDMG: 2d6 + krvácení (1d4)"}
        self.assertEqual(item_damage_expr(item), "2d6")

    def test_atk_fallback(self):
        self.assertEqual(item_damage_expr({"atk": 7}), "7")

    def test_atk_dice(self):
        self.assertEqual(item_damage_expr({"atk": "4d6+1"}), "4d6+1")

    def test_atk_beats_desc(self):
        item = {"atk": "1d8", "desc": "DMG: 2d6"}
        self.assertEqual(item_damage_expr(item), "1d8")

    def test_broken_atk_falls_through(self):
        self.assertIsNone(item_damage_expr({"atk": "hodně"}))

    def test_none(self):
        self.assertIsNone(item_damage_expr({"name": "Chleba"}))
        self.assertIsNone(item_damage_expr(None))


class TestApplyHit(unittest.TestCase):
    def setUp(self):
        from src.logic import combat
        self.combat = combat

    def test_def_then_fury(self):
        stat = {"hp": 40, "max_hp": 40, "def": 3, "fur": 5}
        result = self.combat.apply_hit(stat, 12)
        self.assertEqual(stat["fur"], 0)        # 12-3=9, furioka pohltí 5
        self.assertEqual(result["dmg"], 4)
        self.assertEqual(stat["hp"], 36)

    def test_def_absorbs_all(self):
        stat = {"hp": 20, "max_hp": 20, "def": 10, "fur": 0}
        result = self.combat.apply_hit(stat, 8)
        self.assertEqual(result["dmg"], 0)
        self.assertEqual(stat["hp"], 20)

    def test_hp_floor(self):
        stat = {"hp": 3, "max_hp": 30, "def": 0, "fur": 0}
        self.combat.apply_hit(stat, 99)
        self.assertEqual(stat["hp"], 0)


class TestTurnState(unittest.TestCase):
    def setUp(self):
        from src.logic import combat
        self.combat = combat
        self.state = {}

    def test_attack_once_per_turn(self):
        self.assertTrue(self.combat.use_action(self.state, "<@1>", "attack"))
        self.assertFalse(self.combat.use_action(self.state, "<@1>", "attack"))

    def test_bonus_is_separate(self):
        self.combat.use_action(self.state, "<@1>", "attack")
        self.assertTrue(self.combat.use_action(self.state, "<@1>", "bonus"))

    def test_force_overrides(self):
        self.combat.use_action(self.state, "<@1>", "attack")
        self.assertTrue(
            self.combat.use_action(self.state, "<@1>", "attack", force=True))

    def test_reset_turn_keeps_reaction(self):
        self.combat.use_action(self.state, "<@1>", "attack")
        self.combat.use_action(self.state, "<@1>", "reaction")
        self.combat.reset_turn(self.state, "<@1>")
        self.assertTrue(self.combat.use_action(self.state, "<@1>", "attack"))
        self.assertFalse(self.combat.use_action(self.state, "<@1>", "reaction"))

    def test_reset_reactions_new_round(self):
        self.combat.use_action(self.state, "<@1>", "reaction")
        self.combat.reset_reactions(self.state)
        self.assertTrue(self.combat.use_action(self.state, "<@1>", "reaction"))

    def test_actors_are_independent(self):
        self.combat.use_action(self.state, "<@1>", "attack")
        self.assertTrue(self.combat.use_action(self.state, "<@2>", "attack"))


class TestWeaponLookup(unittest.TestCase):
    def setUp(self):
        from src.logic import combat
        self.combat = combat

    def test_prefers_engraved_piece(self):
        profile = {"inventory": [
            {"type": "registered", "id": "mec", "qty": 2},
            {"type": "registered", "id": "mec", "qty": 1, "runes": ["led_1"]},
        ]}
        entry = self.combat._weapon_entry(profile, "mec")
        self.assertEqual(entry["runes"], ["led_1"])

    def test_equipped_first(self):
        profile = {
            "equipment": {"hand_r": "luk"},
            "inventory": [{"type": "registered", "id": "mec", "qty": 1}],
        }
        self.assertEqual(self.combat._player_weapons(profile)[0], "luk")


class TestConsumableEntry(unittest.TestCase):
    def setUp(self):
        from src.logic import inventory
        self.inv = inventory

    def test_skips_engraved_piece(self):
        inventory = [
            {"type": "registered", "id": "dyka", "qty": 1, "runes": ["jed_1"]},
            {"type": "registered", "id": "dyka", "qty": 3},
        ]
        entry = self.inv._find_consumable_entry(inventory, "dyka")
        self.assertNotIn("runes", entry)
        self.inv._remove_entry(inventory, entry, 1)
        self.assertEqual(entry["qty"], 2)
        self.assertEqual(inventory[0]["runes"], ["jed_1"])

    def test_plain_consumable_removed(self):
        inventory = [{"type": "registered", "id": "lektvar", "qty": 1}]
        entry = self.inv._find_consumable_entry(inventory, "lektvar")
        self.inv._remove_entry(inventory, entry, 1)
        self.assertEqual(inventory, [])

    def test_engraved_only_is_fallback(self):
        inventory = [
            {"type": "registered", "id": "dyka", "qty": 1, "coating": {"hits": 2}},
        ]
        entry = self.inv._find_consumable_entry(inventory, "dyka")
        self.assertIn("coating", entry)   # volající takový kus odmítne spotřebovat


if __name__ == "__main__":
    unittest.main()
