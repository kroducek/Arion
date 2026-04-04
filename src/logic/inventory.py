import re
import discord
import logging
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.utils.paths import PROFILES as PROFILES_FILE, ITEMS as ITEMS_FILE
from src.utils.json_utils import load_json, save_json

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACE
# ══════════════════════════════════════════════════════════════════════════════

EQUIPMENT_SLOTS = [
    "hand_l", "hand_r",
    "helmet", "armor", "boots", "cloak", "belt",
    "ring_1", "ring_2",
    "amulet_1", "amulet_2",
]

SLOT_LABELS = {
    "hand_l":   "Zbraň L",
    "hand_r":   "Zbraň P",
    "helmet":   "Helma",
    "armor":    "Zbroj",
    "boots":    "Boty",
    "cloak":    "Plášť",
    "belt":     "Opasek",
    "ring_1":   "Prsten 1",
    "ring_2":   "Prsten 2",
    "amulet_1": "Amulet 1",
    "amulet_2": "Amulet 2",
}

SLOT_EMOJIS = {
    "hand_l":   "🗡️",
    "hand_r":   "🗡️",
    "helmet":   "🪖",
    "armor":    "🛡️",
    "boots":    "👢",
    "cloak":    "🧥",
    "belt":     "🪢",
    "ring_1":   "💍",
    "ring_2":   "💍",
    "amulet_1": "📿",
    "amulet_2": "📿",
}

CATEGORIES = [
    "dýky", "jednoruční", "obouruční", "luky_kuše",
    "střelné", "náboje", "hůlky_hole",
    "runy_krystaly", "svitky", "speciální",
    "brnění", "amulety", "prsteny", "pásky",
    "jídlo", "lektvary", "unikátní", "ostatní",
]

# Sloty které zabírá full_set item
FULL_SET_SLOTS = ["helmet", "armor", "boots", "cloak", "belt"]

# Mapování require klíčů Vlivu na pole profilu
VLIV_REQUIRES = {
    "TEMNOTA":   "vliv_temnota",
    "SVETLO":    "vliv_svetlo",
    "ROVNOVAHA": "vliv_rovnovaha",
}

# Kategorie dostupné v /use
USE_CATEGORIES = ["jídlo", "lektvary", "svitky", "ostatní"]

DM_ROLE_NAME = "DM"
EMBED_COLOR  = 0x2b2d31
PAGE_SIZE    = 15

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load_profiles() -> dict:
    return load_json(PROFILES_FILE, default={})

def _save_profiles(data: dict) -> None:
    save_json(PROFILES_FILE, data)

def _load_items() -> dict:
    return load_json(ITEMS_FILE, default={})

def _save_items(data: dict) -> None:
    save_json(ITEMS_FILE, data)

def _get_profile(uid: int) -> dict | None:
    return _load_profiles().get(str(uid))

def _default_equipment() -> dict:
    return {slot: None for slot in EQUIPMENT_SLOTS}

def _ensure_inv_fields(profile: dict) -> dict:
    """Zajistí že profil má všechna potřebná pole inventáře."""
    profile.setdefault("inventory", [])
    profile.setdefault("notes", [])
    profile.setdefault("equipment", {})
    profile.setdefault("ring_slots", 2)
    profile.setdefault("amulet_slots", 2)
    # Zajisti že všechny sloty existují (i v případě starého/částečného profilu)
    for s in ["hand_l", "hand_r", "helmet", "armor", "boots", "cloak", "belt"]:
        profile["equipment"].setdefault(s, None)
    for i in range(1, profile["ring_slots"] + 1):
        profile["equipment"].setdefault(f"ring_{i}", None)
    for i in range(1, profile["amulet_slots"] + 1):
        profile["equipment"].setdefault(f"amulet_{i}", None)
    # Vitální pole — nutná pro /use efekty
    profile.setdefault("hp_max",     50)
    profile.setdefault("hp_cur",     profile.get("hp_max", 50))
    profile.setdefault("hunger_max", 10)
    profile.setdefault("hunger_cur", profile.get("hunger_max", 10))
    profile.setdefault("mana_max",   5)
    profile.setdefault("mana_cur",   0)
    profile.setdefault("fury_max",   0)
    profile.setdefault("fury_cur",   0)
    return profile

# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _parse_requires(raw: str) -> dict[str, int]:
    """Parsuje string 'STR:2 INS:1 CHA:3' na dict {stat: hodnota}."""
    result = {}
    for part in raw.replace(",", " ").split():
        if ":" in part:
            k, _, v = part.partition(":")
            try:
                result[k.upper()] = int(v)
            except ValueError:
                pass
    return result

def _find_inv_entry(inventory: list, item_key: str) -> dict | None:
    """Najde položku v inventáři dle ID (registrovaný) nebo jména (volný — legacy)."""
    key = item_key.lower()
    for entry in inventory:
        if entry["type"] == "registered" and entry["id"].lower() == key:
            return entry
        if entry["type"] == "free" and entry.get("name", "").lower() == key:
            return entry
    return None

def _add_to_inventory(inventory: list, item_id: str, qty: int) -> None:
    """Přidá nebo navýší registrovaný item v inventáři."""
    entry = _find_inv_entry(inventory, item_id)
    if entry and entry["type"] == "registered":
        entry["qty"] = entry.get("qty", 1) + qty
    else:
        inventory.append({"type": "registered", "id": item_id, "qty": qty})

def _remove_from_inventory(inventory: list, item_key: str, qty: int) -> bool:
    """Odebere qty kusů. Vrátí True pokud se povedlo."""
    entry = _find_inv_entry(inventory, item_key)
    if not entry or entry.get("qty", 1) < qty:
        return False
    entry["qty"] -= qty
    if entry["qty"] <= 0:
        inventory.remove(entry)
    return True

def _item_display_name(entry: dict, items_db: dict) -> str:
    if entry["type"] == "registered":
        db_item = items_db.get(entry["id"])
        return db_item["name"] if db_item else f"[{entry['id']}]"
    return entry.get("name", "?")

def _parse_modifiers(db_item: dict) -> str:
    """Vrátí inline modifikátory z DMG řádku jako emoji string: '💧4', '🔥5', '🧪3' atd."""
    desc = db_item.get("desc", "")
    dmg_line = ""
    for line in desc.split("\n"):
        if line.upper().startswith("DMG:"):
            dmg_line = line
            break
    if not dmg_line:
        return ""
    parts = []
    m = re.search(r"krv[aá]cení\s*\(1d(\d+)", dmg_line, re.IGNORECASE)
    if m:
        parts.append(f"🩸{m.group(1)}")
    elif re.search(r"krv[aá]cení", dmg_line, re.IGNORECASE):
        parts.append("🩸")
    m = re.search(r"1d(\d+)\s*(?:burn|fire)", dmg_line, re.IGNORECASE)
    if m:
        parts.append(f"🔥{m.group(1)}")
    m = re.search(r"otráv[eě]n[íi]\s*\(1d(\d+)", dmg_line, re.IGNORECASE)
    if m:
        parts.append(f"🧪{m.group(1)}")
    return " ".join(parts)

def _active_ring_slots(profile: dict) -> list[str]:
    return [f"ring_{i+1}" for i in range(profile.get("ring_slots", 2))]

def _active_amulet_slots(profile: dict) -> list[str]:
    return [f"amulet_{i+1}" for i in range(profile.get("amulet_slots", 2))]

def _active_slots(profile: dict) -> list[str]:
    base = ["hand_l", "hand_r", "helmet", "armor", "boots", "cloak", "belt"]
    return base + _active_ring_slots(profile) + _active_amulet_slots(profile)

# ══════════════════════════════════════════════════════════════════════════════
# EQUIPMENT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _format_bonus(bonus: dict) -> str:
    """Vrátí lidsky čitelný popis equip_bonus pro zprávu. Prázdný string pokud žádný."""
    if not bonus:
        return ""
    parts = []
    for key, val in bonus.items():
        sign = "+" if val >= 0 else ""
        if key.startswith("vliv_"):
            label = key.replace("vliv_", "").capitalize()
            parts.append(f"{sign}{val} {label}")
        elif key == "mana_max":
            parts.append(f"{sign}{val} 🔷 max mana")
        elif key == "hp_max":
            parts.append(f"{sign}{val} ❤️ max HP")
        elif key == "hunger_max":
            parts.append(f"{sign}{val} 🍖 max hlad")
        else:
            parts.append(f"{sign}{val} {key}")
    return "  ·  ".join(parts)


def _recalc_fury_from_vliv(profile: dict) -> None:
    """Přepočítá fury_max podle celkového Vlivu (1 Vliv = 5 fury_max)."""
    total   = (profile.get("vliv_svetlo", 0)
               + profile.get("vliv_temnota", 0)
               + profile.get("vliv_rovnovaha", 0))
    new_max = total * 5
    old_max = profile.get("fury_max", 0)
    delta   = new_max - old_max
    profile["fury_max"] = new_max
    profile["fury_cur"] = max(0, min(new_max, profile.get("fury_cur", 0) + delta))


def _apply_equip_bonus(profile: dict, bonus: dict) -> None:
    """Aplikuje equip_bonus na profil (při equipu)."""
    if not bonus:
        return
    vliv_changed = False
    stats = profile.setdefault("stats", {})
    for key, val in bonus.items():
        if key.startswith("vliv_"):
            profile[key] = profile.get(key, 0) + val
            vliv_changed = True
        elif key in ("mana_max", "hp_max", "hunger_max"):
            profile[key] = profile.get(key, 0) + val
        else:
            stats[key] = stats.get(key, 0) + val
    if vliv_changed:
        _recalc_fury_from_vliv(profile)


def _remove_equip_bonus(profile: dict, bonus: dict) -> None:
    """Odstraní equip_bonus z profilu (při unequipu)."""
    if not bonus:
        return
    vliv_changed = False
    stats = profile.setdefault("stats", {})
    for key, val in bonus.items():
        if key.startswith("vliv_"):
            profile[key] = max(0, profile.get(key, 0) - val)
            vliv_changed = True
        elif key in ("mana_max", "hp_max", "hunger_max"):
            profile[key] = max(0, profile.get(key, 0) - val)
        else:
            stats[key] = max(0, stats.get(key, 0) - val)
    if vliv_changed:
        _recalc_fury_from_vliv(profile)


def _equip_item(profile: dict, item_id: str, preferred_slot: str | None,
                items_db: dict) -> tuple[bool, str]:
    _ensure_inv_fields(profile)
    db_item = items_db.get(item_id)
    if not db_item:
        return False, f"Item `{item_id}` není v databázi."

    slot_target = db_item.get("slot")
    if not slot_target:
        return False, f"**{db_item['name']}** nelze equipnout."
    # Backwards-compat: "weapon" byl legacy slot value, normalizuj na "hand_l"
    if slot_target == "weapon":
        slot_target = "hand_l"

    inventory = profile["inventory"]
    equipment = profile["equipment"]

    entry = _find_inv_entry(inventory, item_id)
    if not entry:
        return False, f"**{db_item['name']}** nemáš v inventáři."

    # ── Kontrola požadavků (včetně Vlivu) ────────────────────────────────────
    requires     = db_item.get("requires", {})
    player_stats = profile.get("stats", {})
    failed = []
    for stat, needed in requires.items():
        if stat in VLIV_REQUIRES:
            have = profile.get(VLIV_REQUIRES[stat], 0)
        else:
            have = player_stats.get(stat, 0)
        if have < needed:
            failed.append((stat, needed, have))
    if failed:
        reqs = ", ".join(f"**{stat}** {needed} (máš {have})" for stat, needed, have in failed)
        return False, f"**{db_item['name']}** — nesplněné požadavky: {reqs}."

    hand_type   = db_item.get("hand_type")
    equip_bonus = db_item.get("equip_bonus", {})

    # ── Full set ──────────────────────────────────────────────────────────────
    if slot_target == "full_set":
        freed = []
        seen  = set()
        for s in FULL_SET_SLOTS:
            old = equipment.get(s)
            if old and old not in seen:
                _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
                _add_to_inventory(inventory, old, 1)
                freed.append(old)
                seen.add(old)
            equipment[s] = item_id
        _remove_from_inventory(inventory, item_id, 1)
        _apply_equip_bonus(profile, equip_bonus)
        msg = f"Equipoval jsi **{db_item['name']}** (full set)."
        if freed:
            freed_names = [items_db[i]["name"] if i in items_db else i for i in freed]
            msg += f"\nUvolněno: {', '.join(freed_names)} → vráceno do inventáře."
        bonus_str = _format_bonus(equip_bonus)
        if bonus_str:
            msg += f"\n✨ Bonus: {bonus_str}"
        return True, msg

    # ── Obouruční zbraň ───────────────────────────────────────────────────────
    if slot_target == "hand_l" and hand_type == "two":
        freed = []
        seen  = set()
        for s in ("hand_l", "hand_r"):
            old = equipment.get(s)
            if old and old not in seen:
                _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
                _add_to_inventory(inventory, old, 1)
                freed.append(old)
                seen.add(old)
            equipment[s] = None
        equipment["hand_l"] = item_id
        equipment["hand_r"] = item_id  # marker — oba ukazují na stejný item
        _remove_from_inventory(inventory, item_id, 1)
        _apply_equip_bonus(profile, equip_bonus)
        msg = f"Equipoval jsi **{db_item['name']}** (obouruční)."
        if freed:
            freed_names = [items_db[i]["name"] if i in items_db else i for i in freed]
            msg += f"\nUvolněno: {', '.join(freed_names)} → vráceno do inventáře."
        bonus_str = _format_bonus(equip_bonus)
        if bonus_str:
            msg += f"\n✨ Bonus: {bonus_str}"
        return True, msg

    # ── Jednoruční zbraň ──────────────────────────────────────────────────────
    if slot_target == "hand_l" and hand_type == "one":
        if preferred_slot in ("hand_l", "hand_r"):
            target_slot = preferred_slot
        else:
            target_slot = next(
                (s for s in ("hand_l", "hand_r") if not equipment.get(s)),
                "hand_l"
            )
        old = equipment.get(target_slot)
        freed_msg = ""
        if old:
            if equipment.get("hand_l") == equipment.get("hand_r") == old:
                equipment["hand_l"] = None
                equipment["hand_r"] = None
            _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
            _add_to_inventory(inventory, old, 1)
            old_name  = items_db[old]["name"] if old in items_db else old
            freed_msg = f"\nUvolněno: {old_name} → vráceno do inventáře."
        equipment[target_slot] = item_id
        _remove_from_inventory(inventory, item_id, 1)
        _apply_equip_bonus(profile, equip_bonus)
        slot_label = SLOT_LABELS.get(target_slot, target_slot)
        bonus_str  = _format_bonus(equip_bonus)
        bonus_line = f"\n✨ Bonus: {bonus_str}" if bonus_str else ""
        return True, f"Equipoval jsi **{db_item['name']}** do slotu **{slot_label}**.{freed_msg}{bonus_line}"

    # ── Prsteny / amulety ─────────────────────────────────────────────────────
    if slot_target in ("ring", "amulet"):
        active = _active_ring_slots(profile) if slot_target == "ring" else _active_amulet_slots(profile)
        if preferred_slot and preferred_slot in active:
            target_slot = preferred_slot
        else:
            target_slot = next((s for s in active if not equipment.get(s)), active[0])
    else:
        # Přímý slot (helmet, armor, boots, cloak, belt, hand_l bez hand_type)
        target_slot = slot_target
        if target_slot not in profile["equipment"]:
            return False, f"Slot `{target_slot}` neexistuje."

    old = equipment.get(target_slot)
    freed_msg = ""
    if old:
        _remove_equip_bonus(profile, items_db.get(old, {}).get("equip_bonus", {}))
        _add_to_inventory(inventory, old, 1)
        old_name  = items_db[old]["name"] if old in items_db else old
        freed_msg = f"\nUvolněno: {old_name} → vráceno do inventáře."

    equipment[target_slot] = item_id
    _remove_from_inventory(inventory, item_id, 1)
    _apply_equip_bonus(profile, equip_bonus)
    slot_label = SLOT_LABELS.get(target_slot, target_slot)
    bonus_str  = _format_bonus(equip_bonus)
    bonus_line = f"\n✨ Bonus: {bonus_str}" if bonus_str else ""
    return True, f"Equipoval jsi **{db_item['name']}** ({slot_label}).{freed_msg}{bonus_line}"


def _unequip_slot(profile: dict, slot: str, items_db: dict) -> tuple[bool, str]:
    _ensure_inv_fields(profile)
    equipment = profile["equipment"]
    item_id   = equipment.get(slot)

    if not item_id:
        return False, f"Slot **{SLOT_LABELS.get(slot, slot)}** je prázdný."

    db_item     = items_db.get(item_id, {})
    name        = db_item.get("name", item_id)
    hand_type   = db_item.get("hand_type")
    slot_type   = db_item.get("slot")
    equip_bonus = db_item.get("equip_bonus", {})

    _remove_equip_bonus(profile, equip_bonus)

    if slot_type == "full_set":
        for s in FULL_SET_SLOTS:
            if equipment.get(s) == item_id:
                equipment[s] = None
    elif hand_type == "two" and slot in ("hand_l", "hand_r"):
        equipment["hand_l"] = None
        equipment["hand_r"] = None
    else:
        equipment[slot] = None

    _add_to_inventory(profile["inventory"], item_id, 1)
    return True, f"Sundal jsi **{name}** → vráceno do inventáře."

# ══════════════════════════════════════════════════════════════════════════════
# EMBED BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_inv_embed(profile: dict, member: discord.Member,
                     items_db: dict, page: int = 0) -> tuple[discord.Embed, int]:
    _ensure_inv_fields(profile)
    equipment = profile["equipment"]
    inventory = profile["inventory"]
    notes     = profile.get("notes", [])

    embed = discord.Embed(color=EMBED_COLOR)
    embed.set_author(name=f"{member.display_name} — Inventář",
                     icon_url=member.display_avatar.url)

    # ── Equipment sekce ───────────────────────────────────────────────────────
    equip_lines = []
    total_def   = 0
    seen_items  = set()
    for slot in _active_slots(profile):
        label   = SLOT_LABELS.get(slot, slot)
        emoji   = SLOT_EMOJIS.get(slot, "▪️")
        item_id = equipment.get(slot)
        if not item_id:
            equip_lines.append(f"{emoji} **{label}**  —")
        else:
            if slot == "hand_r" and equipment.get("hand_l") == item_id:
                continue
            db_item = items_db.get(item_id) or {}
            name    = db_item.get("name", f"[{item_id}]")
            suffix  = "  *(obouruční)*" if db_item.get("hand_type") == "two" else ""
            def_val = db_item.get("def", 0)
            atk_val = db_item.get("atk", 0)
            mods    = _parse_modifiers(db_item)
            stat_str = ""
            if atk_val: stat_str += f"  ⚔️{atk_val}"
            if mods:    stat_str += f"  {mods}"
            if def_val: stat_str += f"  🛡️{def_val}"
            if item_id not in seen_items:
                total_def += def_val
                seen_items.add(item_id)
            equip_lines.append(f"{emoji} **{label}**  {name}{suffix}{stat_str}")

    totals_str = f"  ·  🛡️ DEF celkem: **{total_def}**" if total_def else ""
    embed.add_field(
        name=f"⚔️  Equipment{totals_str}",
        value="\n".join(equip_lines) or "—",
        inline=False,
    )

    # ── Inventář sekce ────────────────────────────────────────────────────────
    total = len(inventory)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page  = max(0, min(page, pages - 1))
    chunk = inventory[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    if not inventory:
        inv_text = "*Inventář je prázdný.*"
    else:
        lines = []
        for entry in chunk:
            name    = _item_display_name(entry, items_db)
            qty     = entry.get("qty", 1)
            qty_str = f"  ×{qty}" if qty > 1 else ""
            tags   = []
            combat = ""
            if entry["type"] == "registered":
                db_item = items_db.get(entry["id"], {})
                if db_item.get("atk"):    combat += f"  ⚔️{db_item['atk']}"
                mods = _parse_modifiers(db_item)
                if mods:                  combat += f"  {mods}"
                if db_item.get("def"):    combat += f"  🛡️{db_item['def']}"
                if db_item.get("consumable"): tags.append("consumable")
            tag_str = f"  *{', '.join(tags)}*" if tags else ""
            lines.append(f"**{name}**{qty_str}{combat}{tag_str}")
        inv_text = "\n".join(lines)

    footer_page = f"  ·  strana {page+1}/{pages}" if pages > 1 else ""
    embed.add_field(
        name=f"📦  Inventář  ({total} položek){footer_page}",
        value=inv_text,
        inline=False,
    )

    # ── Ostatní / poznámky ────────────────────────────────────────────────────
    if notes:
        note_lines = [f"{i+1}. {text}" for i, text in enumerate(notes)]
        embed.add_field(
            name="📝  Ostatní",
            value="\n".join(note_lines),
            inline=False,
        )

    return embed, pages


def _build_inspect_embed(item_id: str, items_db: dict,
                         profile: dict | None = None) -> discord.Embed | None:
    item = items_db.get(item_id)
    if not item:
        return None

    hand_label = {"one": "Jednoruční", "two": "Obouruční"}.get(item.get("hand_type", ""), "")
    slot_label = SLOT_LABELS.get(item.get("slot", ""), item.get("slot", ""))

    tags = []
    if hand_label:
        tags.append(hand_label)
    if item.get("atk"):             tags.append(f"⚔️ ATK {item['atk']}")
    if item.get("def"):             tags.append(f"🛡️ DEF {item['def']}")
    if item.get("hunger_restore"):  tags.append(f"🍖 +{item['hunger_restore']} hlad")
    if item.get("hp_restore"):      tags.append(f"❤️ +{item['hp_restore']} HP")
    if item.get("mana_restore"):    tags.append(f"🔷 +{item['mana_restore']} mana")
    if item.get("mana_cost"):       tags.append(f"🔷 -{item['mana_cost']} mana (cena)")
    if item.get("consumable"):      tags.append("consumable")
    if item.get("stackable"):       tags.append("stackable")

    desc_parts = []
    if item.get("category"):
        desc_parts.append(f"-# {item['category']}")
    if tags:
        desc_parts.append(f"-# {' · '.join(tags)}")
    if item.get("desc"):
        desc_parts.append(f"\n{item['desc']}")

    # ── Požadavky ─────────────────────────────────────────────────────────────
    requires = item.get("requires", {})
    if requires:
        player_stats = profile.get("stats", {}) if profile else {}
        req_lines = []
        for stat, needed in requires.items():
            have = player_stats.get(stat, 0)
            icon = "✅" if have >= needed else "❌"
            line = f"{icon} **{stat}** {needed}"
            if profile:
                line += f"  *(máš {have})*"
            req_lines.append(line)
        desc_parts.append("\n**Požadavky:**\n" + "\n".join(req_lines))

    embed = discord.Embed(
        title=item["name"],
        description="\n".join(desc_parts) if desc_parts else "—",
        color=EMBED_COLOR,
    )
    embed.set_footer(text=f"ID: {item_id}  ·  slot: {slot_label or '—'}")
    return embed

# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

# ══════════════════════════════════════════════════════════════════════════════
# AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

async def _ac_database_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    cur = current.lower()
    return [
        app_commands.Choice(name=v["name"], value=k)
        for k, v in items_db.items()
        if cur in k.lower() or cur in v["name"].lower()
    ][:25]


async def _ac_inventory_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur     = current.lower()
    choices = []
    for entry in profile["inventory"]:
        name = _item_display_name(entry, items_db)
        key  = entry["id"] if entry["type"] == "registered" else entry.get("name", "")
        if cur in name.lower() or cur in key.lower():
            choices.append(app_commands.Choice(name=name, value=key))
    return choices[:25]


async def _ac_equipped_slot(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    profile = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    equipment = profile["equipment"]
    cur       = current.lower()
    choices   = []
    seen      = set()
    for slot in _active_slots(profile):
        item_id = equipment.get(slot)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        label = SLOT_LABELS.get(slot, slot)
        if cur in label.lower() or cur in slot.lower():
            choices.append(app_commands.Choice(name=label, value=slot))
    return choices[:25]


async def _ac_equippable_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur     = current.lower()
    choices = []
    for entry in profile["inventory"]:
        if entry["type"] != "registered":
            continue
        db_item = items_db.get(entry["id"])
        if not db_item or not db_item.get("slot"):
            continue
        name = db_item["name"]
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(name=name, value=entry["id"]))
    return choices[:25]


async def _ac_consumable_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur     = current.lower()
    choices = []
    for entry in profile["inventory"]:
        if entry["type"] != "registered":
            continue
        db_item = items_db.get(entry["id"])
        if not db_item or not db_item.get("consumable"):
            continue
        name = db_item["name"]
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(name=name, value=entry["id"]))
    return choices[:25]

async def _ac_use_item(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete pro /use — filtruje consumable itemy, volitelně podle kategorie."""
    items_db  = _load_items()
    profile   = _get_profile(interaction.user.id)
    if not profile:
        return []
    _ensure_inv_fields(profile)
    cur      = current.lower()
    kategorie = getattr(interaction.namespace, "kategorie", None)

    # "ostatní" = vše consumable co není jídlo/lektvary/svitky
    _other = {"jídlo", "lektvary", "svitky"}

    choices = []
    for entry in profile["inventory"]:
        if entry["type"] != "registered":
            continue
        db_item = items_db.get(entry["id"])
        if not db_item or not db_item.get("consumable"):
            continue
        cat = db_item.get("category", "")
        if kategorie and kategorie != "ostatní" and cat != kategorie:
            continue
        if kategorie == "ostatní" and cat in _other:
            continue
        name = db_item["name"]
        if cur in name.lower() or cur in entry["id"].lower():
            choices.append(app_commands.Choice(name=name, value=entry["id"]))
    return choices[:25]


async def _ac_equip_slot(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Kontextový autocomplete pro slot v /equip — závisí na zvoleném itemu."""
    items_db = _load_items()
    profile  = _get_profile(interaction.user.id)
    item_id  = getattr(interaction.namespace, "item", None)

    db_item = items_db.get(item_id) if item_id else None
    if not db_item:
        return []

    slot_target = db_item.get("slot")
    if not slot_target:
        return []

    equipment = {}
    if profile:
        _ensure_inv_fields(profile)
        equipment = profile["equipment"]

    cur = current.lower()

    def _slot_choice(slot_key: str) -> app_commands.Choice[str]:
        label    = SLOT_LABELS.get(slot_key, slot_key)
        occupied = equipment.get(slot_key)
        if occupied:
            occ_name = items_db.get(occupied, {}).get("name", occupied)
            display  = f"{label}  [{occ_name}]"
        else:
            display  = f"{label}  [volný]"
        return app_commands.Choice(name=display, value=slot_key)

    choices = []
    if slot_target == "weapon":
        for s in ("hand_l", "hand_r"):
            if not cur or cur in SLOT_LABELS[s].lower() or cur in s:
                choices.append(_slot_choice(s))

    elif slot_target == "ring":
        active = _active_ring_slots(profile) if profile else ["ring_1", "ring_2"]
        for s in active:
            if not cur or cur in SLOT_LABELS.get(s, s).lower() or cur in s:
                choices.append(_slot_choice(s))

    elif slot_target == "amulet":
        active = _active_amulet_slots(profile) if profile else ["amulet_1", "amulet_2"]
        for s in active:
            if not cur or cur in SLOT_LABELS.get(s, s).lower() or cur in s:
                choices.append(_slot_choice(s))

    else:
        # Přímý slot (helmet, armor, boots, cloak, belt) — jen jeden, ale ukáž ho
        choices.append(_slot_choice(slot_target))

    return choices[:25]

# ══════════════════════════════════════════════════════════════════════════════
# STRÁNKOVÁNÍ VIEW
# ══════════════════════════════════════════════════════════════════════════════

class InvPageView(discord.ui.View):
    def __init__(self, profile: dict, member: discord.Member,
                 items_db: dict, pages: int):
        super().__init__(timeout=120)
        self.profile  = profile
        self.member   = member
        self.items_db = items_db
        self.pages    = pages
        self.page     = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.pages - 1

    async def _refresh(self, interaction: discord.Interaction):
        profiles = _load_profiles()
        profile  = profiles.get(str(self.member.id))
        if profile:
            _ensure_inv_fields(profile)
            self.profile = profile
        embed, pages = _build_inv_embed(self.profile, self.member, self.items_db, self.page)
        self.pages = pages
        self._update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        self.page -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        self.page += 1
        await self._refresh(interaction)

# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /inv ──────────────────────────────────────────────────────────────────
    @app_commands.command(name="inv", description="Zobrazí inventář, equipment a poznámky.")
    @app_commands.describe(member="Hráč (výchozí: ty).")
    async def inv(self, interaction: discord.Interaction,
                  member: Optional[discord.Member] = None):
        await interaction.response.defer()
        target  = member or interaction.user
        profile = _get_profile(target.id)
        if not profile:
            await interaction.followup.send(
                f"❌ **{target.display_name}** nemá profil.", ephemeral=True)
            return
        _ensure_inv_fields(profile)
        items_db     = _load_items()
        embed, pages = _build_inv_embed(profile, target, items_db)
        if pages > 1:
            view = InvPageView(profile, target, items_db, pages)
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed)

    # ── /inv-note ─────────────────────────────────────────────────────────────
    @app_commands.command(name="inv-note",
                          description="Přidá poznámku do sekce Ostatní (věci mimo databázi).")
    @app_commands.describe(text="Text poznámky — předmět, nález, informace...")
    async def inv_note(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil. Nejdřív `/start`.")
            return
        _ensure_inv_fields(profile)
        profile["notes"].append(text)
        line_num = len(profile["notes"])
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Přidáno jako řádek **{line_num}**: *{text}*")

    # ── /inv-note-edit ────────────────────────────────────────────────────────
    @app_commands.command(name="inv-note-edit",
                          description="Upraví poznámku v sekci Ostatní dle čísla řádku.")
    @app_commands.describe(
        cislo="Číslo řádku (viz /inv → Ostatní).",
        text="Nový text.",
    )
    async def inv_note_edit(self, interaction: discord.Interaction,
                            cislo: int, text: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        notes = profile["notes"]
        if cislo < 1 or cislo > len(notes):
            await interaction.followup.send(
                f"❌ Řádek {cislo} neexistuje. Máš {len(notes)} poznámek.")
            return
        old          = notes[cislo - 1]
        notes[cislo - 1] = text
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Řádek **{cislo}** upraven.\n~~{old}~~ → *{text}*")

    # ── /inv-note-remove ──────────────────────────────────────────────────────
    @app_commands.command(name="inv-note-remove",
                          description="Odebere poznámku z Ostatní dle čísla řádku.")
    @app_commands.describe(cislo="Číslo řádku (viz /inv → Ostatní).")
    async def inv_note_remove(self, interaction: discord.Interaction, cislo: int):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        notes = profile["notes"]
        if cislo < 1 or cislo > len(notes):
            await interaction.followup.send(
                f"❌ Řádek {cislo} neexistuje. Máš {len(notes)} poznámek.")
            return
        removed = notes.pop(cislo - 1)
        _save_profiles(profiles)
        await interaction.followup.send(f"✅ Odebráno řádek **{cislo}**: ~~{removed}~~")

    # ── /inv-remove ───────────────────────────────────────────────────────────
    @app_commands.command(name="inv-remove",
                          description="Odebere registrovaný item z vlastního inventáře.")
    @app_commands.describe(
        item="Název nebo ID itemu.",
        qty="Množství (výchozí: 1).",
    )
    @app_commands.autocomplete(item=_ac_inventory_item)
    async def inv_remove(self, interaction: discord.Interaction,
                         item: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        ok = _remove_from_inventory(profile["inventory"], item, qty)
        if not ok:
            await interaction.followup.send(
                f"❌ Nemáš dost kusů **{item}** v inventáři.")
            return
        _save_profiles(profiles)
        await interaction.followup.send(f"✅ Odebráno: **{item}** ×{qty}.")

    # ── /inv-give ─────────────────────────────────────────────────────────────
    @app_commands.command(name="inv-give", description="Pošle registrovaný item jinému hráči.")
    @app_commands.describe(
        member="Příjemce.",
        item="Název nebo ID itemu.",
        qty="Množství (výchozí: 1).",
    )
    @app_commands.autocomplete(item=_ac_inventory_item)
    async def inv_give(self, interaction: discord.Interaction,
                       member: discord.Member, item: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if member.id == interaction.user.id:
            await interaction.followup.send("❌ Nemůžeš posílat sám sobě.")
            return
        profiles = _load_profiles()
        giver_p  = profiles.get(str(interaction.user.id))
        recvr_p  = profiles.get(str(member.id))
        if not giver_p:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        if not recvr_p:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(giver_p)
        _ensure_inv_fields(recvr_p)
        items_db = _load_items()

        entry = _find_inv_entry(giver_p["inventory"], item)
        if not entry:
            await interaction.followup.send(f"❌ **{item}** nemáš v inventáři.")
            return

        ok = _remove_from_inventory(giver_p["inventory"], item, qty)
        if not ok:
            await interaction.followup.send(f"❌ Nemáš dost kusů **{item}**.")
            return

        name = _item_display_name(entry, items_db)
        if entry["type"] == "registered":
            _add_to_inventory(recvr_p["inventory"], entry["id"], qty)
        else:
            # Legacy volný item — přidej jako poznámku
            for _ in range(qty):
                recvr_p["notes"].append(entry.get("name", item))

        _save_profiles(profiles)
        qty_str = f" ×{qty}" if qty > 1 else ""
        await interaction.followup.send(
            f"✅ Předal jsi **{name}**{qty_str} → **{member.display_name}**.")

    # ── /inv-use ──────────────────────────────────────────────────────────────
    @app_commands.command(name="inv-use", description="Použije consumable item.")
    @app_commands.describe(item="Consumable item z inventáře.")
    @app_commands.autocomplete(item=_ac_consumable_item)
    async def inv_use(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer()
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.", ephemeral=True)
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        db_item  = items_db.get(item)
        if not db_item:
            await interaction.followup.send(
                "❌ Tento item není v databázi.", ephemeral=True)
            return
        if not db_item.get("consumable"):
            await interaction.followup.send(
                f"❌ **{db_item['name']}** není consumable.", ephemeral=True)
            return
        entry = _find_inv_entry(profile["inventory"], item)
        if not entry:
            await interaction.followup.send(
                f"❌ **{db_item['name']}** nemáš v inventáři.", ephemeral=True)
            return

        # ── Zkontroluj mana_cost před použitím ───────────────────────────────
        mana_cost = db_item.get("mana_cost", 0)
        if mana_cost:
            mana_cur = profile.get("mana_cur", profile.get("mana_max", 20))
            if mana_cur < mana_cost:
                await interaction.followup.send(
                    f"❌ Nemáš dost many. Potřebuješ **{mana_cost}** 🔷, máš **{mana_cur}**.",
                    ephemeral=True,
                )
                return

        _remove_from_inventory(profile["inventory"], item, 1)

        # ── Aplikuj efekty ────────────────────────────────────────────────────
        effects = []

        if mana_cost:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            new = max(0, cur - mana_cost)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (-{mana_cost})")

        hunger_restore = db_item.get("hunger_restore", 0)
        if hunger_restore:
            cur = profile.get("hunger_cur", 0)
            máx = profile.get("hunger_max", 10)
            new = min(cur + hunger_restore, máx)
            profile["hunger_cur"] = new
            effects.append(f"🍖 Hlad `{cur}` → `{new}` (+{new - cur})")

        hp_restore = db_item.get("hp_restore", 0)
        if hp_restore:
            cur = profile.get("hp_cur", 0)
            máx = profile.get("hp_max", 50)
            new = min(cur + hp_restore, máx)
            profile["hp_cur"] = new
            effects.append(f"❤️ HP `{cur}` → `{new}` (+{new - cur})")

        mana_restore = db_item.get("mana_restore", 0)
        if mana_restore:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            máx = profile.get("mana_max", 20)
            new = min(cur + mana_restore, máx)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (+{new - cur})")

        _save_profiles(profiles)

        effect_str = "\n".join(effects) if effects else ""
        use_text = db_item.get("lore_drop") or db_item.get("desc", "…")
        embed = discord.Embed(
            title=f"✨ {db_item['name']}",
            description=f"*{use_text}*" + (f"\n\n{effect_str}" if effect_str else ""),
            color=0xf0a500,
        )
        embed.set_footer(text=f"{interaction.user.display_name}  ·  item použit a odebrán")
        await interaction.followup.send(embed=embed)

    # ── /use ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="use", description="Použij consumable item ze svého inventáře.")
    @app_commands.describe(
        kategorie="Filtruj typ itemu (výchozí: vše).",
        item="Item k použití.",
    )
    @app_commands.choices(kategorie=[
        app_commands.Choice(name=c, value=c) for c in USE_CATEGORIES
    ])
    @app_commands.autocomplete(item=_ac_use_item)
    async def use_cmd(
        self,
        interaction: discord.Interaction,
        item: str,
        kategorie: Optional[app_commands.Choice[str]] = None,
    ):
        """Stejná logika jako /inv-use, ale s filtrovaným autocomplete."""
        await interaction.response.defer()
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.", ephemeral=True)
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        db_item  = items_db.get(item)
        if not db_item:
            await interaction.followup.send("❌ Tento item není v databázi.", ephemeral=True)
            return
        if not db_item.get("consumable"):
            await interaction.followup.send(
                f"❌ **{db_item['name']}** není consumable.", ephemeral=True)
            return
        entry = _find_inv_entry(profile["inventory"], item)
        if not entry:
            await interaction.followup.send(
                f"❌ **{db_item['name']}** nemáš v inventáři.", ephemeral=True)
            return

        mana_cost = db_item.get("mana_cost", 0)
        if mana_cost:
            mana_cur = profile.get("mana_cur", profile.get("mana_max", 20))
            if mana_cur < mana_cost:
                await interaction.followup.send(
                    f"❌ Nemáš dost many. Potřebuješ **{mana_cost}** 🔷, máš **{mana_cur}**.",
                    ephemeral=True,
                )
                return

        _remove_from_inventory(profile["inventory"], item, 1)
        effects = []

        if mana_cost:
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            new = max(0, cur - mana_cost)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (-{mana_cost})")

        if db_item.get("hunger_restore", 0):
            cur = profile.get("hunger_cur", 0)
            máx = profile.get("hunger_max", 10)
            new = min(cur + db_item["hunger_restore"], máx)
            profile["hunger_cur"] = new
            effects.append(f"🍖 Hlad `{cur}` → `{new}` (+{new - cur})")

        if db_item.get("hp_restore", 0):
            cur = profile.get("hp_cur", 0)
            máx = profile.get("hp_max", 50)
            new = min(cur + db_item["hp_restore"], máx)
            profile["hp_cur"] = new
            effects.append(f"❤️ HP `{cur}` → `{new}` (+{new - cur})")

        if db_item.get("mana_restore", 0):
            cur = profile.get("mana_cur", profile.get("mana_max", 20))
            máx = profile.get("mana_max", 20)
            new = min(cur + db_item["mana_restore"], máx)
            profile["mana_cur"] = new
            effects.append(f"🔷 Mana `{cur}` → `{new}` (+{new - cur})")

        _save_profiles(profiles)
        effect_str = "\n".join(effects) if effects else ""
        use_text = db_item.get("lore_drop") or db_item.get("desc", "…")
        embed = discord.Embed(
            title=f"✨ {db_item['name']}",
            description=f"*{use_text}*" + (f"\n\n{effect_str}" if effect_str else ""),
            color=0xf0a500,
        )
        embed.set_footer(text=f"{interaction.user.display_name}  ·  item použit a odebrán")
        await interaction.followup.send(embed=embed)

    # ── /inv-inspect ──────────────────────────────────────────────────────────
    @app_commands.command(name="inv-inspect",
                          description="Zobrazí detail registrovaného itemu.")
    @app_commands.describe(item="ID nebo název itemu.")
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_inspect(self, interaction: discord.Interaction, item: str):
        await interaction.response.defer(ephemeral=True)
        items_db = _load_items()
        profile  = _get_profile(interaction.user.id)
        embed    = _build_inspect_embed(item, items_db, profile)
        if not embed:
            await interaction.followup.send(
                f"❌ Item `{item}` není v databázi.")
            return
        await interaction.followup.send(embed=embed)

    # ── /equip ────────────────────────────────────────────────────────────────
    @app_commands.command(name="equip", description="Equipne item ze svého inventáře.")
    @app_commands.describe(
        item="Item k equipnutí.",
        slot="Slot (volitelné — pro prsteny/amulety/zbraně).",
    )
    @app_commands.autocomplete(item=_ac_equippable_item, slot=_ac_equip_slot)
    async def equip(self, interaction: discord.Interaction,
                    item: str, slot: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        items_db = _load_items()
        ok, msg  = _equip_item(profile, item, slot, items_db)
        if ok:
            _save_profiles(profiles)
        await interaction.followup.send(f"{'✅' if ok else '❌'} {msg}")

    # ── /unequip ──────────────────────────────────────────────────────────────
    @app_commands.command(name="unequip", description="Sundá item ze slotu.")
    @app_commands.describe(slot="Slot k uvolnění.")
    @app_commands.autocomplete(slot=_ac_equipped_slot)
    async def unequip(self, interaction: discord.Interaction, slot: str):
        await interaction.response.defer(ephemeral=True)
        profiles = _load_profiles()
        profile  = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil.")
            return
        _ensure_inv_fields(profile)
        if slot not in profile["equipment"]:
            await interaction.followup.send(
                f"❌ Slot `{slot}` neexistuje nebo není aktivní.")
            return
        items_db = _load_items()
        ok, msg  = _unequip_slot(profile, slot, items_db)
        if ok:
            _save_profiles(profiles)
        await interaction.followup.send(f"{'✅' if ok else '❌'} {msg}")

    # ══════════════════════════════════════════════════════════════════════════
    # DATABASE COMMANDY (DM only)
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="inv-db-add", description="[DM] Přidá item do databáze.")
    @app_commands.describe(
        item_id="Konzolové ID (snake_case, např. mec_ocisty).",
        name="Zobrazované jméno.",
        category="Kategorie itemu.",
        slot="Kam lze equipnout (prázdné = nelze).",
        hand_type="Jednoruční / obouruční (jen pro zbraně).",
        atk="Útočná hodnota (např. 12).",
        defense="Obranná hodnota (např. 3).",
        hunger_restore="Kolik hladu obnoví při použití.",
        hp_restore="Kolik HP obnoví při použití (lektvary života).",
        mana_restore="Kolik many obnoví při použití (lektvary many).",
        mana_cost="Kolik many spotřebuje při použití (svitky, kouzla).",
        requires="Požadavky na staty (např. STR:2 INS:1 CHA:3).",
        stackable="Lze stackovat (výchozí: False).",
        consumable="Po použití se zničí (výchozí: False).",
        hp_bonus="Bonus k max HP při equipu (trvalý dokud equipnuto).",
        mana_bonus="Bonus k max maně při equipu (trvalý dokud equipnuto).",
        stat_bonus="Bonusy ke statům při equipu, např. STR:3 DEX:1 (0 = odebrat).",
        desc="Popis, lore, perky — volný text.",
        lore_drop="Narativní hláška zobrazená při použití itemu (místo desc).",
    )
    @app_commands.choices(
        category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES],
        slot=[
            app_commands.Choice(name="Zbraň",  value="weapon"),
            app_commands.Choice(name="Helma",  value="helmet"),
            app_commands.Choice(name="Zbroj",  value="armor"),
            app_commands.Choice(name="Boty",   value="boots"),
            app_commands.Choice(name="Plášť",  value="cloak"),
            app_commands.Choice(name="Opasek", value="belt"),
            app_commands.Choice(name="Prsten", value="ring"),
            app_commands.Choice(name="Amulet", value="amulet"),
            app_commands.Choice(name="—",      value="none"),
        ],
        hand_type=[
            app_commands.Choice(name="Jednoruční", value="one"),
            app_commands.Choice(name="Obouruční",  value="two"),
        ],
    )
    async def inv_db_add(
        self, interaction: discord.Interaction,
        item_id: str, name: str, category: str,
        slot: str = "none", hand_type: Optional[str] = None,
        atk: int = 0, defense: int = 0,
        hunger_restore: int = 0, hp_restore: int = 0,
        mana_restore: int = 0, mana_cost: int = 0,
        requires: Optional[str] = None,
        stackable: bool = False, consumable: bool = False,
        hp_bonus: Optional[int] = None, mana_bonus: Optional[int] = None,
        stat_bonus: Optional[str] = None,
        desc: Optional[str] = None,
        lore_drop: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM může spravovat databázi.")
            return
        item_id  = item_id.lower().replace(" ", "_")
        items_db = _load_items()
        if item_id in items_db:
            await interaction.followup.send(
                f"❌ Item `{item_id}` již existuje. Použij `/inv-db-edit`.")
            return
        # "weapon" je display alias pro "hand_l" — normalizuj před uložením
        resolved_slot = None if slot == "none" else ("hand_l" if slot == "weapon" else slot)
        item: dict = {
            "name":       name,
            "category":   category,
            "slot":       resolved_slot,
            "stackable":  stackable,
            "consumable": consumable,
        }
        if hand_type:          item["hand_type"]      = hand_type
        if atk > 0:            item["atk"]            = atk
        if defense > 0:        item["def"]            = defense
        if hunger_restore > 0: item["hunger_restore"] = hunger_restore
        if hp_restore > 0:     item["hp_restore"]     = hp_restore
        if mana_restore > 0:   item["mana_restore"]   = mana_restore
        if mana_cost > 0:      item["mana_cost"]      = mana_cost
        if desc:               item["desc"]           = desc
        if lore_drop:          item["lore_drop"]      = lore_drop
        if requires:
            req_dict = _parse_requires(requires)
            if req_dict:       item["requires"]       = req_dict
        equip_bonus: dict = {}
        if hp_bonus:   equip_bonus["hp_max"]   = hp_bonus
        if mana_bonus: equip_bonus["mana_max"] = mana_bonus
        if stat_bonus:
            for k, v in _parse_requires(stat_bonus).items():
                if v != 0:
                    equip_bonus[k] = v
        if equip_bonus: item["equip_bonus"] = equip_bonus
        items_db[item_id] = item
        _save_items(items_db)
        await interaction.followup.send(
            f"✅ Item **{name}** (`{item_id}`) přidán do databáze.")

    @app_commands.command(name="inv-db-edit",
                          description="[DM] Upraví existující item v databázi.")
    @app_commands.describe(
        item_id="ID itemu k úpravě.",
        name="Nové jméno (prázdné = beze změny).",
        desc="Nový popis (prázdné = beze změny).",
        atk="Nová útočná hodnota (0 = odebrat).",
        defense="Nová obranná hodnota (0 = odebrat).",
        hunger_restore="Obnova hladu při použití (0 = odebrat).",
        hp_restore="Obnova HP při použití (0 = odebrat).",
        mana_restore="Obnova many při použití (0 = odebrat).",
        mana_cost="Cena v maně při použití (0 = odebrat).",
        requires="Nové požadavky (např. STR:2 INS:1 · prázdné = beze změny).",
        consumable="Změnit consumable příznak.",
        stackable="Změnit stackable příznak.",
        hp_bonus="Bonus k max HP při equipu (0 = odebrat).",
        mana_bonus="Bonus k max maně při equipu (0 = odebrat).",
        stat_bonus="Bonusy ke statům při equipu, např. STR:3 DEX:1 (stat:0 = odebrat).",
        lore_drop="Narativní hláška při použití (prázdné = beze změny · 'clear' = odebrat).",
    )
    @app_commands.autocomplete(item_id=_ac_database_item)
    async def inv_db_edit(
        self, interaction: discord.Interaction,
        item_id: str,
        name: Optional[str] = None,
        desc: Optional[str] = None,
        lore_drop: Optional[str] = None,
        atk: Optional[int] = None,
        defense: Optional[int] = None,
        hunger_restore: Optional[int] = None,
        hp_restore: Optional[int] = None,
        mana_restore: Optional[int] = None,
        mana_cost: Optional[int] = None,
        requires: Optional[str] = None,
        consumable: Optional[bool] = None,
        stackable: Optional[bool] = None,
        hp_bonus: Optional[int] = None,
        mana_bonus: Optional[int] = None,
        stat_bonus: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM může spravovat databázi.")
            return
        items_db = _load_items()
        item     = items_db.get(item_id)
        if not item:
            await interaction.followup.send(f"❌ Item `{item_id}` neexistuje.")
            return
        if name       is not None: item["name"]       = name
        if desc       is not None: item["desc"]       = desc
        if lore_drop  is not None:
            if lore_drop.lower() == "clear": item.pop("lore_drop", None)
            else:                            item["lore_drop"] = lore_drop
        if consumable is not None: item["consumable"] = consumable
        if stackable  is not None: item["stackable"]  = stackable
        if atk is not None:
            if atk > 0:  item["atk"] = atk
            else:        item.pop("atk", None)
        if defense is not None:
            if defense > 0: item["def"] = defense
            else:           item.pop("def", None)

        for key, val in [
            ("hunger_restore", hunger_restore),
            ("hp_restore",     hp_restore),
            ("mana_restore",   mana_restore),
            ("mana_cost",      mana_cost),
        ]:
            if val is not None:
                if val > 0: item[key] = val
                else:       item.pop(key, None)

        if requires is not None:
            req_dict = _parse_requires(requires)
            if req_dict: item["requires"] = req_dict
            else:        item.pop("requires", None)
        if hp_bonus is not None or mana_bonus is not None or stat_bonus is not None:
            eb = item.setdefault("equip_bonus", {})
            if hp_bonus is not None:
                if hp_bonus != 0: eb["hp_max"]   = hp_bonus
                else:             eb.pop("hp_max", None)
            if mana_bonus is not None:
                if mana_bonus != 0: eb["mana_max"] = mana_bonus
                else:               eb.pop("mana_max", None)
            if stat_bonus is not None:
                for k, v in _parse_requires(stat_bonus).items():
                    if v != 0: eb[k]         = v
                    else:      eb.pop(k, None)
            if not eb:
                item.pop("equip_bonus", None)
        _save_items(items_db)
        await interaction.followup.send(
            f"✅ Item **{item['name']}** (`{item_id}`) upraven.")

    @app_commands.command(name="inv-db-find", description="Prohledá databázi itemů.")
    @app_commands.describe(query="Název nebo ID itemu.")
    @app_commands.autocomplete(query=_ac_database_item)
    async def inv_db_find(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)
        items_db = _load_items()
        profile  = _get_profile(interaction.user.id)
        embed    = _build_inspect_embed(query, items_db, profile)
        if not embed:
            await interaction.followup.send(f"❌ Item `{query}` není v databázi.")
            return
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="inv-db-list",
                          description="Vypíše všechny itemy v databázi.")
    @app_commands.describe(category="Filtr dle kategorie (volitelné).")
    @app_commands.choices(category=[
        app_commands.Choice(name=c, value=c) for c in CATEGORIES
    ])
    async def inv_db_list(self, interaction: discord.Interaction,
                          category: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        items_db = _load_items()
        filtered = {
            k: v for k, v in items_db.items()
            if not category or v.get("category") == category
        }
        if not filtered:
            await interaction.followup.send("Žádné itemy v databázi.")
            return

        by_cat: dict[str, list] = {}
        for k, v in filtered.items():
            cat = v.get("category", "ostatní")
            by_cat.setdefault(cat, []).append((k, v))

        embed = discord.Embed(title="📖  Databáze itemů", color=EMBED_COLOR)
        for cat, items in by_cat.items():
            lines = []
            for iid, iv in items:
                tags = []
                if iv.get("consumable"): tags.append("consumable")
                if iv.get("stackable"):  tags.append("stackable")
                tag_str = f"  *{', '.join(tags)}*" if tags else ""
                lines.append(f"**{iv['name']}**  `{iid}`{tag_str}")
            embed.add_field(name=cat, value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # ADMIN COMMANDY (DM only)
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="inv-admin-add", description="[DM] Přidá item hráči.")
    @app_commands.describe(
        member="Hráč.",
        item="ID registrovaného itemu nebo volný text (půjde do Ostatní).",
        qty="Množství.",
        note="Přepíše text poznámky pro volné itemy.",
    )
    @app_commands.autocomplete(item=_ac_database_item)
    async def inv_admin_add(self, interaction: discord.Interaction,
                            member: discord.Member, item: str,
                            qty: int = 1, note: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        items_db  = _load_items()
        if item in items_db:
            name = items_db[item]["name"]
            _add_to_inventory(profile["inventory"], item, qty)
        else:
            # Volný item → do sekce Ostatní jako poznámka
            name     = note or item
            for _ in range(qty):
                profile["notes"].append(name)
        _save_profiles(profiles)
        qty_str = f" ×{qty}" if qty > 1 else ""
        await interaction.followup.send(
            f"✅ Přidáno **{name}**{qty_str} → **{member.display_name}**.")

    @app_commands.command(name="inv-admin-remove",
                          description="[DM] Odebere registrovaný item hráči.")
    @app_commands.describe(member="Hráč.", item="Název nebo ID.", qty="Množství.")
    async def inv_admin_remove(self, interaction: discord.Interaction,
                               member: discord.Member, item: str, qty: int = 1):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        ok = _remove_from_inventory(profile["inventory"], item, qty)
        if not ok:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá dost kusů **{item}**.")
            return
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ Odebráno **{item}** ×{qty} od **{member.display_name}**.")

    @app_commands.command(name="inv-admin-slots",
                          description="[DM] Nastaví počet ring/amulet slotů hráči.")
    @app_commands.describe(
        member="Hráč.",
        slot_type="ring nebo amulet.",
        count="Počet slotů (1–6).",
    )
    @app_commands.choices(slot_type=[
        app_commands.Choice(name="Prsteny", value="ring"),
        app_commands.Choice(name="Amulety", value="amulet"),
    ])
    async def inv_admin_slots(self, interaction: discord.Interaction,
                              member: discord.Member, slot_type: str, count: int):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        if count < 1 or count > 6:
            await interaction.followup.send("❌ Počet slotů musí být 1–6.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá profil.")
            return
        _ensure_inv_fields(profile)
        key   = f"{slot_type}_slots"
        label = "prsten" if slot_type == "ring" else "amulet"
        profile[key] = count
        for i in range(1, count + 1):
            profile["equipment"].setdefault(f"{slot_type}_{i}", None)
        _save_profiles(profiles)
        await interaction.followup.send(
            f"✅ **{member.display_name}** má teď {count}× {label} slot.")


async def setup(bot):
    await bot.add_cog(Inventory(bot))
