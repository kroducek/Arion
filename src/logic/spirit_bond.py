"""Persistent DM bonding; progress and evolution commit together in profiles."""
from src.logic import furioku as energy
from src.utils.json_utils import update_json
from src.utils.paths import PROFILES


def change_bond(channel_id, action, *, profile_key=None, user_id=None,
                spirit_name=None, new_maximum=None, interaction_id=None):
    channel = str(channel_id)
    result = {}

    def mutate(profiles):
        active = [(key, p, p.get('spirit_bonds', {}).get(channel))
                  for key, p in profiles.items() if channel in p.get('spirit_bonds', {})]
        if interaction_id is not None and any(str(interaction_id) in p.get('bond_receipts', []) for p in profiles.values()):
            raise ValueError('Tento krok už byl zpracován.')
        if action == 'start':
            if active:
                raise ValueError('V tomto kanálu už bonding probíhá. Dokonči ho nebo použij /duch bond fail.')
            p = profiles.get(profile_key)
            if p is None:
                raise ValueError('Hráč nemá profil.')
            energy.normalize(p)
            spirit = next((s for s in p['spirits'] if s['name'].casefold() == spirit_name.casefold()), None)
            if spirit is None:
                raise ValueError('Hráč tohoto ducha nevlastní.')
            if any(b['spirit_id'] == spirit['id'] for b in p.get('spirit_bonds', {}).values()):
                raise ValueError('S tímto duchem už bonding probíhá v jiném kanálu.')
            state = dict(user_id=user_id, spirit_id=spirit['id'], spirit_name=spirit['name'], successes=0)
            p.setdefault('spirit_bonds', {})[channel] = state
            result.update(state)
        else:
            if not active:
                raise ValueError('V tomto kanálu neprobíhá žádný bonding.')
            _, p, state = active[0]
            result.update(state)
            if action == 'fail':
                del p['spirit_bonds'][channel]
            elif action == 'success':
                energy.normalize(p)
                spirit = next((s for s in p['spirits'] if s['id'] == state['spirit_id']), None)
                if spirit is None:
                    raise ValueError('Duch už neexistuje. Bonding zruš přes /duch bond fail.')
                count = state['successes'] + 1
                if new_maximum is not None and count != 3:
                    raise ValueError('Nové maximum můžeš zadat až při třetím úspěchu.')
                if count == 3:
                    old = spirit['fury_max']
                    maximum = old * 2 if new_maximum is None else new_maximum
                    if maximum < old:
                        raise ValueError(f'Nové maximum nesmí být menší než současných {old}.')
                    spirit['fury_max'] = spirit['fury'] = maximum
                    spirit['fury_cur'] += maximum - old
                    spirit['bond_evolutions'] = spirit.get('bond_evolutions', 0) + 1
                    result.update(old_maximum=old, new_maximum=maximum)
                    del p['spirit_bonds'][channel]
                else:
                    state['successes'] = count
                result.update(successes=count, spirit_name=spirit['name'])
            else:
                raise ValueError('Neznámá akce bondingu.')
        if interaction_id is not None:
            receipts = p.setdefault('bond_receipts', [])
            receipts.append(str(interaction_id))
            del receipts[:-50]
        return profiles

    update_json(PROFILES, mutate)
    return result
