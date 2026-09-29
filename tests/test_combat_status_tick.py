"""Tik statusů: jed ubírá HP každý tah otráveného a hlásí se v konzoli."""

import unittest
from unittest import mock

from src.core.dnd import blacksmith as bs
from src.logic import combat


REG = {
    "jed": {"name": "Jed I.", "emoji": "🧪", "kind": "fyzický",
            "cure": "fyzické", "dmg": "1d5", "duration": 3,
            "tick": "kazde_kolo"},
}


def _cog() -> combat.CombatCog:
    return combat.CombatCog.__new__(combat.CombatCog)


def _combat() -> dict:
    return {
        "order": ["<@1>", "Goblin"],
        "stats": {
            "<@1>": {"hp": 20, "max_hp": 20, "def": 0, "fur": 0},
            "Goblin": {"hp": 30, "max_hp": 30, "def": 0, "fur": 0},
        },
        "current_index": 0,
        "round": 1,
    }


class TestNormTick(unittest.TestCase):
    def test_diakritika_i_mezery_se_srovnaji(self):
        for raw in ("každé_kolo", "Každé kolo", "KAZDE-KOLO", ""):
            self.assertEqual(bs.norm_tick(raw), "kazde_kolo")
        self.assertEqual(bs.norm_tick("při_zásahu"), "pri_zasahu")

    def test_status_s_diakritikou_tika(self):
        reg = {"jed": dict(REG["jed"], tick="každé_kolo")}
        carrier = {"statuses": []}
        bs.apply_status(carrier, "jed", "zbran", reg)
        dmg, log = bs.tick_statuses(carrier, reg)
        self.assertGreater(dmg, 0)
        self.assertTrue(log)


class TestTickActor(unittest.TestCase):
    def test_jed_ubere_hp_a_kolo(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        bs.apply_status(stat, "jed", "zbran", REG)
        with mock.patch.object(bs, "load_statuses", return_value=REG):
            lines = _cog()._tick_actor(state, "Goblin")
        self.assertLess(stat["hp"], 30)
        self.assertEqual(stat["statuses"][0]["kol_zbyva"], 2)
        self.assertTrue(any("Jed I." in line for line in lines))
        self.assertEqual(state["log"][-1]["kind"], "status")

    def test_jed_vyprchá_po_trvani(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        bs.apply_status(stat, "jed", "zbran", REG)
        cog = _cog()
        with mock.patch.object(bs, "load_statuses", return_value=REG):
            for _ in range(3):
                cog._tick_actor(state, "Goblin")
            self.assertEqual(stat["statuses"], [])
            self.assertEqual(cog._tick_actor(state, "Goblin"), [])

    def test_bez_statusu_zadny_vypis(self):
        state = _combat()
        with mock.patch.object(bs, "load_statuses", return_value=REG):
            self.assertEqual(_cog()._tick_actor(state, "Goblin"), [])


class TestStatusKonzole(unittest.TestCase):
    def test_tracker_ukazuje_dmg_a_kola(self):
        stat = {"hp": 10, "max_hp": 10, "statuses": []}
        bs.apply_status(stat, "jed", "zbran", REG)
        tracker = combat.status_tracker(stat, REG)
        self.assertIn("Jed I.", tracker)
        self.assertIn("1d5", tracker)
        self.assertIn("3 kol", tracker)

    def test_recap_kola_hlasi_otraveneho(self):
        state = _combat()
        bs.apply_status(state["stats"]["<@1>"], "jed", "zbran", REG)
        with mock.patch.object(combat, "_bs", return_value=bs), \
                mock.patch.object(bs, "load_statuses", return_value=REG):
            lines = combat.turn_console(state, "<@1>", new_round=True)
        self.assertTrue(any("Status:" in line and "Jed I." in line
                            for line in lines))


if __name__ == "__main__":
    unittest.main()
