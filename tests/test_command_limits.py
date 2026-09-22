"""Hlídá limit Discordu (100 top-level příkazů na aplikaci) a překryv mezi boty.

Počítá se ze skutečného stromu příkazů po ořezu, který dělá `setup_hook` —
tedy z toho, co by se opravdu nasynchronizovalo.
"""
import unittest

from tests.bot_tree import ENTRYPOINTS, build_entrypoint, full_names, top_level_names

LIMIT = 100


class CommandLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bots = {entrypoint: build_entrypoint(entrypoint) for entrypoint in ENTRYPOINTS}

    def test_under_discord_limit(self):
        for entrypoint, bot in self.bots.items():
            with self.subTest(entrypoint=entrypoint):
                count = len(top_level_names(bot.tree))
                self.assertLess(
                    count, LIMIT,
                    f"{entrypoint} má {count} top-level příkazů — limit Discordu je {LIMIT}",
                )

    def test_dm_commands_are_unique(self):
        dm = full_names(self.bots["main_dm.py"].tree)
        for entrypoint in ("main_bot.py", "main_dnd.py"):
            with self.subTest(entrypoint=entrypoint):
                clash = dm & full_names(self.bots[entrypoint].tree)
                self.assertEqual(
                    set(), clash,
                    f"ArionDM a {entrypoint} registrují stejné příkazy: {sorted(clash)}",
                )


if __name__ == "__main__":
    unittest.main()
