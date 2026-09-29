"""Audit combat trackeru: plné undo, statusy zbraní NPC, padlí aktéři, log."""

import unittest

from src.logic import combat


def _combat() -> dict:
    return {
        "order": ["<@1>", "Goblin", "Kostlivec"],
        "stats": {
            "<@1>": {"hp": 20, "max_hp": 20, "def": 0, "fur": 0},
            "Goblin": {"hp": 30, "max_hp": 30, "def": 0, "fur": 0},
            "Kostlivec": {"hp": 10, "max_hp": 10, "def": 0, "fur": 0},
        },
        "current_index": 0,
        "round": 1,
    }


class TestSnapshotUndo(unittest.TestCase):
    def test_snapshot_bere_i_statusy(self):
        stat = {"hp": 10, "max_hp": 10, "def": 1, "fur": 2,
                "statuses": [{"status": "jed", "rounds": 3}]}
        snap = combat.stat_snapshot(stat)
        self.assertEqual(snap["statuses"], [{"status": "jed", "rounds": 3}])
        snap["statuses"][0]["rounds"] = 1
        self.assertEqual(stat["statuses"][0]["rounds"], 3)

    def test_undo_vrati_statusy_i_furioku(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        before = combat.stat_snapshot(stat)
        stat["hp"] = 20
        stat["fur"] = 5
        stat["statuses"] = [{"status": "jed", "rounds": 3}]
        combat.log_event(state, "attack", "Goblin", before,
                         combat.stat_snapshot(stat), detail="zásah 10")

        event = combat.undo_last(state)

        self.assertIsNotNone(event)
        self.assertEqual(stat["hp"], 30)
        self.assertEqual(stat["fur"], 0)
        self.assertEqual(stat["statuses"], [])

    def test_undo_vrati_jen_jednou(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        before = combat.stat_snapshot(stat)
        stat["hp"] = 20
        combat.log_event(state, "attack", "Goblin", before,
                         combat.stat_snapshot(stat), detail="zásah 10")
        combat.undo_last(state)
        self.assertIsNone(combat.undo_last(state))

    def test_log_nese_spotrebovane_zdroje(self):
        state = _combat()
        stat = state["stats"]["Goblin"]
        snap = combat.stat_snapshot(stat)
        event = combat.log_event(
            state, "attack", "Goblin", snap, snap, detail="zásah",
            resources={"uid": 1, "mana": 3, "ammo_id": "sip", "ammo_qty": 1})
        self.assertEqual(event["resources"]["mana"], 3)


class TestNpcWeaponStatus(unittest.TestCase):
    def test_status_se_ulozi_a_doruci(self):
        stat = {}
        weapon = combat.set_npc_weapon(stat, "main", "1d8", "Dýka", "jed")
        self.assertEqual(weapon["status"], "jed")
        self.assertEqual(combat.npc_weapon_statuses(weapon), [("jed", "zbran")])

    def test_bez_statusu_se_nic_nedoruci(self):
        stat = {}
        weapon = combat.set_npc_weapon(stat, "main", "1d8")
        self.assertNotIn("status", weapon)
        self.assertEqual(combat.npc_weapon_statuses(weapon), [])

    def test_prehled_zbrani_ukaze_status(self):
        stat = {}
        combat.set_npc_weapon(stat, "main", "1d8", "Dýka", "jed")
        self.assertIn("jed", combat.npc_weapons_line(stat))


class TestPadliAkteri(unittest.TestCase):
    def test_is_down(self):
        state = _combat()
        state["stats"]["Goblin"]["hp"] = 0
        self.assertTrue(combat.is_down(state, "Goblin"))
        self.assertFalse(combat.is_down(state, "<@1>"))

    def test_tah_preskoci_padleho(self):
        state = _combat()
        state["stats"]["Goblin"]["hp"] = 0
        actor, rounds, skipped = combat.advance_turn(state)
        self.assertEqual(actor, "Kostlivec")
        self.assertEqual(skipped, ["Goblin"])
        self.assertEqual(rounds, 0)

    def test_obtoceni_pridava_kolo(self):
        state = _combat()
        state["current_index"] = 2
        actor, rounds, _ = combat.advance_turn(state)
        self.assertEqual(actor, "<@1>")
        self.assertEqual(rounds, 1)

    def test_vsichni_padli_neskonci_v_nekonecnu(self):
        state = _combat()
        for stat in state["stats"].values():
            stat["hp"] = 0
        actor, _, skipped = combat.advance_turn(state)
        self.assertIn(actor, state["order"])
        self.assertEqual(len(skipped), len(state["order"]))


class TestSummary(unittest.TestCase):
    def test_summary_ukaze_statusy(self):
        state = _combat()
        state["stats"]["Goblin"]["statuses"] = [{"status": "jed", "rounds": 2}]
        embed = combat.build_summary_embed(state, "Konec")
        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("Statusy", fields)
        self.assertIn("jed", fields["Statusy"])


class TestPersistentViews(unittest.TestCase):
    def test_tlacitka_nemaji_timeout(self):
        cog = object()
        self.assertIsNone(combat.AttackView(cog).timeout)
        self.assertIsNone(combat.EOTView(cog).timeout)
        self.assertIsNone(combat.InitiativeView(cog, 1, "<@1>").timeout)

    def test_tlacitka_maji_custom_id(self):
        for child in combat.AttackView(object()).children:
            self.assertTrue(child.custom_id.startswith("arion:combat:"))

    def test_payload_a_hydrate_prezije_restart(self):
        view = combat.AttackView(object(), 5, "<@1>", 1, "Goblin", 7, "luk",
                                 mana_cost=2, ammo_note="−1 Šíp",
                                 weapon_label="Luk", roll_info="1d8 → 7",
                                 resources={"uid": 1, "mana": 2},
                                 extra_statuses=[("jed", "zbran")])
        restored = combat.AttackView(object())
        self.assertTrue(restored.persistent)
        restored.hydrate(view.payload())
        self.assertEqual(restored.target, "Goblin")
        self.assertEqual(restored.damage, 7)
        self.assertEqual(restored.extra_statuses, [("jed", "zbran")])

    def test_vyhodnoceny_utok_se_z_cekajicich_smaze(self):
        view = combat.AttackView(object())
        view.message_id = "42"
        state = {combat.PENDING_KEY: {"42": {"target": "Goblin"}}}
        view._forget_pending(state)
        self.assertEqual(state[combat.PENDING_KEY], {})


if __name__ == "__main__":
    unittest.main()
