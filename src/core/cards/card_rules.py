"""Shared card balance, display metadata and legacy quality migration."""
import random

RARITIES = {
    "common": {"color": 0xB0B8C4, "emoji": "⚪"},
    "uncommon": {"color": 0x45C878, "emoji": "🟢"},
    "rare": {"color": 0x579CFA, "emoji": "🔵"},
    "epic": {"color": 0xB771F8, "emoji": "🟣"},
    "legendary": {"color": 0xFFD700, "emoji": "🟡"},
    "mythic": {"color": 0xFF648F, "emoji": "🌟"},
}
QUALITIES = {
    "damaged": {"name": "Damaged", "emoji": "💔", "color": 0x8B0000},
    "poor": {"name": "Poor", "emoji": "🩹", "color": 0xA98467},
    "normal": {"name": "Normal", "emoji": "⚪", "color": 0x95A5A6},
    "excellent": {"name": "Excellent", "emoji": "💎", "color": 0x69CFCE},
    "pristine": {"name": "Pristine", "emoji": "✨", "color": 0xFFD700},
}
BASE_RARITY_WEIGHTS = dict(zip(RARITIES, (50, 30, 12.5, 5, 2, 0.5)))
QUALITY_WEIGHTS = dict(zip(QUALITIES, (10, 20, 40, 20, 10)))
# At one ticket the base odds apply. Interpolate weight multipliers up to ten.
MAX_TICKET_MULTIPLIERS = dict(zip(RARITIES, (0.95, 0.98, 1.10, 1.20, 1.30, 1.20)))
RARITY_ORDER = list(reversed(RARITIES))
QUALITY_ORDER = list(reversed(QUALITIES))
DUST_VALUES = dict(zip(RARITIES, (1, 2, 5, 15, 50, 150)))
QUALITY_MULTIPLIERS = dict(zip(QUALITIES, (0.5, 0.75, 1.0, 1.5, 2.0)))
LEGACY_QUALITIES = {"shiny": "pristine", "gold": "excellent"}


def rarity_weights(tickets=1):
    progress = (max(1, min(10, int(tickets))) - 1) / 9
    return {rarity: weight * (1 + (MAX_TICKET_MULTIPLIERS[rarity] - 1) * progress)
            for rarity, weight in BASE_RARITY_WEIGHTS.items()}


def rarity_chances(tickets=1):
    weights = rarity_weights(tickets)
    total = sum(weights.values())
    return {rarity: 100 * weight / total for rarity, weight in weights.items()}


def roll_rarity(tickets=1):
    weights = rarity_weights(tickets)
    return random.choices(list(weights), weights=list(weights.values()), k=1)[0]


def roll_quality():
    return random.choices(list(QUALITY_WEIGHTS), weights=list(QUALITY_WEIGHTS.values()), k=1)[0]


def migrate_qualities():
    """Idempotent and atomic across CARDS/DM startup; retain the original label."""
    from src.database import db
    if not db.doc_exists("cards_inventory.json"):
        return

    def convert(inventory):
        for card in inventory.values():
            if not isinstance(card, dict):
                continue
            old = card.get("quality")
            if old in LEGACY_QUALITIES:
                card.setdefault("legacy_quality", old)
                card["quality"] = LEGACY_QUALITIES[old]
        return inventory

    db.update_doc("cards_inventory.json", convert)
