"""Sdílený stav boje mezi ArionDND a ArionDM.

Boj obsluhují dva procesy (hráčská a vypravěčská konzole), každý s vlastní
instancí `CombatCog`. Stav v paměti proto musí jít obnovit z DB, aby jeden
bot viděl zásahy toho druhého.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="arion-tests-"))

from src.logic.combat import CombatCog
from src.utils.admin_gate import SHARED_COGS


class _Cog(CombatCog):
    def __init__(self):
        self.bot = None
        self.active_combats = self._load_state()


class CombatSharedStateTest(unittest.TestCase):
    def setUp(self):
        self.dnd = _Cog()
        self.dnd.active_combats.clear()
        self.dnd._save_state()
        self.dm = _Cog()

    def test_combat_je_ve_sdilenych_cozich(self):
        self.assertIn("src.logic.combat", SHARED_COGS)

    def test_zmena_z_dm_je_videt_v_dnd(self):
        self.dm.active_combats[1] = {"order": ["<@1>"], "stats": {"Goblin": {"hp": 30}},
                                     "round": 1, "initiative": {}, "log": []}
        self.dm._save_state()

        self.dnd.reload_state()
        self.assertEqual(self.dnd.active_combats[1]["stats"]["Goblin"]["hp"], 30)

        self.dm.active_combats[1]["stats"]["Goblin"]["hp"] = 12
        self.dm._save_state()
        self.dnd.reload_state()
        self.assertEqual(self.dnd.active_combats[1]["stats"]["Goblin"]["hp"], 12)

    def test_ukonceny_boj_zmizi_i_druhemu_botovi(self):
        self.dm.active_combats[2] = {"order": [], "stats": {}, "round": 1,
                                     "initiative": {}, "log": []}
        self.dm._save_state()
        self.dnd.reload_state()
        self.assertIn(2, self.dnd.active_combats)

        del self.dm.active_combats[2]
        self.dm._save_state()
        self.dnd.reload_state()
        self.assertNotIn(2, self.dnd.active_combats)

    def test_reload_zachova_identitu_slovniku(self):
        """Views drží referenci na slovník boje — reload ji nesmí vyměnit."""
        self.dm.active_combats[3] = {"order": [], "stats": {}, "round": 1,
                                     "initiative": {}, "log": []}
        self.dm._save_state()
        self.dnd.reload_state()
        held = self.dnd.active_combats[3]

        self.dm.active_combats[3]["round"] = 4
        self.dm._save_state()
        self.dnd.reload_state()
        self.assertIs(held, self.dnd.active_combats[3])
        self.assertEqual(held["round"], 4)


if __name__ == "__main__":
    unittest.main()
