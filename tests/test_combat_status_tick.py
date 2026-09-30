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

    def test_tik_ignoruje_def_a_bere_furioku(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        stat.update({"def": 10, "fur": 10})
        bs.apply_status(stat, "jed", "zbran", REG)
        with mock.patch.object(bs, "load_statuses", return_value=REG), \
                mock.patch.object(bs, "roll_dice", return_value=4):
            lines = _cog()._tick_actor(state, "Goblin")
        self.assertEqual((stat["hp"], stat["fur"]), (30, 6))
        self.assertTrue(any("furioka `10` → `6`" in line for line in lines))
        combat.undo_last(state)
        self.assertEqual(stat["fur"], 10)

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


class TestProcPriDoruceni(unittest.TestCase):
    def test_jed_tikne_hned_pri_doruceni(self):
        stat = {"hp": 20, "max_hp": 20, "statuses": []}
        with mock.patch.object(bs, "roll_dice", return_value=4):
            applied = combat.deliver_statuses(stat, [("jed", "zbran")], bs, REG)
        self.assertEqual(stat["hp"], 16)
        self.assertEqual(stat["statuses"][0]["kol_zbyva"], 2)
        self.assertEqual(applied, ["🧪 Jed I.: −4 HP (2 kol zbývá)"])

    def test_furioka_pohlti_dmg_ze_statusu(self):
        stat = {"hp": 20, "max_hp": 20, "def": 10, "fur": 3, "statuses": []}
        with mock.patch.object(bs, "roll_dice", return_value=4):
            applied = combat.deliver_statuses(stat, [("jed", "zbran")], bs, REG)
        self.assertEqual(stat["fur"], 0)
        self.assertEqual(stat["hp"], 19)
        self.assertIn("furioka pohltila 3", applied[0])

    def test_status_bez_dmg_netika(self):
        reg = {"mraz": {"name": "Mráz", "emoji": "❄️", "dmg": "",
                        "duration": 2, "tick": "kazde_kolo"}}
        stat = {"hp": 20, "max_hp": 20, "statuses": []}
        applied = combat.deliver_statuses(stat, [("mraz", "runa")], bs, reg)
        self.assertEqual(stat["hp"], 20)
        self.assertEqual(stat["statuses"][0]["kol_zbyva"], 2)
        self.assertEqual(applied, ["❄️ Mráz"])

    def test_jednokolovy_jed_vyprcha_hned(self):
        reg = {"jed": dict(REG["jed"], duration=1)}
        stat = {"hp": 20, "max_hp": 20, "statuses": []}
        with mock.patch.object(bs, "roll_dice", return_value=3):
            combat.deliver_statuses(stat, [("jed", "zbran")], bs, reg)
        self.assertEqual(stat["hp"], 17)
        self.assertEqual(stat["statuses"], [])


class TestStatusEdit(unittest.TestCase):
    def test_upravi_jen_zadana_pole(self):
        sdef = dict(REG["jed"], proc="", desc="Jed v ráně.")
        bs.edit_status(sdef, dmg="1d8", duration=None, tick="každé kolo",
                       desc="-", name=None)
        self.assertEqual(sdef["dmg"], "1d8")
        self.assertEqual(sdef["duration"], 3)
        self.assertEqual(sdef["tick"], "kazde_kolo")
        self.assertEqual(sdef["desc"], "")
        self.assertEqual(sdef["name"], "Jed I.")

    def test_zbran_s_naterem_nic_nedoruci(self):
        entry = {"id": "dyka", "coating": {"status": "jed", "hits_left": 3}}
        self.assertEqual(bs.weapon_delivered(entry, {}), [])


if __name__ == "__main__":
    unittest.main()
