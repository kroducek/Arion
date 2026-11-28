"""Persistent death decisions, written in the same transaction as player HP."""
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from src.database import db
from src.database.characters import MAX_CHARS

DEATHS = "character_deaths.json"
PROFILES = "profiles.json"
CHARACTERS = "characters.json"
COMBAT = "combat_state.json"
ARCHIVE = "character_archive.json"
QUESTS = "quests.json"
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


def _remove_character(conn, profiles, key, uid, slot, allow_last, snapshot=None):
    registry = db._read_doc(conn, CHARACTERS, {})
    record = registry.get(str(uid), {})
    chars = record.get("chars", {})
    if not allow_last and (slot not in chars or len(chars) <= 1):
        return None

    data_key = f"{uid}:{slot}"
    keys = dict.fromkeys((data_key, key))
    if snapshot is not None and slot == "1":
        keys[str(uid)] = None
    hit = []
    for doc, label in (
        (PROFILES, "profil"),
        ("economy.json", "zlaté"),
        ("diaries.json", "deník"),
        ("notes.json", "poznámky"),
        ("player_perks.json", "perky"),
    ):
        data = profiles if doc == PROFILES else db._read_doc(conn, doc, {})
        if keys.keys() & data.keys():
            for entry in keys:
                if entry in data:
                    value = data.pop(entry)
                    if snapshot is not None:
                        snapshot["documents"].setdefault(doc, value)
            hit.append(label)
            db._write_doc(conn, doc, data)

    for doc in ("reputation.json", "timeline.json"):
        data = db._read_doc(conn, doc, {})
        changed = False
        for name, state in data.items():
            if not isinstance(state, dict):
                continue
            players = state.get("players", {})
            for entry in keys:
                if entry in players:
                    value = players.pop(entry)
                    if snapshot is not None:
                        snapshot["nested"].setdefault(doc, {}).setdefault(name, value)
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


def _archive_character(conn, profiles, key, uid, slot, char, reason, *, died=False):
    uid = str(uid)
    character_id = char.get("id") or uuid.uuid4().hex
    snapshot = dict(uid=uid, slot=slot, character={**char, "id": character_id},
                    reason=reason, died=died, archived_at=int(time.time()),
                    documents={}, nested={}, quests=[])
    record = db._read_doc(conn, CHARACTERS, {}).get(uid, {})
    active = str(record.get("active", "1")) == slot
    _remove_character(conn, profiles, key, uid, slot, True, snapshot)
    quests = db._read_doc(conn, QUESTS, {})
    for name, quest in quests.items():
        slots = quest.get("member_slots") or {}
        members = quest.get("members", [])
        if int(uid) in members and (str(slots.get(uid)) == slot or (uid not in slots and active)):
            snapshot["quests"].append(name)
            quest["members"] = [member for member in members if member != int(uid)]
            slots.pop(uid, None)
    if snapshot["quests"]:
        db._write_doc(conn, QUESTS, quests)
    archives = db._read_doc(conn, ARCHIVE, {})
    archives[character_id] = snapshot
    db._write_doc(conn, ARCHIVE, archives)
    return character_id


def archive_character(uid, slot, expected, reason):
    uid, slot = str(uid), str(slot)
    key = f"{uid}:{slot}"
    with db.transaction() as conn:
        record = db._read_doc(conn, CHARACTERS, {}).get(uid, {})
        char = record.get("chars", {}).get(slot)
        if char is None or char != expected:
            raise ValueError("Postava se mezitím změnila. Otevři potvrzení znovu.")
        deaths = db._read_doc(conn, DEATHS, {})
        if key in deaths or (slot == "1" and uid in deaths):
            raise ValueError("O postavě právě běží rozhodnutí o smrti.")
        active = str(record.get("active", "1")) == slot
        combats = db._read_doc(conn, COMBAT, {})
        for combat in combats.values():
            for actor, stat in combat.get("stats", {}).items():
                profile_key = stat.get("profile_key")
                if profile_key == key or (actor in (f"<@{uid}>", f"<@!{uid}>") and active
                                          and profile_key in (None, uid)):
                    raise ValueError("Postava je v aktivním boji. Nejdřív ji odeber z boje.")
        return _archive_character(conn, db._read_doc(conn, PROFILES, {}), key, uid, slot, char, reason)


def restore_character(character_id):
    with db.transaction() as conn:
        archives = db._read_doc(conn, ARCHIVE, {})
        snapshot = archives.get(character_id)
        if snapshot is None or snapshot.get("restored_at"):
            raise ValueError("Archivovaná postava nebyla nalezena nebo už byla obnovena.")
        uid = snapshot["uid"]
        registry = db._read_doc(conn, CHARACTERS, {})
        record = registry.setdefault(uid, {"chars": {}})
        chars = record["chars"]
        slot = next((str(n) for n in range(1, MAX_CHARS + 1) if str(n) not in chars), None)
        if slot is None:
            raise ValueError("Majitel nemá volný slot.")
        key = f"{uid}:{slot}"
        for doc, value in snapshot["documents"].items():
            data = db._read_doc(conn, doc, {})
            if key in data or (slot == "1" and uid in data):
                raise ValueError("Ve volném slotu zůstala data jiné postavy.")
            if doc == PROFILES and snapshot.get("died"):
                value = {**value, "hp_cur": 1}
            data[key] = value
            db._write_doc(conn, doc, data)
        for doc, entries in snapshot["nested"].items():
            data = db._read_doc(conn, doc, {})
            for name, value in entries.items():
                players = data.setdefault(name, {}).setdefault("players", {})
                if key in players or (slot == "1" and uid in players):
                    raise ValueError("Ve volném slotu zůstala data jiné postavy.")
                players[key] = value
            db._write_doc(conn, doc, data)
        quests = db._read_doc(conn, QUESTS, {})
        skipped = []
        for name in snapshot["quests"]:
            quest = quests.get(name)
            if quest is None or int(uid) in quest.get("members", []):
                skipped.append(name)
                continue
            quest.setdefault("members", []).append(int(uid))
            quest.setdefault("member_slots", {})[uid] = slot
        if len(skipped) < len(snapshot["quests"]):
            db._write_doc(conn, QUESTS, quests)
        chars[slot] = snapshot["character"]
        record.setdefault("active", slot)
        snapshot["restored_at"] = int(time.time())
        db._write_doc(conn, CHARACTERS, registry)
        db._write_doc(conn, ARCHIVE, archives)
        return uid, slot, snapshot["character"], skipped


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
                uid, slot = str(death["uid"]), death["slot"]
                record = db._read_doc(conn, CHARACTERS, {}).get(uid, {})
                char = record.get("chars", {}).get(slot) or {"name": death.get("name") or "Postava"}
                _archive_character(conn, profiles, key, uid, slot, char, "smrt", died=True)
                result = "expired" if expired else "deleted"
        del deaths[key]
        db._write_doc(conn, DEATHS, deaths)
        return result
