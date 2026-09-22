"""Rozdělení příkazů mezi ArionDND a ArionDM.

Sdílené cogy se opravdu načtou do bota (bez připojení k Discordu) a kontroluje
se, že admin a hráčská část jdou každá jinam a nic se cestou neztratí.
"""
import unittest

from discord import app_commands

from src.utils.admin_gate import (
    SHARED_COGS,
    drop_admin_commands,
    is_admin_command,
    keep_only_admin,
)
from tests.bot_tree import build_bot, full_names


def _commands(tree):
    """Plná jména → příkaz."""
    result = {}

    def walk(command, prefix=""):
        name = f"{prefix}{command.name}"
        if isinstance(command, app_commands.Group):
            for child in command.commands:
                walk(child, f"{name} ")
        else:
            result[name] = command

    for command in tree.get_commands():
        walk(command)
    return result


class AdminGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bot = build_bot(SHARED_COGS)
        cls.all_commands = _commands(bot.tree)
        cls.admin = {n for n, c in cls.all_commands.items() if is_admin_command(c)}
        cls.player = set(cls.all_commands) - cls.admin

    def test_sdilene_cogy_maji_obe_casti(self):
        self.assertTrue(self.admin, "žádný příkaz není označený jako admin")
        self.assertTrue(self.player, "žádný hráčský příkaz nezbyl")

    def test_hracsky_bot_zahodi_admin_prikazy(self):
        bot = build_bot(SHARED_COGS)
        drop_admin_commands(bot)
        self.assertEqual(full_names(bot.tree), self.player)

    def test_dm_nechava_jen_admin_prikazy(self):
        bot = build_bot(SHARED_COGS)
        keep_only_admin(bot)
        self.assertEqual(full_names(bot.tree), self.admin)

    def test_rozdeleni_nic_neztrati(self):
        dnd = build_bot(SHARED_COGS)
        drop_admin_commands(dnd)
        dm = build_bot(SHARED_COGS)
        keep_only_admin(dm)
        dnd_names = full_names(dnd.tree)
        dm_names = full_names(dm.tree)
        self.assertEqual(dnd_names | dm_names, set(self.all_commands))
        self.assertFalse(dnd_names & dm_names)

    def test_vybrane_prikazy_konci_spravne(self):
        for name in ("gadd", "quest add", "perk give", "inv-db add", "dmset", "sp give",
                     "cards print", "summon give", "admin-kostky add", "leaderboards setup"):
            self.assertIn(name, self.admin, f"{name} má být admin příkaz")
        for name in ("inv", "quests", "profile", "duch equip", "cards album", "summon open"):
            if name in self.all_commands:
                self.assertIn(name, self.player, f"{name} má zůstat hráčům")

    def test_prikazy_na_behovy_stav_zustavaji_hostiteli(self):
        """`/kostky cancel` ruší hru drženou v paměti ArionBOTu — v ArionDM nemá co dělat."""
        self.assertIn("kostky cancel", self.player)


if __name__ == "__main__":
    unittest.main()
