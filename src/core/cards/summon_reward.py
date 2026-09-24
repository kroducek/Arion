"""Commit crate, card and luck together before presenting the reward."""
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
    clovers: int
    remaining_clovers: int
    jackpot: bool


def settle_opening(uid, crate, tickets, *, preview=False, forced_clovers=None):
    """Preview draws the same way but writes no documents and grants no card."""
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
        luck = read("summon_luck.json", {})
        state = luck.setdefault(uid, {"clovers": 0})
        before = max(0, min(5, int(state.get("clovers", 0))))
        tickets = max(1, min(10, int(tickets)))
        clovers = min(5, before + (tickets == 10))
        if preview and forced_clovers is not None:
            clovers = max(0, min(5, int(forced_clovers)))
        jackpot = clovers == 5
        unique_id, card = draw_random_card(uid, templates, inventory, tickets=tickets,
                                          clovers=clovers, guaranteed_jackpot=jackpot)
        remaining = 0 if jackpot else clovers
        if not preview:
            inventory[unique_id] = card
            owned[crate] -= 1
            state['clovers'] = remaining
            write(CARDS_CRATES, crates)
            write(CARDS_INVENTORY, inventory)
            write("summon_luck.json", luck)
        return OpeningReward(unique_id, card, tickets, clovers, remaining, jackpot)
