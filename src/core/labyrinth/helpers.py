"""Pomocné funkce a generátor mapy."""

import asyncio
import random
import discord

from .constants import (
    ROOM_DESCRIPTIONS, CODE_LORE, DARK_ROOM_CHANCE,
    WEAPON_ITEMS, ALL_ITEMS, ITEM_EMOJI,
)


# ── Generátor mapy ────────────────────────────────────────────────────────────

def build_map(rows: int, cols: int) -> dict:
    """Vytvoří mřížku místností. Klíče: 'A1', 'A2', 'B1', ..."""
    rooms = {}
    labels_row = [chr(ord("A") + r) for r in range(rows)]

    for r, row_label in enumerate(labels_row):
        for c in range(1, cols + 1):
            room_id = f"{row_label}{c}"
            connections = []
            if r > 0:
                connections.append(f"{labels_row[r-1]}{c}")
            if r < rows - 1:
                connections.append(f"{labels_row[r+1]}{c}")
            if c > 1:
                connections.append(f"{row_label}{c-1}")
            if c < cols:
                connections.append(f"{row_label}{c+1}")

            rooms[room_id] = {
                "thread_id": None,
                "description": random.choice(ROOM_DESCRIPTIONS),
                "connections": connections,
                "players": [],
                "items": [],
                "code_number": None,
                "code_found": False,
                "bodies": [],
                "is_exit": False,
                "has_key": False,
                "last_round_players": [],
                "dark": False,
                "candle_lit": False,
                "trap": None,
                "vote_room": False,
                "chest": None,
                "ghost_arion": False,
                "custom_name": None,
            }
    return rooms


def scatter_items_and_codes(game: dict) -> None:
    """Rozmístí předměty, kódy, exit, hlasovací místnost, tmu po mapě."""
    room_ids = list(game["map"].keys())
    n_rooms = len(room_ids)
    start_room = room_ids[0]

    # ── Exit: vždy v rohu ──────────────────────────────────────────────────────
    rows_g = game.get("rows", 3)
    cols_g = game.get("cols", 3)
    row_labels = [chr(ord("A") + r) for r in range(rows_g)]
    corner_ids = {
        f"{row_labels[0]}1", f"{row_labels[0]}{cols_g}",
        f"{row_labels[-1]}1", f"{row_labels[-1]}{cols_g}",
    }
    exit_candidates = [r for r in room_ids if r != start_room and r in corner_ids]
    if not exit_candidates:
        exit_candidates = [r for r in room_ids if r != start_room]
    exit_room = random.choice(exit_candidates)
    game["map"][exit_room]["is_exit"] = True
    game["exit_room"] = exit_room

    # ── Hlasovací místnost ────────────────────────────────────────────────────
    vote_candidates = [r for r in room_ids if r not in (start_room, exit_room)]
    if vote_candidates:
        vote_room_id = random.choice(vote_candidates)
        game["map"][vote_room_id]["vote_room"] = True
        game["vote_room_id"] = vote_room_id

    # ── Kódy ─────────────────────────────────────────────────────────────────
    n_codes = max(4, n_rooms // 4)
    game["total_codes"] = n_codes
    code_pool = [r for r in room_ids if r != exit_room]
    code_rooms = random.sample(code_pool, min(n_codes, len(code_pool)))
    game["exit_code"] = []
    for room_id in code_rooms:
        num = random.randint(0, 9)
        game["map"][room_id]["code_number"] = num
        game["exit_code"].append(num)

    non_exit_rooms = [r for r in room_ids if r != exit_room]

    # ── Tmavé místnosti ───────────────────────────────────────────────────────
    code_room_ids = set(code_rooms)
    dark_candidates = [
        r for r in room_ids
        if r not in (start_room, exit_room) and r not in code_room_ids
    ]
    for room_id in dark_candidates:
        if random.random() < DARK_ROOM_CHANCE:
            game["map"][room_id]["dark"] = True

    # ── Běžné předměty (1-2 per místnost, bez kanystru) ──────────────────────
    common_items_all = ["baterka", "zapalovač", "svíčka"]
    for room_id in non_exit_rooms:
        count = 1 if game["map"][room_id].get("dark") else random.randint(1, 2)
        pool = common_items_all * 2
        random.shuffle(pool)
        seen: set[str] = set()
        items: list[str] = []
        for item in pool:
            if item not in seen and len(items) < count:
                seen.add(item)
                items.append(item)
        game["map"][room_id]["items"] = items

    # ── Vzácné zbraně ────────────────────────────────────────────────────────
    n_weapons = max(1, n_rooms // 3)
    weapon_candidates = [r for r in non_exit_rooms if not game["map"][r].get("dark")]
    if len(weapon_candidates) < n_weapons:
        weapon_candidates = list(non_exit_rooms)
    for room_id in random.sample(weapon_candidates, min(n_weapons, len(weapon_candidates))):
        weapon = random.choice(WEAPON_ITEMS)
        if weapon not in game["map"][room_id]["items"]:
            game["map"][room_id]["items"].append(weapon)

    # ── Kanystry: aspoň (hráčů + 3), max 12 ─────────────────────────────────
    n_players = len(game["players"])
    target_fuel = max(n_players + 3, min(n_rooms // 2 + 2, 12))
    spawned_fuel = sum(
        1 for r in game["map"].values()
        for i in r.get("items", []) if i == "kanystr"
    )
    extra_needed = max(0, target_fuel - spawned_fuel)
    if extra_needed > 0:
        fuel_candidates = [r for r in non_exit_rooms if not game["map"][r].get("dark")]
        if not fuel_candidates:
            fuel_candidates = list(non_exit_rooms)
        placed = 0
        attempts = 0
        cands = fuel_candidates[:]
        random.shuffle(cands)
        while placed < extra_needed and attempts < len(cands) * 2:
            room_id = cands[attempts % len(cands)]
            attempts += 1
            if "kanystr" not in game["map"][room_id]["items"]:
                game["map"][room_id]["items"].append("kanystr")
                placed += 1

    # ── Amulet Druhé Naděje (1-2 kusů, vzácný) ───────────────────────────────
    n_amulets = random.randint(1, 2)
    amulet_pool = [r for r in non_exit_rooms if not game["map"][r].get("dark")]
    if not amulet_pool:
        amulet_pool = list(non_exit_rooms)
    for room_id in random.sample(amulet_pool, min(n_amulets, len(amulet_pool))):
        game["map"][room_id]["items"].append("amulet")

    # ── Truhla (1 kus v libovolné ne-exitové místnosti) ──────────────────────
    chest_candidates = [r for r in non_exit_rooms if not game["map"][r].get("dark")]
    if not chest_candidates:
        chest_candidates = list(non_exit_rooms)
    if chest_candidates:
        chest_room = random.choice(chest_candidates)
        chest_weapon = random.choice(WEAPON_ITEMS)
        game["map"][chest_room]["chest"] = {
            "locked": True,
            "contents": ["kanystr", chest_weapon],
        }
        game["chest_room"] = chest_room

    # ── Duch Temné Arion (1 tmavá místnost) ──────────────────────────────────
    dark_rooms = [
        r for r in non_exit_rooms
        if r != start_room and game["map"][r].get("dark")
    ]
    if dark_rooms:
        ghost_room = random.choice(dark_rooms)
        game["map"][ghost_room]["ghost_arion"] = True
        game["ghost_arion_used"] = False


# ── Herní pomocné funkce ──────────────────────────────────────────────────────

def alive_players(game: dict) -> list[str]:
    return [uid for uid, p in game["players"].items() if p["alive"]]


def innocents_alive(game: dict) -> list[str]:
    murderer_uid = game.get("murderer_uid", "")
    return [
        uid for uid, p in game["players"].items()
        if p["alive"] and uid != murderer_uid
    ]


def room_of(game: dict, uid: str) -> str:
    return game["players"][uid]["room"]


def players_in_room(game: dict, room_id: str) -> list[str]:
    return game["map"][room_id]["players"]


def item_list_str(items: list[str]) -> str:
    if not items:
        return "žádné"
    return ", ".join(f"{ITEM_EMOJI.get(i, '?')} {i}" for i in items)


def room_direction(from_id: str, to_id: str) -> str:
    """Vrátí světovou stranu z from_id do to_id."""
    from_row = ord(from_id[0].upper()) - ord("A")
    from_col = int(from_id[1:]) - 1
    to_row   = ord(to_id[0].upper())   - ord("A")
    to_col   = int(to_id[1:])   - 1
    dr = to_row - from_row
    dc = to_col - from_col
    if abs(dr) >= abs(dc):
        return "jih" if dr > 0 else "sever"
    return "východ" if dc > 0 else "západ"


def check_win(game: dict) -> str | None:
    """Vrátí 'murderer', 'innocents', nebo None.

    Innocents win if murderer dies OR all innocents escaped/died and ≥1 escaped.
    Murderer wins if no innocent is alive, pending, or escaped.
    """
    murderer_uid = game.get("murderer_uid", "")
    murderer_alive = game["players"][murderer_uid]["alive"]

    if not murderer_alive:
        return "innocents"

    alive_inn = innocents_alive(game)
    pending_uids = {r["uid"] for r in game.get("pending_revivals", [])}
    pending_inn = [uid for uid in pending_uids if uid != murderer_uid]

    if not alive_inn and not pending_inn:
        escaped_inn = [
            uid for uid, p in game["players"].items()
            if uid != murderer_uid and p.get("escaped")
        ]
        return "innocents" if escaped_inn else "murderer"

    return None


def render_map(game: dict, current_room: str, hide_exit: bool = False) -> str:
    """Vykreslí ASCII mapu s hráčem označeným hvězdičkou."""
    rows = game.get("rows", 3)
    cols = game.get("cols", 3)
    row_labels = [chr(ord("A") + r) for r in range(rows)]
    lines = []
    for row_label in row_labels:
        row_cells = []
        for c in range(1, cols + 1):
            rid = f"{row_label}{c}"
            room = game["map"].get(rid, {})
            if rid == current_room:
                cell = "🔸"
            elif room.get("is_exit") and not hide_exit:
                cell = "🚪"
            elif room.get("dark") and not room.get("candle_lit"):
                cell = "🌑"
            elif room.get("vote_room"):
                cell = "🔴"
            else:
                n = len([u for u in room.get("players", []) if game["players"].get(u, {}).get("alive")])
                cell = f"[{n}]" if n > 0 else "[ ]"
            row_cells.append(cell)
        lines.append(" ".join(row_cells))
    return "\n".join(lines)


async def delete_after(msg: discord.Message, delay: float = 10.0) -> None:
    """Smaže zprávu po určité době."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass
