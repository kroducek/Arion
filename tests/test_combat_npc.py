"""Zbraně NPC a záznam minutého útoku v logu boje."""

import unittest

from src.logic import combat
from src.logic.dice import DiceError


def _combat() -> dict:
    return {
        "order": ["<@1>", "Goblin"],
        "stats": {
            "<@1>": {"hp": 20, "max_hp": 20, "def": 0, "fur": 0},
            "Goblin": {"hp": 30, "max_hp": 30, "def": 0, "fur": 0},
        },
        "round": 1,
    }


class TestNpcWeapons(unittest.TestCase):
    def test_hole_cislo_je_kostka(self):
        stat = {}
        weapon = combat.set_npc_weapon(stat, "main", "16", "Palcát")
        self.assertEqual(weapon, {"dmg": "1d16", "name": "Palcát"})
        self.assertEqual(combat.npc_weapon(stat, "main"), weapon)

    def test_kostkovy_vyraz_zustava(self):
        stat = {}
        combat.set_npc_weapon(stat, "bonus", "2d6+1")
        self.assertEqual(combat.npc_weapon(stat, "bonus")["dmg"], "2d6+1")

    def test_nesmyslny_vyraz_neprojde(self):
        stat = {}
        with self.assertRaises(DiceError):
            combat.set_npc_weapon(stat, "main", "kladivo")
        self.assertIsNone(combat.npc_weapon(stat, "main"))

    def test_prazdny_vyraz_zbran_smaze(self):
        stat = {}
        combat.set_npc_weapon(stat, "main", "1d8")
        self.assertEqual(combat.set_npc_weapon(stat, "main", ""), {})
        self.assertIsNone(combat.npc_weapon(stat, "main"))

    def test_bez_nazvu_se_pouzije_slot(self):
        stat = {}
        weapon = combat.set_npc_weapon(stat, "bonus", "1d4")
        self.assertEqual(combat.npc_weapon_label(weapon, "bonus"), "bonusová zbraň")

    def test_prehled_zbrani(self):
        stat = {}
        combat.set_npc_weapon(stat, "main", "1d8", "Palcát")
        combat.set_npc_weapon(stat, "bonus", "1d4", "Dýka")
        line = combat.npc_weapons_line(stat)
        self.assertIn("Palcát `1d8`", line)
        self.assertIn("Dýka `1d4`", line)

    def test_npc_utok_se_hodi_ze_zbrane(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        combat.set_npc_weapon(stat, "main", "1d1", "Palcát")
        roll = combat.roll_expr(combat.npc_weapon(stat, "main")["dmg"])
        target = state["stats"]["<@1>"]
        before = combat.stat_snapshot(target)
        result = combat.apply_hit(target, roll.total)
        combat.log_event(state, "attack", "<@1>", before,
                         combat.stat_snapshot(target),
                         detail=result["change_str"], actor="Goblin")
        self.assertEqual(target["hp"], 19)
        self.assertEqual(state["log"][-1]["actor"], "Goblin")

    def test_npc_ma_vlastni_pojistku_akci(self):
        state = _combat()
        self.assertTrue(combat.use_action(state, "Goblin", "attack"))
        self.assertFalse(combat.use_action(state, "Goblin", "attack"))
        self.assertTrue(combat.use_action(state, "Goblin", "bonus"))
        self.assertTrue(combat.use_action(state, "Goblin", "attack", force=True))


class TestMissLog(unittest.TestCase):
    def _miss(self, state: dict) -> dict:
        snapshot = combat.stat_snapshot(state["stats"]["Goblin"])
        return combat.log_event(state, "miss", "Goblin", snapshot, snapshot,
                                detail="Luk — minul (7 dmg)", actor="<@1>",
                                revert=False)

    def test_minuti_je_v_logu(self):
        state = _combat()
        event = self._miss(state)
        self.assertEqual(state["log"], [event])
        self.assertIn("minul", combat.format_log_event(event))

    def test_undo_minuti_preskoci(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        before = combat.stat_snapshot(stat)
        combat.apply_hit(stat, 10)
        hit = combat.log_event(state, "attack", "Goblin", before,
                               combat.stat_snapshot(stat), actor="<@1>")
        self._miss(state)

        undone = combat.undo_last(state)
        self.assertEqual(undone["id"], hit["id"])
        self.assertEqual(stat["hp"], 30)
        self.assertIsNone(combat.undo_last(state))

    def test_minuti_se_nepocita_do_shrnuti(self):
        state = _combat()
        self._miss(state)
        self.assertEqual(combat.damage_tally(state), [])


if __name__ == "__main__":
    unittest.main()
