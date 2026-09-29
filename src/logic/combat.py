import copy
import discord
import asyncio
import logging
import random
from typing import Optional
from discord.ext import commands
from discord import app_commands, ui
from src.utils.paths import COMBAT_STATE
from src.utils.json_utils import load_json, save_json, update_json
from src.database.profiles import (
    load_items as _load_items_db,
    load_profiles as _load_profiles,
    profile_key as _pk,
    save_profiles as _save_profiles,
)
from src.logic.dice import DiceError, implicit_die, item_damage_expr, roll_expr
from src.logic.inventory import (
    TOULEC_ITEM_ID,
    _add_to_inventory,
    _remove_from_inventory,
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

def _actor_uid(actor: str):
    """Z '<@123>' / '<@!123>' vytáhne int id, jinak None (NPC)."""
    if actor.startswith("<@"):
        digits = "".join(ch for ch in actor if ch.isdigit())
        return int(digits) if digits else None
    return None

def _writeback_player_state(uid: int, carrier: dict, bs,
                            tick_coatings: bool = True) -> None:
    """Hráči zapíše hp_cur + statusy zpět do profilu a ubere kolo jeho nátěrům.

    `tick_coatings=False` je zápis, který změnu jen vrací (undo) — tam by bylo
    ubírání kol nátěrům navíc.
    """
    try:
        profiles = _load_profiles()
        p = profiles.get(_pk(profiles, uid))
        if not p:
            return
        p["hp_cur"]   = max(0, min(carrier.get("hp", 0), p.get("hp_max", 50)))
        p["statuses"] = carrier.get("statuses", [])
        if bs and tick_coatings:
            bs.tick_coatings(p)
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

def _writeback_hp_to_profile(user_id: int, new_hp: int):
    """
    Zapíše nové hp_cur zpět do profiles.json pro daného hráče.
    """
    try:
        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, user_id))
        if not profile:
            return
        hp_max = profile.get("hp_max", 50)
        profile["hp_cur"] = max(0, min(new_hp, hp_max))
        _save_profiles(profiles)
    except Exception:
        logging.exception("[combat] Nelze zapsat HP zpět do profilu")


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
    fur = int(stat.get("fur", 0) or 0)

    after_def = max(0, raw_hit - dfn)
    absorbed = min(fur, after_def)
    stat["fur"] = fur - absorbed
    final = after_def - absorbed

    old_hp = int(stat.get("hp", 0) or 0)
    stat["hp"] = max(0, old_hp - final)

    parts = [f"zásah {raw_hit}"]
    if dfn:
        parts.append(f"−{min(dfn, raw_hit)} DEF")
    if absorbed:
        parts.append(f"−{absorbed} 🔥furioku")
    parts.append(f"= {final} do HP")

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


def set_npc_weapon(stat: dict, slot: str, expr: str, name: str = "",
                   status: str = "") -> dict:
    """Uloží zbraň NPC do statů. `expr` prázdný = zbraň se smaže.

    `status` je id statusu z blacksmithu (jed, krácení…), který zbraň doručí
    při potvrzeném zásahu — NPC tak umí to samé co hráčská natřená zbraň.
    """
    weapons = stat.setdefault("weapons", {})
    if not str(expr or "").strip():
        weapons.pop(slot, None)
        return {}
    weapon = {"dmg": normalize_dmg_expr(expr)}
    if name.strip():
        weapon["name"] = name.strip()
    if status.strip():
        weapon["status"] = status.strip()
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


def hp_recap_console(combat: dict) -> list[str]:
    """Přehled HP všech bojovníků — řádek na jednoho, ve stylu konzole."""
    stats = combat.get("stats", {})
    lines = []
    for name in (combat.get("order") or list(stats)):
        s = stats.get(name)
        if not s:
            continue
        hp, max_hp = s.get("hp", 0), s.get("max_hp", 0)
        bar = _make_bar(hp, max_hp, 8)
        dead = "  💀" if hp == 0 else ""
        lines.append(console(f"❤️ **{name}** `{hp}/{max_hp}` {bar}{dead}"))
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


def reset_reactions(combat: dict) -> None:
    """Nové kolo — všem se vrací reakce."""
    for actor in list(combat.get("turn_state", {})):
        turn_state(combat, actor)["reaction"] = 0


# ── Log boje + undo ──────────────────────────────────────────────────────────

LOG_LIMIT = 60
LOG_ICON = {"attack": "⚔️", "sethp": "🩹", "status": "🩸", "perk": "✨", "miss": "🛡️",
            "effect": "🧪", "cure": "🌿", "stat": "🛡", "remove": "❌"}

SNAPSHOT_KEYS = ("hp", "fur", "def", "max_hp")


def stat_snapshot(stat: dict) -> dict:
    """Stav aktéra pro undo — čísla i statusy (kopie, ne odkaz)."""
    snap = {key: int(stat.get(key, 0) or 0) for key in SNAPSHOT_KEYS}
    snap["statuses"] = copy.deepcopy(stat.get("statuses") or [])
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
        event["undone"] = True
        return event
    return None


def refund_resources(event: dict) -> str:
    """Vrátí útočníkovi manu a munici z vráceného útoku. Vrací poznámku do konzole."""
    res = event.get("resources") or {}
    uid = res.get("uid")
    if not uid:
        return ""
    notes = []
    try:
        profiles = _load_profiles()
        profile = profiles.get(_pk(profiles, int(uid)))
        if not profile:
            return ""
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
    def __init__(self, cog: "CombatCog", channel_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id

    @ui.button(label="⏭️  End of Turn", style=discord.ButtonStyle.danger)
    async def eot_button(self, interaction: discord.Interaction, button: ui.Button):
        self.cog.reload_state()
        if self.channel_id not in self.cog.active_combats:
            return await interaction.response.send_message(
                "❌ *Combat byl ukončen.*", ephemeral=True
            )

        combat = self.cog.active_combats[self.channel_id]

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
        is_admin      = interaction.user.guild_permissions.administrator
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

        # Advance — padlí aktéři se přeskakují
        reset_turn(combat, current_actor)
        clear_buffs(combat, current_actor)
        next_actor, rounds, skipped = advance_turn(combat)
        combat["active_player"] = next_actor
        # Začátek tahu maže i akce utracené mimo tah (NPC útok, reakce).
        reset_turn(combat, next_actor, reaction=True)

        # Nové kolo (pořadí se obtočilo) → auto-tick statusů (dmg z jedu/krvácení atd.)
        tick_lines: list[str] = []
        new_round = rounds > 0
        if new_round:
            combat["round"] = int(combat.get("round", 1)) + rounds
            reset_reactions(combat)
            if combat.get("auto_tick", True):
                tick_lines = self.cog._tick_round(combat)
        self.cog._save_state()

        lines = turn_console(combat, next_actor, new_round=new_round)
        lines += [console(f"💀 *{who} je mimo boj — tah přeskočen.*") for who in skipped]
        lines += tick_lines
        view = EOTView(self.cog, self.channel_id)
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
        super().__init__(timeout=120)
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
            logger.exception("[combat] oznámení iniciativy selhalo")


# ── Zbraně hráče ──────────────────────────────────────────────────────────────

WEAPON_SLOTS = ("hand_l", "hand_r")


def _iter_entries(profile: dict):
    for entry in profile.get("inventory", []):
        yield entry
    for storage in (profile.get("storages") or {}).values():
        for entry in storage:
            yield entry


def _weapon_entry(profile: dict, item_id: str) -> dict | None:
    """Instance zbraně v inventáři — přednost má kus s runou/nátěrem."""
    fallback = None
    for entry in _iter_entries(profile):
        if entry.get("type") != "registered" or entry.get("id") != item_id:
            continue
        if entry.get("runes") or entry.get("coating"):
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
    coat = entry.get("coating")
    if isinstance(coat, dict) and coat.get("status"):
        names.append(f"🧪 {coat['status']}")
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

class DamageModal(ui.Modal, title="Upravit poškození"):
    dmg = ui.TextInput(label="Poškození", placeholder="např. 12", max_length=5)

    def __init__(self, view: "AttackView", default: int):
        super().__init__()
        self.view_ref = view
        self.dmg.default = str(default)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.dmg.value).strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ Zadej číslo.", ephemeral=True)
        await self.view_ref.resolve_hit(interaction, value)


class AttackView(ui.View):
    """Útok čeká na potvrzení — cíl může uhnout, GM upravit číslo."""

    def __init__(self, cog: "CombatCog", channel_id: int, attacker: str,
                 attacker_uid: int | None, target: str, damage: int,
                 weapon_id: str | None, mana_cost: int = 0,
                 ammo_note: str = "", weapon_label: str = "",
                 roll_info: str = "", resources: dict | None = None,
                 extra_statuses: list | None = None):
        super().__init__(timeout=600)
        self.resources = resources or {}
        self.extra_statuses = list(extra_statuses or [])
        self.cog = cog
        self.channel_id = channel_id
        self.attacker = attacker
        self.attacker_uid = attacker_uid
        self.target = target
        self.damage = damage
        self.weapon_id = weapon_id
        self.mana_cost = mana_cost
        self.ammo_note = ammo_note
        self.weapon_label = weapon_label
        self.roll_info = roll_info
        self.resolved = False

    # ── oprávnění ────────────────────────────────────────────────────────────

    def _may_resolve(self, interaction: discord.Interaction) -> bool:
        """Rozhodovat smí GM, cíl útoku i útočník (ať GM nemusí klikat vše)."""
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is not None and perms.administrator:
            return True
        mention = interaction.user.mention
        return mention in (self.target, self.attacker)

    def _disable(self):
        for child in self.children:
            child.disabled = True

    async def _replace_with_console(self, interaction: discord.Interaction,
                                    lines: list[str]) -> None:
        """Smaže embed útoku a pošle výsledek jako novou zprávu konzole.

        Mezi útokem a rozhodnutím bývají RP zprávy, takže by se přepsaný
        embed ztratil v konverzaci — proto nová zpráva dole v kanálu.
        """
        if not interaction.response.is_done():
            await interaction.response.defer()
        message = interaction.message or getattr(self, "message", None)
        if message is not None:
            try:
                await message.delete()
            except Exception:
                logging.exception("[combat] embed útoku se nepodařilo smazat")
        await self.cog.send_console(interaction.channel, lines)

    # ── aplikace zásahu ──────────────────────────────────────────────────────

    async def resolve_hit(self, interaction: discord.Interaction, damage: int):
        if self.resolved:
            return await interaction.response.send_message(
                "⏳ *Tenhle útok už je vyhodnocený.*", ephemeral=True)
        self.resolved = True
        self.cog.reload_state()
        combat = self.cog.active_combats.get(self.channel_id)
        if not combat or self.target not in combat["stats"]:
            self.resolved = False
            return await interaction.response.send_message(
                "❌ *Cíl už není v boji.*", ephemeral=True)

        bs = _bs()
        delivered = self.cog._consume_weapon(self.attacker_uid, self.weapon_id,
                                             self.mana_cost)
        statuses = list(delivered.get("statuses") or []) + self.extra_statuses
        reg = bs.load_statuses() if bs else {}
        applied: list[str] = []

        def change(state: dict) -> dict | None:
            stat = state.get("stats", {}).get(self.target)
            if stat is None:
                return None
            before = stat_snapshot(stat)
            out = apply_hit(stat, damage)
            for status_id, source in statuses:
                if bs and bs.apply_status(stat, status_id, source, reg):
                    sdef = reg.get(status_id, {})
                    applied.append(f"{sdef.get('emoji', '•')} {sdef.get('name', status_id)}")
            log_event(state, "attack", self.target, before, stat_snapshot(stat),
                      detail=out["change_str"], actor=self.attacker,
                      resources=self.resources)
            out["max_hp"] = stat.get("max_hp", 0)
            out["stat"] = stat
            return out

        result = self.cog.mutate_combat(self.channel_id, change)
        if result is None:
            self.resolved = False
            return await interaction.response.send_message(
                "❌ *Cíl už není v boji.*", ephemeral=True)
        combat = self.cog.active_combats[self.channel_id]
        stat = result["stat"]
        max_hp = result["max_hp"]

        roll_info = self.roll_info
        if roll_info and damage != self.damage:
            roll_info += f" → upraveno na {damage}"

        notes = []
        if self.ammo_note:
            notes.append(self.ammo_note)
        if delivered.get("mana_note"):
            notes.append(delivered["mana_note"])
        if applied:
            notes.append("Doručeno: " + " · ".join(applied))

        uid = _actor_uid(self.target)
        if uid is not None:
            if bs:
                _writeback_player_state(uid, stat, bs)
            else:
                _writeback_hp_to_profile(uid, stat["hp"])

        self._disable()

        lines = hp_console(self.target, result["old_hp"], result["new_hp"], max_hp,
                           result["change_str"], attacker=self.attacker,
                           notes=["  ·  ".join(notes)] if notes else None,
                           weapon=self.weapon_label or None,
                           roll_info=roll_info or None)
        await self._replace_with_console(interaction, lines)

        if combat.get("boss", {}).get("name") == self.target:
            asyncio.create_task(self.cog._update_boss_bar(combat, flashing=True))
        asyncio.create_task(self.cog.check_wipeout(interaction.channel, combat))

    # ── tlačítka ─────────────────────────────────────────────────────────────

    @ui.button(label="Zasáhl", emoji="✅", style=discord.ButtonStyle.success)
    async def hit(self, interaction: discord.Interaction, button: ui.Button):
        if not self._may_resolve(interaction):
            return await interaction.response.send_message(
                "❌ *Rozhodnout může GM, útočník nebo cíl.*", ephemeral=True)
        await self.resolve_hit(interaction, self.damage)

    @ui.button(label="Uhnul / minul", emoji="🛡️", style=discord.ButtonStyle.secondary)
    async def miss(self, interaction: discord.Interaction, button: ui.Button):
        if not self._may_resolve(interaction):
            return await interaction.response.send_message(
                "❌ *Rozhodnout může GM, útočník nebo cíl.*", ephemeral=True)
        if self.resolved:
            return await interaction.response.send_message(
                "⏳ *Tenhle útok už je vyhodnocený.*", ephemeral=True)
        self.resolved = True
        self._disable()
        # Runa procne vždycky, když ji útočník použije — mana se strhává i při
        # minutí, stejně jako se už odčetla munice při výstřelu.
        spent = self.cog._consume_weapon(self.attacker_uid, self.weapon_id,
                                         self.mana_cost, deliver_statuses=False)

        def change(state: dict) -> dict | None:
            stat = state.get("stats", {}).get(self.target)
            if stat is None:
                return None
            snapshot = stat_snapshot(stat)
            detail = f"minul ({self.damage} dmg)"
            if self.weapon_label:
                detail = f"{self.weapon_label} — {detail}"
            return log_event(state, "miss", self.target, snapshot, snapshot,
                             detail=detail, actor=self.attacker, revert=False)

        self.cog.mutate_combat(self.channel_id, change)
        lines = miss_console(self.target, self.attacker, self.damage,
                             weapon=self.weapon_label or None,
                             roll_info=self.roll_info or None)
        if self.ammo_note:
            lines.append(console(self.ammo_note))
        if spent.get("mana_note"):
            lines.append(console(spent["mana_note"]))
        await self._replace_with_console(interaction, lines)

    @ui.button(label="Upravit", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: ui.Button):
        if not self._may_resolve(interaction):
            return await interaction.response.send_message(
                "❌ *Rozhodnout může GM, útočník nebo cíl.*", ephemeral=True)
        await interaction.response.send_modal(DamageModal(self, self.damage))

    @ui.button(label="Reakce (1d20)", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def reaction(self, interaction: discord.Interaction, button: ui.Button):
        self.cog.reload_state()
        combat = self.cog.active_combats.get(self.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Combat už neběží.*", ephemeral=True)
        actor = interaction.user.mention
        if actor != self.target:
            return await interaction.response.send_message(
                "❌ *Reakci hází cíl útoku.*", ephemeral=True)
        if not use_action(combat, actor, "reaction"):
            return await interaction.response.send_message(
                "⛔ *Reakci jsi v tomhle kole už použil.*", ephemeral=True)
        self.cog._save_state()
        roll = random.randint(1, 20)
        lines = [
            console(f"🎲 {actor} hází reakci (úhyb/check)"),
            console(f"**{roll}**"),
            console("*GM rozhodne tlačítkem ✅ / 🛡️*"),
        ]
        await interaction.response.send_message(lines[0])
        asyncio.create_task(self.cog._stream(interaction, lines))


class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_combats = self._load_state()

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
        hodnotu `change`, nebo None když v kanále žádný boj není.
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
            box["result"] = change(combat)
            raw[key] = combat
            return raw

        try:
            update_json(COMBAT_STATE, mutate)
        except Exception:
            logging.exception("[combat] atomický zápis stavu selhal")
        return box["result"]

    # ── Konzole ───────────────────────────────────────────────────────────────

    async def send_console(self, channel, lines: list[str],
                           header: str = "") -> None:
        """Pošle konzolový výpis jako novou zprávu a dopisuje zbytek řádků."""
        if not lines:
            return
        try:
            message = await channel.send(header + lines[0])
        except Exception:
            logging.exception("[combat] konzoli se nepodařilo odeslat")
            return
        if len(lines) > 1:
            asyncio.create_task(stream_console(message, lines, header))

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
        try:
            serializable = {str(k): v for k, v in self.active_combats.items()}
            save_json(COMBAT_STATE, serializable)
        except Exception:
            logging.exception("[combat] Nelze uložit stav")

    def _load_state(self) -> dict:
        try:
            raw = load_json(COMBAT_STATE, default={})
            state = {int(k): v for k, v in raw.items()}
            # migrace: staré combaty uložené před iniciativou nemají klíč
            for combat in state.values():
                combat.setdefault("initiative", {})
                combat.setdefault("round", 1)
                combat.setdefault("log", [])
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

    def _tick_round(self, combat: dict) -> list[str]:
        """Konec kola: u všech aktérů udělí dmg ze statusů a sníží trvání.

        Hráčům zapíše hp + statusy zpět do profilu a uberou kolo jejich nátěrům.
        Vrací řádky konzole (prázdný seznam, když se nic nestalo).
        """
        bs = _bs()
        if not bs:
            return []
        reg   = bs.load_statuses()
        lines = []
        for actor, s in combat["stats"].items():
            before = stat_snapshot(s)
            dmg, log = bs.tick_statuses(s, reg)
            if dmg:
                s["hp"] = max(0, s.get("hp", 0) - dmg)
                log_event(combat, "status", actor, before, stat_snapshot(s),
                          detail=f"statusy −{dmg}")
            uid = _actor_uid(actor)
            if uid is not None:
                _writeback_player_state(uid, s, bs)
            if log:
                lines.append(console(f"🩸 **{actor}**: " + " · ".join(log)))
        if not lines:
            return []
        return [console("── statusy na konci kola ──")] + lines

    combat_group = app_commands.Group(
        name="combat", description="Bojový systém — start, join, správa aktérů a efektů (DM)")

    combat_effect = app_commands.Group(
        name="effect", description="Statusy v boji — jed/krvácení atd. (DM).", parent=combat_group)

    async def _ac_actor(self, interaction: discord.Interaction, current: str):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return []
        cur = current.lower()
        return [app_commands.Choice(name=a[:100], value=a)
                for a in combat["order"] if cur in a.lower()][:25]

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
            combat["stats"][user] = {
                "hp":     synced["hp"],
                "max_hp": synced["max_hp"],
                "def":    synced["def"],
                "fur":    synced["fur"],
            }

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
                _writeback_hp_to_profile(uid, new_hp)
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
        dmg="Damage (`1d8`, `2d6+2`, holé číslo = kostka). Prázdné = zbraň smazat.",
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
            weapon = set_npc_weapon(stat, zbran.value, dmg or "", nazev or "",
                                    status or "")
        except DiceError:
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
        """Spotřeba zbraně: doručené statusy, úbytek nátěru a many.

        `deliver_statuses=False` je minutý útok — mana se strhává (runa procla),
        ale nátěr zůstává a nic se nedoručí.
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
                bs.consume_coating_hit(entry)
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
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        if cil not in combat["stats"]:
            return await interaction.response.send_message(
                f"❌ *`{cil}` není v boji (nebo nemá zaznamenané HP).*", ephemeral=True)

        actor = interaction.user.mention
        action = (akce.value if akce else "attack")
        is_gm = interaction.user.guild_permissions.administrator
        if is_down(combat, cil) and not (force and is_gm):
            return await interaction.response.send_message(
                f"💀 *`{cil}` už je na zemi — škoda rány.* (GM může přes `force`.)",
                ephemeral=True)
        if not use_action(combat, actor, action, force=force and is_gm):
            return await interaction.response.send_message(
                f"⛔ *{ACTION_LABEL[action].capitalize()} jsi v tomhle tahu už použil.* "
                "Zkus bonusový útok, nebo ať GM zopakuje s `force`.",
                ephemeral=True)

        profiles = _load_profiles()
        profile  = profiles.get(_pk(profiles, interaction.user.id)) or {}
        items_db = _load_items_db()

        weapon_id = zbran or (profile.get("equipment", {}) or {}).get(
            "hand_r" if action == "attack" else "hand_l")
        if not weapon_id:
            release_action(combat, actor, action)
            return await interaction.response.send_message(
                "❌ *Nemáš v ruce zbraň — nejdřív si ji vezmi přes `/equip`.*",
                ephemeral=True)

        equipped = _player_weapons(profile)
        if weapon_id not in equipped and not (force and is_gm):
            release_action(combat, actor, action)
            have = ", ".join(f"`{w}`" for w in equipped) or "*nic*"
            return await interaction.response.send_message(
                f"⛔ **{items_db.get(weapon_id, {}).get('name', weapon_id)}** nemáš v ruce. "
                f"V rukou máš: {have}. Přezbroj přes `/equip` (se souhlasem GM).",
                ephemeral=True)

        db_item = items_db.get(weapon_id) or {}
        expr = item_damage_expr(db_item)
        if not expr:
            release_action(combat, actor, action)
            return await interaction.response.send_message(
                f"❌ **{db_item.get('name', weapon_id)}** nemá damage ani `atk`. "
                f"Doplň ho: `/inv-db combat {weapon_id} dmg:1d8`.", ephemeral=True)
        try:
            roll = roll_expr(expr)
        except DiceError:
            release_action(combat, actor, action)
            return await interaction.response.send_message(
                f"❌ *Damage `{expr}` nejde hodit — oprav item `{weapon_id}`.*", ephemeral=True)

        # ── Munice: vlastní `atk` navíc a odečtení kusu ──────────────────────
        ammo_total = 0
        ammo_line  = ""
        ammo_note  = ""
        ammo_bit   = ""
        ammo_spent: str | None = None
        if ammo:
            db_ammo = items_db.get(ammo) or {}
            if db_ammo.get("category") != AMMO_CATEGORY:
                release_action(combat, actor, action)
                return await interaction.response.send_message(
                    f"❌ **{db_ammo.get('name', ammo)}** není munice (kategorie *{AMMO_CATEGORY}*).",
                    ephemeral=True)
            have_ammo = _ammo_count(profile, ammo)
            if have_ammo <= 0:
                release_action(combat, actor, action)
                return await interaction.response.send_message(
                    f"🎯 **{db_ammo.get('name', ammo)}** nemáš — doplň munici do Toulce.",
                    ephemeral=True)
            ammo_expr   = item_damage_expr(db_ammo)
            ammo_detail = ""
            if ammo_expr:
                try:
                    ammo_roll = roll_expr(ammo_expr)
                except DiceError:
                    release_action(combat, actor, action)
                    return await interaction.response.send_message(
                        f"❌ *Damage `{ammo_expr}` nejde hodit — oprav item `{ammo}`.*",
                        ephemeral=True)
                ammo_total  = ammo_roll.total
                ammo_detail = f" — `{ammo_expr}` → **+{ammo_total}**"
                ammo_bit    = f"{ammo_expr} → {ammo_total}"
            _consume_ammo(profile, ammo)
            _save_profiles(profiles)
            ammo_spent = ammo
            ammo_line = (f"🎯 **{db_ammo.get('name', ammo)}**{ammo_detail}  "
                         f"*(zbývá {have_ammo - 1})*")
            ammo_note = (f"🎯 −1 {db_ammo.get('name', ammo)}  "
                         f"*(zbývá {have_ammo - 1})*")
        elif _is_ranged(db_item):
            owned = _player_ammo(profile, items_db)
            if owned:
                release_action(combat, actor, action)
                names = ", ".join(
                    f"**{items_db.get(iid, {}).get('name', iid)}** ×{qty}"
                    for iid, qty in owned)
                return await interaction.response.send_message(
                    f"🎯 *Vyber munici do `ammo`.* Máš: {names}", ephemeral=True)
            ammo_line = "🎯 *Nemáš žádnou munici — střílíš naslepo.*"

        buffs = take_attack_buffs(combat, actor)
        buff_total = 0
        buff_lines = []
        buff_bits = []
        for buff in buffs:
            try:
                buff_roll = roll_expr(str(buff.get("dmg") or "0"))
            except DiceError:
                continue
            buff_total += buff_roll.total
            buff_lines.append(f"✨ {buff['name']}: `{buff['dmg']}` → **+{buff_roll.total}**")
            buff_bits.append(f"{buff['name']} → +{buff_roll.total}")

        damage = max(0, roll.total + ammo_total + int(bonus) + buff_total)

        # Rozpis hodu nad konzolový výpis: `1d10 → 7 + 1d2 → 2 = 9`
        roll_bits = [f"{expr} → {roll.total}"]
        if ammo_bit:
            roll_bits.append(ammo_bit)
        roll_bits += buff_bits
        if bonus:
            roll_bits.append(f"bonus {int(bonus):+d}")
        roll_info = " + ".join(roll_bits) + (f" = {damage}" if len(roll_bits) > 1 else "")
        weapon_label = db_item.get("name", weapon_id)

        # ── Runy: použití stojí manu; když nestačí, runa neprocne ─────────────
        entry = _weapon_entry(profile, weapon_id)
        bs = _bs()
        runes_reg = bs.load_runes() if bs else {}
        rune_text = _rune_names(entry, runes_reg) if entry else ""
        mana_cost, runes_active, mana_note = mana_for_attack(db_item, profile)

        bonus_str = f" {'+' if bonus >= 0 else '−'}{abs(int(bonus))}" if bonus else ""
        desc = (f"**{db_item.get('name', weapon_id)}** — `{expr}`{bonus_str}\n"
                f"{roll.detail}  →  **{damage} dmg**")
        if ammo_line:
            desc += f"\n{ammo_line}"
        if buff_lines:
            desc += "\n" + "\n".join(buff_lines)
        if rune_text:
            desc += f"\n{rune_text}" + ("" if runes_active else "  *(neaktivní)*")
        if mana_note:
            desc += f"\n{mana_note}"
        if roll.nat20:
            desc += "\n✨ **Nat 20!**"
        elif roll.nat1:
            desc += "\n💀 *Nat 1…*"

        embed = discord.Embed(
            title=f"⚔️  {ACTION_LABEL[action].capitalize()}: {actor} → {cil}",
            description=desc,
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Damage se aplikuje až po potvrzení — cíl má prostor na reakci.")

        resources = {"uid": interaction.user.id, "mana": mana_cost,
                     "ammo_id": ammo_spent, "ammo_qty": 1 if ammo_spent else 0}
        view = AttackView(self, interaction.channel_id, actor,
                          interaction.user.id, cil, damage, weapon_id, mana_cost,
                          ammo_note, weapon_label, roll_info, resources=resources)

        if combat.get("auto_apply"):
            stat = combat["stats"][cil]
            before = stat_snapshot(stat)
            result = apply_hit(stat, damage)
            log_event(combat, "attack", cil, before, stat_snapshot(stat),
                      detail=result["change_str"], actor=actor,
                      resources=resources)
            delivered = self._consume_weapon(interaction.user.id, weapon_id,
                                             mana_cost, runes_active)
            notes = []
            if ammo_note:
                notes.append(ammo_note)
            if delivered.get("mana_note"):
                notes.append(delivered["mana_note"])
            if bs and delivered["statuses"]:
                reg = bs.load_statuses()
                applied = []
                for status_id, source in delivered["statuses"]:
                    inst = bs.apply_status(stat, status_id, source, reg)
                    if inst:
                        sdef = reg.get(status_id, {})
                        applied.append(f"{sdef.get('emoji', '•')} {sdef.get('name', status_id)}")
                if applied:
                    notes.append("Doručeno: " + " · ".join(applied))
            uid = _actor_uid(cil)
            if uid is not None:
                if bs:
                    _writeback_player_state(uid, stat, bs)
                else:
                    _writeback_hp_to_profile(uid, stat["hp"])
            self._save_state()
            lines = hp_console(cil, result["old_hp"], result["new_hp"],
                               stat.get("max_hp", 0), result["change_str"],
                               attacker=actor, weapon=weapon_label,
                               roll_info=roll_info,
                               notes=["  ·  ".join(notes)] if notes else None)
            header = f"{desc}\n"
            await interaction.response.send_message(header + lines[0])
            asyncio.create_task(self._stream(interaction, lines, header))
            if combat.get("boss", {}).get("name") == cil:
                asyncio.create_task(self._update_boss_bar(combat, flashing=True))
            asyncio.create_task(self.check_wipeout(interaction.channel, combat))
            return

        self._save_state()
        await interaction.response.send_message(embed=embed, view=view)

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
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        if utocnik not in combat["stats"]:
            return await interaction.response.send_message(
                f"❌ *`{utocnik}` není v boji.*", ephemeral=True)
        if cil not in combat["stats"]:
            return await interaction.response.send_message(
                f"❌ *`{cil}` není v boji (nebo nemá zaznamenané HP).*", ephemeral=True)
        if cil == utocnik:
            return await interaction.response.send_message(
                "❌ *NPC nemůže útočit samo na sebe.*", ephemeral=True)
        if is_down(combat, cil) and not force:
            return await interaction.response.send_message(
                f"💀 *`{cil}` už leží — útok povolí `force`.*", ephemeral=True)

        attacker_stat = combat["stats"][utocnik]
        if int(attacker_stat.get("hp", 0) or 0) <= 0 and not force:
            return await interaction.response.send_message(
                f"💀 *{utocnik} je mimo boj — útok povolí `force`.*", ephemeral=True)

        slot = zbran.value if zbran else "main"
        action = "bonus" if slot == "bonus" else "attack"
        if not use_action(combat, utocnik, action, force=force):
            return await interaction.response.send_message(
                f"⛔ *{utocnik} už {ACTION_LABEL[action]} v tomhle tahu použil.* "
                "Zopakuj s `force`.", ephemeral=True)

        weapon = npc_weapon(attacker_stat, slot)
        if dmg:
            try:
                expr = normalize_dmg_expr(dmg)
            except DiceError:
                release_action(combat, utocnik, action)
                return await interaction.response.send_message(
                    "❌ *Damage nejde hodit — použij zápis jako `1d8`, `2d6+2` nebo `16`.*",
                    ephemeral=True)
            weapon_label = npc_weapon_label(weapon, slot) if weapon else "improvizovaný útok"
        elif weapon:
            expr = weapon["dmg"]
            weapon_label = npc_weapon_label(weapon, slot)
        else:
            release_action(combat, utocnik, action)
            return await interaction.response.send_message(
                f"❌ *{utocnik} nemá nastavenou {NPC_SLOTS[slot]}.* "
                f"Doplň ji: `/combat setdmg {utocnik} {NPC_SLOTS[slot]} 1d8`.",
                ephemeral=True)

        try:
            roll = roll_expr(expr)
        except DiceError:
            release_action(combat, utocnik, action)
            return await interaction.response.send_message(
                f"❌ *Damage `{expr}` nejde hodit.*", ephemeral=True)

        damage = max(0, roll.total + int(bonus))
        roll_bits = [f"{expr} → {roll.total}"]
        if bonus:
            roll_bits.append(f"bonus {int(bonus):+d}")
        roll_info = " + ".join(roll_bits) + (f" = {damage}" if len(roll_bits) > 1 else "")

        bonus_str = f" {'+' if bonus >= 0 else '−'}{abs(int(bonus))}" if bonus else ""
        desc = (f"**{weapon_label}** — `{expr}`{bonus_str}\n"
                f"{roll.detail}  →  **{damage} dmg**")
        if roll.nat20:
            desc += "\n✨ **Nat 20!**"
        elif roll.nat1:
            desc += "\n💀 *Nat 1…*"

        embed = discord.Embed(
            title=f"💀  {ACTION_LABEL[action].capitalize()}: {utocnik} → {cil}",
            description=desc,
            color=discord.Color.dark_red(),
        )
        embed.set_footer(text="Damage se aplikuje až po potvrzení — cíl má prostor na reakci.")

        # Status ze zbraně NPC (jed, krácení…) — doručí se stejně jako u hráče.
        statuses = npc_weapon_statuses(weapon) if weapon and not dmg else []

        if combat.get("auto_apply"):
            stat = combat["stats"][cil]
            before = stat_snapshot(stat)
            result = apply_hit(stat, damage)
            bs = _bs()
            applied = []
            if bs and statuses:
                reg = bs.load_statuses()
                for status_id, source in statuses:
                    if bs.apply_status(stat, status_id, source, reg):
                        sdef = reg.get(status_id, {})
                        applied.append(
                            f"{sdef.get('emoji', '•')} {sdef.get('name', status_id)}")
            log_event(combat, "attack", cil, before, stat_snapshot(stat),
                      detail=result["change_str"], actor=utocnik)
            uid = _actor_uid(cil)
            if uid is not None:
                if bs:
                    _writeback_player_state(uid, stat, bs)
                else:
                    _writeback_hp_to_profile(uid, stat["hp"])
            self._save_state()
            lines = hp_console(cil, result["old_hp"], result["new_hp"],
                               stat.get("max_hp", 0), result["change_str"],
                               attacker=utocnik, weapon=weapon_label,
                               roll_info=roll_info,
                               notes=["Doručeno: " + " · ".join(applied)] if applied else None)
            header = f"{desc}\n"
            await interaction.response.send_message(header + lines[0])
            asyncio.create_task(self._stream(interaction, lines, header))
            if combat.get("boss", {}).get("name") == cil:
                asyncio.create_task(self._update_boss_bar(combat, flashing=True))
            asyncio.create_task(self.check_wipeout(interaction.channel, combat))
            return

        view = AttackView(self, interaction.channel_id, utocnik, None, cil,
                          damage, None, 0, "", weapon_label, roll_info,
                          extra_statuses=statuses)
        self._save_state()
        await interaction.response.send_message(embed=embed, view=view)

    # ── /combat log a /combat undo ────────────────────────────────────

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
            description="\n".join(format_log_event(e) for e in events),
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Poslední změnu vrátíš přes /combat undo")
        await interaction.response.send_message(embed=embed)

    @combat_group.command(
        name="undo",
        description="[GM] Vrátí poslední změnu HP zpět.")
    @admin_only()
    async def combat_undo(self, interaction: discord.Interaction):
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
            if bs:
                _writeback_player_state(uid, stat, bs, tick_coatings=False)
            else:
                _writeback_hp_to_profile(uid, stat["hp"])
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
        description="[GM] Aplikovat damage z /attack rovnou, bez potvrzení.")
    @admin_only()
    async def combat_autoapply(self, interaction: discord.Interaction, zapnuto: bool):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        combat["auto_apply"] = zapnuto
        self._save_state()
        await interaction.response.send_message(
            f"⚙️ Auto-aplikace útoků: **{'zapnuta' if zapnuto else 'vypnuta'}**.")

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