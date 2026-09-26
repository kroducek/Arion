"""Filtering and personal tags for card inventories."""
import re
import unicodedata
from datetime import datetime
from src.core.cards.card_rules import RARITY_ORDER, QUALITY_ORDER


def normalize_tag(value):
    value = value.strip().casefold()
    if not re.fullmatch(r'[\w-]{1,24}', value):
        raise ValueError('Tag musí mít 1–24 písmen, číslic, podtržítek nebo pomlček.')
    return value


def edit_tags(inventory, uid, ids, tag, remove=False):
    tag = normalize_tag(tag)
    ids = list(dict.fromkeys(ids))
    if not 1 <= len(ids) <= 50:
        raise ValueError('Zadej 1–50 ID karet oddělených čárkou.')
    for cid in ids:
        card = inventory.get(cid)
        if not isinstance(card, dict) or card.get('owner_id') != uid:
            raise ValueError(f'Karta {cid} neexistuje nebo ti nepatří. Nic nebylo změněno.')
        if not remove and tag not in card.get('tags', []) and len(card.get('tags', [])) >= 8:
            raise ValueError(f'Karta {cid} už má 8 tagů. Nic nebylo změněno.')
    for cid in ids:
        tags = list(inventory[cid].get('tags', []))
        if remove:
            tags = [t for t in tags if t != tag]
        elif tag not in tags:
            tags.append(tag)
        inventory[cid]['tags'] = tags
    return inventory


def _search(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).casefold()) if not unicodedata.combining(c))


def select_cards(inventory, uid, *, character=None, collection=None, rarity=None, quality=None,
                 frame=None, locked=None, tag=None, sort='print'):
    def date(card):
        try:
            return datetime.fromisoformat(card.get('created_at', '')).timestamp()
        except (ValueError, TypeError, OverflowError):
            return 0
    result = []
    for cid, card in inventory.items():
        if not isinstance(card, dict) or card.get('owner_id') != uid:
            continue
        if character and _search(character) not in _search(card.get('name', '')):
            continue
        if any(value and str(card.get(key, '')).casefold() != value.casefold()
               for key, value in [('collection', collection), ('rarity', rarity), ('quality', quality)]):
            continue
        if frame and (bool(card.get('frame')) if frame.casefold() == 'none' else str(card.get('frame', '')).casefold() != frame.casefold()):
            continue
        if locked is not None and bool(card.get('locked', False)) != locked:
            continue
        if tag and tag.strip().casefold() not in card.get('tags', []):
            continue
        result.append((cid, card))
    def key(item):
        cid, card = item
        if sort in ('newest', 'oldest'):
            stamp = date(card)
            primary = -stamp if sort == 'newest' else stamp
        elif sort == 'rarity':
            primary = RARITY_ORDER.index(card['rarity']) if card.get('rarity') in RARITY_ORDER else 99
        elif sort == 'quality':
            primary = QUALITY_ORDER.index(card['quality']) if card.get('quality') in QUALITY_ORDER else 99
        else:
            primary = int(card.get('print_number') or 0)
        return primary, cid
    return sorted(result, key=key)
