"""Frame drops and atomic movement between cards and inventories."""
import json
import os
from src.database import db
from src.utils.paths import CARDS_FRAMES, CARDS_INVENTORY, FRAMES_INVENTORY
from src.core.cards.card_render import _load_frame


def frame_drop_chance(tickets):
    return 0.01 * (1 + (max(1, min(10, int(tickets))) - 1) / 9)


def eligible_frames(frames, rarity=None):
    return [f for f in frames if f.get('id') and f['id'] != 'chosen_by_fire'
            and (rarity is None or not f.get('rarity_exclusive') or f['rarity_exclusive'] == rarity)
            and _load_frame(f['id']) is not None]


def move_frame(uid, unique_id, frame_id):
    """None removes a frame; replacing returns the old frame. Consume one copy."""
    with db.transaction() as conn:
        def read(path, default):
            row = conn.execute('SELECT data FROM docs WHERE name=?', (os.path.basename(path),)).fetchone()
            return json.loads(row['data']) if row else default
        def write(path, data):
            conn.execute("INSERT INTO docs(name,data) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=datetime('now')",
                         (os.path.basename(path), json.dumps(data, ensure_ascii=False)))
        inv = read(CARDS_INVENTORY, {})
        card = inv.get(unique_id)
        if not card or card.get('owner_id') != uid:
            raise ValueError('Karta neexistuje nebo ti nepatří.')
        old = card.get('frame')
        if old == frame_id:
            raise ValueError('Tento rámeček už je nasazený.' if old else 'Karta nemá rámeček.')
        catalog = {f['id']: f for f in read(CARDS_FRAMES, [])}
        holdings = read(FRAMES_INVENTORY, {})
        owned = holdings.setdefault(uid, [])
        if frame_id:
            entry = catalog.get(frame_id)
            if not entry or not eligible_frames([entry], card.get('rarity')):
                raise ValueError('Rámeček není dostupný nebo neodpovídá raritě karty.')
            index = next((i for i, f in enumerate(owned) if f.get('id') == frame_id), None)
            if index is None:
                raise ValueError('Tento rámeček nemáš v inventáři.')
            owned.pop(index)
        if old:
            owned.append({'id': old, 'name': catalog.get(old, {}).get('name', old)})
        card['frame'] = frame_id
        write(CARDS_INVENTORY, inv)
        write(FRAMES_INVENTORY, holdings)
        return card
