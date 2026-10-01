"""Shared, storage-independent furioku rules for profiles and combat."""
from uuid import uuid5, NAMESPACE_URL

UTOK = 'furioku_utok'
OBRANA = 'furioku_obrana'
JEDNOTA = 'furioku_jednota'


def normalize(p):
    p.setdefault('fury_cur', 0)
    p.setdefault('fury_max', 0)
    spirits = p.setdefault('spirits', [])
    for i, s in enumerate(spirits):
        s.setdefault('id', uuid5(NAMESPACE_URL, f"arion-spirit:{s.get('created_at')}:{s.get('name')}:{i}").hex)
        s.setdefault('fury_max', max(0, int(s.get('fury', 0))))
        s.setdefault('fury_cur', s['fury_max'])
        s['fury_cur'] = max(0, min(s['fury_max'], s['fury_cur']))
        s['fury'] = s['fury_max']  # legacy display compatibility, never spent
    if 'equipped_spirit_ids' not in p:
        idx = p.get('equipped_spirit_idx')
        p['equipped_spirit_ids'] = [spirits[idx]['id']] if isinstance(idx, int) and 0 <= idx < len(spirits) else []
    valid = {s['id'] for s in spirits}
    p['equipped_spirit_ids'] = list(dict.fromkeys(i for i in p['equipped_spirit_ids'] if i in valid))
    f = p.setdefault('furioka', {})
    f.setdefault('atk_amount', 0)
    f.setdefault('def_amount', 0)
    if 'spirit_ids' not in f:
        enabled = f.get('use_spirit') or f.get('atk_spirit') or f.get('def_spirit')
        f['spirit_ids'] = list(p['equipped_spirit_ids']) if enabled else []
    if 'main_spirit_id' not in p:
        previous = p['equipped_spirit_ids']
        p['main_spirit_id'] = previous[0] if len(previous) == 1 else None
        p['main_spirit_choice_pending'] = len(previous) > 1
    if p['main_spirit_id'] not in valid:
        p['main_spirit_id'] = None
    p['equipped_spirit_ids'] = [p['main_spirit_id']] if p['main_spirit_id'] else []
    f['spirit_ids'] = list(dict.fromkeys(i for i in f['spirit_ids'] if i in valid))
    f['use_spirit'] = bool(f['spirit_ids'])
    if spirits or sum(p.get(k, 0) for k in ('vliv_svetlo', 'vliv_temnota', 'vliv_rovnovaha')) > 0:
        p['furioku_unlocked'] = True
    return p


def equipped(p):
    normalize(p)
    by_id = {s['id']: s for s in p['spirits']}
    return [by_id[i] for i in p['equipped_spirit_ids']]


def linked(p, perks):
    normalize(p)
    by_id = {s['id']: s for s in p['spirits']}
    return [by_id[i] for i in p['furioka']['spirit_ids']] if JEDNOTA in perks else []


def pool(p, perks):
    return max(0, p.get('fury_cur', 0)) + sum(s['fury_cur'] for s in linked(p, perks))


def totals(p, perks):
    spirits = linked(p, perks)
    return (p['fury_cur'] + sum(s['fury_cur'] for s in spirits),
            p['fury_max'] + sum(s['fury_max'] for s in spirits))


def choose_main(p, spirit_id):
    normalize(p)
    if spirit_id is not None and spirit_id not in {s['id'] for s in p['spirits']}:
        raise ValueError('Duch už není ve tvé sbírce.')
    p['main_spirit_id'] = spirit_id
    p['main_spirit_choice_pending'] = False
    normalize(p)


def bonuses(p, perks):
    available = pool(p, perks)
    f = p['furioka']
    atk = min(available, max(0, f['atk_amount'])) if UTOK in perks else 0
    defense = min(available - atk, max(0, f['def_amount'])) if OBRANA in perks else 0
    return atk, defense


def spend(p, amount, perks):
    amount = min(max(0, amount), pool(p, perks))
    remaining = amount
    sources = {s['id']: s for s in linked(p, perks)}
    order = list(dict.fromkeys(p['furioka'].get('source_order', []) + ['self'] + list(sources)))
    report = []
    for key in order:
        source = p if key == 'self' else sources.get(key)
        if source is None:
            continue
        before = source['fury_cur']
        take = min(before, remaining)
        source['fury_cur'] -= take
        remaining -= take
        if take:
            report.append(dict(name='vlastní' if key == 'self' else source['name'], amount=take,
                               exhausted=key != 'self' and before > 0 and source['fury_cur'] == 0))
    p['_furioku_spent'] = report
    return amount


def absorb(p, damage, perks):
    _, defense = bonuses(p, perks)
    amount = min(max(0, damage), defense)
    spend(p, amount, perks)
    p['furioka']['def_amount'] = max(0, p['furioka']['def_amount'] - amount)
    return max(0, damage) - amount, amount


def attack(p, perks):
    amount, _ = bonuses(p, perks)
    spend(p, amount, perks)
    p['furioka']['atk_amount'] = 0
    return amount


def recalc(p):
    normalize(p)
    maximum = max(0, 5 * sum(p.get(k, 0) for k in ('vliv_svetlo', 'vliv_temnota', 'vliv_rovnovaha')) + p.get('fury_max_bonus', 0))
    p['fury_cur'] = max(0, min(maximum, p.get('fury_cur', 0) + maximum - p.get('fury_max', 0)))
    p['fury_max'] = maximum


def threshold(rank):
    return max(1, int(100 * rank ** 1.6))


def grant_xp(p, amount):
    results = []
    if amount <= 0:
        return results
    for s in equipped(p):
        old = s['rank']
        original_max = s['fury_max']
        s['xp'] = s.get('xp', 0) + amount
        s['total_xp'] = s.get('total_xp', 0) + amount
        # Ignore legacy penalties from failed random advancement.
        while s['xp'] >= threshold(s['rank']):
            s['xp'] -= threshold(s['rank'])
            s['rank'] += 1
            gain = max(1, int(s['fury_max'] * .25))
            s['fury_max'] += gain
            s['fury_cur'] += gain
        s['fury'] = s['fury_max']
        s['xp_threshold'] = threshold(s['rank'])
        results.append(dict(ranked_up=s['rank'] > old, old_rank=old, new_rank=s['rank'], spirit_name=s['name'], fury_gained=s['fury_max'] - original_max))
    return results


def rest(p, pct):
    normalize(p)
    lines = []
    for s in p['spirits']:
        old = s['fury_cur']
        s['fury_cur'] = min(s['fury_max'], old + int(s['fury_max'] * pct))
        if old != s['fury_cur']:
            lines.append(f"👻 {s['name']}: {old} → **{s['fury_cur']}** / {s['fury_max']}")
    return lines


def consumption_note(p):
    report = p.pop('_furioku_spent', [])
    if not report:
        return ''
    detail = ' · '.join(f"{r['name']} {r['amount']}" for r in report)
    exhausted = ' '.join(f"💤 {r['name']} vyčerpal svou furioku." for r in report if r['exhausted'])
    return f"🔥 Spotřeba: {detail}. {exhausted}".strip()


def allocate(p, perks, attack_amount, defense_amount):
    normalize(p)
    if attack_amount < 0 or defense_amount < 0:
        raise ValueError('Částky nesmí být záporné.')
    if attack_amount and UTOK not in perks or defense_amount and OBRANA not in perks:
        raise ValueError('Chybí perk Útok nebo Obrana.')
    if attack_amount + defense_amount > pool(p, perks):
        raise ValueError('Nemáš tolik dostupné energie.')
    p['furioka'].update(atk_amount=attack_amount, def_amount=defense_amount)


def set_source_order(p, names):
    normalize(p)
    by_name = {s['name'].casefold(): s['id'] for s in p['spirits']}
    order = []
    for name in names:
        key = 'self' if name.strip().casefold() == 'já' else by_name.get(name.strip().casefold())
        if key is None:
            raise ValueError(f'Neznámý duch: {name}')
        if key in order:
            raise ValueError('Každý zdroj uveď jen jednou.')
        order.append(key)
    p['furioka']['source_order'] = order


def save_preset(p, name):
    from copy import deepcopy
    normalize(p)
    name = name.strip()
    if not name or len(name) > 60:
        raise ValueError('Název sestavy musí mít 1–60 znaků.')
    p.setdefault('furioku_presets', {})[name] = deepcopy({
        key: p['furioka'].get(key, [] if key in ('spirit_ids', 'source_order') else 0)
        for key in ('spirit_ids', 'source_order', 'atk_amount', 'def_amount')})


def load_preset(p, name, perks):
    from copy import deepcopy
    normalize(p)
    preset = p.get('furioku_presets', {}).get(name.strip())
    if preset is None:
        raise ValueError('Tato sestava neexistuje.')
    f = deepcopy(preset)
    valid = {s['id'] for s in p['spirits']}
    f['spirit_ids'] = [i for i in f['spirit_ids'] if i in valid] if JEDNOTA in perks else []
    f['source_order'] = [i for i in f['source_order'] if i == 'self' or i in valid]
    p['furioka'] = f
    attack_amount, defense_amount = bonuses(p, perks)
    f.update(atk_amount=attack_amount, def_amount=defense_amount)
    return 'Sestava načtena. Přidělení je omezené aktuální energií a vlastněnými perky.'
