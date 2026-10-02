import copy
from src.logic import furioku as energy
import discord
import asyncio
import logging
import random
from typing import Optional
from discord.ext import commands
from discord import app_commands, ui
from src.utils.paths import COMBAT_STATE
from src.utils.json_utils import load_json, save_json, update_json
from src.database.characters import active_name as _active_char_name
from src.database.profiles import (
    load_items as _load_items_db,
    load_profiles as _load_profiles,
    profile_key as _pk,
    save_profiles as _save_profiles,
)
from src.logic.dice import DiceError, implicit_die, item_damage_expr, roll_expr
from src.logic.inventory import (
    TOULEC_ITEM_ID,
    _ac_consumable_item,
    _add_to_inventory,
    _find_consumable_entry,
    _remove_entry,
    _remove_from_inventory,
    apply_item_effects,
)
from src.utils.admin_gate import admin_only, mark_admin

# Munice a zbraně, které ji potřebují.
AMMO_CATEGORY     = "náboje"
RANGED_CATEGORIES = {"luky_kuše", "střelné"}

SOURCE_LABEL = {"zbran": "zbraň", "runa": "runa", "prostredi": "prostředí", "schopnost": "schopnost"}

def _bs():
    """Lazy import status/rune enginu (blacksmith). None když nedostupný."""
    try:
        from src.core.dnd import blacksmith
        return blacksmith
    except Exception:
        logging.getLogger(__name__).warning(
            "blacksmith modul nedostupný — statusy v boji vypnuty")
        return None

def _merge_energy(profile, state):
    if state is None:
        return
    energy.normalize(profile)
    profile['fury_cur'] = max(0, min(profile.get('fury_max', 0), state.get('fury_cur', 0)))
    profile['furioka']['atk_amount'] = state['furioka']['atk_amount']
    profile['furioka']['def_amount'] = state['furioka']['def_amount']
    current = {s['id']: s for s in state['spirits']}
    for spirit in profile['spirits']:
        if spirit['id'] in current:
            spirit['fury_cur'] = min(spirit['fury_max'], current[spirit['id']]['fury_cur'])


def _energy_state(profile):
    energy.normalize(profile)
    return copy.deepcopy({k: profile.get(k) for k in ('fury_cur', 'fury_max', 'spirits', 'main_spirit_id', 'equipped_spirit_ids', 'furioka')})


def _refresh_energy(combat):
    profiles = _load_profiles()
    from src.logic.spirits import _owned_perks
    for actor, stat in combat.get('stats', {}).items():
        uid = _actor_uid(actor)
        if uid is None:
            continue
        key = stat.get('profile_key') or _pk(profiles, uid)
        profile = profiles.get(key)
        if profile is None:
            continue
        stat['profile_key'] = key
        stat['energy'] = _energy_state(profile)
        from src.database.characters import use_slot
        with use_slot(uid, key.split(':')[-1]):
            stat['energy_perks'] = _owned_perks(uid)
        stat['fur'] = energy.pool(stat['energy'], stat['energy_perks'])
        stat['fur_max'] = energy.totals(stat['energy'], stat['energy_perks'])[1]


def _absorb_energy(stat, damage):
    if 'energy' in stat:
        rest, absorbed = energy.absorb(stat['energy'], damage, stat.get('energy_perks', []))
        stat['_energy_note'] = energy.consumption_note(stat['energy'])
        stat['fur'] = energy.pool(stat['energy'], stat.get('energy_perks', []))
        return rest, absorbed
    stat['_energy_note'] = ''
    # NPCs retain their explicitly configured shield.
    absorbed = min(max(0, stat.get('fur', 0)), damage)
    stat['fur'] = max(0, stat.get('fur', 0) - absorbed)
    return damage - absorbed, absorbed


def _attack_energy(combat, actor, resources):
    stat = combat.get('stats', {}).get(actor, {})
    if 'energy' not in stat:
        return 0
    before = copy.deepcopy(stat['energy'])
    amount = energy.attack(stat['energy'], stat.get('energy_perks', []))
    resources['energy_note'] = energy.consumption_note(stat['energy'])
    stat['fur'] = energy.pool(stat['energy'], stat.get('energy_perks', []))
    if amount:
        resources['energy_before'] = before
        resources['profile_key'] = stat.get('profile_key')
    return amount


def _writeback_attack(combat, actor, resources):
    if resources.get('energy_before') and _actor_uid(actor):
        stat = combat['stats'][actor]
        profiles = _load_profiles()
        profile = profiles.get(stat.get('profile_key') or _pk(profiles, _actor_uid(actor)))
        if profile is not None:
            _merge_energy(profile, stat['energy'])
            _save_profiles(profiles)


def apply_status_dmg(stat: dict, dmg: int) -> int:
    """Dmg ze statusu: DEF ignoruje, napřed ubere furioku, zbytek jde do HP.

    Mutuje `stat` (fur, hp). Vrací, kolik pohltila furioka.
    """
    dmg = max(0, int(dmg))
    rest, absorbed = _absorb_energy(stat, dmg)
    stat['hp'] = max(0, int(stat.get('hp', 0) or 0) - rest)
    return absorbed

def deliver_statuses(stat: dict, statuses: list, bs, reg: dict) -> list[str]:
    """Doručí statusy ze zásahu a hned jim dá první tik (jed −dmg HP).

    Mutuje `stat` (statuses, hp). Vrací popisky do konzole.
    """
    applied: list[str] = []
    if not bs:
        return applied
    for status_id, source in statuses:
        inst = bs.apply_status(stat, status_id, source, reg)
        if not inst:
            continue
        sdef = reg.get(status_id, {})
        label = f"{sdef.get('emoji', '•')} {sdef.get('name', status_id)}"
        dmg, note = bs.proc_on_delivery(stat, inst, reg)
        if dmg:
            absorbed = apply_status_dmg(stat, dmg)
            if absorbed:
                note += f" · 🔥 furioka pohltila {absorbed}"
                if stat.get("_energy_note"):
                    note += " · " + stat["_energy_note"]
        applied.append(f"{label}: {note}" if note else label)
    return applied

def _actor_uid(actor: str):
    """Z '<@123>' / '<@!123>' vytáhne int id, jinak None (NPC)."""
    if actor.startswith("<@"):
        digits = "".join(ch for ch in actor if ch.isdigit())
        return int(digits) if digits else None
    return None

def _writeback_player_state(uid: int, carrier: dict, bs=None) -> None:
    """Zapíše HP, statusy a energii do postavy svázané s bojem."""
    try:
        profiles = _load_profiles()
        p = profiles.get(carrier.get("profile_key") or _pk(profiles, uid))
        if not p:
            return
        p["hp_cur"]   = max(0, min(carrier.get("hp", 0), p.get("hp_max", 50)))
        p["statuses"] = carrier.get("statuses", [])
        _merge_energy(p, carrier.get('energy'))
        _save_profiles(profiles)
    except Exception:
        logging.exception("[combat] writeback hp/statusů selhal")

def _compute_def_from_equipment(profile: dict, items_db: dict) -> int:
    """Spočítá celkový DEF z equipmentu hráče."""
    equipment = profile.get("equipment", {})
    seen  = set()
    total = 0
    for item_id in equipment.values():
        if item_id and item_id not in seen:
            seen.add(item_id)
            total += items_db.get(item_id, {}).get("def", 0)
    return total

def _sync_player_from_profile(mention: str, user_id: int) -> dict | None:
    """
    Načte aktuální HP/DEF/FUR hráče z profiles.json.
    Vrátí dict {hp, max_hp, def, fur} nebo None pokud profil neexistuje.
    """
    profiles = _load_profiles()
    profile  = profiles.get(_pk(profiles, user_id))
    if not profile:
        return None
    items_db = _load_items_db()
    hp_cur  = profile.get("hp_cur",  profile.get("hp_max", 50))
    hp_max  = profile.get("hp_max",  50)
    fur_cur = profile.get("fury_cur", 0)
    fur_max = profile.get("fury_max", 0)
    def_val = _compute_def_from_equipment(profile, items_db)
    return {
        "hp":     hp_cur,
        "max_hp": hp_max,
        "def":    def_val,
        "fur":    fur_cur,
        "fur_max": fur_max,   # uložíme pro referenci
    }

# ── Bar helpers ───────────────────────────────────────────────────────────────

def _make_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "░" * length
    filled = max(0, min(length, round((current / maximum) * length)))
    return "█" * filled + "░" * (length - filled)


def apply_hit(stat: dict, raw_hit: int) -> dict:
    """Zásah: DEF pohltí napřed, pak se spotřebuje furioka, zbytek jde do HP.

    Mutuje `stat` (hp, fur) a vrací souhrn pro hlášku.
    """
    raw_hit = max(0, int(raw_hit))
    dfn = int(stat.get("def", 0) or 0)
    after_def = max(0, raw_hit - dfn)
    final, absorbed = _absorb_energy(stat, after_def)

    old_hp = int(stat.get("hp", 0) or 0)
    stat["hp"] = max(0, old_hp - final)

    parts = [f"zásah {raw_hit}"]
    if dfn:
        parts.append(f"−{min(dfn, raw_hit)} DEF")
    if absorbed:
        parts.append(f"−{absorbed} 🔥furioku")
    parts.append(f"= {final} do HP")
    if stat.get("_energy_note"):
        parts.append(stat["_energy_note"])

    return {
        "old_hp": old_hp,
        "new_hp": stat["hp"],
        "dmg": final,
        "absorbed_fur": absorbed,
        "change_str": "  ".join(parts),
    }


# ── Zbraně NPC ────────────────────────────────────────────────────────────────

NPC_SLOTS = {"main": "hlavní zbraň", "bonus": "bonusová zbraň"}


def normalize_dmg_expr(raw: str) -> str:
    """Zápis damage NPC → hoditelný výraz. Holé číslo je kostka (`16` → `1d16`).

    Vyhodí `DiceError`, když výraz nejde hodit.
    """
    expr = implicit_die(str(raw or "").strip().replace(" ", ""))
    if not expr:
        raise DiceError("prázdný zápis")
    roll_expr(expr)
    return expr


CLEAR_TOKENS = {"-", "—", "smazat", "zadny", "žádný", "none", "zrušit"}


def set_npc_weapon(stat: dict, slot: str, expr: str | None = None,
                   name: str | None = None,
                   status: str | None = None) -> dict:
    """Založí nebo upraví zbraň NPC. `None` = pole se nemění.

    Zbraň se smaže jen `expr` z `CLEAR_TOKENS` (`-`), aby šlo doplňovat samotný
    status už nastavené zbrani; `status="-"` status sundá.

    `status` je id statusu z blacksmithu (jed, krácení…), který zbraň doručí
    při potvrzeném zásahu — NPC tak umí to samé co hráčská natřená zbraň.
    """
    weapons = stat.setdefault("weapons", {})
    expr_txt = str(expr).strip() if expr is not None else ""
    if expr is not None and expr_txt.lower() in CLEAR_TOKENS:
        weapons.pop(slot, None)
        return {}

    current = weapons.get(slot)
    weapon = dict(current) if isinstance(current, dict) else {}
    if expr_txt:
        weapon["dmg"] = normalize_dmg_expr(expr_txt)
    if not weapon.get("dmg"):
        raise DiceError("zbraň nemá damage")

    if name is not None and name.strip():
        weapon["name"] = name.strip()
    if status is not None:
        status_txt = status.strip()
        if not status_txt or status_txt.lower() in CLEAR_TOKENS:
            weapon.pop("status", None)
        else:
            weapon["status"] = status_txt
    weapons[slot] = weapon
    return weapon


def npc_weapon_statuses(weapon: dict) -> list[tuple[str, str]]:
    """Statusy, které zbraň NPC doručuje — formát sdílený s hráčskými zbraněmi."""
    status = str((weapon or {}).get("status") or "").strip()
    return [(status, "zbran")] if status else []


def npc_weapon(stat: dict, slot: str) -> dict | None:
    """Zbraň NPC, nebo None když ji nemá."""
    weapon = (stat.get("weapons") or {}).get(slot)
    return weapon if isinstance(weapon, dict) and weapon.get("dmg") else None


def npc_weapon_label(weapon: dict, slot: str) -> str:
    return str(weapon.get("name") or NPC_SLOTS.get(slot, slot)).strip()


def npc_weapons_line(stat: dict) -> str:
    """Přehled zbraní NPC pro embed: `⚔️ Palcát 1d8  ·  🗡️ Dýka 1d4`."""
    bits = []
    for slot, emoji in (("main", "⚔️"), ("bonus", "🗡️")):
        weapon = npc_weapon(stat, slot)
        if weapon:
            venom = f" 🩸{weapon['status']}" if weapon.get("status") else ""
            bits.append(
                f"{emoji} {npc_weapon_label(weapon, slot)} `{weapon['dmg']}`{venom}")
    return "  ·  ".join(bits)


# ── Konzole ───────────────────────────────────────────────────────────────────

CONSOLE_PREFIX = "-# "
CONSOLE_DELAY = 1.0


def console(text: str) -> str:
    """Řádek Arionovy konzole — malé písmo (`-#`)."""
    return CONSOLE_PREFIX + text


def hp_console(name: str, old_hp: int, new_hp: int, max_hp: int,
               change_str: str, attacker: str | None = None,
               notes: list[str] | None = None, weapon: str | None = None,
               roll_info: str | None = None) -> list[str]:
    """Hláška o změně HP rozepsaná na řádky konzole (vypisují se po jednom)."""
    bar = _make_bar(new_hp, max_hp, 8)
    with_weapon = f" *{weapon}*" if weapon else ""
    who = f"⚔️ {attacker}{with_weapon} → " if attacker else ""
    dead = "  💀" if new_hp == 0 else ""
    lines = []
    if roll_info:
        lines.append(console(f"**HIT** *({roll_info})*"))
    lines += [
        console(f"{who}❤️ **{name}**"),
        console(f"`{old_hp}` → `{new_hp}/{max_hp}` {bar}"),
        console(f"*({change_str})*{dead}"),
    ]
    lines += [console(note) for note in (notes or [])]
    return lines


def miss_console(target: str, attacker: str, damage: int,
                 weapon: str | None = None,
                 roll_info: str | None = None) -> list[str]:
    """Uhnutí / minutí — stejný výpis jako zásah, jen bez ubraných HP."""
    with_weapon = f" *{weapon}*" if weapon else ""
    return ([console(f"**MISS** *({roll_info})*")] if roll_info else []) + [
        console(f"🛡️ {attacker}{with_weapon} → ❤️ **{target}**"),
        console("`—` *uhnul / minul*"),
        console(f"*({damage} dmg se neaplikovalo)*"),
    ]


def status_tracker(stat: dict, registry: dict | None = None) -> str:
    """Statusy aktéra s trackerem dmg: `🧪 Jed I. 1d5 (2 kol)`."""
    reg = registry if registry is not None else {}
    bits = []
    for inst in stat.get("statuses") or []:
        sdef = reg.get(inst.get("status"), {})
        name = sdef.get("name", inst.get("status"))
        dmg = inst.get("dmg") or sdef.get("dmg", "")
        dmg_txt = f" `{dmg}`" if dmg else ""
        left = inst.get("kol_zbyva", 0)
        left_txt = f" *({left} kol)*" if left else ""
        bits.append(f"{sdef.get('emoji', '•')} {name}{dmg_txt}{left_txt}")
    return "  ·  ".join(bits)


def hp_recap_console(combat: dict) -> list[str]:
    """Přehled HP všech bojovníků — řádek na jednoho, ve stylu konzole."""
    stats = combat.get("stats", {})
    bs = _bs()
    reg = bs.load_statuses() if bs else {}
    lines = []
    for name in (combat.get("order") or list(stats)):
        s = stats.get(name)
        if not s:
            continue
        hp, max_hp = s.get("hp", 0), s.get("max_hp", 0)
        bar = _make_bar(hp, max_hp, 8)
        dead = "  💀" if hp == 0 else ""
        lines.append(console(f"❤️ **{name}** `{hp}/{max_hp}` {bar}{dead}"))
        tracker = status_tracker(s, reg)
        if tracker:
            lines.append(console(f"Status: {tracker}"))
    return lines


def turn_console(combat: dict, next_actor: str, new_round: bool = False) -> list[str]:
    """Předání tahu (a případný start nového kola) jako výpis konzole."""
    lines = []
    if new_round:
        lines.append(console(f"── kolo {combat.get('round', 1)} ──"))
        lines += hp_recap_console(combat)
    lines.append(console(f"⏭️ na tahu **{next_actor}**"))
    order = combat.get("order") or []
    if len(order) > 1 and next_actor in order:
        after = order[(order.index(next_actor) + 1) % len(order)]
        lines.append(console(f"po něm: {after}"))
    return lines


def undo_console(event: dict, target: str, hp: int, max_hp: int) -> list[str]:
    """Vrácení poslední změny HP ve stejném stylu jako zásah."""
    return [
        console(f"↩️ ❤️ **{target}**"),
        console(f"`{event['after'].get('hp', 0)}` → `{hp}/{max_hp}`"),
        console(f"*(vráceno: {event.get('detail') or event.get('kind', '')})*"),
    ]


async def stream_console(message, lines: list[str], header: str = "",
                         delay: float = CONSOLE_DELAY) -> None:
    """Dopisuje řádky do už odeslané zprávy po jednom — výpis konzole."""
    shown = lines[:1]
    for line in lines[1:]:
        await asyncio.sleep(delay)
        shown.append(line)
        try:
            await message.edit(content=header + "\n".join(shown))
        except Exception:
            logging.exception("[combat] výpis konzole se nepodařilo dopsat")
            return


# ── Akce v tahu (attack / bonus attack / perk / reakce) ───────────────────────

TURN_ACTIONS = ("attack", "bonus", "perk", "reaction")
ACTION_LABEL = {"attack": "útok", "bonus": "bonusový útok",
                "perk": "perk", "reaction": "reakce"}


def turn_state(combat: dict, actor: str) -> dict:
    """Počitadlo akcí aktéra v aktuálním tahu (vytvoří, když chybí)."""
    states = combat.setdefault("turn_state", {})
    state = states.setdefault(actor, {})
    for key in TURN_ACTIONS:
        state.setdefault(key, 0)
    return state


def use_action(combat: dict, actor: str, action: str, force: bool = False) -> bool:
    """Zapíše použití akce. False = aktér ji v tomhle tahu už použil."""
    state = turn_state(combat, actor)
    if state.get(action, 0) >= 1 and not force:
        return False
    state[action] = state.get(action, 0) + 1
    return True


def release_action(combat: dict, actor: str, action: str) -> None:
    """Vrátí akci zpět — útok se nakonec nekonal (chybí zbraň, munice, damage)."""
    state = turn_state(combat, actor)
    state[action] = max(0, state.get(action, 0) - 1)


def reset_turn(combat: dict, actor: str, reaction: bool = False) -> None:
    """Vyčistí počítadla aktéra — volá se na konci i na začátku jeho tahu.

    Začátek tahu musí smazat i akce, které aktér utratil mimo svůj tah
    (NPC útok z `/combat attack_npc`, reakce) — jinak by si je ukousl z
    příštího tahu. `reaction=True` vrací i reakci (začátek tahu, nové kolo).
    """
    state = turn_state(combat, actor)
    for key in ("attack", "bonus", "perk"):
        state[key] = 0
    if reaction:
        state["reaction"] = 0
        serial = combat.setdefault("turn_serial", {})
        serial[actor] = serial.get(actor, 0) + 1


def reset_reactions(combat: dict) -> None:
    """Nové kolo — všem se vrací reakce."""
    for actor in list(combat.get("turn_state", {})):
        turn_state(combat, actor)["reaction"] = 0


# ── Log boje + undo ──────────────────────────────────────────────────────────

LOG_LIMIT = 60
LOG_ICON = {"attack": "⚔️", "sethp": "🩹", "status": "🩸", "perk": "✨", "miss": "🛡️",
            "effect": "🧪", "cure": "🌿", "stat": "🛡", "remove": "❌", "item": "🧴"}

SNAPSHOT_KEYS = ("hp", "fur", "def", "max_hp")


def stat_snapshot(stat: dict) -> dict:
    """Stav aktéra pro undo — čísla i statusy (kopie, ne odkaz)."""
    snap = {key: int(stat.get(key, 0) or 0) for key in SNAPSHOT_KEYS}
    snap["statuses"] = copy.deepcopy(stat.get("statuses") or [])
    if "energy" in stat:
        snap["energy"] = copy.deepcopy(stat["energy"])
    return snap


def log_event(combat: dict, kind: str, target: str, before: dict, after: dict,
              detail: str = "", actor: str | None = None,
              revert: bool = True, resources: dict | None = None) -> dict:
    """Zapíše událost do logu boje. Vrací zapsaný záznam.

    `revert=False` je zápis bez změny stavu (minutý útok) — undo ani shrnutí
    ho neřeší, slouží jen jako stopa v historii. `resources` drží, co útok
    stál útočníka (`{"uid": 1, "mana": 10, "ammo_id": "sip", "ammo_qty": 1}`),
    aby to undo mohlo vrátit.
    """
    event = {
        "id": int(combat.get("log_seq", 0)) + 1,
        "kind": kind,
        "actor": actor,
        "target": target,
        "detail": detail,
        "before": before,
        "after": after,
        "round": int(combat.get("round", 1)),
        "undone": False,
        "revert": revert,
        "resources": resources or {},
    }
    combat["log_seq"] = event["id"]
    log = combat.setdefault("log", [])
    log.append(event)
    del log[:-LOG_LIMIT]
    return event


def undo_last(combat: dict) -> dict | None:
    """Vrátí poslední nezrušenou změnu zpět. None = není co vracet.

    Vrací všechno, co je v `before`: HP, furioka, DEF i statusy. Spotřebovanou
    manu a munici řeší cog přes `event["resources"]`.
    """
    for event in reversed(combat.get("log", [])):
        if event.get("undone") or not event.get("revert", True):
            continue
        stat = combat.get("stats", {}).get(event["target"])
        if stat is None:
            continue
        before = event.get("before", {})
        for key in SNAPSHOT_KEYS:
            if key in before:
                stat[key] = before[key]
        if "statuses" in before:
            stat["statuses"] = copy.deepcopy(before["statuses"])
        if 'energy' in before:
            stat['energy'] = copy.deepcopy(before['energy'])
        attacker = combat.get('stats', {}).get(event.get('actor'))
        original = event.get('resources', {}).get('energy_before')
        if attacker is not None and original is not None:
            attacker['energy'] = copy.deepcopy(original)
            attacker['fur'] = energy.pool(original, attacker.get('energy_perks', []))
        event["undone"] = True
        return event
    return None


def refund_resources(event: dict) -> str:
    """Vrátí manu, munici a použitý item z vrácené akce. Vrací poznámku do konzole."""
    res = event.get("resources") or {}
    uid = res.get("uid")
    if not uid:
        return ""
    notes = []
    try:
        profiles = _load_profiles()
        profile = profiles.get(res.get("profile_key") or _pk(profiles, int(uid)))
        if not profile:
            return ""
        _merge_energy(profile, res.get("energy_before"))
        if res.get("energy_before"):
            notes.append("🔥 Obnovena furioku hráče i duchů a přidělení do útoku.")
        mana = int(res.get("mana", 0) or 0)
        if mana:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            profile["mana_cur"] = min(profile.get("mana_max", cur + mana), cur + mana)
            notes.append(f"🔷 mana `{cur}` → `{profile['mana_cur']}`")
        ammo_id = res.get("ammo_id")
        ammo_qty = int(res.get("ammo_qty", 0) or 0)
        if ammo_id and ammo_qty:
            store = profile.setdefault("inventory", [])
            _add_to_inventory(store, str(ammo_id), ammo_qty)
            notes.append(f"🎯 +{ammo_qty} {ammo_id}")
        item_id = res.get("item_id")
        item_qty = int(res.get("item_qty", 0) or 0)
        if item_id and item_qty:
            _add_to_inventory(profile.setdefault("inventory", []), str(item_id), item_qty)
            notes.append(f"🧴 +{item_qty} {item_id}")
        if notes:
            _save_profiles(profiles)
    except Exception:
        logging.exception("[combat] vrácení many/munice selhalo")
        return ""
    return "  ·  ".join(notes)


def format_log_event(event: dict) -> str:
    icon = LOG_ICON.get(event.get("kind", ""), "•")
    who = f"{event['actor']} → " if event.get("actor") else ""
    hp_from = event["before"].get("hp", 0)
    hp_to = event["after"].get("hp", 0)
    if not event.get("revert", True):
        change = "minul"
    elif hp_from == hp_to:
        change = f"{hp_to} HP"        # změna mimo HP (status, DEF) — detail řekne co
    else:
        change = f"{hp_from} → {hp_to} HP"
    line = (f"`{event['id']:>2}` ⟳{event.get('round', 1)} {icon} {who}"
            f"**{event['target']}** {change}")
    if event.get("detail"):
        line += f" *({event['detail']})*"
    if event.get("undone"):
        line = f"~~{line}~~ ↩️"
    return line


# ── Shrnutí boje ─────────────────────────────────────────────────────────────

WIPEOUT_TITLE = {
    "npc": "🏆  Nepřátelé padli!",
    "players": "💀  Družina padla!",
}
MEDALS = ("🥇", "🥈", "🥉")


def actor_label(actor: str, guild=None) -> str:
    """Čitelné jméno aktéra pro autocomplete — u hráče postava a přezdívka místo <@id>."""
    uid = _actor_uid(actor)
    if uid is None:
        return actor
    try:
        char = _active_char_name(uid)
    except Exception:
        char = None
    member = guild.get_member(uid) if guild else None
    nick = member.display_name if member else None
    if char and nick and char != nick:
        return f"🧑 {char} (@{nick})"
    if char or nick:
        return f"🧑 {char or nick}"
    return actor


def is_player(actor: str) -> bool:
    return actor.startswith("<@")


def is_down(combat: dict, actor: str) -> bool:
    """Aktér na 0 HP — padl, takže nehraje a neútočí se na něj."""
    stat = combat.get("stats", {}).get(actor)
    return stat is not None and int(stat.get("hp", 0) or 0) <= 0


def advance_turn(combat: dict) -> tuple[str, int, list[str]]:
    """Posune pořadí na dalšího živého aktéra.

    Vrací `(další aktér, kolik kol přibylo, přeskočení padlí)`. Padlí se
    přeskakují, ať GM nemusí mrtvé NPC ručně odebírat; když padli všichni,
    zůstane na řadě ten, kdo byl (wipeout si vezme slovo hned potom).
    """
    order = combat["order"]
    rounds = 0
    skipped: list[str] = []
    for _ in range(len(order)):
        combat["current_index"] = (combat["current_index"] + 1) % len(order)
        if combat["current_index"] == 0:
            rounds += 1
        actor = order[combat["current_index"]]
        if not is_down(combat, actor):
            return actor, rounds, skipped
        skipped.append(actor)
    return order[combat["current_index"]], rounds, skipped


def damage_tally(combat: dict) -> list[tuple[str, dict]]:
    """Kdo kolik rozdal/schytal/vyléčil podle logu. Vrácené záznamy se nepočítají.

    Seřazeno podle uděleného damage sestupně.
    """
    tally: dict[str, dict] = {}

    def slot(actor: str) -> dict:
        return tally.setdefault(actor, {"dealt": 0, "taken": 0, "healed": 0})

    for event in combat.get("log", []):
        if event.get("undone") or not event.get("revert", True):
            continue
        delta = event["before"].get("hp", 0) - event["after"].get("hp", 0)
        target = slot(event["target"])
        if delta >= 0:
            target["taken"] += delta
        else:
            target["healed"] += -delta
        actor = event.get("actor")
        if actor and actor != event["target"] and delta > 0:
            slot(actor)["dealt"] += delta

    return sorted(tally.items(), key=lambda kv: (-kv[1]["dealt"], -kv[1]["taken"]))


def wipeout_side(combat: dict) -> str | None:
    """'npc' když padli všichni nepřátelé, 'players' když družina. None = boj běží."""
    sides: dict[str, list[dict]] = {"players": [], "npc": []}
    for actor, stat in combat.get("stats", {}).items():
        sides["players" if is_player(actor) else "npc"].append(stat)
    if not sides["players"] or not sides["npc"]:
        return None
    for side, stats in sides.items():
        if all(int(s.get("hp", 0) or 0) <= 0 for s in stats):
            return side
    return None


def build_summary_embed(combat: dict, title: str) -> discord.Embed:
    rows = damage_tally(combat)
    lines = []
    for i, (actor, nums) in enumerate(rows):
        medal = MEDALS[i] if i < len(MEDALS) and nums["dealt"] else "▫️"
        parts = [f"⚔️ `{nums['dealt']}`", f"🩸 `{nums['taken']}`"]
        if nums["healed"]:
            parts.append(f"💚 `{nums['healed']}`")
        lines.append(f"{medal} **{actor}** — " + "  ".join(parts))

    stats = combat.get("stats", {})
    fallen = [a for a, s in stats.items() if int(s.get("hp", 0) or 0) <= 0]
    embed = discord.Embed(
        title=title,
        description="\n".join(lines) if lines else "*Nikdo si ani neškrábl.*",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Kol", value=str(combat.get("round", 1)), inline=True)
    embed.add_field(
        name="Padlí",
        value=", ".join(fallen) if fallen else "—",
        inline=True,
    )
    afflicted = [
        f"{actor}: " + ", ".join(
            str(s.get("status")) for s in stat.get("statuses") or [])
        for actor, stat in stats.items() if stat.get("statuses")
    ]
    if afflicted:
        embed.add_field(name="Statusy", value="\n".join(afflicted), inline=False)
    embed.set_footer(text="⚔️ uděleno · 🩸 utrženo · 💚 vyléčeno")
    return embed


# ── Perkové buffy (efekt perku na následující útok / kolo) ───────────────────


def add_perk_buff(combat: dict, actor: str, perk_id: str, name: str,
                  dmg: str, scope: str = "attack") -> dict:
    """Zaregistruje efekt perku aktérovi. scope: 'attack' (nejbližší útok) / 'round'."""
    buff = {"perk_id": perk_id, "name": name, "dmg": dmg, "scope": scope}
    combat.setdefault("buffs", {}).setdefault(actor, []).append(buff)
    return buff


def take_attack_buffs(combat: dict, actor: str) -> list[dict]:
    """Buffy platné pro tenhle útok. Ty se scope 'attack' se spotřebují."""
    buffs = combat.get("buffs", {}).get(actor, [])
    if not buffs:
        return []
    combat["buffs"][actor] = [b for b in buffs if b.get("scope") != "attack"]
    return list(buffs)


def clear_buffs(combat: dict, actor: str) -> None:
    """Konec tahu — efekty perků aktéra vyprší."""
    combat.get("buffs", {}).pop(actor, None)


def _hp_color(hp: int, max_hp: int) -> int:
    if max_hp <= 0:
        return 0x95a5a6
    pct = hp / max_hp
    if pct <= 0.25:
        return 0xe74c3c   # červená
    if pct <= 0.60:
        return 0xe67e22   # oranžová
    return 0x2ecc71       # zelená


# ── Formát řádku v order listu ────────────────────────────────────────────────

def _format_actor_line(name: str, stats: dict, is_active: bool, idx_marker: bool,
                       status_str: str = "") -> str:
    """
    Vrátí jeden řádek pro order embed.
    - Hráči (mention) bez stats → jen mention
    - NPC / hráči se stats → HP bar + DEF + FUR (+ ikony statusů)
    """
    s = stats.get(name)

    if s:
        hp      = s["hp"]
        max_hp  = s["max_hp"]
        defense = s.get("def", 0)
        fury    = s.get("fur", 0)
        bar     = _make_bar(hp, max_hp, 8)

        hp_str  = f"❤️ `{hp:>3}/{max_hp}` {bar}"
        def_str = f"  🛡️`{defense}`" if defense > 0 else ""
        fur_str = f"  🔥`{fury}`"    if fury    > 0 else ""
        st_str  = f"  {status_str}" if status_str else ""
        stats_line = f"\n> *{hp_str}{def_str}{fur_str}{st_str}*"
    else:
        stats_line = ""

    if idx_marker:
        prefix = "▶️"
        name_fmt = f"**{name}**"
        suffix = "  *(na řadě)*"
    else:
        prefix = "◽"
        name_fmt = name
        suffix = ""

    return f"{prefix} {name_fmt}{suffix}{stats_line}"


# ── Boss bar embed ─────────────────────────────────────────────────────────────

def _boss_embed(name: str, s: dict, flashing: bool = False) -> discord.Embed:
    hp      = s["hp"]
    max_hp  = s["max_hp"]
    defense = s.get("def", 0)
    fury    = s.get("fur", 0)
    hp_pct  = round((hp / max_hp) * 100) if max_hp > 0 else 0
    rage    = 100 - hp_pct
    color   = _hp_color(hp, max_hp)

    if flashing:
        return discord.Embed(
            title=f"💥  {name}  💥",
            description="*— přijímá poškození —*",
            color=0xff0000,
        )

    hp_bar   = _make_bar(hp, max_hp)
    rage_bar = _make_bar(rage, 100)
    dead     = hp == 0

    desc = (
        f"```\n"
        f"╔══════════════════════╗\n"
        f"║  HP    {hp_bar}  {hp:>4}/{max_hp}\n"
        f"║  Rage  {rage_bar}  {rage:>3}%\n"
        f"╚══════════════════════╝\n"
        f"```"
    )
    if defense > 0:
        desc += f"\n🛡️ DEF: **{defense}**"
    if fury > 0:
        desc += f"  🔥 FUR: **{fury}**"
    if dead:
        desc += "\n\n💀 **Boss padl.**"

    return discord.Embed(
        title=f"{'💀' if dead else '☠️'}  {name}",
        description=desc,
        color=color,
    )


# ── Order embed builder ────────────────────────────────────────────────────────

def _build_order_embed(title: str, combat: dict, note: str = "") -> discord.Embed:
    """Sestaví embed s pořadím bojovníků, HP/DEF/FUR stats a aktuálním na řadě."""
    order   = combat["order"]
    idx     = combat["current_index"]
    stats   = combat["stats"]
    locked  = combat["locked"]

    lines = []
    bs  = _bs()
    reg = bs.load_statuses() if bs else {}
    init = combat.get("initiative", {})
    for i, name in enumerate(order):
        is_active = locked and (i == idx)
        s = stats.get(name)
        st_str = bs.status_icons(s, reg) if (bs and s) else ""
        line = _format_actor_line(name, stats, is_active=is_active,
                                  idx_marker=is_active, status_str=st_str)
        # před uzamčením ukaž hozenou iniciativu (nebo že ještě nehodil)
        if not locked:
            if name in init:
                line = f"🎲`{init[name]:>2}`  " + line
            else:
                line = "🎲` ?`  " + line
        lines.append(line)

    description = "\n".join(lines) if lines else "*Seznam je prázdný.*"
    if note:
        description = f"*{note}*\n\n" + description

    active = combat.get("active_player") or (order[idx] if locked and order else None)
    footer = f"Kolo {combat.get('round', 1)}"
    if active:
        footer += f"  ·  Na řadě: {active}"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold(),
    )
    if footer:
        embed.set_footer(text=footer)
    return embed


# ── EOT Button View ────────────────────────────────────────────────────────────

class EOTView(ui.View):
    """Tlačítko konce tahu. Bez `channel_id` slouží jako persistent view — kanál
    si vezme z interakce, takže tlačítko šlape i po restartu bota.
    """

    def __init__(self, cog: "CombatCog", channel_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id

    @ui.button(label="⏭️  End of Turn", style=discord.ButtonStyle.danger,
               custom_id="arion:combat:eot")
    async def eot_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.advance(interaction)

    async def advance(self, interaction, allow_pending=False):
        self.cog.reload_state()
        channel_id = self.channel_id if self.channel_id is not None else interaction.channel_id
        if channel_id not in self.cog.active_combats:
            return await interaction.response.send_message(
                "❌ *Combat byl ukončen.*", ephemeral=True
            )

        combat = self.cog.active_combats[channel_id]

        if not combat.get("locked"):
            return await interaction.response.send_message(
                "⚠️ *Combat ještě není uzavřen. Čekej na `/combat setorder`.*",
                ephemeral=True,
            )

        order = combat["order"]
        if not order:
            return await interaction.response.send_message(
                "⚠️ *Pořadí je prázdné.*", ephemeral=True
            )

        current_actor = order[combat["current_index"]]
        is_npc_turn   = not current_actor.startswith("<@")
        is_admin      = is_dm(interaction)
        is_current    = interaction.user.mention == current_actor

        if is_npc_turn and not is_admin:
            return await interaction.response.send_message(
                f"🎲 *Tah NPC **{current_actor}** může předat pouze GM (admin).*",
                ephemeral=True,
            )

        if not is_npc_turn and not is_current and not is_admin:
            return await interaction.response.send_message(
                f"⏳ *Nejsi na řadě! Nyní hraje: {current_actor}*",
                ephemeral=True,
            )

        if combat.get(PENDING_KEY) and not allow_pending:
            if not is_admin:
                return await interaction.response.send_message('Nejprve dořešte čekající útoky; předání tahu může povolit DM.', ephemeral=True)
            view = ui.View(timeout=180)
            button = ui.Button(label='Předat tah i s čekajícími útoky', style=discord.ButtonStyle.danger)
            async def confirm(i):
                if not is_dm(i):
                    return await i.response.send_message('Pouze DM.', ephemeral=True)
                await self.advance(i, allow_pending=True)
            button.callback = confirm
            view.add_item(button)
            return await interaction.response.send_message('Některé útoky nejsou dořešené.', view=view, ephemeral=True)

        # Advance — padlí aktéři se přeskakují
        reset_turn(combat, current_actor)
        clear_buffs(combat, current_actor)
        next_actor, rounds, skipped = advance_turn(combat)
        combat["active_player"] = next_actor
        # Začátek tahu maže i akce utracené mimo tah (NPC útok, reakce).
        reset_turn(combat, next_actor, reaction=True)

        new_round = rounds > 0
        if new_round:
            combat["round"] = int(combat.get("round", 1)) + rounds

        # Statusy tikají tomu, kdo přichází na tah — jed tak ubírá HP každý
        # jeho tah. Tik může aktéra srazit, pak se tah předá dál (a tikne zas).
        tick_lines: list[str] = []
        if combat.get("auto_tick", True):
            ticked: set[str] = set()
            while next_actor not in ticked:
                ticked.add(next_actor)
                if is_down(combat, next_actor):
                    break
                tick_lines += self.cog._tick_actor(combat, next_actor)
                if not is_down(combat, next_actor):
                    break
                skipped.append(next_actor)
                next_actor, extra_rounds, more = advance_turn(combat)
                skipped += more
                combat["active_player"] = next_actor
                reset_turn(combat, next_actor, reaction=True)
                if extra_rounds:
                    combat["round"] = int(combat.get("round", 1)) + extra_rounds
                    new_round = True
        self.cog._save_state()

        lines = turn_console(combat, next_actor, new_round=new_round)
        lines += [console(f"💀 *{who} je mimo boj — tah přeskočen.*") for who in skipped]
        lines += tick_lines
        view = EOTView(self.cog, channel_id)
        await interaction.response.send_message(content=lines[0], view=view)
        await self.cog._stream(interaction, lines)
        if tick_lines:
            if combat.get("boss"):
                asyncio.create_task(self.cog._update_boss_bar(combat))
            await self.cog.check_wipeout(interaction.channel, combat)


# ── CombatCog ─────────────────────────────────────────────────────────────────

class InitiativeView(ui.View):
    """Ephemeral tlačítko pro hod iniciativy. Zapíše číslo do combat['initiative']."""

    def __init__(self, cog, channel_id: int, actor: str):
        super().__init__(timeout=None)
        self.cog        = cog
        self.channel_id = channel_id
        self.actor      = actor

    @ui.button(label="Hodit iniciativu (1d20)", emoji="🎲", style=discord.ButtonStyle.primary)
    async def roll(self, interaction: discord.Interaction, button: ui.Button):
        self.cog.reload_state()
        combat = self.cog.active_combats.get(self.channel_id)
        if not combat:
            return await interaction.response.send_message("❌ *Combat už neběží.*", ephemeral=True)
        if combat.get("locked"):
            return await interaction.response.send_message(
                "🔒 *Pořadí je uzavřeno — iniciativa se už neháže.*", ephemeral=True)
        if self.actor in combat.get("initiative", {}):
            return await interaction.response.send_message(
                f"🎲 *Už jsi házel: **{combat['initiative'][self.actor]}**.*", ephemeral=True)

        roll = random.randint(1, 20)
        combat.setdefault("initiative", {})[self.actor] = roll
        self.cog._save_state()

        for item in self.children:
            item.disabled = True
        crit = "  ✨ **Nat 20!**" if roll == 20 else ("  💀 *Nat 1…*" if roll == 1 else "")
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🎲  Iniciativa hozena",
                description=f"# {roll}{crit}\n-# GM tě zařadí přes `/combat setorder`.",
                color=discord.Color.gold()),
            view=self,
        )
        # veřejné oznámení do kanálu, ať GM i ostatní vidí hod
        try:
            ch = interaction.channel
            await ch.send(f"🎲 {self.actor} hodil iniciativu: **{roll}**")
        except Exception:
            logging.exception("[combat] oznámení iniciativy selhalo")


# ── Zbraně hráče ──────────────────────────────────────────────────────────────

WEAPON_SLOTS = ("hand_l", "hand_r")


def _iter_entries(profile: dict):
    for entry in profile.get("inventory", []):
        yield entry
    for storage in (profile.get("storages") or {}).values():
        for entry in storage:
            yield entry


def _weapon_entry(profile: dict, item_id: str) -> dict | None:
    """Instance zbraně v inventáři — přednost má kus s runou."""
    fallback = None
    for entry in _iter_entries(profile):
        if entry.get("type") != "registered" or entry.get("id") != item_id:
            continue
        if entry.get("runes"):
            return entry
        fallback = fallback or entry
    return fallback


def _player_weapons(profile: dict) -> list[str]:
    """ID zbraní, které má hráč v rukou — jen s nimi jde útočit."""
    out: list[str] = []
    equipment = profile.get("equipment", {}) or {}
    for slot in WEAPON_SLOTS:
        item_id = equipment.get(slot)
        if item_id and item_id not in out:
            out.append(item_id)
    return out


def _rune_names(entry: dict, runes_reg: dict) -> str:
    names = []
    for rid in (entry.get("runes") or []):
        rune = runes_reg.get(rid, {})
        names.append(f"{rune.get('emoji', '🔹')} {rune.get('name', rid)}")
    return " · ".join(names)


def _is_ranged(db_item: dict) -> bool:
    return (db_item or {}).get("category") in RANGED_CATEGORIES


def _ammo_stores(profile: dict) -> list[list]:
    """Místa, kde hráč drží munici — Toulec (pokud ho má) a inventář."""
    stores = []
    toulec = (profile.get("storages", {}) or {}).get(TOULEC_ITEM_ID)
    if toulec is not None:
        stores.append(toulec)
    stores.append(profile.setdefault("inventory", []))
    return stores


def _ammo_count(profile: dict, item_id: str) -> int:
    return sum(e.get("qty", 1)
               for store in _ammo_stores(profile) for e in store
               if e.get("type") == "registered" and e.get("id") == item_id)


def _consume_ammo(profile: dict, item_id: str, qty: int = 1) -> bool:
    """Odečte munici z prvního místa, kde ji hráč má."""
    for store in _ammo_stores(profile):
        if any(e.get("type") == "registered" and e.get("id") == item_id
               and e.get("qty", 1) >= qty for e in store):
            return _remove_from_inventory(store, item_id, qty)
    return False


def _player_ammo(profile: dict, items_db: dict) -> list[tuple[str, int]]:
    """(id, počet) veškeré munice hráče — pro našeptávač i hlášku 'nemáš munici'."""
    counts: dict[str, int] = {}
    for store in _ammo_stores(profile):
        for entry in store:
            if entry.get("type") != "registered":
                continue
            iid = entry.get("id", "")
            if (items_db.get(iid) or {}).get("category") != AMMO_CATEGORY:
                continue
            counts[iid] = counts.get(iid, 0) + entry.get("qty", 1)
    return sorted(counts.items())


def mana_for_attack(db_item: dict, profile: dict) -> tuple[int, bool, str]:
    """Cena many za útok: platí každý item s `mana_cost` (runa i runou zdobená zbraň).

    Vrací (odečítaná mana, procne runa, poznámka do embedu).
    """
    cost = int(db_item.get("mana_cost", 0) or 0)
    if not cost:
        return 0, True, ""
    cur = profile.get("mana_cur", profile.get("mana_max", 20))
    if cur < cost:
        return 0, False, f"🔷 *Málo many ({cur}/{cost}) — runa neprocne.*"
    return cost, True, ""


# ── Attack: potvrzení zásahu ──────────────────────────────────────────────────

# Attack UI is shared by player and DM bots; state lives in the database.
from src.logic.attack_ui import AttackView, DamageModal, is_dm
from src.logic import attack_flow
PENDING_KEY = "pending_attacks"
PENDING_LIMIT = 25


_MISSING_STATE = object()


def _merge_state_changes(base, local, remote):
    """Three-way merge: an unrelated tracker write cannot resurrect a settled attack."""
    if local == base:
        return remote
    if remote == base or local == remote:
        return local
    if all(isinstance(value, dict) for value in (base, local, remote)):
        merged = {}
        for key in base.keys() | local.keys() | remote.keys():
            value = _merge_state_changes(base.get(key, _MISSING_STATE),
                local.get(key, _MISSING_STATE), remote.get(key, _MISSING_STATE))
            if value is not _MISSING_STATE:
                merged[key] = value
        return merged
    raise ValueError('Stav boje se mezitím změnil. Zopakuj poslední příkaz.')


class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_combats = self._load_state()

    async def cog_load(self):
        # Persistent views: tlačítka bez timeoutu fungují i po restartu bota.
        self.bot.add_view(EOTView(self))
        self.bot.add_view(AttackView(self))
        from src.logic.attack_ui import refresh_cards
        self._attack_refresh = asyncio.create_task(refresh_cards(self))

    async def cog_unload(self):
        task = getattr(self, '_attack_refresh', None)
        if task:
            task.cancel()

    # ── Persistence ───────────────────────────────────────────────────────────

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Před každým příkazem cogu načte stav boje z DB.

        Hráčskou a vypravěčskou konzoli obsluhují dva procesy (ArionDND a
        ArionDM), takže stav v paměti jednoho z nich může být zastaralý.
        """
        self.reload_state()
        return True

    def reload_state(self) -> None:
        """Přepíše stav boje tím z DB; slovníky bojů si drží identitu."""
        fresh = self._load_state()
        for channel_id, combat in fresh.items():
            current = self.active_combats.get(channel_id)
            if current is None:
                self.active_combats[channel_id] = combat
            else:
                current.clear()
                current.update(combat)
        for channel_id in [c for c in self.active_combats if c not in fresh]:
            del self.active_combats[channel_id]

    def save_state(self):
        """Uloží stav boje (volají i jiné cogy, např. perky)."""
        self._save_state()

    def mutate_combat(self, channel_id: int, change):
        """Atomicky změní jeden boj: čerstvý stav z DB → `change(combat)` → uložit.

        Hráčská (ArionDND) i vypravěčská (ArionDM) konzole píšou do stejného
        dokumentu, takže read-modify-write musí proběhnout v jedné transakci —
        jinak by zápis jednoho procesu přepsal změnu druhého. Vrací návratovou
        hodnotu `change`, nebo None když v kanále žádný boj není. Když zápis
        selže, vrací taky None — volající pak zásah nesmí hlásit jako platný.
        """
        box: dict = {"result": None}

        def mutate(raw: dict):
            key = str(channel_id)
            stored = raw.get(key)
            if stored is None:
                self.active_combats.pop(channel_id, None)
                return raw
            combat = self.active_combats.get(channel_id)
            if combat is None:
                combat = stored
                self.active_combats[channel_id] = combat
            else:
                combat.clear()
                combat.update(stored)
            _refresh_energy(combat)
            box["result"] = change(combat)
            raw[key] = combat
            return raw

        try:
            update_json(COMBAT_STATE, mutate)
        except Exception:
            logging.exception("[combat] atomický zápis stavu selhal")
            return None
        return box["result"]

    async def _store_pending(self, interaction: discord.Interaction,
                             view: "AttackView") -> None:
        message = await interaction.original_response()
        view.message_id = str(message.id)
        attack_flow.attach_message(interaction.channel_id, view.aid, message.id,
                                   interaction.client.user.id)
        self.reload_state()

    async def _send_attack(self, interaction, data):
        from src.logic.attack_ui import attack_embed
        view = AttackView(self, interaction.channel_id, data=data)
        try:
            await interaction.response.send_message(embed=attack_embed(data), view=view,
                allowed_mentions=discord.AllowedMentions.none())
            await self._store_pending(interaction, view)
        except Exception:
            # A failed Discord send must not leave ammo/actions stranded.
            attack_flow.resolve(interaction.channel_id, data['id'], True, 'cancel')
            self.reload_state()
            raise

    # ── Konzole ───────────────────────────────────────────────────────────────

    async def send_console(self, channel, lines: list[str],
                           header: str = "") -> None:
        """Deliver all console lines before the caller removes a working card."""
        if not lines:
            return True
        chunks, chunk = [], header
        for line in lines:
            for part in [line[n:n+1900] for n in range(0, len(line), 1900)]:
                if len(chunk) + len(part) + 1 > 1950:
                    chunks.append(chunk)
                    chunk = ''
                chunk += ('\n' if chunk else '') + part
        if chunk:
            chunks.append(chunk)
        try:
            for content in chunks:
                rows = content.splitlines()
                message = await channel.send(rows[0], allowed_mentions=discord.AllowedMentions.none())
                shown = rows[0]
                for row in rows[1:]:
                    await asyncio.sleep(CONSOLE_DELAY)
                    shown += '\n' + row
                    await message.edit(content=shown, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            logging.exception('[combat] konzoli se nepodařilo odeslat')
            return False
        return True

    async def _stream(self, interaction: discord.Interaction,
                      lines: list[str], header: str = "") -> None:
        """Dopíše zbytek konzolového výpisu do odpovědi interakce."""
        if len(lines) < 2:
            return
        try:
            message = await interaction.original_response()
        except Exception:
            logging.exception("[combat] zprávu konzole se nepodařilo načíst")
            return
        await stream_console(message, lines, header)

    # ── Shrnutí ───────────────────────────────────────────────────────────────

    async def send_summary(self, channel, combat: dict, title: str) -> None:
        try:
            await channel.send(embed=build_summary_embed(combat, title))
        except Exception:
            logging.exception("[combat] shrnutí boje se nepodařilo odeslat")

    async def check_wipeout(self, channel, combat: dict) -> None:
        """Padla-li celá jedna strana, pošle shrnutí (jednou za boj)."""
        side = wipeout_side(combat)
        if not side or combat.get("summary_sent"):
            return
        combat["summary_sent"] = True
        self._save_state()
        await self.send_summary(channel, combat, WIPEOUT_TITLE[side])

    def _save_state(self):
        local = {str(k): v for k, v in self.active_combats.items()}
        baseline = getattr(self, '_state_baseline', {})
        def merge(remote):
            for combat in remote.values():
                combat.setdefault('initiative', {})
                combat.setdefault('round', 1)
                combat.setdefault('log', [])
                _refresh_energy(combat)
            return _merge_state_changes(baseline, local, remote)
        try:
            saved = update_json(COMBAT_STATE, merge)
        except Exception:
            self.reload_state()
            raise
        self._state_baseline = copy.deepcopy(saved)
        for key, state in copy.deepcopy(saved).items():
            current = self.active_combats.setdefault(int(key), {})
            current.clear()
            current.update(copy.deepcopy(state))
        for key in set(self.active_combats) - {int(k) for k in saved}:
            del self.active_combats[key]

    def _load_state(self) -> dict:
        try:
            raw = load_json(COMBAT_STATE, default={})
            state = {int(k): v for k, v in raw.items()}
            # migrace: staré combaty uložené před iniciativou nemají klíč
            for combat in state.values():
                combat.setdefault("initiative", {})
                combat.setdefault("round", 1)
                combat.setdefault("log", [])
                _refresh_energy(combat)
            self._state_baseline = copy.deepcopy({str(k): v for k, v in state.items()})
            return state
        except Exception:
            logging.exception("[combat] Nelze načíst stav")
            return {}

    # ── Boss bar ──────────────────────────────────────────────────────────────

    async def _update_boss_bar(self, combat: dict, flashing: bool = False):
        boss = combat.get("boss")
        if not boss:
            return
        try:
            channel = self.bot.get_channel(boss["channel_id"])
            if not channel:
                return
            msg = await channel.fetch_message(boss["message_id"])
            s = combat["stats"].get(boss["name"])
            if not s:
                return
            if flashing:
                await msg.edit(embed=_boss_embed(boss["name"], s, flashing=True))
                await asyncio.sleep(0.7)
            await msg.edit(embed=_boss_embed(boss["name"], s))
        except Exception:
            logging.exception("[combat] Nelze aktualizovat boss bar")

    # ── Helpers pro odpovědi ──────────────────────────────────────────────────

    async def _send_order(self, interaction: discord.Interaction, title: str, note: str = ""):
        """Odešle order embed bez EOT tlačítka (použij před setorder)."""
        combat = self.active_combats[interaction.channel_id]
        embed  = _build_order_embed(title, combat, note)
        await interaction.response.send_message(embed=embed)

    async def _send_order_with_eot(self, interaction: discord.Interaction, title: str, note: str = ""):
        """Odešle order embed s EOT tlačítkem (po setorder)."""
        combat = self.active_combats[interaction.channel_id]
        embed  = _build_order_embed(title, combat, note)
        view   = EOTView(self, interaction.channel_id)
        # Pokud interaction už byl deferred, použij followup
        try:
            await interaction.followup.send(embed=embed, view=view)
        except Exception:
            await interaction.response.send_message(embed=embed, view=view)

    # ── Statusy: tick + ovládání ───────────────────────────────────────────────

    def _tick_actor(self, combat: dict, actor: str) -> list[str]:
        """Začátek tahu: statusy aktéra udělí dmg a uberou kolo trvání.

        Hráči zapíše hp + statusy zpět do profilu.
        Vrací řádky konzole (prázdný seznam, když se nic nestalo).
        """
        bs = _bs()
        stat = (combat.get("stats") or {}).get(actor)
        if not bs or not stat:
            return []
        uid = _actor_uid(actor)
        if not stat.get("statuses"):
            return []
        reg = bs.load_statuses()
        before = stat_snapshot(stat)
        dmg, log = bs.tick_statuses(stat, reg)
        absorbed = 0
        if dmg:
            absorbed = apply_status_dmg(stat, dmg)
            log_event(combat, "status", actor, before, stat_snapshot(stat),
                      detail=f"statusy −{dmg}")
        if uid is not None:
            _writeback_player_state(uid, stat, bs)
        if not log:
            return []
        lines = [console(f"🩸 Status: **{actor}** — " + " · ".join(log))]
        if dmg:
            hp, max_hp = stat.get("hp", 0), stat.get("max_hp", 0)
            bar = _make_bar(hp, max_hp, 8)
            dead = "  💀" if hp == 0 else ""
            fur_note = (f"  ·  🔥 furioka `{before.get('fur', 0)}` → `{stat.get('fur', 0)}`"
                        if absorbed else "")
            lines.append(console(
                f"❤️ `{before.get('hp', hp)}` → `{hp}/{max_hp}` {bar}{dead}{fur_note}"))
        if dmg and stat.get("_energy_note"):
            lines.append(console(stat["_energy_note"]))
        return lines

    combat_group = app_commands.Group(
        name="combat", description="Bojový systém — start, join, správa aktérů a efektů (DM)")

    combat_effect = app_commands.Group(
        name="effect", description="Statusy v boji — jed/krvácení atd. (DM).", parent=combat_group)

    async def _ac_actor(self, interaction: discord.Interaction, current: str):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return []
        cur = current.lower()
        out = []
        for actor in combat["order"]:
            label = actor_label(actor, interaction.guild)
            if cur in actor.lower() or cur in label.lower():
                out.append(app_commands.Choice(name=label[:100], value=actor))
        return out[:25]

    async def _ac_status_id(self, interaction: discord.Interaction, current: str):
        bs = _bs()
        if not bs:
            return []
        reg = bs.load_statuses(); cur = current.lower()
        return [app_commands.Choice(name=f"{s.get('emoji','•')} {s['name']} ({sid})"[:100], value=sid)
                for sid, s in reg.items() if cur in sid.lower() or cur in s.get("name","").lower()][:25]

    @combat_effect.command(name="add", description="[DM] Přidej status aktérovi.")
    @mark_admin
    @app_commands.describe(target="Aktér (hráč/NPC).", status="Status.", source="Odkud efekt je.")
    @app_commands.choices(source=[
        app_commands.Choice(name="zbraň",     value="zbran"),
        app_commands.Choice(name="runa",      value="runa"),
        app_commands.Choice(name="prostředí", value="prostredi"),
        app_commands.Choice(name="schopnost", value="schopnost"),
    ])
    @app_commands.autocomplete(target=_ac_actor, status=_ac_status_id)
    async def combat_status_add(self, interaction: discord.Interaction,
                                target: str, status: str, source: str = "prostredi"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Jen GM (admin).", ephemeral=True)
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or target not in combat["stats"]:
            return await interaction.response.send_message("❌ Aktér není v boji.", ephemeral=True)
        bs = _bs()
        if not bs:
            return await interaction.response.send_message("❌ Status engine nedostupný.", ephemeral=True)
        reg  = bs.load_statuses()
        before = stat_snapshot(combat["stats"][target])
        inst = bs.apply_status(combat["stats"][target], status, source, reg)
        if not inst:
            return await interaction.response.send_message(f"❌ Status `{status}` neexistuje.", ephemeral=True)
        log_event(combat, "effect", target, before,
                  stat_snapshot(combat["stats"][target]),
                  detail=f"+{reg.get(status, {}).get('name', status)} "
                         f"({SOURCE_LABEL.get(source, source)})",
                  actor=interaction.user.mention)
        uid = _actor_uid(target)
        if uid is not None:
            _writeback_player_state(uid, combat["stats"][target], bs)
        self._save_state()
        sdef = reg.get(status, {})
        await interaction.response.send_message(
            f"{sdef.get('emoji','•')} **{sdef.get('name', status)}** přidán na **{target}** "
            f"(zdroj: {SOURCE_LABEL.get(source, source)}).")

    @combat_effect.command(name="clear", description="[DM] Vyléč statusy aktéra (dle typu).")
    @mark_admin
    @app_commands.describe(target="Aktér.", cure="Typ léčení.")
    @app_commands.choices(cure=[
        app_commands.Choice(name="fyzické", value="fyzické"),
        app_commands.Choice(name="magické", value="magické"),
        app_commands.Choice(name="vše",     value="vse"),
    ])
    @app_commands.autocomplete(target=_ac_actor)
    async def combat_status_clear(self, interaction: discord.Interaction,
                                  target: str, cure: str = "vse"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Jen GM (admin).", ephemeral=True)
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or target not in combat["stats"]:
            return await interaction.response.send_message("❌ Aktér není v boji.", ephemeral=True)
        bs = _bs()
        if not bs:
            return await interaction.response.send_message("❌ Status engine nedostupný.", ephemeral=True)
        carrier = combat["stats"][target]
        before = stat_snapshot(carrier)
        if cure == "vse":
            removed = [s.get("status") for s in carrier.get("statuses", [])]
            carrier["statuses"] = []
        else:
            removed = bs.cure_statuses(carrier, cure)
        log_event(combat, "cure", target, before, stat_snapshot(carrier),
                  detail=f"sundáno: {', '.join(removed) if removed else 'nic'}",
                  actor=interaction.user.mention)
        uid = _actor_uid(target)
        if uid is not None:
            _writeback_player_state(uid, carrier, bs)
        self._save_state()
        await interaction.response.send_message(
            f"🩹 **{target}** — sundáno: {', '.join(removed) if removed else 'nic'}.")

    @combat_effect.command(name="list", description="Zobraz statusy aktéra.")
    @app_commands.autocomplete(target=_ac_actor)
    async def combat_status_list(self, interaction: discord.Interaction, target: str):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or target not in combat["stats"]:
            return await interaction.response.send_message("❌ Aktér není v boji.", ephemeral=True)
        bs = _bs()
        desc = bs.describe_statuses(combat["stats"][target]) if bs else ""
        await interaction.response.send_message(
            f"**{target}** statusy:\n{desc or '*žádné*'}", ephemeral=True)

    @combat_effect.command(name="autotick", description="[DM] Zapni/vypni auto-odečet dmg ze statusů.")
    @mark_admin
    async def combat_status_autotick(self, interaction: discord.Interaction, zapnuto: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Jen GM (admin).", ephemeral=True)
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message("❌ V téhle místnosti není boj.", ephemeral=True)
        combat["auto_tick"] = zapnuto
        self._save_state()
        await interaction.response.send_message(
            f"⚙️ Auto-tick statusů: **{'zapnut' if zapnuto else 'vypnut'}**.")

    # ── /combat start ─────────────────────────────────────────────────────────

    @combat_group.command(name="start", description="Zahájí boj v této místnosti")
    async def combat_start(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        self.active_combats[channel_id] = {
            "order":         [],
            "current_index": 0,
            "locked":        False,
            "stats":         {},
            "first":         None,
            "active_player": None,
            "initiative":    {},   # {jméno: hozené číslo} — setorder podle něj seřadí
            "round":         1,
            "log":           [],
        }
        self._save_state()
        embed = discord.Embed(
            title="⚔️  Boj začíná!",
            description=(
                "*Combat byl zahájen v tomto kanálu.*\n\n"
                "Hráči: `/combat join` → hoď si iniciativu\n"
                "GM přidá NPC: `/combat add_npc`\n"
                "GM uzavře pořadí: `/combat setorder` *(seřadí dle iniciativy)*"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat join ──────────────────────────────────────────────────────────

    @combat_group.command(name="join", description="Hráč se zapojí do boje")
    async def combat_join(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        user   = interaction.user.mention

        if combat["locked"]:
            return await interaction.response.send_message(
                "🔒 *Pořadí je uzavřeno. Počkej na svůj tah.*", ephemeral=True
            )

        just_joined = user not in combat["order"]
        if just_joined:
            combat["order"].append(user)
            if combat["first"] is None:
                combat["first"] = user

        # ── Synchronizace stats z profilu ────────────────────────────────────
        synced = _sync_player_from_profile(user, interaction.user.id)
        if synced:
            statuses = (combat["stats"].get(user) or {}).get("statuses") or []
            combat["stats"][user] = {
                "hp":     synced["hp"],
                "max_hp": synced["max_hp"],
                "def":    synced["def"],
                "fur":    synced["fur"],
                "statuses": statuses,
            }

        _refresh_energy(combat)
        if combat.get("active_player") is None:
            combat["active_player"] = user
        self._save_state()

        already_rolled = user in combat.get("initiative", {})
        stats_info = (
            f"\n❤️ `{synced['hp']}/{synced['max_hp']}`  🛡️ `{synced['def']}`  🔥 `{synced['fur']}`"
            if synced else ""
        )
        if already_rolled:
            init_val = combat["initiative"][user]
            await interaction.response.send_message(
                f"✅ *Jsi v boji.*{stats_info}\n🎲 Iniciativa: **{init_val}**",
                ephemeral=True,
            )
            return

        # Hidden embed s tlačítkem na hod iniciativy
        embed = discord.Embed(
            title="🎲  Hoď si iniciativu",
            description=("Klikni a hoď si číslo — podle něj tě GM zařadí do pořadí "
                         "(nejvyšší jde první)." + stats_info),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed, view=InitiativeView(self, channel_id, user), ephemeral=True)

    # ── /combat add_npc ───────────────────────────────────────────────────────

    @combat_group.command(name="add_npc", description="GM přidá NPC/potvoru s HP, DEF a FUR")
    @admin_only()
    @app_commands.describe(
        name="Jméno NPC",
        hp="Maximum životů (výchozí: 100)",
        current_hp="Aktuální HP při vstupu — pokud nenastaveno, použije se max HP",
        defense="Obrana / DEF (výchozí: 0)",
        fury="Zuřivost / FUR (výchozí: 0)",
        dmg="Damage hlavní zbraně (`1d8`, `2d6+2`, holé číslo = kostka).",
        zbran="Název hlavní zbraně (jen do výpisu).",
        dmg_bonus="Damage bonusové zbraně (druhý útok).",
        zbran_bonus="Název bonusové zbraně.",
    )
    async def combat_add_npc(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 100,
        current_hp: int = -1,
        defense: int = 0,
        fury: int = 0,
        dmg: Optional[str] = None,
        zbran: Optional[str] = None,
        dmg_bonus: Optional[str] = None,
        zbran_bonus: Optional[str] = None,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        name = name.strip()
        if not name:
            return await interaction.response.send_message(
                "⚠️ *Jméno NPC nesmí být prázdné.*", ephemeral=True
            )

        actual_current = hp if current_hp == -1 else max(0, min(current_hp, hp))
        combat = self.active_combats[channel_id]

        final_name = name
        counter = 2
        while final_name in combat["stats"] or final_name in combat["order"]:
            final_name = f"{name} {counter}"
            counter += 1

        stat = {
            "hp":     actual_current,
            "max_hp": hp,
            "def":    defense,
            "fur":    fury,
        }
        try:
            if dmg:
                set_npc_weapon(stat, "main", dmg, zbran or "")
            if dmg_bonus:
                set_npc_weapon(stat, "bonus", dmg_bonus, zbran_bonus or "")
        except DiceError:
            return await interaction.response.send_message(
                "❌ *Damage nejde hodit — použij zápis jako `1d8`, `2d6+2` nebo `16`.*",
                ephemeral=True,
            )

        combat["order"].append(final_name)
        combat["stats"][final_name] = stat
        # NPC si hodí iniciativu automaticky (GM může přepsat /combat setinit)
        npc_init = random.randint(1, 20)
        combat.setdefault("initiative", {})[final_name] = npc_init
        self._save_state()

        weapons = npc_weapons_line(stat)
        await self._send_order(
            interaction,
            f"💀  {final_name} vstupuje do boje!",
            note=(f"NPC přidáno — HP {actual_current}/{hp}  DEF {defense}  FUR {fury}  "
                  f"🎲 init {npc_init}" + (f"\n{weapons}" if weapons else "")),
        )

    # ── /combat add_player_stats ──────────────────────────────────────────────

    @combat_group.command(
        name="add_player_stats",
        description="GM přidá HP/DEF/FUR hráči (např. pro tracking zranění)"
    )
    @admin_only()
    @app_commands.describe(
        mention="Hráč (mention)",
        hp="Maximum životů",
        current_hp="Aktuální HP (výchozí = max HP)",
        defense="DEF (výchozí: 0)",
        fury="FUR / Zuřivost (výchozí: 0)",
    )
    async def combat_add_player_stats(
        self,
        interaction: discord.Interaction,
        mention: discord.Member,
        hp: int = 100,
        current_hp: int = -1,
        defense: int = 0,
        fury: int = 0,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat      = self.active_combats[channel_id]
        player_key  = mention.mention
        actual_hp   = hp if current_hp == -1 else max(0, min(current_hp, hp))

        combat["stats"][player_key] = {
            "hp":     actual_hp,
            "max_hp": hp,
            "def":    defense,
            "fur":    fury,
        }
        self._save_state()

        await interaction.response.send_message(
            f"✅ *Stats přidány pro {player_key}* — ❤️ `{actual_hp}/{hp}`  🛡️ `{defense}`  🔥 `{fury}`",
            ephemeral=True,
        )

    # ── /combat add_boss ──────────────────────────────────────────────────────

    @combat_group.command(name="add_boss", description="GM přidá bosse s odděleným boss barem")
    @admin_only()
    @app_commands.describe(
        name="Jméno bosse",
        hp="Maximum životů (výchozí: 200)",
        defense="DEF (výchozí: 0)",
        fury="FUR (výchozí: 0)",
        dmg="Damage hlavní zbraně (`1d8`, `2d6+2`, holé číslo = kostka).",
        zbran="Název hlavní zbraně (jen do výpisu).",
        dmg_bonus="Damage bonusové zbraně (druhý útok).",
        zbran_bonus="Název bonusové zbraně.",
    )
    async def combat_add_boss(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 200,
        defense: int = 0,
        fury: int = 0,
        dmg: Optional[str] = None,
        zbran: Optional[str] = None,
        dmg_bonus: Optional[str] = None,
        zbran_bonus: Optional[str] = None,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        if combat.get("boss"):
            return await interaction.response.send_message(
                "⚠️ *V tomto combatu už boss je. Nejdřív ho odeber přes `/combat remove`.*",
                ephemeral=True,
            )

        name = name.strip()
        if not name:
            return await interaction.response.send_message(
                "⚠️ *Jméno bosse nesmí být prázdné.*", ephemeral=True
            )

        if name in combat["stats"]:
            return await interaction.response.send_message(
                f"⚠️ *V boji už je aktér **{name}** — zvol jiné jméno.*", ephemeral=True
            )

        stat = {"hp": hp, "max_hp": hp, "def": defense, "fur": fury}
        try:
            if dmg:
                set_npc_weapon(stat, "main", dmg, zbran or "")
            if dmg_bonus:
                set_npc_weapon(stat, "bonus", dmg_bonus, zbran_bonus or "")
        except DiceError:
            return await interaction.response.send_message(
                "❌ *Damage nejde hodit — použij zápis jako `1d8`, `2d6+2` nebo `16`.*",
                ephemeral=True,
            )

        combat["order"].append(name)
        combat["stats"][name] = stat
        combat.setdefault("initiative", {})[name] = random.randint(1, 20)

        await interaction.response.defer()

        boss_msg = await interaction.channel.send(embed=_boss_embed(name, combat["stats"][name]))

        combat["boss"] = {
            "name":       name,
            "message_id": boss_msg.id,
            "channel_id": channel_id,
        }
        self._save_state()

        weapons = npc_weapons_line(stat)
        await interaction.followup.send(
            f"☠️ *Boss **{name}** vstoupil do boje!*  ❤️ `{hp}` HP  🛡️ `{defense}` DEF  "
            f"🔥 `{fury}` FUR  🎲 init {combat['initiative'][name]}"
            + (f"\n{weapons}" if weapons else "")
        )

    # ── /combat sethp ─────────────────────────────────────────────────────────

    @combat_group.command(name="sethp", description="Admin: nastaví HP NPC/hráči během combatu")
    @admin_only()
    @app_commands.describe(
        name="Jméno NPC nebo mention hráče (@mention nebo přesné jméno)",
        hp="Nové HP (záporná hodnota = poškození, kladná = absolutní nastavení)",
        utocnik="Kdo zásah způsobil (jen do hlášky).",
    )
    @app_commands.autocomplete(name=_ac_actor, utocnik=_ac_actor)
    async def combat_sethp(self, interaction: discord.Interaction, name: str, hp: int,
                           utocnik: Optional[str] = None):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        stats  = combat["stats"]

        if name not in stats:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané HP.*\n"
                "NPC: `/combat add_npc`  |  Hráč: `/combat add_player_stats` nebo `/combat join`",
                ephemeral=True,
            )

        old_hp = stats[name]["hp"]
        max_hp = stats[name]["max_hp"]
        before = stat_snapshot(stats[name])

        if hp < 0:
            result     = apply_hit(stats[name], -hp)
            new_hp     = result["new_hp"]
            change_str = result["change_str"]
        else:
            new_hp     = min(hp, max_hp)
            change_str = f"nastaveno na {new_hp}"
            stats[name]["hp"] = new_hp

        log_event(combat, "sethp", name, before, stat_snapshot(stats[name]),
                  detail=change_str, actor=utocnik)
        self._save_state()

        # ── Zpětný zápis do profilu pokud jde o hráče (mention) ──────────────
        is_player = name.startswith("<@")
        if is_player:
            # Parsujeme user ID z mentiony: <@123456> nebo <@!123456>
            try:
                uid = int(name.strip("<@!>"))
                _writeback_player_state(uid, stats[name])
            except ValueError:
                pass

        # Krátká hláška (default) — plný přehled je na /combat status.
        if not combat.get("verbose"):
            lines = hp_console(name, old_hp, new_hp, max_hp, change_str,
                               attacker=utocnik)
            await interaction.response.send_message(lines[0])
            asyncio.create_task(self._stream(interaction, lines))
            if combat.get("boss", {}).get("name") == name:
                asyncio.create_task(self._update_boss_bar(combat, flashing=(hp < 0)))
            asyncio.create_task(self.check_wipeout(interaction.channel, combat))
            return

        bar   = _make_bar(new_hp, max_hp)
        color = _hp_color(new_hp, max_hp)
        dead  = new_hp == 0

        embed = discord.Embed(
            title=f"❤️  HP upraveno — {name}",
            description=(
                f"`{bar}` **{new_hp}/{max_hp}**\n"
                f"*{old_hp} → {new_hp}  ({change_str})*\n"
                f"🛡️ DEF: `{stats[name]['def']}`  🔥 FUR: `{stats[name].get('fur', 0)}`"
                + ("\n*↩️ Zapsáno do profilu hráče.*" if is_player else "")
                + ("\n\n💀 *HP dosáhlo nuly! Zvaž `/combat remove`.*" if dead else "")
            ),
            color=discord.Color.red() if dead else color,
        )
        await interaction.response.send_message(embed=embed)

        is_boss = combat.get("boss", {}).get("name") == name
        if is_boss:
            asyncio.create_task(self._update_boss_bar(combat, flashing=(hp < 0)))
        asyncio.create_task(self.check_wipeout(interaction.channel, combat))

    # ── /combat setdef ────────────────────────────────────────────────────────

    @combat_group.command(name="setdef", description="Admin: nastaví DEF NPC/hráči")
    @admin_only()
    @app_commands.describe(name="Jméno NPC nebo mention hráče", defense="Nová hodnota obrany")
    async def combat_setdef(self, interaction: discord.Interaction, name: str, defense: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        stats = self.active_combats[channel_id]["stats"]
        if name not in stats:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané stats.*", ephemeral=True
            )

        old_def        = stats[name]["def"]
        before = stat_snapshot(stats[name])
        stats[name]["def"] = max(0, defense)
        log_event(self.active_combats[channel_id], "stat", name, before,
                  stat_snapshot(stats[name]),
                  detail=f"DEF {old_def} → {stats[name]['def']}",
                  actor=interaction.user.mention)
        self._save_state()

        embed = discord.Embed(
            title=f"🛡️  DEF upraveno — {name}",
            description=f"*{old_def} → **{stats[name]['def']}***",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat setfur ────────────────────────────────────────────────────────

    @combat_group.command(name="setfur", description="Admin: nastaví FUR (zuřivost) NPC/hráči")
    @admin_only()
    @app_commands.describe(name="Jméno NPC nebo mention hráče", fury="Nová hodnota zuřivosti")
    async def combat_setfur(self, interaction: discord.Interaction, name: str, fury: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        stats = self.active_combats[channel_id]["stats"]
        if name not in stats:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané stats.*", ephemeral=True
            )

        old_fur        = stats[name].get("fur", 0)
        before = stat_snapshot(stats[name])
        stats[name]["fur"] = max(0, fury)
        if 'energy' in stats[name]:
            state = stats[name]['energy']
            state['fury_cur'] = min(state.get('fury_max', 0), max(0, fury))
            stats[name]['fur'] = energy.pool(state, stats[name].get('energy_perks', []))
            _writeback_player_state(_actor_uid(name), stats[name])
        log_event(self.active_combats[channel_id], "stat", name, before,
                  stat_snapshot(stats[name]),
                  detail=f"FUR {old_fur} → {stats[name]['fur']}",
                  actor=interaction.user.mention)
        self._save_state()

        embed = discord.Embed(
            title=f"🔥  FUR upraveno — {name}",
            description=f"*{old_fur} → **{stats[name]['fur']}***",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat setinit ───────────────────────────────────────────────────────

    @combat_group.command(name="setinit", description="Admin: nastaví iniciativu aktérovi")
    @admin_only()
    @app_commands.describe(name="Jméno NPC nebo mention hráče", value="Nová iniciativa")
    async def combat_setinit(self, interaction: discord.Interaction, name: str, value: int):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message("❌ *Zde neběží combat.*", ephemeral=True)
        combat = self.active_combats[channel_id]
        if name not in combat["order"]:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` není v boji.*", ephemeral=True)
        old = combat.get("initiative", {}).get(name)
        combat.setdefault("initiative", {})[name] = value
        # když už je pořadí uzamčené, přeřaď za běhu
        if combat.get("locked"):
            init = combat["initiative"]
            active = combat["order"][combat["current_index"]] if combat["order"] else None
            combat["order"].sort(key=lambda nm: init.get(nm, -1), reverse=True)
            if active in combat["order"]:
                combat["current_index"] = combat["order"].index(active)
        self._save_state()
        await interaction.response.send_message(
            f"🎲 *Iniciativa {name}: {old if old is not None else '—'} → **{value}***")

    # ── /combat setdmg ────────────────────────────────────────────────────────

    @combat_group.command(name="setdmg", description="Admin: nastaví damage zbraně NPC/bosse")
    @admin_only()
    @app_commands.describe(
        name="NPC nebo boss v boji",
        zbran="Který slot upravuješ",
        dmg="Damage (`1d8`, `2d6+2`, holé číslo = kostka). `-` = zbraň smazat.",
        nazev="Název zbraně (jen do výpisu).",
        status="Status, který zbraň doručí při zásahu (jed, krácení…).",
    )
    @app_commands.choices(zbran=[
        app_commands.Choice(name="hlavní zbraň",   value="main"),
        app_commands.Choice(name="bonusová zbraň", value="bonus"),
    ])
    @app_commands.autocomplete(name=_ac_actor, status=_ac_status_id)
    async def combat_setdmg(self, interaction: discord.Interaction, name: str,
                            zbran: app_commands.Choice[str],
                            dmg: Optional[str] = None,
                            nazev: Optional[str] = None,
                            status: Optional[str] = None):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat or name not in combat["stats"]:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nemá zaznamenané stats.*", ephemeral=True)

        bs = _bs()
        reg = bs.load_statuses() if bs else {}
        if status and status not in reg:
            return await interaction.response.send_message(
                f"❌ *Status `{status}` neexistuje.*", ephemeral=True)

        stat = combat["stats"][name]
        try:
            weapon = set_npc_weapon(stat, zbran.value, dmg, nazev, status)
        except DiceError:
            if not npc_weapon(stat, zbran.value):
                return await interaction.response.send_message(
                    f"❌ *{name} zatím {NPC_SLOTS[zbran.value]} nemá — zadej i `dmg`.*",
                    ephemeral=True)
            return await interaction.response.send_message(
                "❌ *Damage nejde hodit — použij zápis jako `1d8`, `2d6+2` nebo `16`.*",
                ephemeral=True)
        self._save_state()

        if not weapon:
            return await interaction.response.send_message(
                f"🗑️ *{name} už {NPC_SLOTS[zbran.value]} nemá.*")
        venom = ""
        if weapon.get("status"):
            sdef = reg.get(weapon["status"], {})
            venom = (f"  {sdef.get('emoji', '🩸')} doručuje "
                     f"**{sdef.get('name', weapon['status'])}**")
        await interaction.response.send_message(
            f"⚔️ *{name} — {NPC_SLOTS[zbran.value]}: "
            f"**{npc_weapon_label(weapon, zbran.value)}** `{weapon['dmg']}`*{venom}")

    # ── /combat remove ────────────────────────────────────────────────────────

    @combat_group.command(name="remove", description="Odebere někoho z pořadí")
    @admin_only()
    async def combat_remove(self, interaction: discord.Interaction, name: str):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        order  = combat["order"]

        to_remove = name if name in order else next(
            (item for item in order if name in item), None)
        if not to_remove:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nebyl v pořadí nalezen.*", ephemeral=True
            )

        if any(to_remove in (a.get('attacker'), a.get('target')) or to_remove in a.get('actors', {})
               for a in combat.get(PENDING_KEY, {}).values()):
            return await interaction.response.send_message('Nejprve vyhodnoť nebo zruš čekající útoky tohoto účastníka.', ephemeral=True)
        removed_idx = order.index(to_remove)
        gone = combat["stats"].get(to_remove) or {}
        snapshot = stat_snapshot(gone)
        log_event(combat, "remove", to_remove, snapshot, snapshot,
                  detail="odebrán z boje", actor=interaction.user.mention,
                  revert=False)
        order.remove(to_remove)
        combat["stats"].pop(to_remove, None)
        combat.get("initiative", {}).pop(to_remove, None)
        combat.get("turn_state", {}).pop(to_remove, None)

        if combat.get("boss", {}).get("name") == to_remove:
            combat.pop("boss", None)

        if combat.get("active_player") == to_remove:
            combat["active_player"] = order[0] if order else None

        if combat["locked"]:
            if not order:
                combat["locked"]        = False
                combat["current_index"] = 0
            elif removed_idx <= combat["current_index"]:
                combat["current_index"] = max(0, combat["current_index"] - 1)

        self._save_state()
        await interaction.response.send_message(
            f"❌ *{to_remove} byl odstraněn z boje.*"
        )

    # ── /combat setorder ──────────────────────────────────────────────────────

    @combat_group.command(
        name="setorder",
        description="Uzavře pořadí do pevné smyčky a spustí combat"
    )
    @admin_only()
    async def combat_setorder(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats or not self.active_combats[channel_id]["order"]:
            return await interaction.response.send_message(
                "⚠️ *Seznam je prázdný.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]

        # Seřaď pořadí podle hozené iniciativy (nejvyšší jde první).
        # Kdo nehodil, spadne na konec (init −1) — GM může dohodit /combat remove.
        init = combat.get("initiative", {})
        combat["order"].sort(key=lambda nm: init.get(nm, -1), reverse=True)

        combat["locked"]        = True
        combat["current_index"] = 0
        combat["active_player"] = combat["order"][0]
        self._save_state()

        embed = _build_order_embed(
            "🔒  Pořadí uzavřeno — boj začíná!",
            combat,
            note="Admin uzavřel pořadí. Použij tlačítko ⏭️ pro předání tahu.",
        )
        view = EOTView(self, channel_id)

        await interaction.response.defer()
        await interaction.followup.send(embed=embed, view=view)

    # ── /combat end ───────────────────────────────────────────────────────────

    @combat_group.command(name="end", description="Ukončí combat a vymaže data")
    @admin_only()
    async def combat_end(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        combat = self.active_combats.get(channel_id)
        if combat and combat.get(PENDING_KEY):
            return await interaction.response.send_message('Nejprve vyhodnoť nebo zruš čekající útoky, aby se správně vrátily jejich rezervace.', ephemeral=True)
        combat = self.active_combats.pop(channel_id, None)
        if combat is None:
            return await interaction.response.send_message(
                "⚠️ *Žádný aktivní boj.*", ephemeral=True
            )
        self._save_state()
        await interaction.response.send_message(
            embed=build_summary_embed(combat, "🏁  Combat ukončen"))

    @combat_group.command(
        name="summary",
        description="Shrnutí boje — kdo udělil a schytal nejvíc damage.")
    async def combat_summary(self, interaction: discord.Interaction):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        await interaction.response.send_message(
            embed=build_summary_embed(combat, "📊  Shrnutí boje"))

    # ── /attack ───────────────────────────────────────────────────────────────

    def _consume_weapon(self, uid: int | None, weapon_id: str | None,
                        mana_cost: int = 0, runes_active: bool = True,
                        deliver_statuses: bool = True) -> dict:
        """Spotřeba zbraně: doručené statusy a mana.

        `deliver_statuses=False` je minutý útok — mana se strhává (runa procla),
        ale nic se nedoručí.
        """
        out = {"statuses": [], "mana_note": ""}
        if uid is None or not weapon_id:
            return out
        try:
            profiles = _load_profiles()
            profile = profiles.get(_pk(profiles, uid))
            if not profile:
                return out
            entry = _weapon_entry(profile, weapon_id)
            bs = _bs()
            if entry is not None and bs and deliver_statuses:
                delivered = bs.weapon_delivered(entry)
                out["statuses"] = [(sid, src) for sid, src in delivered
                                   if runes_active or src != "runa"]
            if mana_cost:
                cur = profile.get("mana_cur", profile.get("mana_max", 20))
                new = max(0, cur - mana_cost)
                profile["mana_cur"] = new
                out["mana_note"] = f"🔷 mana `{cur}` → `{new}`"
            _save_profiles(profiles)
        except Exception:
            logging.exception("[combat] spotřeba zbraně selhala")
        return out

    async def _ac_weapon(self, interaction: discord.Interaction, current: str):
        try:
            profiles = _load_profiles()
            profile  = profiles.get(_pk(profiles, interaction.user.id)) or {}
            items_db = _load_items_db()
        except Exception:
            return []
        cur = current.lower()
        out = []
        for item_id in _player_weapons(profile):
            db_item = items_db.get(item_id) or {}
            expr = item_damage_expr(db_item)
            if not expr:
                continue
            name = db_item.get("name", item_id)
            if cur and cur not in name.lower() and cur not in item_id.lower():
                continue
            out.append(app_commands.Choice(name=f"{name} ({expr})"[:100], value=item_id))
        return out[:25]

    async def _ac_ammo(self, interaction: discord.Interaction, current: str):
        try:
            profiles = _load_profiles()
            profile  = profiles.get(_pk(profiles, interaction.user.id)) or {}
            items_db = _load_items_db()
        except Exception:
            return []
        cur = current.lower()
        out = []
        for item_id, qty in _player_ammo(profile, items_db):
            db_item = items_db.get(item_id) or {}
            name = db_item.get("name", item_id)
            if cur and cur not in name.lower() and cur not in item_id.lower():
                continue
            expr = item_damage_expr(db_item)
            label = f"{name} ×{qty}" + (f" ({expr})" if expr else "")
            out.append(app_commands.Choice(name=label[:100], value=item_id))
        return out[:25]

    @app_commands.command(
        name="attack",
        description="Útok zbraní — hodí damage a nabídne potvrzení zásahu.")
    @app_commands.describe(
        cil="Koho útočíš (aktér v boji).",
        zbran="Zbraň (výchozí: co máš v ruce).",
        ammo="Munice pro střelnou zbraň — přičte svůj atk a odečte se kus.",
        akce="Útok nebo bonusový útok (dual wielding).",
        bonus="Ruční bonus k poškození (perky, situace).",
        force="[GM] Ignoruj pojistku na už použitou akci i na zbraň mimo ruce.",
    )
    @app_commands.choices(akce=[
        app_commands.Choice(name="útok",          value="attack"),
        app_commands.Choice(name="bonusový útok", value="bonus"),
    ])
    @app_commands.autocomplete(cil=_ac_actor, zbran=_ac_weapon, ammo=_ac_ammo)
    async def attack(
        self,
        interaction: discord.Interaction,
        cil: str,
        zbran: Optional[str] = None,
        ammo: Optional[str] = None,
        akce: Optional[app_commands.Choice[str]] = None,
        bonus: int = 0,
        force: bool = False,
    ):
        try:
            data = attack_flow.prepare(interaction.channel_id, interaction.user.mention, cil,
                action=akce.value if akce else 'attack', weapon_id=zbran, ammo=ammo,
                bonus=bonus, dm=is_dm(interaction), force=force)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        await self._send_attack(interaction, data)

    # ── /combat use ───────────────────────────────────────────────────────────

    @combat_group.command(
        name="use",
        description="Použij lektvar/protijed v boji — stojí bonusovou akci.")
    @app_commands.describe(
        item="Item z inventáře (lektvar, protijed…).",
        force="[GM] Ignoruj pojistku na už použitou bonusovou akci.")
    @app_commands.autocomplete(item=_ac_consumable_item)
    async def combat_use(self, interaction: discord.Interaction, item: str,
                         force: bool = False):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        actor = interaction.user.mention
        if actor not in combat["stats"]:
            return await interaction.response.send_message(
                "❌ *Nejsi v tomhle boji.*", ephemeral=True)

        profiles = _load_profiles()
        profile = profiles.get(_pk(profiles, interaction.user.id))
        db_item = _load_items_db().get(item) or {}
        if not profile:
            return await interaction.response.send_message("❌ Nemáš profil.", ephemeral=True)
        if not db_item.get("consumable"):
            return await interaction.response.send_message(
                f"❌ **{db_item.get('name', item)}** se nedá použít.", ephemeral=True)
        entry = _find_consumable_entry(profile.setdefault("inventory", []), item)
        if not entry:
            return await interaction.response.send_message(
                f"❌ **{db_item['name']}** nemáš v inventáři.", ephemeral=True)
        if entry.get("runes"):
            return await interaction.response.send_message(
                f"⛔ Jediný kus **{db_item['name']}** má vyrytou runu — spotřebou "
                "by o ni přišel.", ephemeral=True)
        mana_cost = int(db_item.get("mana_cost", 0) or 0)
        if mana_cost and profile.get("mana_cur", profile.get("mana_max", 20)) < mana_cost:
            return await interaction.response.send_message(
                f"❌ Nemáš dost many (potřebuješ **{mana_cost}** 🔷).", ephemeral=True)

        is_gm = interaction.user.guild_permissions.administrator
        bs = _bs()
        reg = bs.load_statuses() if bs else {}
        reusable = bool(db_item.get("reusable"))
        resources = {"uid": interaction.user.id, "mana": mana_cost,
                     "item_id": None if reusable else item,
                     "item_qty": 0 if reusable else 1}

        def change(c: dict):
            stat = c["stats"].get(actor)
            if stat is None:
                return "missing"
            if is_down(c, actor):
                return "down"
            if not use_action(c, actor, "bonus", force=force and is_gm):
                return "used"
            before = stat_snapshot(stat)
            effects = apply_item_effects(profile, db_item, carrier=stat, registry=reg)
            log_event(c, "item", actor, before, stat_snapshot(stat),
                      detail=f"použil {db_item['name']}", actor=actor,
                      resources=resources)
            return {"effects": effects, "hp": stat.get("hp", 0),
                    "statuses": copy.deepcopy(stat.get("statuses") or [])}

        result = self.mutate_combat(interaction.channel_id, change)
        if result == "missing" or result is None:
            return await interaction.response.send_message(
                "❌ *Boj se mezitím změnil — zkus to znovu.*", ephemeral=True)
        if result == "down":
            return await interaction.response.send_message(
                "💀 *Na zemi už nic nevypiješ.*", ephemeral=True)
        if result == "used":
            return await interaction.response.send_message(
                "⛔ *Bonusovou akci jsi v tomhle tahu už použil.* "
                "(GM může přes `force`.)", ephemeral=True)

        if not reusable:
            _remove_entry(profile["inventory"], entry, 1)
        profile["hp_cur"] = max(0, min(result["hp"], profile.get("hp_max", 50)))
        profile["statuses"] = result["statuses"]
        _save_profiles(profiles)

        lines = [console(f"🧴 {actor} použil **{db_item['name']}**  *(bonusová akce)*")]
        lines += [console(line) for line in result["effects"]]
        await interaction.response.send_message("\n".join(lines))

    # ── /combat attack_npc ────────────────────────────────────────────────────

    async def _ac_npc(self, interaction: discord.Interaction, current: str):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return []
        cur = current.lower()
        out = []
        for name in combat["order"]:
            if is_player(name) or cur not in name.lower():
                continue
            weapons = npc_weapons_line(combat["stats"].get(name, {}))
            label = f"{name} — {weapons}" if weapons else name
            out.append(app_commands.Choice(name=label[:100], value=name))
        return out[:25]

    @combat_group.command(
        name="attack_npc",
        description="[GM] NPC útočí — hodí damage své zbraně a nabídne potvrzení.")
    @admin_only()
    @app_commands.describe(
        utocnik="NPC/boss, který útočí.",
        cil="Koho NPC napadá.",
        zbran="Hlavní nebo bonusová zbraň NPC (výchozí: hlavní).",
        dmg="Jednorázový damage místo zbraně (`1d8`, `16`).",
        bonus="Ruční bonus k poškození.",
        force="Ignoruj pojistku na už použitou akci NPC.",
    )
    @app_commands.choices(zbran=[
        app_commands.Choice(name="hlavní zbraň",   value="main"),
        app_commands.Choice(name="bonusová zbraň", value="bonus"),
    ])
    @app_commands.autocomplete(utocnik=_ac_npc, cil=_ac_actor)
    async def combat_attack_npc(
        self,
        interaction: discord.Interaction,
        utocnik: str,
        cil: str,
        zbran: Optional[app_commands.Choice[str]] = None,
        dmg: Optional[str] = None,
        bonus: int = 0,
        force: bool = False,
    ):
        if _actor_uid(utocnik) is not None:
            return await interaction.response.send_message('Tento příkaz je pro NPC.', ephemeral=True)
        slot = zbran.value if zbran else 'main'
        try:
            data = attack_flow.prepare(interaction.channel_id, utocnik, cil,
                action='bonus' if slot == 'bonus' else 'attack', bonus=bonus,
                dm=is_dm(interaction), force=force, npc_expr=dmg, npc_slot=slot)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        await self._send_attack(interaction, data)

    @combat_group.command(
        name="log",
        description="Historie změn HP v tomhle boji.")
    @app_commands.describe(pocet="Kolik posledních záznamů (výchozí 10).")
    async def combat_log(self, interaction: discord.Interaction, pocet: int = 10):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        events = combat.get("log", [])[-max(1, min(pocet, LOG_LIMIT)):]
        if not events:
            return await interaction.response.send_message(
                "📜 *Log je zatím prázdný.*", ephemeral=True)
        embed = discord.Embed(
            title="📜  Log boje",
            description="\n".join(format_log_event(e)[:350] for e in events)[-4000:],
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Poslední změnu vrátíš přes /combat undo")
        await interaction.response.send_message(embed=embed)

    async def _ac_pending(self, interaction, current):
        self.reload_state()
        state = self.active_combats.get(interaction.channel_id, {})
        return [app_commands.Choice(name=f"{a['attacker']} → {a['target']} · {a.get('weapon_label', '')}"[:100], value=aid)
                for aid, a in state.get(PENDING_KEY, {}).items()
                if current.lower() in f"{a['attacker']} {a['target']} {a.get('weapon_label', '')}".lower()][:25]

    @combat_group.command(name="pending", description="[GM] Obnoví kartu čekajícího útoku bez nového hodu.")
    @admin_only()
    @app_commands.autocomplete(utok=_ac_pending)
    async def combat_pending(self, interaction: discord.Interaction, utok: str):
        from src.logic.attack_ui import attack_embed
        state = self.active_combats.get(interaction.channel_id, {})
        data = state.get(PENDING_KEY, {}).get(utok)
        if not data:
            return await interaction.response.send_message('Útok už nečeká na vyhodnocení.', ephemeral=True)
        if not data.get('flow_version'):
            data = attack_flow.migrate_legacy(interaction.channel_id, utok)
        view = AttackView(self, interaction.channel_id, data=data)
        await interaction.response.send_message(embed=attack_embed(data), view=view,
            allowed_mentions=discord.AllowedMentions.none())
        await self._store_pending(interaction, view)

    @combat_group.command(
        name="undo",
        description="[GM] Vrátí poslední změnu; u útoku i zdroje obou stran.")
    @admin_only()
    async def combat_undo(self, interaction: discord.Interaction):
        try:
            event = attack_flow.undo(interaction.channel_id)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        if event:
            self.reload_state()
            await interaction.response.send_message(console('↩️ Rozhodnutí vráceno včetně zdrojů obou stran. Hody zůstávají v logu.'))
            combat = self.active_combats[interaction.channel_id]
            if combat.get('boss'):
                await self._update_boss_bar(combat)
            return
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        event = undo_last(combat)
        if not event:
            return await interaction.response.send_message(
                "↩️ *Není co vracet.*", ephemeral=True)

        target = event["target"]
        stat = combat["stats"][target]
        bs = _bs()
        uid = _actor_uid(target)
        if uid is not None:
            # Statusy i HP musí zpátky do profilu, jinak se stav rozejde.
            _writeback_player_state(uid, stat, bs)
        refund = refund_resources(event)
        self._save_state()

        lines = undo_console(event, target, stat["hp"], stat.get("max_hp", 0))
        if refund:
            lines.append(console(refund))
        await interaction.response.send_message(lines[0])
        asyncio.create_task(self._stream(interaction, lines))
        if combat.get("boss", {}).get("name") == target:
            asyncio.create_task(self._update_boss_bar(combat))

    @combat_group.command(
        name="autoapply",
        description="[GM] Informace o potvrzování útoků.")
    @admin_only()
    async def combat_autoapply(self, interaction: discord.Interaction, zapnuto: bool):
        await interaction.response.send_message(
            'Útok nyní vždy čeká na rozhodnutí DM na kartě útoku. Automatické zásahy jsou vypnuté.',
            ephemeral=True)

    @combat_group.command(
        name="verbose",
        description="[GM] Dlouhé embedy místo krátkých hlášek při úpravě HP.")
    @admin_only()
    async def combat_verbose(self, interaction: discord.Interaction, zapnuto: bool):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        combat["verbose"] = zapnuto
        self._save_state()
        await interaction.response.send_message(
            f"⚙️ Dlouhé HP embedy: **{'zapnuty' if zapnuto else 'vypnuty'}**.")

    # ── /combat status ────────────────────────────────────────────────────────

    @combat_group.command(name="status", description="Zobrazí aktuální pořadí a stats")
    async def combat_status(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        embed  = _build_order_embed("📋  Aktuální stav combatu", combat)
        view   = EOTView(self, channel_id) if combat.get("locked") else discord.utils.MISSING

        if combat.get("locked"):
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(CombatCog(bot))