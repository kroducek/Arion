"""Check the delivered GIF, including missing-art fallback and playback timing."""
import io
import unittest
from PIL import Image
from src.core.cards.summon_render import render_opening, SIZE, MAX_BYTES


class SummonRenderTests(unittest.TestCase):
    def test_missing_art_still_produces_bounded_single_play_animation(self):
        payload, seconds = render_opening(
            {'rarity': 'rare', 'quality': 'normal'}, None, [])
        self.assertLess(len(payload), MAX_BYTES)
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual(image.size, SIZE)
            self.assertNotIn('loop', image.info)
            total = 0
            for index in range(image.n_frames):
                image.seek(index)
                total += image.info['duration']
            self.assertAlmostEqual(total / 1000, seconds)
            self.assertGreater(image.n_frames, 40)


if __name__ == '__main__':
    unittest.main()
