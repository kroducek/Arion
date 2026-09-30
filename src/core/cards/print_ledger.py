"""Permanent per-template print sequence and lifecycle journal.

All writers use the caller's SQLite transaction; burning never lowers counters.
Legacy gaps are unknown, not evidence that a card was destroyed.
"""
import copy
import json
import os
import uuid
from datetime import datetime, timezone
from src.database import db
from src.utils.paths import CARDS_INVENTORY, CARDS_DATA, PROFILES, STARDUST
from src.core.cards.card_rules import RARITIES, QUALITIES, DUST_VALUES, QUALITY_MULTIPLIERS

LEDGER = 'cards_print_ledger.json'


def read(conn, path, default=None):
    row = conn.execute('SELECT data FROM docs WHERE name=?', (os.path.basename(path),)).fetchone()
    return json.loads(row['data']) if row else ({} if default is None else default)


def write(conn, path, value):
    conn.execute("INSERT INTO docs(name,data) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=datetime('now')",
                 (os.path.basename(path), json.dumps(value, ensure_ascii=False)))


def event(kind, actor=None, **details):
    return dict(kind=kind, at=datetime.now(timezone.utc).isoformat(), actor=actor, **details)


def sync(conn, inventory):
    ledger = read(conn, LEDGER)
    counters = ledger.setdefault('counters', {})
    records = ledger.setdefault('records', {})
    for uid, card in inventory.items():
        if not isinstance(card, dict):
            continue
        cid, number = card.get('card_id'), card.get('print_number')
        if cid is None or not isinstance(number, int) or number < 1:
            continue
        key = str(cid)
        counters[key] = max(counters.get(key, 0), number)
        if uid not in records:
            records[uid] = dict(card=copy.deepcopy(card), status='active', events=[event('legacy_import')])
    return ledger


def migrate():
    with db.transaction() as conn:
        ledger = sync(conn, read(conn, CARDS_INVENTORY))
        write(conn, LEDGER, ledger)
        pairs = {}
        for uid, record in ledger['records'].items():
            card = record['card']
            if card.get('card_id') is not None and isinstance(card.get('print_number'), int):
                pairs.setdefault((card['card_id'], card['print_number']), []).append(uid)
        return {f'{cid} / #{number}': ids for (cid, number), ids in pairs.items() if len(ids) > 1}


def allocate(conn, inventory, proposed_uid, card, *, preview=False, actor=None):
    ledger = sync(conn, inventory)
    cid = str(card['card_id'])
    card['print_number'] = ledger['counters'].get(cid, 0) + 1
    uid = proposed_uid
    while uid in inventory or uid in ledger['records']:
        uid = uuid.uuid4().hex[:8]
    if not preview:
        ledger['counters'][cid] = card['print_number']
        ledger['records'][uid] = dict(card=copy.deepcopy(card), status='active', events=[event('printed', actor)])
        inventory[uid] = card
        write(conn, LEDGER, ledger)
    return uid, card


def destroy(uid, *, owner=None, actor=None, burn=False, all_cards=False):
    with db.transaction() as conn:
        inventory = read(conn, CARDS_INVENTORY)
        ledger = sync(conn, inventory)
        if all_cards:
            selected = {key: c for key,c in inventory.items() if isinstance(c,dict) and c.get('owner_id') == owner and not c.get('locked')}
        else:
            card = inventory.get(uid)
            if not card:
                raise ValueError('missing')
            if owner is not None and card.get('owner_id') != owner:
                raise ValueError('owner')
            if burn and card.get('locked'):
                raise ValueError('locked')
            selected = {uid: card}
        protected = sum(1 for c in inventory.values() if isinstance(c,dict) and c.get('owner_id') == owner and c.get('locked'))
        dust = 0
        profiles = read(conn, PROFILES)
        profiles_changed = False
        for key, card in selected.items():
            if burn:
                dust += max(1, int(DUST_VALUES.get(card.get('rarity','uncommon'),1) * QUALITY_MULTIPLIERS.get(card.get('quality','normal'),1)))
            record = ledger['records'].setdefault(key, dict(events=[]))
            record.update(card=copy.deepcopy(card), status='destroyed')
            record['events'].append(event('burned' if burn else 'admin_removed', actor or owner))
            profile = profiles.get(card.get('owner_id'), {})
            if profile.get('active_card_id') == key:
                profile['active_card_id'] = None
                profiles_changed = True
            del inventory[key]
        if selected:
            if burn:
                wallet = read(conn, STARDUST)
                wallet[owner] = int(wallet.get(owner,0)) + dust
                write(conn, STARDUST, wallet)
            if profiles_changed:
                write(conn, PROFILES, profiles)
            write(conn, CARDS_INVENTORY, inventory)
        write(conn, LEDGER, ledger)
        return dict(count=len(selected), protected=protected, dust=dust), selected


def check(card_id, number):
    with db.transaction() as conn:
        inventory = read(conn, CARDS_INVENTORY)
        ledger = sync(conn, inventory)
        write(conn, LEDGER, ledger)
        matches = []
        for uid, record in ledger['records'].items():
            card = inventory.get(uid, record['card'])
            if card.get('card_id') == card_id and card.get('print_number') == number:
                matches.append(dict(uid=uid, card=card, status='active' if uid in inventory else ('destroyed' if record['status']=='destroyed' else 'unknown'), events=record['events']))
        if len(matches)>1:
            return dict(status='conflict', matches=matches)
        if matches:
            return matches[0]
        maximum = ledger['counters'].get(str(card_id),0)
        return dict(status='unknown' if number <= maximum else 'never', maximum=maximum)


def restore(card_id, number, owner, actor, *, rarity=None, quality=None):
    if number < 1:
        raise ValueError('Print musí být kladný.')
    with db.transaction() as conn:
        inventory = read(conn, CARDS_INVENTORY)
        ledger = sync(conn, inventory)
        matches = [(uid,r) for uid,r in ledger['records'].items() if r['card'].get('card_id') == card_id and r['card'].get('print_number') == number]
        if len(matches)>1:
            raise ValueError('Print má duplicitní historické záznamy. Nejprve je nutné vyřešit konflikt.')
        if matches:
            uid, record = matches[0]
            if uid in inventory:
                raise ValueError('Tento print už existuje.')
            card = copy.deepcopy(record['card'])
            if record['status'] != 'destroyed':
                raise ValueError('Zničení tohoto kusu není doložené; nelze ho automaticky obnovit.')
            kind = 'restored'
        else:
            if number > ledger['counters'].get(str(card_id),0):
                raise ValueError('Print je nad známým počítadlem; nejde o doloženou starší mezeru.')
            if rarity not in RARITIES or quality not in QUALITIES:
                raise ValueError('Historie chybí. Pro ruční rekonstrukci zadej raritu i kvalitu.')
            template = next((t for t in read(conn,CARDS_DATA,[]) if t.get('id')==card_id),None)
            if template is None:
                raise ValueError('Vzor karty neexistuje.')
            card = {k:template.get(k) for k in ('name','description','image','collection')}
            card.update(card_id=card_id, print_number=number, rarity=rarity, quality=quality, frame=None, created_at=None)
            uid = uuid.uuid4().hex[:8]
            while uid in inventory or uid in ledger['records']:
                uid = uuid.uuid4().hex[:8]
            record = dict(events=[])
            ledger['records'][uid] = record
            kind = 'reconstructed'
        card.update(owner_id=owner, locked=True)
        card.pop('tags',None)
        inventory[uid] = card
        record.update(card=copy.deepcopy(card), status='active')
        record['events'].append(event(kind, actor, owner=owner))
        write(conn, CARDS_INVENTORY, inventory)
        write(conn, LEDGER, ledger)
        return uid, card, kind


def counters():
    with db.transaction() as conn:
        ledger = sync(conn, read(conn, CARDS_INVENTORY))
        write(conn, LEDGER, ledger)
        return ledger['counters']
