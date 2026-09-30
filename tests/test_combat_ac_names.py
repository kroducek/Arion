"""Combat autocomplete ukazuje u hráčů jména postav místo <@id>."""

import asyncio
import unittest
from unittest import mock

from src.logic import combat


class _Member:
    display_name = "Kroducek"


class _Guild:
    def get_member(self, uid):
        return _Member() if uid == 1 else None


class _Interaction:
    channel_id = 7
    guild = _Guild()


class TestActorLabel(unittest.TestCase):
    def test_hrac_ukaze_postavu_a_prezdivku(self):
        with mock.patch.object(combat, "_active_char_name", return_value="Kaiser"):
            self.assertEqual(combat.actor_label("<@1>", _Guild()),
                             "🧑 Kaiser (@Kroducek)")

    def test_bez_postavy_a_membera_zustane_id(self):
        with mock.patch.object(combat, "_active_char_name", return_value=None):
            self.assertEqual(combat.actor_label("<@2>", _Guild()), "<@2>")

    def test_npc_beze_zmeny(self):
        self.assertEqual(combat.actor_label("Obří štír", _Guild()), "Obří štír")

    def test_autocomplete_hleda_podle_jmena_a_vraci_id(self):
        cog = combat.CombatCog.__new__(combat.CombatCog)
        cog.active_combats = {7: {"order": ["<@1>", "Obří štír"]}}
        with mock.patch.object(combat, "_active_char_name", return_value="Kaiser"):
            choices = asyncio.run(cog._ac_actor(_Interaction(), "kai"))
        self.assertEqual([(c.name, c.value) for c in choices],
                         [("🧑 Kaiser (@Kroducek)", "<@1>")])


if __name__ == "__main__":
    unittest.main()
