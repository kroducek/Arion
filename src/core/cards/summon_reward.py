"""Commit crate and card together before presenting the reward."""
import json
import os
from dataclasses import dataclass

from src.database import db
from src.core.cards.cards import draw_random_card
from src.utils.paths import CARDS_CRATES, CARDS_DATA, CARDS_INVENTORY


class NoCrates(ValueError):
    pass


class EmptyCardPool(ValueError):
    pass


@dataclass
class OpeningReward:
    unique_id: str
    card: dict
    tickets: int


def settle_opening(uid, crate, tickets, *, preview=False):
    """Preview draws normally, but never grants or consumes anything."""
    with db.transaction() as conn:
        def read(path, default):
            row = conn.execute("SELECT data FROM docs WHERE name = ?", (os.path.basename(path),)).fetchone()
            return json.loads(row['data']) if row else default

        def write(path, value):
            conn.execute(
                "INSERT INTO docs (name, data) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=datetime('now')",
                (os.path.basename(path), json.dumps(value, ensure_ascii=False)),
            )

        crates = read(CARDS_CRATES, {})
        owned = crates.setdefault(uid, {"basic": 1})
        if not preview and owned.get(crate, 0) < 1:
            raise NoCrates()
        templates = read(CARDS_DATA, [])
        if not templates:
            raise EmptyCardPool()
        inventory = read(CARDS_INVENTORY, {})
        tickets = max(1, min(10, int(tickets)))
        unique_id, card = draw_random_card(uid, templates, inventory, tickets=tickets)
        if not preview:
            inventory[unique_id] = card
            owned[crate] -= 1
            write(CARDS_CRATES, crates)
            write(CARDS_INVENTORY, inventory)
        return OpeningReward(unique_id, card, tickets)
