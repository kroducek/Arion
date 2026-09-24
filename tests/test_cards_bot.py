"""Cards ownership: all player commands move; all admin commands stay in DM."""
import unittest

from tests.bot_tree import build_bot, build_entrypoint, full_names
from tests.test_admin_gate import _commands
from src.utils.admin_gate import is_admin_command


class CardsBotTests(unittest.TestCase):
    def test_cards_partition_preserves_every_command(self):
        complete = build_bot(["src.core.cards.cards", "src.core.cards.summon"])
        commands = _commands(complete.tree)
        admin = {name for name, cmd in commands.items() if is_admin_command(cmd)}
        player = set(commands) - admin
        cards = build_entrypoint("main_cards.py")
        dm = build_entrypoint("main_dm.py")
        bot = build_entrypoint("main_bot.py")

        self.assertIn("cards print", admin)
        self.assertIn("summon give", admin)
        self.assertIn("cards trade", player)
        self.assertIn("summon open", player)
        self.assertEqual(full_names(cards.tree), player)
        self.assertEqual(full_names(dm.tree) & set(commands), admin)
        self.assertFalse(full_names(bot.tree) & set(commands))
        for name in admin:
            self.assertTrue(commands[name].checks, name)


if __name__ == "__main__":
    unittest.main()
