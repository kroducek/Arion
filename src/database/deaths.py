"""Persistent death decisions, written in the same transaction as player HP."""
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from src.database import db

DEATHS = "character_deaths.json"
PROFILES = "profiles.json"
CHARACTERS = "characters.json"
COMBAT = "combat_state.json"
DELAY = 600

death_channel = ContextVar("death_channel", default=None)


@contextmanager
def in_channel(channel_id):
    token = death_channel.set(channel_id)
    try:
        yield
    finally:
        death_channel.reset(token)


def track_deaths(conn, previous, profiles):
    deaths = db._read_doc(conn, DEATHS, {})
    changed = False
    for key, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        if key in deaths:
            profile["hp_cur"] = 0
            continue
        old = previous.get(key)
        if not isinstance(old, dict) or profile.get("hp_cur") != 0:
            continue
        if (old.get("hp_cur", old.get("hp_max", 50)) or 0) <= 0:
            continue
        uid, _, slot = key.partition(":")
        if not uid.isdecimal():
            continue
        slot = slot or "1"
        registry = db._read_doc(conn, CHARACTERS, {})
        char = registry.get(uid, {}).get("chars", {}).get(slot, {})
        deaths[key] = {
            "id": uuid.uuid4().hex,
            "uid": int(uid),
            "slot": slot,
            "name": char.get("name") or profile.get("name"),
            "deadline": time.time() + DELAY,
            "channel_id": death_channel.get(),
        }
        changed = True
    if changed:
        db._write_doc(conn, DEATHS, deaths)


def pending_deaths():
    return db.load_doc(DEATHS)


def attach_message(key, death_id, message):
    def change(deaths):
        death = deaths.get(key)
        if death and death["id"] == death_id:
            death.update(message_id=message.id, message_channel_id=message.channel.id)
    current = db.update_doc(DEATHS, change).get(key)
    return current is not None and current["id"] == death_id


def _remove_character(conn, profiles, key, uid, slot, allow_last):
    registry = db._read_doc(conn, CHARACTERS, {})
    record = registry.get(str(uid), {})
    chars = record.get("chars", {})
    if not allow_last and (slot not in chars or len(chars) <= 1):
        return None

    data_key = f"{uid}:{slot}"
    keys = {key, data_key}
    hit = []
    for doc, label in (
        (PROFILES, "profil"),
        ("economy.json", "zlaté"),
        ("diaries.json", "deník"),
        ("notes.json", "poznámky"),
        ("player_perks.json", "perky"),
    ):
        data = profiles if doc == PROFILES else db._read_doc(conn, doc, {})
        if keys.intersection(data):
            for entry in keys:
                data.pop(entry, None)
            hit.append(label)
            db._write_doc(conn, doc, data)

    for doc in ("reputation.json", "timeline.json"):
        data = db._read_doc(conn, doc, {})
        changed = False
        for state in data.values():
            if not isinstance(state, dict):
                continue
            players = state.get("players", {})
            for entry in keys.intersection(players):
                del players[entry]
                changed = True
        if changed:
            db._write_doc(conn, doc, data)
            if doc == "reputation.json":
                hit.append("reputace")

    if slot in chars:
        del chars[slot]
        if not chars:
            registry.pop(str(uid), None)
        elif str(record.get("active")) == slot:
            record["active"] = next(iter(chars))
        db._write_doc(conn, CHARACTERS, registry)
    return hit


def _update_combat(conn, key, death, revive):
    combats = db._read_doc(conn, COMBAT, {})
    record = db._read_doc(conn, CHARACTERS, {}).get(str(death["uid"]), {})
    is_active = str(record.get("active", "1")) == death["slot"]
    changed = False
    for combat in combats.values():
        stats = combat.get("stats", {})
        for actor, stat in list(stats.items()):
            if stat.get("profile_key") != key and not (
                stat.get("profile_key") is None and is_active
                and actor in (f'<@{death["uid"]}>', f'<@!{death["uid"]}>')
            ):
                continue
            changed = True
            if revive:
                stat["hp"] = 1
                continue
            del stats[actor]
            order = combat.get("order", [])
            if actor in order:
                index = order.index(actor)
                order.remove(actor)
                turn = combat.get("current_index", 0)
                combat["current_index"] = (turn - (index < turn)) % len(order) if order else 0
                if not order:
                    combat["locked"] = False
                if combat.get("active_player") == actor:
                    combat["active_player"] = order[combat["current_index"]] if order else None
                if combat.get("first") == actor:
                    combat["first"] = order[0] if order else None
            for field in ("initiative", "turn_state"):
                if isinstance(combat.get(field), dict):
                    combat[field].pop(actor, None)
    if changed:
        db._write_doc(conn, COMBAT, combats)


def delete_character(uid, slot):
    key = f"{uid}:{slot}"
    with db.transaction() as conn:
        hit = _remove_character(conn, db._read_doc(conn, PROFILES, {}), key, uid, slot, False)
        if hit is not None:
            deaths = db._read_doc(conn, DEATHS, {})
            if deaths.pop(key, None):
                db._write_doc(conn, DEATHS, deaths)
        return hit


def resolve(key, death_id, action):
    with db.transaction() as conn:
        deaths = db._read_doc(conn, DEATHS, {})
        death = deaths.get(key)
        if not death or death["id"] != death_id:
            return None
        expired = time.time() >= death["deadline"]
        if action == "expire" and not expired:
            return None

        profiles = db._read_doc(conn, PROFILES, {})
        result = "missing"
        if key in profiles:
            revive = action == "revive" and not expired
            if revive:
                profiles[key]["hp_cur"] = 1
                db._write_doc(conn, PROFILES, profiles)
                _update_combat(conn, key, death, True)
                result = "revived"
            else:
                _update_combat(conn, key, death, False)
                _remove_character(conn, profiles, key, death["uid"], death["slot"], True)
                result = "expired" if expired else "deleted"
        del deaths[key]
        db._write_doc(conn, DEATHS, deaths)
        return result
