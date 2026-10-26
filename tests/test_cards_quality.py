import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from src.core.cards import print_ledger, quality_service as service
from src.utils.paths import CARDS_INVENTORY, STARDUST


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE docs(name TEXT PRIMARY KEY, data TEXT, updated_at TEXT)")
        self.card = dict(owner_id="1", card_id=7, print_number=3,
                         rarity="mythic", quality="damaged", locked=True, frame="gold")
        print_ledger.write(self.conn, CARDS_INVENTORY, {"card": self.card})
        print_ledger.write(self.conn, STARDUST, {"1": 2000})
        self.conn.commit()

        @contextmanager
        def transaction():
            with self.conn:
                yield self.conn

        self.patcher = patch.object(service.db, "transaction", transaction)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.conn.close)

    def test_cost_progression_and_cap(self):
        for rarity, base in service.BASE_COSTS.items():
            for index, quality in enumerate(["damaged", "poor", "normal", "excellent"]):
                expected = 666 if rarity == "mythic" and index == 0 else round(base * 2 ** index * 2 / 3)
                self.assertEqual(service.quote(dict(rarity=rarity, quality=quality))[1], expected)
        with self.assertRaises(ValueError):
            service.quote(dict(rarity="mythic", quality="pristine"))

    def test_payment_history_and_card_identity(self):
        card, cost = service.upgrade("1", "card", "damaged", "mythic")
        self.assertEqual(cost, 666)
        self.assertEqual(card, dict(self.card, quality="poor"))
        self.assertEqual(print_ledger.read(self.conn, STARDUST), {"1": 1334})
        record = print_ledger.read(self.conn, print_ledger.LEDGER)["records"]["card"]
        self.assertEqual(record["card"], card)
        self.assertEqual(record["events"][-1]["kind"], "quality_upgraded")

    def test_rejections_do_not_charge(self):
        for owner, uid, quality in [("2", "card", "damaged"), ("1", "missing", "damaged"),
                                    ("1", "card", "poor")]:
            with self.assertRaises(ValueError):
                service.upgrade(owner, uid, quality, "mythic")
        print_ledger.write(self.conn, STARDUST, {"1": 665})
        self.conn.commit()
        with self.assertRaises(ValueError):
            service.upgrade("1", "card", "damaged", "mythic")
        self.assertEqual(print_ledger.read(self.conn, STARDUST), {"1": 665})
        self.assertEqual(print_ledger.read(self.conn, CARDS_INVENTORY)["card"], self.card)

    def test_repeated_confirmation_cannot_charge_twice(self):
        service.upgrade("1", "card", "damaged", "mythic")
        with self.assertRaises(ValueError):
            service.upgrade("1", "card", "damaged", "mythic")
        self.assertEqual(print_ledger.read(self.conn, STARDUST), {"1": 1334})
