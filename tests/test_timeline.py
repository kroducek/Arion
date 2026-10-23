"""Story-time invariants, animated output and command ownership."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from PIL import Image
from src.core.dnd import timeline as t
from src.utils.admin_gate import drop_admin_commands, keep_only_admin
from tests.bot_tree import build_bot, full_names


class TimelineTests(unittest.TestCase):
    def test_alice_advance_preserves_player_day_and_guild_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(t, "timeline_path", return_value=str(Path(directory) / "timeline.json")):
                t.set_entry(1, None, 10, "večer", "Alice", "")
                t.set_entry(1, "42:1", -2, "ráno", "Arion", "")
                t.set_entry(1, "42:2", 0, "noc", "Nyx", "")
                state = t.set_entry(1, None, 11, "ráno", "Alice", "")
                self.assertEqual(state["players"]["42:1"]["day"], 8)
                self.assertEqual(state["players"]["42:2"]["day"], 10)
                self.assertEqual(t.relative_text(state["players"]["42:1"], state["alice"]), "3 d před Alicí")
                self.assertEqual(t.guild_state(2)["players"], {})

    def test_same_day_orders_periods(self):
        alice = {"day": 0, "period": "odpoledne"}
        earlier = {"day": 0, "period": "ráno"}
        self.assertLess(t.position(earlier), t.position(alice))
        self.assertIn("dříve", t.relative_text(earlier, alice))
        self.assertEqual(t.relative_text(alice, alice), "přítomnost")

    def test_source_art_is_available(self):
        with Image.open(t.timeline_media()) as image:
            self.assertGreater(image.width, image.height * 2)
        self.assertTrue(t.timeline_media().is_file())

    def test_location_is_preserved_when_time_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(t, "timeline_path", return_value=str(Path(directory) / "timeline.json")):
                t.set_entry(1, "42:1", -2, "ráno", "Arion", "", "Kalexie")
                state = t.set_entry(1, "42:1", -1, "noc", "Arion", "")
                self.assertEqual(state["players"]["42:1"]["location"], "Kalexie")

    def test_locations_filter_and_paginate(self):
        async def scenario():
            players = [{"name": f"Hráč {i}", "day": -i, "period": "ráno", "location": f"Město {i}"} for i in range(43)]
            view = t.TimelineView(42, {"day": 0, "period": "ráno"}, players)
            self.assertEqual(view.pages, 3)
            self.assertLessEqual(len(view.children), 25)
            self.assertTrue(all(button.emoji is None for button in view.children))
            interaction = MagicMock()
            interaction.response.edit_message = AsyncMock()
            button = next(button for button in view.children if button.label == "Město 0")
            await button.callback(interaction)
            self.assertEqual(len(view.filtered()), 1)
            self.assertEqual(view.page, 1)
            self.assertEqual(view.embeds()[1].description.count("Hráč"), 1)
            self.assertFalse(view.embeds()[1].fields)
            self.assertEqual(t.location_of({}), "Bez lokace")
            view.players = [{"name": "*" * 32, "day": -100000, "period": "ráno", "location": "*" * 60} for _ in range(80)]
            view.location = None
            for page in range(1, view.pages + 1):
                view.page = page
                self.assertLessEqual(len(view.embeds()[1].description), 4096)
        asyncio.run(scenario())

    def test_commands_are_partitioned(self):
        player = build_bot(["src.core.dnd.timeline"])
        drop_admin_commands(player)
        self.assertEqual(full_names(player.tree), {"timeline", "time"})
        dm = build_bot(["src.core.dnd.timeline"])
        keep_only_admin(dm)
        self.assertEqual(full_names(dm.tree), {"timeline_set", "timeline_present", "timeline_remove"})

    def test_timeline_is_private_and_text_follows_art(self):
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        state = {"alice": {"day": 0, "period": "ráno"}, "players": {}}
        with patch.object(t, "guild_state", return_value=state):
            asyncio.run(t.Timeline.timeline.callback(t.Timeline(None), interaction))
        interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
        kwargs = interaction.followup.send.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertEqual(kwargs["embeds"][0].image.url, f"attachment://{t.timeline_media().name}")
        self.assertIn("Alice", kwargs["embeds"][1].description)

    def test_time_is_private(self):
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        state = {"alice": {"day": 0, "period": "ráno"},
                 "players": {"42:1": {"name": "Arion", "day": -2, "period": "noc"}}}
        interaction.user.id = 42
        with patch.object(t, "guild_state", return_value=state), patch.object(t, "get_active_slot", return_value="1"), patch.object(t, "get_char", return_value={"name": "Arion"}):
            asyncio.run(t.Timeline.time.callback(t.Timeline(None), interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
