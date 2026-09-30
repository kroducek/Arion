"""Protijed: skupiny statusů, léčení itemem a /combat use za bonusovou akci."""

import asyncio
import unittest
from unittest import mock

from src.core.dnd import blacksmith as bs
from src.logic import combat, inventory


REG = {
    "jed": {"name": "Jed I.", "dmg": "1d5", "duration": 3, "tick": "kazde_kolo"},
    "jed2": {"name": "Jed II.", "dmg": "1d8", "duration": 3, "tick": "kazde_kolo",
             "group": "jed"},
    "krvaceni": {"name": "Krvácení", "dmg": "1d4", "duration": 3,
                 "tick": "kazde_kolo"},
}
PROTIJED = {"name": "Protijed", "consumable": True, "cures": ["jed"],
            "hp_restore": 5}


def _poisoned() -> dict:
    return {"hp": 10, "max_hp": 20, "statuses": [
        {"status": "jed", "kol_zbyva": 2}, {"status": "jed2", "kol_zbyva": 3},
        {"status": "krvaceni", "kol_zbyva": 1}]}


class TestSkupiny(unittest.TestCase):
    def test_skupina_bez_pole_je_id(self):
        self.assertEqual(bs.status_group("jed", REG["jed"]), "jed")
        self.assertEqual(bs.status_group("jed2", REG["jed2"]), "jed")

    def test_protijed_leci_celou_skupinu(self):
        stat = _poisoned()
        removed = bs.cure_groups(stat, ["jed"], REG)
        self.assertEqual(removed, ["Jed I.", "Jed II."])
        self.assertEqual([i["status"] for i in stat["statuses"]], ["krvaceni"])

    def test_status_edit_nastavi_a_smaze_skupinu(self):
        sdef = {"name": "Jed III."}
        bs.edit_status(sdef, group=" Jed ")
        self.assertEqual(sdef["group"], "jed")
        bs.edit_status(sdef, group="-")
        self.assertEqual(sdef["group"], "")


class TestEfektyItemu(unittest.TestCase):
    def test_cures_z_textu(self):
        self.assertEqual(inventory.item_cures({"cures": "Jed, krvaceni"}),
                         ["jed", "krvaceni"])

    def test_v_boji_jde_hp_a_leceni_do_aktera(self):
        profile = {"hp_cur": 10, "hp_max": 20, "statuses": []}
        stat = _poisoned()
        effects = inventory.apply_item_effects(profile, PROTIJED, carrier=stat,
                                               registry=REG)
        self.assertEqual(stat["hp"], 15)
        self.assertEqual(profile["hp_cur"], 10)
        self.assertEqual([i["status"] for i in stat["statuses"]], ["krvaceni"])
        self.assertIn("🌿 Sundáno: Jed I., Jed II.", effects)

    def test_mimo_boj_leci_profil(self):
        profile = {"hp_cur": 18, "hp_max": 20, "statuses": _poisoned()["statuses"]}
        inventory.apply_item_effects(profile, PROTIJED, registry=REG)
        self.assertEqual(profile["hp_cur"], 20)
        self.assertEqual(len(profile["statuses"]), 1)

    def test_hrac_v_boji(self):
        state = {"123": {"stats": {"<@1>": {}, "Goblin": {}}}}
        with mock.patch.object(inventory, "load_json", return_value=state):
            self.assertTrue(inventory.in_active_combat(1))
            self.assertFalse(inventory.in_active_combat(2))


class _User:
    id = 1
    mention = "<@1>"

    class guild_permissions:
        administrator = False


class _Response:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class _Interaction:
    channel_id = 7

    def __init__(self):
        self.user = _User()
        self.response = _Response()


class TestCombatUse(unittest.TestCase):
    def _run(self, state, profiles):
        cog = combat.CombatCog.__new__(combat.CombatCog)
        cog.active_combats = {7: state}
        cog.mutate_combat = lambda _cid, change: change(state)
        inter = _Interaction()
        with mock.patch.object(combat, "_load_profiles", return_value=profiles), \
                mock.patch.object(combat, "_save_profiles") as save, \
                mock.patch.object(combat, "_load_items_db",
                                  return_value={"protijed": PROTIJED}), \
                mock.patch.object(bs, "load_statuses", return_value=REG), \
                mock.patch.object(combat, "_bs", return_value=bs):
            asyncio.run(combat.CombatCog.combat_use.callback(cog, inter, "protijed"))
        return inter.response.sent, save

    def _setup(self):
        state = {"order": ["<@1>"], "stats": {"<@1>": _poisoned()}, "round": 1}
        profiles = {"1": {"hp_cur": 10, "hp_max": 20, "inventory": [
            {"type": "registered", "id": "protijed", "qty": 2}]}}
        return state, profiles

    def test_leci_stoji_bonus_a_spotrebuje_kus(self):
        state, profiles = self._setup()
        sent, save = self._run(state, profiles)
        stat = state["stats"]["<@1>"]
        self.assertEqual(stat["hp"], 15)
        self.assertEqual([i["status"] for i in stat["statuses"]], ["krvaceni"])
        self.assertEqual(state["turn_state"]["<@1>"]["bonus"], 1)
        self.assertEqual(profiles["1"]["inventory"][0]["qty"], 1)
        self.assertEqual(profiles["1"]["hp_cur"], 15)
        save.assert_called_once()
        self.assertIn("Protijed", sent[0][0])
        self.assertEqual(state["log"][-1]["resources"]["item_id"], "protijed")

    def test_druhy_bonus_v_tahu_neprojde(self):
        state, profiles = self._setup()
        self._run(state, profiles)
        sent, _ = self._run(state, profiles)
        self.assertIn("Bonusovou akci", sent[0][0])
        self.assertEqual(profiles["1"]["inventory"][0]["qty"], 1)


class TestUndoItemu(unittest.TestCase):
    def test_undo_vrati_item(self):
        profiles = {"1": {"inventory": []}}
        with mock.patch.object(combat, "_load_profiles", return_value=profiles), \
                mock.patch.object(combat, "_save_profiles"):
            note = combat.refund_resources(
                {"resources": {"uid": 1, "item_id": "protijed", "item_qty": 1}})
        self.assertIn("protijed", note)
        self.assertEqual(profiles["1"]["inventory"][0]["id"], "protijed")


if __name__ == "__main__":
    unittest.main()
