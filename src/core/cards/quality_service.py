"""Quality restoration with an atomic dust payment and print history."""
import copy

from src.core.cards import print_ledger
from src.core.cards.card_rules import QUALITIES
from src.database import db
from src.utils.paths import CARDS_INVENTORY, STARDUST

BASE_COSTS = dict(common=100, uncommon=200, rare=350, epic=500, legendary=750, mythic=1000)


def quote(card):
    quality = card.get("quality", "normal")
    levels = list(QUALITIES)
    if quality not in levels or card.get("rarity") not in BASE_COSTS:
        raise ValueError("Karta má neznámou kvalitu nebo raritu.")
    index = levels.index(quality)
    if index == len(levels) - 1:
        raise ValueError("Karta už má nejvyšší kvalitu Pristine.")
    # Two thirds of the original price, rounded only after the tier multiplier.
    cost = (BASE_COSTS[card["rarity"]] * 2 ** index * 2 + 1) // 3
    if card["rarity"] == "mythic" and index == 0:
        cost = 666
    return levels[index + 1], cost


def upgrade(owner, unique_id, expected_quality, expected_rarity):
    with db.transaction() as conn:
        inventory = print_ledger.read(conn, CARDS_INVENTORY)
        card = inventory.get(unique_id)
        if not card:
            raise ValueError("Karta neexistuje.")
        if card.get("owner_id") != owner:
            raise ValueError("Tato karta ti nepatří.")
        if (card.get("quality", "normal"), card.get("rarity")) != (expected_quality, expected_rarity):
            raise ValueError("Karta se změnila. Spusť /cards quality znovu pro aktuální cenu.")
        target, cost = quote(card)
        wallet = print_ledger.read(conn, STARDUST)
        balance = int(wallet.get(owner, 0))
        if balance < cost:
            raise ValueError(f"Nemáš dost hvězdného prachu: potřebuješ {cost:,}, máš {balance:,}.")
        ledger = print_ledger.sync(conn, inventory)
        old = card.get("quality", "normal")
        card["quality"] = target
        wallet[owner] = balance - cost
        record = ledger["records"].setdefault(unique_id, dict(events=[]))
        record.update(card=copy.deepcopy(card), status="active")
        record["events"].append(print_ledger.event(
            "quality_upgraded", owner, old_quality=old, quality=target, dust=cost))
        print_ledger.write(conn, CARDS_INVENTORY, inventory)
        print_ledger.write(conn, STARDUST, wallet)
        print_ledger.write(conn, print_ledger.LEDGER, ledger)
        return card, cost
