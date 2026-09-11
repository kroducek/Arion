import unittest
from unittest.mock import patch

from src.database import characters as ch
from src.utils.char_target import char_label, resolve_postava

REGISTRY = {
    "42": {
        "active": "2",
        "chars": {
            "1": {"name": "Erith", "created_at": 0},
            "2": {"name": "Enel", "created_at": 0},
        },
    }
}


class TestCharTarget(unittest.TestCase):
    def setUp(self):
        p = patch.object(ch, "_load", lambda: REGISTRY)
        p.start()
        self.addCleanup(p.stop)

    def test_resolve_by_name_slot_and_prefix(self):
        self.assertEqual(ch.resolve_slot(42, "Erith"), "1")
        self.assertEqual(ch.resolve_slot(42, "enel"), "2")
        self.assertEqual(ch.resolve_slot(42, "1"), "1")
        self.assertEqual(ch.resolve_slot(42, "Eri"), "1")
        self.assertIsNone(ch.resolve_slot(42, "E"))        # sedí na obě → nejednoznačné
        self.assertIsNone(ch.resolve_slot(42, "Kaiser"))

    def test_resolve_postava_defaults_to_active(self):
        slot, err = resolve_postava(42, None)
        self.assertEqual((slot, err), ("2", None))

    def test_resolve_postava_unknown_returns_error(self):
        slot, err = resolve_postava(42, "Kaiser")
        self.assertIsNone(slot)
        self.assertIn("Erith", err)

    def test_use_slot_redirects_pkey(self):
        self.assertEqual(ch.pkey(42), "42:2")
        with ch.use_slot(42, "1"):
            self.assertEqual(ch.pkey(42), "42:1")
            self.assertEqual(ch.pkey(43), "43:1")   # jiný účet se nemění
        self.assertEqual(ch.pkey(42), "42:2")

    def test_char_label(self):
        self.assertEqual(char_label(42, "1"), "Erith")


if __name__ == "__main__":
    unittest.main()
