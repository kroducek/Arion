import discord
import asyncio
import logging
import random
from typing import Optional
from discord.ext import commands
from discord import app_commands, ui
from src.utils.paths import COMBAT_STATE
from src.utils.json_utils import load_json, save_json
from src.database.profiles import (
    load_items as _load_items_db,
    load_profiles as _load_profiles,
    profile_key as _pk,
    save_profiles as _save_profiles,
)
from src.logic.dice import DiceError, item_damage_expr, roll_expr

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

def _writeback_player_state(uid: int, carrier: dict, bs) -> None:
    """Hráči zapíše hp_cur + statusy zpět do profilu a ubere kolo jeho nátěrům."""
    try:
        profiles = _load_profiles()
        p = profiles.get(_pk(profiles, uid))
        if not p:
            return
        p["hp_cur"]   = max(0, min(carrier.get("hp", 0), p.get("hp_max", 50)))
        p["statuses"] = carrier.get("statuses", [])
        if bs:
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


def hp_line(name: str, old_hp: int, new_hp: int, max_hp: int,
            change_str: str, attacker: str | None = None) -> str:
    """Krátká jednořádková hláška o změně HP (místo velkého embedu)."""
    bar = _make_bar(new_hp, max_hp, 8)
    who = f"⚔️ {attacker} → " if attacker else ""
    dead = "  💀" if new_hp == 0 else ""
    return (f"{who}❤️ **{name}** `{old_hp}` → `{new_hp}/{max_hp}` {bar}"
            f"  *({change_str})*{dead}")


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


def reset_turn(combat: dict, actor: str, reaction: bool = False) -> None:
    """Konec tahu aktéra — akce zase k dispozici. Reakce jen na začátku kola."""
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
LOG_ICON = {"attack": "⚔️", "sethp": "🩹", "status": "🩸", "perk": "✨"}


def stat_snapshot(stat: dict) -> dict:
    """HP a furioka aktéra — podklad pro undo."""
    return {"hp": int(stat.get("hp", 0) or 0), "fur": int(stat.get("fur", 0) or 0)}


def log_event(combat: dict, kind: str, target: str, before: dict, after: dict,
              detail: str = "", actor: str | None = None) -> dict:
    """Zapíše změnu HP/FUR do logu boje. Vrací zapsaný záznam."""
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
    }
    combat["log_seq"] = event["id"]
    log = combat.setdefault("log", [])
    log.append(event)
    del log[:-LOG_LIMIT]
    return event


def undo_last(combat: dict) -> dict | None:
    """Vrátí poslední nezrušenou změnu HP/FUR zpět. None = není co vracet.

    Statusy ani spotřebovanou manu nevrací — ty řeší `/combat_effect clear`.
    """
    for event in reversed(combat.get("log", [])):
        if event.get("undone"):
            continue
        stat = combat.get("stats", {}).get(event["target"])
        if stat is None:
            continue
        stat["hp"] = event["before"].get("hp", stat.get("hp", 0))
        stat["fur"] = event["before"].get("fur", stat.get("fur", 0))
        event["undone"] = True
        return event
    return None


def format_log_event(event: dict) -> str:
    icon = LOG_ICON.get(event.get("kind", ""), "•")
    who = f"{event['actor']} → " if event.get("actor") else ""
    hp_from = event["before"].get("hp", 0)
    hp_to = event["after"].get("hp", 0)
    line = (f"`{event['id']:>2}` ⟳{event.get('round', 1)} {icon} {who}"
            f"**{event['target']}** {hp_from} → {hp_to} HP")
    if event.get("detail"):
        line += f" *({event['detail']})*"
    if event.get("undone"):
        line = f"~~{line}~~ ↩️"
    return line


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
        if self.channel_id not in self.cog.active_combats:
            return await interaction.response.send_message(
                "❌ *Combat byl ukončen.*", ephemeral=True
            )

        combat = self.cog.active_combats[self.channel_id]

        if not combat.get("locked"):
            return await interaction.response.send_message(
                "⚠️ *Combat ještě není uzavřen. Čekej na `/combat_setorder`.*",
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

        # Advance
        reset_turn(combat, current_actor)
        clear_buffs(combat, current_actor)
        combat["current_index"] = (combat["current_index"] + 1) % len(order)
        next_actor = order[combat["current_index"]]
        combat["active_player"] = next_actor

        # Nové kolo (pořadí se obtočilo) → auto-tick statusů (dmg z jedu/krvácení atd.)
        tick_note = ""
        if combat["current_index"] == 0:
            combat["round"] = int(combat.get("round", 1)) + 1
            reset_reactions(combat)
            if combat.get("auto_tick", True):
                tick_note = self.cog._tick_round(combat)
        self.cog._save_state()

        note = f"Tah předán — nyní hraje {next_actor}"
        if tick_note:
            note += f"\n\n{tick_note}"
        embed = _build_order_embed("⏭️  Další na řadě!", combat, note=note)
        view = EOTView(self.cog, self.channel_id)
        await interaction.response.send_message(embed=embed, view=view)


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
                description=f"# {roll}{crit}\n-# GM tě zařadí přes `/combat_setorder`.",
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
    """ID zbraní v rukou + zbylé zbraně z inventáře (pro autocomplete)."""
    out: list[str] = []
    equipment = profile.get("equipment", {}) or {}
    for slot in WEAPON_SLOTS:
        item_id = equipment.get(slot)
        if item_id and item_id not in out:
            out.append(item_id)
    for entry in _iter_entries(profile):
        item_id = entry.get("id")
        if entry.get("type") == "registered" and item_id and item_id not in out:
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
                 weapon_id: str | None, mana_cost: int = 0):
        super().__init__(timeout=600)
        self.cog = cog
        self.channel_id = channel_id
        self.attacker = attacker
        self.attacker_uid = attacker_uid
        self.target = target
        self.damage = damage
        self.weapon_id = weapon_id
        self.mana_cost = mana_cost
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

    # ── aplikace zásahu ──────────────────────────────────────────────────────

    async def resolve_hit(self, interaction: discord.Interaction, damage: int):
        combat = self.cog.active_combats.get(self.channel_id)
        if not combat or self.target not in combat["stats"]:
            return await interaction.response.send_message(
                "❌ *Cíl už není v boji.*", ephemeral=True)

        stat = combat["stats"][self.target]
        before = stat_snapshot(stat)
        result = apply_hit(stat, damage)
        max_hp = stat.get("max_hp", 0)
        log_event(combat, "attack", self.target, before, stat_snapshot(stat),
                  detail=result["change_str"], actor=self.attacker)

        notes = []
        bs = _bs()
        delivered = self.cog._consume_weapon(self.attacker_uid, self.weapon_id,
                                             self.mana_cost)
        if delivered.get("mana_note"):
            notes.append(delivered["mana_note"])
        if bs and delivered.get("statuses"):
            reg = bs.load_statuses()
            applied = []
            for status_id, source in delivered["statuses"]:
                inst = bs.apply_status(stat, status_id, source, reg)
                if inst:
                    sdef = reg.get(status_id, {})
                    applied.append(f"{sdef.get('emoji', '•')} {sdef.get('name', status_id)}")
            if applied:
                notes.append("Doručeno: " + " · ".join(applied))

        uid = _actor_uid(self.target)
        if uid is not None:
            if bs:
                _writeback_player_state(uid, stat, bs)
            else:
                _writeback_hp_to_profile(uid, stat["hp"])

        self.resolved = True
        self._disable()
        self.cog._save_state()

        line = hp_line(self.target, result["old_hp"], result["new_hp"], max_hp,
                       result["change_str"], attacker=self.attacker)
        if notes:
            line += "\n-# " + "  ·  ".join(notes)
        await interaction.response.edit_message(content=line, embed=None, view=self)

        if combat.get("boss", {}).get("name") == self.target:
            asyncio.create_task(self.cog._update_boss_bar(combat, flashing=True))

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
        self.resolved = True
        self._disable()
        await interaction.response.edit_message(
            content=f"🛡️ **{self.target}** uhnul útoku od {self.attacker} "
                    f"— *{self.damage} dmg se neaplikovalo.*",
            embed=None, view=self)

    @ui.button(label="Upravit", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: ui.Button):
        if not self._may_resolve(interaction):
            return await interaction.response.send_message(
                "❌ *Rozhodnout může GM, útočník nebo cíl.*", ephemeral=True)
        await interaction.response.send_modal(DamageModal(self, self.damage))

    @ui.button(label="Reakce (1d20)", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def reaction(self, interaction: discord.Interaction, button: ui.Button):
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
        await interaction.response.send_message(
            f"🎲 {actor} hází reakci (úhyb/check): **{roll}**\n"
            f"-# GM rozhodne tlačítkem ✅ / 🛡️.")


class CombatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_combats = self._load_state()

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_state(self):
        """Uloží stav boje (volají i jiné cogy, např. perky)."""
        self._save_state()

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

    def _tick_round(self, combat: dict) -> str:
        """Konec kola: u všech aktérů udělí dmg ze statusů a sníží trvání.

        Hráčům zapíše hp + statusy zpět do profilu a uberou kolo jejich nátěrům.
        Vrací shrnutí pro embed (prázdné, když se nic nestalo).
        """
        bs = _bs()
        if not bs:
            return ""
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
                lines.append(f"**{actor}**: " + " · ".join(log))
        if not lines:
            return ""
        return "🩸 **Konec kola — statusy:**\n" + "\n".join(lines)

    combat_effect = app_commands.Group(
        name="combat_effect", description="Statusy v boji — jed/krvácení atd. (DM).")

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
        inst = bs.apply_status(combat["stats"][target], status, source, reg)
        if not inst:
            return await interaction.response.send_message(f"❌ Status `{status}` neexistuje.", ephemeral=True)
        uid = _actor_uid(target)
        if uid is not None:
            _writeback_player_state(uid, combat["stats"][target], bs)
        self._save_state()
        sdef = reg.get(status, {})
        await interaction.response.send_message(
            f"{sdef.get('emoji','•')} **{sdef.get('name', status)}** přidán na **{target}** "
            f"(zdroj: {SOURCE_LABEL.get(source, source)}).")

    @combat_effect.command(name="clear", description="[DM] Vyléč statusy aktéra (dle typu).")
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
        if cure == "vse":
            removed = [s.get("status") for s in carrier.get("statuses", [])]
            carrier["statuses"] = []
        else:
            removed = bs.cure_statuses(carrier, cure)
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

    # ── /combat_start ─────────────────────────────────────────────────────────

    @app_commands.command(name="combat_start", description="Zahájí boj v této místnosti")
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
                "Hráči: `/combat_join` → hoď si iniciativu\n"
                "GM přidá NPC: `/combat_add_npc`\n"
                "GM uzavře pořadí: `/combat_setorder` *(seřadí dle iniciativy)*"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat_join ──────────────────────────────────────────────────────────

    @app_commands.command(name="combat_join", description="Hráč se zapojí do boje")
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

    # ── /combat_add_npc ───────────────────────────────────────────────────────

    @app_commands.command(name="combat_add_npc", description="GM přidá NPC/potvoru s HP, DEF a FUR")
    @app_commands.describe(
        name="Jméno NPC",
        hp="Maximum životů (výchozí: 100)",
        current_hp="Aktuální HP při vstupu — pokud nenastaveno, použije se max HP",
        defense="Obrana / DEF (výchozí: 0)",
        fury="Zuřivost / FUR (výchozí: 0)",
    )
    async def combat_add_npc(
        self,
        interaction: discord.Interaction,
        name: str,
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

        combat["order"].append(final_name)
        combat["stats"][final_name] = {
            "hp":     actual_current,
            "max_hp": hp,
            "def":    defense,
            "fur":    fury,
        }
        # NPC si hodí iniciativu automaticky (GM může přepsat /combat_setinit)
        npc_init = random.randint(1, 20)
        combat.setdefault("initiative", {})[final_name] = npc_init
        self._save_state()

        await self._send_order(
            interaction,
            f"💀  {final_name} vstupuje do boje!",
            note=f"NPC přidáno — HP {actual_current}/{hp}  DEF {defense}  FUR {fury}  🎲 init {npc_init}",
        )

    # ── /combat_add_player_stats ──────────────────────────────────────────────

    @app_commands.command(
        name="combat_add_player_stats",
        description="GM přidá HP/DEF/FUR hráči (např. pro tracking zranění)"
    )
    @app_commands.checks.has_permissions(administrator=True)
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

    # ── /combat_add_boss ──────────────────────────────────────────────────────

    @app_commands.command(name="combat_add_boss", description="GM přidá bosse s odděleným boss barem")
    @app_commands.describe(
        name="Jméno bosse",
        hp="Maximum životů (výchozí: 200)",
        defense="DEF (výchozí: 0)",
        fury="FUR (výchozí: 0)",
    )
    async def combat_add_boss(
        self,
        interaction: discord.Interaction,
        name: str,
        hp: int = 200,
        defense: int = 0,
        fury: int = 0,
    ):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        if combat.get("boss"):
            return await interaction.response.send_message(
                "⚠️ *V tomto combatu už boss je. Nejdřív ho odeber přes `/combat_remove`.*",
                ephemeral=True,
            )

        name = name.strip()
        if not name:
            return await interaction.response.send_message(
                "⚠️ *Jméno bosse nesmí být prázdné.*", ephemeral=True
            )

        combat["order"].append(name)
        combat["stats"][name] = {"hp": hp, "max_hp": hp, "def": defense, "fur": fury}

        await interaction.response.defer()

        boss_msg = await interaction.channel.send(embed=_boss_embed(name, combat["stats"][name]))

        combat["boss"] = {
            "name":       name,
            "message_id": boss_msg.id,
            "channel_id": channel_id,
        }
        self._save_state()

        await interaction.followup.send(
            f"☠️ *Boss **{name}** vstoupil do boje!*  ❤️ `{hp}` HP  🛡️ `{defense}` DEF  🔥 `{fury}` FUR"
        )

    # ── /combat_sethp ─────────────────────────────────────────────────────────

    @app_commands.command(name="combat_sethp", description="Admin: nastaví HP NPC/hráči během combatu")
    @app_commands.checks.has_permissions(administrator=True)
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
                "NPC: `/combat_add_npc`  |  Hráč: `/combat_add_player_stats` nebo `/combat_join`",
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

        # Krátká hláška (default) — plný přehled je na /combat_status.
        if not combat.get("verbose"):
            line = hp_line(name, old_hp, new_hp, max_hp, change_str, attacker=utocnik)
            await interaction.response.send_message(line)
            if combat.get("boss", {}).get("name") == name:
                asyncio.create_task(self._update_boss_bar(combat, flashing=(hp < 0)))
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
                + ("\n\n💀 *HP dosáhlo nuly! Zvaž `/combat_remove`.*" if dead else "")
            ),
            color=discord.Color.red() if dead else color,
        )
        await interaction.response.send_message(embed=embed)

        is_boss = combat.get("boss", {}).get("name") == name
        if is_boss:
            asyncio.create_task(self._update_boss_bar(combat, flashing=(hp < 0)))

    # ── /combat_setdef ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_setdef", description="Admin: nastaví DEF NPC/hráči")
    @app_commands.checks.has_permissions(administrator=True)
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
        stats[name]["def"] = max(0, defense)
        self._save_state()

        embed = discord.Embed(
            title=f"🛡️  DEF upraveno — {name}",
            description=f"*{old_def} → **{stats[name]['def']}***",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat_setfur ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_setfur", description="Admin: nastaví FUR (zuřivost) NPC/hráči")
    @app_commands.checks.has_permissions(administrator=True)
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
        stats[name]["fur"] = max(0, fury)
        self._save_state()

        embed = discord.Embed(
            title=f"🔥  FUR upraveno — {name}",
            description=f"*{old_fur} → **{stats[name]['fur']}***",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /combat_setinit ───────────────────────────────────────────────────────

    @app_commands.command(name="combat_setinit", description="Admin: nastaví iniciativu aktérovi")
    @app_commands.checks.has_permissions(administrator=True)
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

    # ── /combat_remove ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_remove", description="Odebere někoho z pořadí")
    async def combat_remove(self, interaction: discord.Interaction, name: str):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]
        order  = combat["order"]

        to_remove = next((item for item in order if name in item), None)
        if not to_remove:
            return await interaction.response.send_message(
                f"⚠️ *`{name}` nebyl v pořadí nalezen.*", ephemeral=True
            )

        removed_idx = order.index(to_remove)
        order.remove(to_remove)
        combat["stats"].pop(to_remove, None)
        combat.get("initiative", {}).pop(to_remove, None)

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

    # ── /combat_setorder ──────────────────────────────────────────────────────

    @app_commands.command(
        name="combat_setorder",
        description="Uzavře pořadí do pevné smyčky a spustí combat"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def combat_setorder(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.active_combats or not self.active_combats[channel_id]["order"]:
            return await interaction.response.send_message(
                "⚠️ *Seznam je prázdný.*", ephemeral=True
            )

        combat = self.active_combats[channel_id]

        # Seřaď pořadí podle hozené iniciativy (nejvyšší jde první).
        # Kdo nehodil, spadne na konec (init −1) — GM může dohodit /combat_remove.
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

    # ── /combat_end ───────────────────────────────────────────────────────────

    @app_commands.command(name="combat_end", description="Ukončí combat a vymaže data")
    async def combat_end(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id in self.active_combats:
            del self.active_combats[channel_id]
            self._save_state()
            embed = discord.Embed(
                title="🏁  Combat ukončen",
                description="*Boj skončil. Data byla vymazána.*",
                color=discord.Color.greyple(),
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(
                "⚠️ *Žádný aktivní boj.*", ephemeral=True
            )

    # ── /attack ───────────────────────────────────────────────────────────────

    def _consume_weapon(self, uid: int | None, weapon_id: str | None,
                        mana_cost: int = 0, runes_active: bool = True) -> dict:
        """Při potvrzeném zásahu: doručené statusy, úbytek nátěru a many."""
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
            if entry is not None and bs:
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

    @app_commands.command(
        name="attack",
        description="Útok zbraní — hodí damage a nabídne potvrzení zásahu.")
    @app_commands.describe(
        cil="Koho útočíš (aktér v boji).",
        zbran="Zbraň (výchozí: co máš v ruce).",
        akce="Útok nebo bonusový útok (dual wielding).",
        bonus="Ruční bonus k poškození (perky, situace).",
        force="[GM] Ignoruj pojistku na už použitou akci.",
    )
    @app_commands.choices(akce=[
        app_commands.Choice(name="útok",          value="attack"),
        app_commands.Choice(name="bonusový útok", value="bonus"),
    ])
    @app_commands.autocomplete(cil=_ac_actor, zbran=_ac_weapon)
    async def attack(
        self,
        interaction: discord.Interaction,
        cil: str,
        zbran: Optional[str] = None,
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
            return await interaction.response.send_message(
                "❌ *Nemáš v ruce zbraň — vyber ji parametrem `zbran`.*", ephemeral=True)

        db_item = items_db.get(weapon_id) or {}
        expr = item_damage_expr(db_item)
        if not expr:
            return await interaction.response.send_message(
                f"❌ **{db_item.get('name', weapon_id)}** nemá damage ani `atk`. "
                f"Doplň ho: `/inv-db combat {weapon_id} dmg:1d8`.", ephemeral=True)
        try:
            roll = roll_expr(expr)
        except DiceError:
            return await interaction.response.send_message(
                f"❌ *Damage `{expr}` nejde hodit — oprav item `{weapon_id}`.*", ephemeral=True)

        buffs = take_attack_buffs(combat, actor)
        buff_total = 0
        buff_lines = []
        for buff in buffs:
            try:
                buff_roll = roll_expr(str(buff.get("dmg") or "0"))
            except DiceError:
                continue
            buff_total += buff_roll.total
            buff_lines.append(f"✨ {buff['name']}: `{buff['dmg']}` → **+{buff_roll.total}**")

        damage = max(0, roll.total + int(bonus) + buff_total)

        # ── Runy: použití stojí manu; když nestačí, runa neprocne ─────────────
        entry = _weapon_entry(profile, weapon_id)
        bs = _bs()
        runes_reg = bs.load_runes() if bs else {}
        rune_text = _rune_names(entry, runes_reg) if entry else ""
        mana_cost = int(db_item.get("mana_cost", 0) or 0)
        runes_active = True
        mana_note = ""
        if mana_cost and (entry and entry.get("runes")):
            mana_cur = profile.get("mana_cur", profile.get("mana_max", 20))
            if mana_cur < mana_cost:
                runes_active = False
                mana_cost = 0
                mana_note = f"🔷 *Málo many ({mana_cur}/{db_item['mana_cost']}) — runa neprocne.*"
        else:
            mana_cost = 0

        bonus_str = f" {'+' if bonus >= 0 else '−'}{abs(int(bonus))}" if bonus else ""
        desc = (f"**{db_item.get('name', weapon_id)}** — `{expr}`{bonus_str}\n"
                f"{roll.detail}  →  **{damage} dmg**")
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

        view = AttackView(self, interaction.channel_id, actor,
                          interaction.user.id, cil, damage, weapon_id, mana_cost)

        if combat.get("auto_apply"):
            stat = combat["stats"][cil]
            before = stat_snapshot(stat)
            result = apply_hit(stat, damage)
            log_event(combat, "attack", cil, before, stat_snapshot(stat),
                      detail=result["change_str"], actor=actor)
            delivered = self._consume_weapon(interaction.user.id, weapon_id,
                                             mana_cost, runes_active)
            if bs and delivered["statuses"]:
                reg = bs.load_statuses()
                for status_id, source in delivered["statuses"]:
                    bs.apply_status(stat, status_id, source, reg)
            uid = _actor_uid(cil)
            if uid is not None:
                if bs:
                    _writeback_player_state(uid, stat, bs)
                else:
                    _writeback_hp_to_profile(uid, stat["hp"])
            self._save_state()
            line = hp_line(cil, result["old_hp"], result["new_hp"],
                           stat.get("max_hp", 0), result["change_str"], attacker=actor)
            await interaction.response.send_message(f"{desc}\n{line}")
            if combat.get("boss", {}).get("name") == cil:
                asyncio.create_task(self._update_boss_bar(combat, flashing=True))
            return

        self._save_state()
        await interaction.response.send_message(embed=embed, view=view)

    # ── /combat_log a /combat_undo ────────────────────────────────────

    @app_commands.command(
        name="combat_log",
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
        embed.set_footer(text="Poslední změnu vrátíš přes /combat_undo")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="combat_undo",
        description="[GM] Vrátí poslední změnu HP zpět.")
    @app_commands.checks.has_permissions(administrator=True)
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
        uid = _actor_uid(target)
        if uid is not None:
            _writeback_hp_to_profile(uid, stat["hp"])
        self._save_state()

        await interaction.response.send_message(
            f"↩️ Vráceno: **{target}** {event['after'].get('hp', 0)} → "
            f"`{stat['hp']}/{stat.get('max_hp', 0)}` HP"
            f"  *({event.get('detail') or event.get('kind', '')})*")
        if combat.get("boss", {}).get("name") == target:
            asyncio.create_task(self._update_boss_bar(combat))

    @app_commands.command(
        name="combat_autoapply",
        description="[GM] Aplikovat damage z /attack rovnou, bez potvrzení.")
    @app_commands.checks.has_permissions(administrator=True)
    async def combat_autoapply(self, interaction: discord.Interaction, zapnuto: bool):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        combat["auto_apply"] = zapnuto
        self._save_state()
        await interaction.response.send_message(
            f"⚙️ Auto-aplikace útoků: **{'zapnuta' if zapnuto else 'vypnuta'}**.")

    @app_commands.command(
        name="combat_verbose",
        description="[GM] Dlouhé embedy místo krátkých hlášek při úpravě HP.")
    @app_commands.checks.has_permissions(administrator=True)
    async def combat_verbose(self, interaction: discord.Interaction, zapnuto: bool):
        combat = self.active_combats.get(interaction.channel_id)
        if not combat:
            return await interaction.response.send_message(
                "❌ *Zde neběží combat.*", ephemeral=True)
        combat["verbose"] = zapnuto
        self._save_state()
        await interaction.response.send_message(
            f"⚙️ Dlouhé HP embedy: **{'zapnuty' if zapnuto else 'vypnuty'}**.")

    # ── /combat_status ────────────────────────────────────────────────────────

    @app_commands.command(name="combat_status", description="Zobrazí aktuální pořadí a stats")
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