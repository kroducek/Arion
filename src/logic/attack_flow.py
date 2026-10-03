"""DM-directed attack lifecycle. Related state/resources are committed atomically."""
import copy
import os
import uuid
from src.database import db
from src.utils.paths import COMBAT_STATE, PROFILES, PLAYER_PERKS
from src.logic.dice import roll_expr
from src.logic import furioku as energy

COMBAT = os.path.basename(COMBAT_STATE)
PROFILES_DOC = os.path.basename(PROFILES)
PERKS_DOC = os.path.basename(PLAYER_PERKS)
PENDING = 'pending_attacks'


def transaction(channel, change):
    def mutate(docs):
        state = docs[COMBAT].get(str(channel))
        if state is None:
            raise ValueError('Combat už neběží.')
        return change(state, docs[PROFILES_DOC], docs[PERKS_DOC])
    return db.update_documents([COMBAT, PROFILES_DOC, PERKS_DOC], mutate)


def pending(state, attack_id):
    attack = state.get(PENDING, {}).get(str(attack_id))
    if not attack:
        raise ValueError('Útok už byl vyhodnocen nebo zrušen.')
    return attack


def actor_profile(state, profiles, actor):
    from src.logic import combat as c
    stat = state.get('stats', {}).get(actor)
    if stat is None:
        raise ValueError('Účastník už není v boji.')
    uid = c._actor_uid(actor)
    if uid is None:
        return None, None
    key = stat.get('profile_key') or c._pk(profiles, uid)
    p = profiles.get(key)
    if p is None:
        raise ValueError('Profil účastníka neexistuje.')
    stat['profile_key'] = key
    return key, p


def check_turn(state, actor, dm=False, force=False):
    from src.logic import combat as c
    if actor not in state.get('order', []) or actor not in state.get('stats', {}):
        raise ValueError('Nejsi účastníkem tohoto boje.')
    if dm and force:
        return
    if c.is_down(state, actor):
        raise ValueError('Vyřazený účastník nemůže útočit.')
    if not state.get('locked'):
        raise ValueError('DM musí nejprve potvrdit pořadí boje.')
    current = state['order'][state.get('current_index', 0)]
    if actor != current:
        raise ValueError('Nejsi na tahu. Akci mimo tah může povolit DM.')


def prepare(channel, actor, target, action='attack', weapon_id=None, ammo=None,
            bonus=0, dm=False, force=False, npc_expr=None, npc_slot='main'):
    from src.logic import combat as c
    def change(state, profiles, player_perks):
        check_turn(state, actor, dm, force)
        if action not in ('attack', 'bonus'):
            raise ValueError('Neplatná útočná akce.')
        if actor == target:
            raise ValueError('Útok musí mít jiný cíl.')
        if target not in state['stats']:
            raise ValueError('Cíl není v boji.')
        if c.is_down(state, target) and not (dm and force):
            raise ValueError('Cíl je vyřazený; výjimku povolí DM.')
        if len(state.get(PENDING, {})) >= 25:
            raise ValueError('Nejprve vyřešte některé z čekajících útoků.')
        key, p = actor_profile(state, profiles, actor)
        target_key, _ = actor_profile(state, profiles, target)
        from src.database.characters import pkey
        if p is not None and not _active_character(key, c._actor_uid(actor)):
            raise ValueError('Přepni se na postavu účastnící se boje.')
        resources = dict(uid=c._actor_uid(actor), profile_key=key, mana=0,
                         ammo_id=None, ammo_qty=0)
        statuses = []
        mana_note = ''
        if p is not None:
            items = c._load_items_db()
            wid = weapon_id or p.get('equipment', {}).get('hand_l' if action == 'bonus' else 'hand_r')
            if not wid or wid not in c._player_weapons(p) and not (dm and force):
                raise ValueError('Vyber zbraň, kterou máš v ruce.')
            item = items.get(wid, {})
            expr = c.item_damage_expr(item)
            if not expr:
                raise ValueError('Zbraň nemá nastavené poškození.')
            weapon_label = item.get('name', wid)
            mana, runes_active, mana_note = c.mana_for_attack(item, p)
            resources['mana'] = mana
            entry = c._weapon_entry(p, wid)
            bs = c._bs()
            if entry and bs:
                statuses = [(sid, source) for sid, source in bs.weapon_delivered(entry, db.load_doc(os.path.basename(bs.RUNES_FILE), {}) or bs.DEFAULT_RUNES)
                            if runes_active or source != 'runa']
        else:
            if not dm:
                raise ValueError('Za NPC jedná DM.')
            weapon = c.npc_weapon(state['stats'][actor], npc_slot)
            expr = c.normalize_dmg_expr(npc_expr) if npc_expr else (weapon or {}).get('dmg')
            if not expr:
                raise ValueError('NPC nemá nastavené poškození zbraně.')
            wid = None
            weapon_label = c.npc_weapon_label(weapon, npc_slot) if weapon else 'improvizovaný útok'
            statuses = c.npc_weapon_statuses(weapon) if weapon and not npc_expr else []
        if not c.use_action(state, actor, action, force=dm and force):
            raise ValueError('Tuto akci už jsi použil. Výjimku povolí DM.')
        roll = roll_expr(expr)
        damage = roll.total + int(bonus)
        details = [f'{expr}: {roll.detail} = {roll.total}']
        if bonus:
            details.append(f'úprava {bonus:+d}')
        if ammo and p is not None:
            ammunition = items.get(ammo, {})
            if ammunition.get('category') != c.AMMO_CATEGORY or not c._consume_ammo(p, ammo):
                raise ValueError('Tuto munici nemáš nebo nejde o munici.')
            ammo_expr = c.item_damage_expr(ammunition)
            if ammo_expr:
                ammo_roll = roll_expr(ammo_expr)
                damage += ammo_roll.total
                details.append(f'munice {ammo_roll.detail} = {ammo_roll.total}')
            resources.update(ammo_id=ammo, ammo_qty=1)
        elif p is not None and c._is_ranged(item):
            raise ValueError('Vyber dostupnou munici pro střelnou zbraň.')
        buffs_before = copy.deepcopy(state.get('buffs', {}).get(actor, []))
        for buff in c.take_attack_buffs(state, actor):
            r = roll_expr(str(buff.get('dmg') or '0'))
            damage += r.total
            details.append(f"{buff['name']}: {r.detail} = {r.total}")
        # Stable id exists before Discord sends the message.
        aid = uuid.uuid4().hex
        attack = dict(flow_version=1, id=aid, attacker=actor, attacker_uid=c._actor_uid(actor),
                      target=target, damage=max(0, damage), weapon_id=wid, weapon_label=weapon_label,
                      mana_cost=resources['mana'], mana_note=mana_note, resources=resources, extra_statuses=statuses,
                      roll_info=' · '.join(details), action=action, reaction='', requests=[],
                      costs=[], actors={actor: key, target: target_key}, buffs_before=buffs_before,
                      turn_serial=state.get('turn_serial', {}).get(actor, 0), phase='reaction')
        state.setdefault(PENDING, {})[aid] = attack
        return copy.deepcopy(attack)
    return transaction(channel, change)


def attach_message(channel, aid, message_id, bot_id):
    def change(state, profiles, perks):
        pending(state, aid).update(message_id=str(message_id), bot_id=str(bot_id))
    transaction(channel, change)


def update_reaction(channel, aid, user_id, dm, text):
    from src.logic import combat as c
    def change(state, profiles, perks):
        a = pending(state, aid)
        if not dm and (c._actor_uid(a['target']) != user_id or not _active_character(a.get('actors', {}).get(a['target']), user_id)):
            raise ValueError('Reakci zadává cíl útoku nebo DM.')
        if not text.strip():
            raise ValueError('Popiš reakci alespoň jednou větou.')
        a['reaction'] = text.strip()[:600]
        a['phase'] = 'decision'
        return copy.deepcopy(a)
    return transaction(channel, change)


class _ValidationRng:
    def randint(self, lo, hi):
        return lo


def request_roll(channel, aid, dm, actor, expr, attrs=(), note='', reroll=None):
    if not dm:
        raise ValueError('Hody vyžaduje DM.')
    from src.logic.roll import CHECK_ATTRS
    expr = expr.lower().replace(' ', '')
    roll_expr(expr, rng=_ValidationRng())
    attrs = list(dict.fromkeys(a.upper() for a in attrs if a))
    if len(attrs) > 2 or any(a not in CHECK_ATTRS for a in attrs):
        raise ValueError('Zadej nejvýše dva platné atributy, např. DEX nebo STR,DEX.')
    def change(state, profiles, perks):
        a = pending(state, aid)
        selected = a['attacker'] if actor in ('útok', 'utok') else a['target'] if actor in ('cíl', 'cil') else actor
        key, _ = actor_profile(state, profiles, selected)
        if len(a.setdefault('requests', [])) >= 40:
            raise ValueError('Tento útok už má příliš mnoho požadavků na hod.')
        if reroll:
            old = next((r for r in a['requests'] if r['id'] == reroll), None)
            if old is None or old.get('superseded'):
                raise ValueError('Původní hod neexistuje.')
            old['superseded'] = True
        r = dict(id=uuid.uuid4().hex[:12], actor=selected, profile_key=key,
                 expr=expr, attrs=attrs, note=note[:200], result=None)
        a['requests'].append(r)
        a['actors'][selected] = key
        a['phase'] = 'rolls'
        return copy.deepcopy(a)
    return transaction(channel, change)


def available_rolls(channel, user_id, dm=False, expr=None, attrs=None):
    from src.logic import combat as c
    state = db.load_doc(COMBAT, {}).get(str(channel), {})
    out = []
    for aid, a in state.get(PENDING, {}).items():
        for r in a.get('requests', []):
            uid = c._actor_uid(r['actor'])
            if r.get('result') is not None or r.get('superseded'):
                continue
            if uid != user_id and not (uid is None and dm):
                continue
            if expr is not None and r['expr'] != expr.lower().replace(' ', ''):
                continue
            if attrs is not None and set(r['attrs']) != set(attrs):
                continue
            out.append((aid, copy.deepcopy(r)))
    return out


def submit_roll(channel, aid, rid, user_id, dm=False):
    from src.logic import combat as c
    from src.logic.roll import evaluate_roll
    from src.database.characters import pkey, use_slot
    def change(state, profiles, perks):
        a = pending(state, aid)
        r = next((r for r in a.get('requests', []) if r['id'] == rid), None)
        if r is None or r.get('superseded') or r.get('result') is not None:
            raise ValueError('Tento hod už je uzavřený. Další pokus povolí DM.')
        uid = c._actor_uid(r['actor'])
        stat = state.get('stats', {}).get(r['actor'])
        if stat is None or r.get('profile_key') and stat.get('profile_key') != r['profile_key']:
            raise ValueError('Účastník se změnil. DM musí vyžádat nový hod.')
        if uid is not None:
            if uid != user_id or not _active_character(r['profile_key'], uid):
                raise ValueError('Hod patří jiné postavě. Přepni se na správnou postavu.')
            p = profiles.get(r['profile_key'])
            if p is None:
                raise ValueError('Profil již neexistuje.')
            with use_slot(uid, r['profile_key'].split(':')[-1] if ':' in r['profile_key'] else '1'):
                result = evaluate_roll(r['expr'], p, uid, r['attrs'])
        else:
            if not dm:
                raise ValueError('Za NPC hází DM.')
            result = evaluate_roll(r['expr'], state['stats'][r['actor']], None, r['attrs'])
        r['result'] = result
        a['phase'] = 'rolls' if any(x.get('result') is None and not x.get('superseded') for x in a['requests']) else 'decision'
        return copy.deepcopy(a), copy.deepcopy(r)
    return transaction(channel, change)


def confirm_cost(channel, aid, dm, mana=0, reaction=False, perk_id='', already_paid=False):
    """Confirmed defensive costs remain paid on a miss; cancel can explicitly refund."""
    if not dm:
        raise ValueError('Náklady potvrzuje DM.')
    if mana < 0:
        raise ValueError('Cena many nesmí být záporná.')
    from src.logic import combat as c
    from src.core.dnd.perks import load_perks, _check_and_use_cooldown
    def change(state, profiles, perks):
        a = pending(state, aid)
        if a.get('costs'):
            raise ValueError('Náklady už byly potvrzeny; nepřičítají se podruhé.')
        key, p = actor_profile(state, profiles, a['target'])
        record = dict(profile_key=key, actor=a['target'], mana=mana, reaction=reaction,
                      perk_id=perk_id, already_paid=already_paid,
                      turn_serial=state.get('turn_serial', {}).get(a['target'], 0))
        if not already_paid:
            if mana:
                if p is None or p.get('mana_cur', p.get('mana_max', 0)) < mana:
                    raise ValueError('Cíl nemá dost many.')
                p['mana_cur'] = p.get('mana_cur', p.get('mana_max', 0)) - mana
            if reaction and not c.use_action(state, a['target'], 'reaction'):
                raise ValueError('Reakce je už spotřebovaná. Pokud byla použita jiným příkazem, označ již zaplaceno.')
            if perk_id:
                player = perks.get(key, {})
                perk = load_perks().get(perk_id)
                if not perk or perk_id not in player.get('perks', []):
                    raise ValueError('Cíl tento perk nevlastní.')
                record['cooldown_before'] = copy.deepcopy(player.get('cooldowns', {}).get(perk_id))
                player.setdefault('cooldowns', {})
                ok, error = _check_and_use_cooldown(player, perk_id, perk)
                if not ok:
                    raise ValueError(error)
                record['cooldown_after'] = copy.deepcopy(player['cooldowns'].get(perk_id))
        a['costs'] = [record]
        return copy.deepcopy(a)
    return transaction(channel, change)


def _refund_costs(state, profiles, perks, costs):
    from src.logic import combat as c
    for cost in costs:
        if cost.get('already_paid'):
            continue
        p = profiles.get(cost.get('profile_key'))
        if p is not None and cost.get('mana'):
            p['mana_cur'] = min(p.get('mana_max', 0), p.get('mana_cur', 0) + cost['mana'])
        if cost.get('reaction') and state.get('turn_serial', {}).get(cost['actor'], 0) == cost.get('turn_serial', 0):
            c.release_action(state, cost['actor'], 'reaction')
        if cost.get('perk_id'):
            cds = perks.get(cost.get('profile_key'), {}).get('cooldowns', {})
            pid = cost['perk_id']
            # Do not erase a later unrelated use of the same ability.
            if cds.get(pid) == cost.get('cooldown_after'):
                if cost.get('cooldown_before') is None:
                    cds.pop(pid, None)
                else:
                    cds[pid] = cost['cooldown_before']


def context_lines(a):
    lines = []
    if a.get('reaction'):
        lines.append('Reakce: ' + a['reaction'])
    for r in a.get('requests', []):
        if r.get('result'):
            suffix = ' (nahrazený hod)' if r.get('superseded') else ''
            result = r['result']
            lines.append(f"🎲 {r['actor']} · {','.join(r['attrs']) or r['expr']}: {result['total']}{suffix} · {result.get('stat_note', '')}")
    for cost in a.get('costs', []):
        lines.append(f"Náklady obrany: {cost['mana']} many · reakce {'ano' if cost['reaction'] else 'ne'} · perk {cost['perk_id'] or '—'}" + (' (zaplaceno jiným příkazem)' if cost['already_paid'] else ''))
    return lines


def resolve(channel, aid, dm, outcome, damage=None, bypass=False, refund=False):
    from src.logic import combat as c
    if not dm:
        raise ValueError('Výsledek určuje pouze DM.')
    if outcome not in ('hit', 'miss', 'cancel') or damage is not None and damage < 0:
        raise ValueError('Neplatný výsledek nebo záporné poškození.')
    def change(state, profiles, perks):
        a = pending(state, aid)
        incomplete = not a.get('reaction') or any(r.get('result') is None and not r.get('superseded') for r in a.get('requests', []))
        if incomplete and outcome != 'cancel' and not bypass:
            raise ValueError('Chybí reakce nebo hod. DM může použít „Rozhodnout bez čekání“.')
        attacker, target = a['attacker'], a['target']
        for actor, key in (a.get('actors', {}).items() if outcome != 'cancel' else []):
            if actor not in state['stats'] or key and (state['stats'][actor].get('profile_key') != key or key not in profiles):
                raise ValueError('Účastníci se změnili. Zruš útok a vytvoř nový.')
        stat = state['stats'].get(target, {})
        key = a.get('actors', {}).get(attacker) or a.get('resources', {}).get('profile_key')
        p = profiles.get(key)
        before_profiles = {}
        before_stats = {}
        for actor in dict.fromkeys((attacker, target)):
            carrier = state['stats'].get(actor)
            if carrier is None:
                continue
            pk = a.get('actors', {}).get(actor)
            prof = profiles.get(pk)
            if prof is not None:
                carrier['energy'] = c._energy_state(prof)
                from src.logic.spirits import _owned_perks
                from src.database.characters import use_slot
                uid = c._actor_uid(actor)
                with use_slot(uid, pk.split(':')[-1] if ':' in pk else '1'):
                    carrier['energy_perks'] = _owned_perks(uid)
                carrier['hp'] = prof.get('hp_cur', carrier.get('hp', 0))
                carrier['statuses'] = copy.deepcopy(prof.get('statuses', []))
                carrier['fur'] = energy.pool(carrier['energy'], carrier['energy_perks'])
                before_profiles[pk] = dict(energy=c._energy_state(prof), hp_cur=prof.get('hp_cur'), statuses=copy.deepcopy(prof.get('statuses', [])))
            before_stats[actor] = c.stat_snapshot(carrier)
        before = c.stat_snapshot(stat)
        res = copy.deepcopy(a.get('resources', {}))
        res['flow'] = True
        mana_paid = 0
        lines = [f"⚔️ {attacker} → {target} · {a.get('weapon_label', '')}", a.get('roll_info', '')] + context_lines(a)
        if damage is not None:
            lines.append(f'DM upravil celkové poškození na {damage} před DEF a štítem.')
        if bypass and incomplete:
            lines.append('DM rozhodl bez čekání na reakci / zbývající hody.')
        if outcome == 'cancel':
            if p is not None and res.get('ammo_qty'):
                c._add_to_inventory(p.setdefault('inventory', []), res['ammo_id'], res['ammo_qty'])
            if state.get('turn_serial', {}).get(attacker, 0) == a.get('turn_serial', 0):
                c.release_action(state, attacker, a.get('action', 'attack'))
                _restore_buffs(state, a)
            if refund:
                _refund_costs(state, profiles, perks, a.get('costs', []))
            lines.append('DM: útok zrušen. Rezervace vráceny.' + (' Potvrzené náklady obrany vráceny.' if refund else ' Potvrzené náklady obrany zůstávají zaplacené.'))
        else:
            if p is not None and res.get('mana'):
                mana_paid = res['mana']
                if p.get('mana_cur', p.get('mana_max', 0)) < mana_paid:
                    raise ValueError('Útočník už nemá dost many. Doplň ji nebo útok zruš.')
                p['mana_cur'] = p.get('mana_cur', p.get('mana_max', 0)) - mana_paid
            if outcome == 'hit':
                fury = c._attack_energy(state, attacker, res)
                # DM override is the complete raw damage, including any furioku contribution.
                raw = a['damage'] + fury if damage is None else damage
                result = c.apply_hit(stat, raw)
                bs = c._bs()
                applied = c.deliver_statuses(stat, a.get('extra_statuses', []), bs, (db.load_doc(os.path.basename(bs.STATUSES_FILE), {}) or bs.DEFAULT_STATUSES) if bs else {})
                lines.append('DM: zásah · ' + result['change_str'])
                if res.get('energy_note'):
                    lines.append('Útok: ' + res['energy_note'])
                lines += applied
            else:
                lines.append('DM: minutí.')
            for actor in (attacker, target):
                pk = a.get('actors', {}).get(actor)
                prof = profiles.get(pk)
                carrier = state['stats'][actor]
                if prof is not None:
                    c._merge_energy(prof, carrier.get('energy'))
                    prof['hp_cur'] = carrier['hp']
                    prof['statuses'] = copy.deepcopy(carrier.get('statuses', []))
            lines.append(f"❤️ {target}: {before['hp']} → {stat['hp']}/{stat.get('max_hp', 0)}")
            if mana_paid:
                lines.append(f'🔷 Útočník: −{mana_paid} many')
        event = c.log_event(state, 'attack' if outcome == 'hit' else outcome, target, before,
                            c.stat_snapshot(stat), detail=' · '.join(lines), actor=attacker,
                            revert=outcome != 'cancel', resources=res)
        event['flow_attack'] = copy.deepcopy(a)
        event['flow_before_profiles'] = before_profiles
        event['flow_before_stats'] = before_stats
        event['flow_mana_paid'] = mana_paid
        del state[PENDING][str(aid)]
        return dict(attack=copy.deepcopy(a), lines=lines, event=event)
    return transaction(channel, change)


def undo(channel):
    from src.logic import combat as c
    def change(state, profiles, perks):
        event = next((e for e in reversed(state.get('log', [])) if not e.get('undone') and e.get('revert', True)), None)
        if not event or 'flow_attack' not in event:
            return None
        a = event['flow_attack']
        for actor, snapshot in event['flow_before_stats'].items():
            if actor in state['stats']:
                state['stats'][actor].update(copy.deepcopy(snapshot))
        for pk, snapshot in event['flow_before_profiles'].items():
            p = profiles.get(pk)
            if p is not None:
                c._merge_energy(p, snapshot['energy'])
                p['hp_cur'] = snapshot['hp_cur']
                p['statuses'] = snapshot['statuses']
        p = profiles.get(a.get('resources', {}).get('profile_key'))
        if p is not None:
            p['mana_cur'] = min(p.get('mana_max', 0), p.get('mana_cur', 0) + event.get('flow_mana_paid', 0))
            res = a.get('resources', {})
            if res.get('ammo_qty'):
                c._add_to_inventory(p.setdefault('inventory', []), res['ammo_id'], res['ammo_qty'])
        _refund_costs(state, profiles, perks, a.get('costs', []))
        if state.get('turn_serial', {}).get(a['attacker'], 0) == a.get('turn_serial', 0):
            c.release_action(state, a['attacker'], a.get('action', 'attack'))
            _restore_buffs(state, a)
        event['undone'] = True
        return copy.deepcopy(event)
    return transaction(channel, change)


def _restore_buffs(state, a):
    current = state.setdefault('buffs', {}).setdefault(a['attacker'], [])
    current.extend(copy.deepcopy(b) for b in a.get('buffs_before', []) if b.get('scope') == 'attack')


def migrate_legacy(channel, aid):
    """Keep pre-rework pending attacks usable, without reserving ammunition twice."""
    from src.logic import combat as c
    def change(state, profiles, perks):
        a = pending(state, aid)
        if a.get('flow_version'):
            return copy.deepcopy(a)
        actors = {}
        for actor in (a['attacker'], a['target']):
            actors[actor], _ = actor_profile(state, profiles, actor)
        res = a.setdefault('resources', {})
        res.setdefault('profile_key', actors[a['attacker']])
        res.setdefault('mana', a.get('mana_cost', 0))
        a.update(flow_version=1, id=str(aid), message_id=str(aid), actors=actors,
                 action='attack', reaction='', requests=[], costs=[], buffs_before=[],
                 turn_serial=state.get('turn_serial', {}).get(a['attacker'], 0), phase='reaction')
        # Old player attacks captured statuses only at confirmation.
        p = profiles.get(actors[a['attacker']])
        if p and a.get('weapon_id'):
            entry = c._weapon_entry(p, a['weapon_id'])
            bs = c._bs()
            if entry and bs:
                item = c._load_items_db().get(a['weapon_id'], {})
                _, active, _ = c.mana_for_attack(item, p)
                a['extra_statuses'] = [(sid, source) for sid, source in bs.weapon_delivered(entry, db.load_doc(os.path.basename(bs.RUNES_FILE), {}) or bs.DEFAULT_RUNES)
                                       if active or source != 'runa']
        return copy.deepcopy(a)
    return transaction(channel, change)


def _active_character(key, uid):
    from src.database.characters import pkey
    active = pkey(uid)
    return key == active or (key == str(uid) and active == f'{uid}:1')


def set_npc_stats(channel, actor, dm, values):
    """Set check attributes for an NPC in this combat, or return their current values."""
    from src.logic import combat as c
    from src.logic.stats import STAT_LABELS
    if not dm:
        raise ValueError('Atributy NPC nastavuje pouze DM.')
    if any(k not in STAT_LABELS or type(v) is not int or v < 0 for k, v in values.items()):
        raise ValueError('Atribut musí být nezáporné celé číslo: STR, DEX, INS, INT, CHA nebo WIS.')
    def change(state, profiles, perks):
        stat = state.get('stats', {}).get(actor)
        if stat is None:
            raise ValueError('Toto NPC není v boji.')
        if c._actor_uid(actor) is not None:
            raise ValueError('Tento příkaz je pouze pro NPC a bosse. Hráčovy atributy se čtou z profilu.')
        attrs = stat.setdefault('stats', {})
        before = {k: attrs.get(k, 0) for k in STAT_LABELS}
        attrs.update(values)
        if values:
            snapshot = c.stat_snapshot(stat)
            c.log_event(state, 'stat', actor, snapshot, snapshot,
                detail=' · '.join(f'{k} {before[k]} → {v}' for k, v in values.items()), revert=False)
        return {k: attrs.get(k, 0) for k in STAT_LABELS}
    return transaction(channel, change)
