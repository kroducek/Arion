"""Story-time invariants, animated output and command ownership."""
import io
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

    def test_gif_is_animated_and_bounded(self):
        alice = {"day": 0, "period": "večer", "note": "Přítomnost"}
        players = [{"name": f"Hráč {i}", "day": -i, "period": "ráno", "note": "Široký svět " * 12}
                   for i in range(6)]
        output = t.render_timeline(alice, players)
        self.assertLess(output.getbuffer().nbytes, 8_000_000)
        image = Image.open(io.BytesIO(output.getvalue()))
        self.assertEqual(image.format, "GIF")
        self.assertEqual(image.n_frames, t.FRAME_COUNT)
        self.assertEqual(image.info["loop"], 0)

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
        with patch.object(t, "guild_state", return_value=state), patch.object(t, "render_timeline", return_value=io.BytesIO(b"gif")):
            asyncio.run(t.Timeline.timeline.callback(t.Timeline(None), interaction))
        interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
        kwargs = interaction.followup.send.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertEqual(kwargs["embeds"][0].image.url, "attachment://timeline.gif")
        self.assertIn("Alice", kwargs["embeds"][1].fields[0].name)

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
