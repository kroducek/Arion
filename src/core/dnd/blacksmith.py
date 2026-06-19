"""
Blacksmith / Status & Rune systém — Aurionis

Tři vrstvy:
  1) REGISTR STATUSŮ (statuses.json) — co status JE. Sdílený pro runy, nátěry,
     prostředí i schopnosti. Status nese kind (fyzický/magický), cure (čím se
     sundá), dmg (kostky), duration (kola) a tick (kdy dmg padá).
  2) DORUČENÍ — jak se status na cíl dostane: runa (trvale na zbrani), nátěr
     (dočasně na zbrani: 3 zásahy NEBO 2 kola), prostředí, schopnost.
  3) AKTIVNÍ STATUS na postavě — zapsaný na "nositeli" (profil hráče nebo
     combat-stat NPC) jako {status, zdroj, kol_zbyva, dmg}.

Combat integrace: combat.py si přes tick_statuses() nechá spočítat dmg na konci
kola a odečte ho z HP (auto-tick je default). Léčení sundává statusy dle cure.
"""
import os
import re
import random
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.paths import PROFILES as PROFILES_FILE
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger(__name__)

RUNE_COLOR   = 0x5b8cb0
STATUS_COLOR = 0x9b59b6
DM_ROLE_NAME = "DM"
MAX_RUNES_PER_ITEM = 3

# Datové soubory drž vedle profiles.json (žádný nový path konstant netřeba)
_DATA_DIR     = os.path.dirname(PROFILES_FILE)
STATUSES_FILE = os.path.join(_DATA_DIR, "statuses.json")
RUNES_FILE    = os.path.join(_DATA_DIR, "runes.json")

KINDS   = ["fyzický", "magický"]
CURES   = ["fyzické", "magické", "obojí"]
SOURCES = ["zbran", "runa", "prostredi", "schopnost"]
SOURCE_LABELS = {"zbran": "zbraň", "runa": "runa", "prostredi": "prostředí", "schopnost": "schopnost"}
TICKS   = ["kazde_kolo", "pri_zasahu"]

# ── Výchozí registr (nasadí se při prvním běhu / po smazání souboru) ──────────
DEFAULT_STATUSES: dict[str, dict] = {
    "jed": {
        "name": "Jed I.", "emoji": "🧪", "kind": "fyzický", "cure": "fyzické",
        "dmg": "1d5", "duration": 3, "tick": "kazde_kolo", "proc_roll": "", "proc": "",
        "desc": "Jed v ráně — 1d5 dmg každé kolo po 3 kola.",
    },
    "krvaceni": {
        "name": "Krvácení", "emoji": "🩸", "kind": "fyzický", "cure": "fyzické",
        "dmg": "1d4", "duration": 3, "tick": "kazde_kolo", "proc_roll": "", "proc": "",
        "desc": "Otevřená rána — 1d4 dmg každé kolo po 3 kola.",
    },
    "mraz": {
        "name": "Led I.", "emoji": "❄️", "kind": "magický", "cure": "magické",
        "dmg": "1d5", "duration": 0, "tick": "pri_zasahu", "proc_roll": "1d20", "proc": "stun",
        "desc": "Mráz při zásahu — 1d5 dmg + šance na stun (hod 1d20).",
    },
}

DEFAULT_RUNES: dict[str, dict] = {
    "led_1": {"name": "Led I.", "emoji": "❄️", "status": "mraz", "proc_roll": "1d20"},
    "jed_1": {"name": "Jed I.", "emoji": "🧪", "status": "jed",  "proc_roll": ""},
}


# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def load_statuses() -> dict:
    data = load_json(STATUSES_FILE, default=None)
    if not data:
        save_json(STATUSES_FILE, DEFAULT_STATUSES)
        return dict(DEFAULT_STATUSES)
    return data

def save_statuses(data: dict) -> None:
    save_json(STATUSES_FILE, data)

def load_runes() -> dict:
    data = load_json(RUNES_FILE, default=None)
    if not data:
        save_json(RUNES_FILE, DEFAULT_RUNES)
        return dict(DEFAULT_RUNES)
    return data

def save_runes(data: dict) -> None:
    save_json(RUNES_FILE, data)

def _load_profiles() -> dict:
    return load_json(PROFILES_FILE, default={})

def _save_profiles(data: dict) -> None:
    save_json(PROFILES_FILE, data)


# ══════════════════════════════════════════════════════════════════════════════
# KOSTKY
# ══════════════════════════════════════════════════════════════════════════════

_DICE_RE = re.compile(r"^(\d+)d(\d+)$", re.IGNORECASE)

def roll_dice(expr: str) -> int:
    """Hodí výraz '1d5', '2d6+1d4', '12'. Vrátí součet (0 pro prázdné/nevalidní)."""
    if not expr:
        return 0
    total = 0
    for tok in str(expr).replace(" ", "").split("+"):
        if tok.isdigit():
            total += int(tok)
            continue
        m = _DICE_RE.match(tok)
        if m:
            n, sides = int(m.group(1)), int(m.group(2))
            total += sum(random.randint(1, max(1, sides)) for _ in range(n))
    return total


# ══════════════════════════════════════════════════════════════════════════════
# STATUS INSTANCE — operují nad "nositelem" (dict s klíčem 'statuses')
# Funguje pro profil hráče i pro combat-stat NPC.
# ══════════════════════════════════════════════════════════════════════════════

def _carrier_statuses(carrier: dict) -> list:
    return carrier.setdefault("statuses", [])

def apply_status(carrier: dict, status_id: str, source: str,
                 registry: Optional[dict] = None) -> Optional[dict]:
    """Přidá status na nositele. Když už tam stejný je, obnoví trvání. Vrací instanci."""
    reg = registry if registry is not None else load_statuses()
    sdef = reg.get(status_id)
    if not sdef:
        return None
    statuses = _carrier_statuses(carrier)
    for inst in statuses:
        if inst.get("status") == status_id:
            inst["kol_zbyva"] = sdef.get("duration", 0)
            inst["zdroj"]     = source
            return inst
    inst = {
        "status":    status_id,
        "zdroj":     source,
        "kol_zbyva": sdef.get("duration", 0),
        "dmg":       sdef.get("dmg", ""),
    }
    statuses.append(inst)
    return inst

def tick_statuses(carrier: dict, registry: Optional[dict] = None) -> tuple[int, list[str]]:
    """Konec kola: statusy s tick='kazde_kolo' udělí dmg a sníží kol_zbyva.

    Vrací (celkový_dmg, log_řádky). Vypršelé statusy odstraní.
    Statusy s tick='pri_zasahu' (momentální) se NEtikají.
    """
    reg = registry if registry is not None else load_statuses()
    statuses = _carrier_statuses(carrier)
    total = 0
    log: list[str] = []
    survivors = []
    for inst in statuses:
        sdef = reg.get(inst.get("status"), {})
        if sdef.get("tick") != "kazde_kolo":
            survivors.append(inst)
            continue
        dmg = roll_dice(inst.get("dmg") or sdef.get("dmg", ""))
        total += dmg
        inst["kol_zbyva"] = inst.get("kol_zbyva", 0) - 1
        emoji = sdef.get("emoji", "•")
        nm    = sdef.get("name", inst.get("status"))
        if inst["kol_zbyva"] > 0:
            survivors.append(inst)
            log.append(f"{emoji} {nm}: −{dmg} HP ({inst['kol_zbyva']} kol zbývá)")
        else:
            log.append(f"{emoji} {nm}: −{dmg} HP (vyprchalo)")
    carrier["statuses"] = survivors
    return total, log

def cure_statuses(carrier: dict, cure_type: str,
                  registry: Optional[dict] = None) -> list[str]:
    """Sundá statusy léčitelné daným typem ('fyzické'/'magické').

    Status se sundá, pokud jeho cure == cure_type nebo == 'obojí'.
    Vrací názvy sundaných statusů.
    """
    reg = registry if registry is not None else load_statuses()
    statuses = _carrier_statuses(carrier)
    removed, survivors = [], []
    for inst in statuses:
        sdef = reg.get(inst.get("status"), {})
        c = sdef.get("cure", "fyzické")
        if c == cure_type or c == "obojí":
            removed.append(sdef.get("name", inst.get("status")))
        else:
            survivors.append(inst)
    carrier["statuses"] = survivors
    return removed

def status_icons(carrier: dict, registry: Optional[dict] = None) -> str:
    """Krátký řádek ikon aktivních statusů pro embed (např. '🩸🧪')."""
    statuses = carrier.get("statuses") or []
    if not statuses:
        return ""
    reg = registry if registry is not None else load_statuses()
    return "".join(reg.get(i.get("status"), {}).get("emoji", "•") for i in statuses)

def describe_statuses(carrier: dict, registry: Optional[dict] = None) -> str:
    """Víceřádkový výpis aktivních statusů (pro profil / quicksheet)."""
    statuses = carrier.get("statuses") or []
    if not statuses:
        return ""
    reg = registry if registry is not None else load_statuses()
    lines = []
    for inst in statuses:
        sdef = reg.get(inst.get("status"), {})
        emoji = sdef.get("emoji", "•")
        nm    = sdef.get("name", inst.get("status"))
        kol   = inst.get("kol_zbyva", 0)
        src   = SOURCE_LABELS.get(inst.get("zdroj", ""), inst.get("zdroj", ""))
        tail  = f" · {kol} kol" if kol > 0 else ""
        lines.append(f"{emoji} **{nm}** ({src}){tail}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# RUNY & NÁTĚRY na instanci itemu (entry)
# ══════════════════════════════════════════════════════════════════════════════

def get_item_runes(entry: dict) -> list[str]:
    r = entry.get("runes")
    return list(r) if isinstance(r, list) else []

def weapon_delivered(entry: dict, runes_reg: Optional[dict] = None) -> list[tuple[str, str]]:
    """Co zbraň DORUČÍ při zásahu → [(status_id, zdroj)]. Z run i z nátěru."""
    runes_reg = runes_reg if runes_reg is not None else load_runes()
    out: list[tuple[str, str]] = []
    for rid in get_item_runes(entry):
        st = runes_reg.get(rid, {}).get("status")
        if st:
            out.append((st, "runa"))
    coat = entry.get("coating")
    if isinstance(coat, dict) and coat.get("status"):
        out.append((coat["status"], "zbran"))
    return out

def consume_coating_hit(entry: dict) -> bool:
    """Po zásahu zbraní s nátěrem — ubere 1 zásah; odstraní vyprchaný nátěr. True=spotřebováno."""
    coat = entry.get("coating")
    if not isinstance(coat, dict):
        return False
    coat["hits_left"] = coat.get("hits_left", 0) - 1
    if coat["hits_left"] <= 0:
        entry.pop("coating", None)
    return True

def tick_coatings(profile: dict) -> list[str]:
    """Konec kola: nátěrům na všech zbraních hráče ubere 1 kolo; vyprchané smaže."""
    expired = []
    def _walk(entries):
        for e in entries:
            coat = e.get("coating")
            if isinstance(coat, dict):
                coat["rounds_left"] = coat.get("rounds_left", 0) - 1
                if coat["rounds_left"] <= 0:
                    expired.append(e.get("id", "?"))
                    e.pop("coating", None)
    _walk(profile.get("inventory", []))
    for stor in profile.get("storages", {}).values():
        _walk(stor)
    return expired


# ══════════════════════════════════════════════════════════════════════════════
# UTIL
# ══════════════════════════════════════════════════════════════════════════════

def _is_dm(interaction: discord.Interaction) -> bool:
    if isinstance(interaction.user, discord.Member):
        if any(r.name == DM_ROLE_NAME for r in interaction.user.roles):
            return True
        if interaction.user.guild_permissions.administrator:
            return True
    return False

def _iter_item_entries(profile: dict):
    for entry in profile.get("inventory", []):
        yield entry
    for stor in profile.get("storages", {}).values():
        for entry in stor:
            yield entry

def _find_storage_and_entry(profile: dict, item_id: str):
    inv = profile.get("inventory", [])
    for i, e in enumerate(inv):
        if e.get("type") == "registered" and e.get("id") == item_id:
            return inv, i
    for stor in profile.get("storages", {}).values():
        for i, e in enumerate(stor):
            if e.get("type") == "registered" and e.get("id") == item_id:
                return stor, i
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# EMBEDY
# ══════════════════════════════════════════════════════════════════════════════

def _status_registry_embed(reg: dict) -> discord.Embed:
    embed = discord.Embed(title="📖 Registr statusů", color=STATUS_COLOR,
                          description="Sdílené pro runy, nátěry, prostředí i schopnosti.")
    if not reg:
        embed.description += "\n\n*Žádné statusy.*"
        return embed
    for sid, s in reg.items():
        dmg = f"{s['dmg']} dmg" if s.get("dmg") else "—"
        dur = f"{s['duration']} kol" if s.get("duration") else "okamžitý"
        proc = f" · proc {s['proc_roll']}→{s['proc']}" if s.get("proc") else ""
        embed.add_field(
            name=f"{s.get('emoji','•')} {s['name']}  ·  `{sid}`",
            value=(f"{s.get('desc','—')}\n-# {s.get('kind','?')} · léčí: {s.get('cure','?')} "
                   f"· {dmg} · {dur} · tick: {s.get('tick','?')}{proc}"),
            inline=False)
    embed.set_footer(text="kind = povaha (řídí léčení) · cure = čím se sundá")
    return embed

def _rune_embed(runes_reg: dict, status_reg: dict) -> discord.Embed:
    embed = discord.Embed(title="⚒️ Kovárna — Runy", color=RUNE_COLOR,
                          description="*Kovář rozžhaví výheň a ukáže runové vzory...*")
    if not runes_reg:
        embed.description += "\n\n*Žádné runy.*"
        return embed
    for rid, r in runes_reg.items():
        s = status_reg.get(r.get("status"), {})
        dmg = f"{s.get('dmg','?')} dmg" if s.get("dmg") else "—"
        proc = f" · proc {r['proc_roll']}" if r.get("proc_roll") else ""
        embed.add_field(
            name=f"{r.get('emoji','🔹')} {r['name']}  ·  `{rid}`",
            value=(f"Status: **{s.get('name', r.get('status','?'))}** "
                   f"({s.get('kind','?')})\n-# {dmg}{proc}"),
            inline=False)
    embed.set_footer(text="⚒️ runa = trvalé doručení statusu · zapisuje se na konkrétní zbraň")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

async def _ac_status(interaction: discord.Interaction, current: str):
    reg = load_statuses(); cur = current.lower()
    out = []
    for sid, s in reg.items():
        if cur in sid.lower() or cur in s.get("name", "").lower():
            out.append(app_commands.Choice(name=f"{s.get('emoji','•')} {s['name']} ({sid})"[:100], value=sid))
    return out[:25]

async def _ac_rune(interaction: discord.Interaction, current: str):
    reg = load_runes(); cur = current.lower()
    out = []
    for rid, r in reg.items():
        if cur in rid.lower() or cur in r.get("name", "").lower():
            out.append(app_commands.Choice(name=f"{r.get('emoji','🔹')} {r['name']} ({rid})"[:100], value=rid))
    return out[:25]

async def _ac_member_item(interaction: discord.Interaction, current: str):
    member = getattr(interaction.namespace, "member", None)
    if member is None:
        return []
    profile = _load_profiles().get(str(member.id))
    if not profile:
        return []
    cur, seen, out = current.lower(), set(), []
    for e in _iter_item_entries(profile):
        if e.get("type") != "registered":
            continue
        iid = e.get("id", "")
        if iid in seen or cur not in iid.lower():
            continue
        seen.add(iid)
        out.append(app_commands.Choice(name=iid[:100], value=iid))
    return out[:25]


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class BlacksmithCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    blacksmith = app_commands.Group(name="blacksmith", description="Kovárna — runy, nátěry a statusy.")

    # ── runy / statusy: výpis ──────────────────────────────────────────────────
    @blacksmith.command(name="runes", description="Zobraz dostupné runy.")
    async def runes_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=_rune_embed(load_runes(), load_statuses()), ephemeral=True)

    @blacksmith.command(name="statuses", description="Zobraz registr statusů.")
    async def statuses_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=_status_registry_embed(load_statuses()), ephemeral=True)

    # ── status-create ───────────────────────────────────────────────────────────
    @blacksmith.command(name="status-create", description="[DM] Vytvoř/uprav status.")
    @app_commands.describe(
        status_id="Krátké ID (např. jed).", name="Název.", kind="Povaha (řídí léčení).",
        cure="Čím se sundá.", dmg="Dmg kostky (např. 1d5, prázdné=žádné).",
        duration="Kola trvání (0 = okamžitý při zásahu).", tick="Kdy dmg padá.",
        proc="Vedlejší efekt (stun…), prázdné=žádný.", proc_roll="Hod na proc (např. 1d20).",
        emoji="Emoji.", desc="Popis.")
    @app_commands.choices(
        kind=[app_commands.Choice(name=k, value=k) for k in KINDS],
        cure=[app_commands.Choice(name=c, value=c) for c in CURES],
        tick=[app_commands.Choice(name="každé kolo", value="kazde_kolo"),
              app_commands.Choice(name="při zásahu", value="pri_zasahu")])
    async def status_create(
        self, interaction: discord.Interaction,
        status_id: str, name: str, kind: str, cure: str,
        dmg: Optional[str] = None, duration: int = 0, tick: str = "kazde_kolo",
        proc: Optional[str] = None, proc_roll: Optional[str] = None,
        emoji: Optional[str] = None, desc: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM."); return
        sid = status_id.strip().lower().replace(" ", "_")
        reg = load_statuses()
        existed = sid in reg
        reg[sid] = {
            "name": name.strip(), "emoji": (emoji or "•").strip(),
            "kind": kind, "cure": cure, "dmg": (dmg or "").strip(),
            "duration": max(0, duration), "tick": tick,
            "proc": (proc or "").strip(), "proc_roll": (proc_roll or "").strip(),
            "desc": (desc or "").strip(),
        }
        save_statuses(reg)
        await interaction.followup.send(
            f"📖 Status **{name}** `{sid}` {'upraven' if existed else 'vytvořen'}.")

    @blacksmith.command(name="status-delete", description="[DM] Smaž status z registru.")
    @app_commands.describe(status="Status ke smazání.")
    @app_commands.autocomplete(status=_ac_status)
    async def status_delete(self, interaction: discord.Interaction, status: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM."); return
        reg = load_statuses()
        if status not in reg:
            await interaction.followup.send(f"❌ Status `{status}` neexistuje."); return
        nm = reg.pop(status)["name"]; save_statuses(reg)
        await interaction.followup.send(f"🗑️ Status **{nm}** `{status}` smazán.")

    # ── rune-create / delete (runa = odkaz na status) ────────────────────────────
    @blacksmith.command(name="rune-create", description="[DM] Vytvoř runu (doručí status).")
    @app_commands.describe(rune_id="ID runy (např. led_2).", name="Název.",
                           status="Který status runa doručí.",
                           proc_roll="Hod na proc (prázdné = dle statusu).", emoji="Emoji.")
    @app_commands.autocomplete(status=_ac_status)
    async def rune_create(self, interaction: discord.Interaction,
                          rune_id: str, name: str, status: str,
                          proc_roll: Optional[str] = None, emoji: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM."); return
        if status not in load_statuses():
            await interaction.followup.send(f"❌ Status `{status}` neexistuje. Vytvoř ho dřív `/blacksmith status-create`."); return
        rid = rune_id.strip().lower().replace(" ", "_")
        reg = load_runes(); existed = rid in reg
        reg[rid] = {"name": name.strip(), "emoji": (emoji or "🔹").strip(),
                    "status": status, "proc_roll": (proc_roll or "").strip()}
        save_runes(reg)
        await interaction.followup.send(f"⚒️ Runa **{name}** `{rid}` {'upravena' if existed else 'vytvořena'}.")

    @blacksmith.command(name="rune-delete", description="[DM] Smaž runu.")
    @app_commands.describe(rune="Runa ke smazání.")
    @app_commands.autocomplete(rune=_ac_rune)
    async def rune_delete(self, interaction: discord.Interaction, rune: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM."); return
        reg = load_runes()
        if rune not in reg:
            await interaction.followup.send(f"❌ Runa `{rune}` neexistuje."); return
        nm = reg.pop(rune)["name"]; save_runes(reg)
        await interaction.followup.send(f"🗑️ Runa **{nm}** `{rune}` smazána.")

    # ── engrave / unengrave ──────────────────────────────────────────────────────
    @blacksmith.command(name="engrave", description="[DM] Vyryj runu na zbraň hráče.")
    @app_commands.describe(member="Hráč.", item="ID itemu hráče.", rune="Runa.")
    @app_commands.autocomplete(item=_ac_member_item, rune=_ac_rune)
    async def engrave(self, interaction: discord.Interaction,
                      member: discord.Member, item: str, rune: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM."); return
        if rune not in load_runes():
            await interaction.followup.send(f"❌ Runa `{rune}` neexistuje."); return
        profiles = _load_profiles(); profile = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil."); return
        store, idx = _find_storage_and_entry(profile, item)
        if store is None:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá `{item}`."); return
        entry = store[idx]; existing = get_item_runes(entry)
        if rune in existing:
            await interaction.followup.send("ℹ️ Runa už na zbrani je."); return
        if len(existing) >= MAX_RUNES_PER_ITEM:
            await interaction.followup.send(f"❌ Max počet run ({MAX_RUNES_PER_ITEM})."); return
        if entry.get("qty", 1) > 1:
            entry["qty"] -= 1
            store.insert(idx + 1, {"type": "registered", "id": item, "qty": 1,
                                   "runes": existing + [rune]})
        else:
            entry["runes"] = existing + [rune]
        _save_profiles(profiles)
        r = load_runes()[rune]
        await interaction.followup.send(
            f"⚒️ Na **{item}** ({member.display_name}) vyryta runa {r.get('emoji','🔹')} **{r['name']}**.")

    @blacksmith.command(name="unengrave", description="[DM] Odstraň runu ze zbraně hráče.")
    @app_commands.describe(member="Hráč.", item="ID itemu.", rune="Runa.")
    @app_commands.autocomplete(item=_ac_member_item, rune=_ac_rune)
    async def unengrave(self, interaction: discord.Interaction,
                        member: discord.Member, item: str, rune: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM."); return
        profiles = _load_profiles(); profile = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil."); return
        target = None
        for e in _iter_item_entries(profile):
            if e.get("type") == "registered" and e.get("id") == item and rune in get_item_runes(e):
                target = e; break
        if target is None:
            await interaction.followup.send("❌ Tahle runa na itemu není."); return
        target["runes"] = [r for r in get_item_runes(target) if r != rune]
        if not target["runes"]:
            target.pop("runes", None)
        _save_profiles(profiles)
        await interaction.followup.send(f"🧹 Runa `{rune}` odstraněna z **{item}**.")

    # ── coat (nátěr čepele: 3 zásahy NEBO 2 kola) ───────────────────────────────
    @blacksmith.command(name="coat", description="Potři čepel statusem — vydrží 3 zásahy nebo 2 kola.")
    @app_commands.describe(item="Tvoje zbraň (ID).", status="Status k nanesení.",
                           hits="Počet zásahů (výchozí 3).", rounds="Počet kol (výchozí 2).")
    @app_commands.autocomplete(status=_ac_status)
    async def coat(self, interaction: discord.Interaction,
                   item: str, status: str, hits: int = 3, rounds: int = 2):
        await interaction.response.defer(ephemeral=True)
        if status not in load_statuses():
            await interaction.followup.send(f"❌ Status `{status}` neexistuje."); return
        profiles = _load_profiles(); profile = profiles.get(str(interaction.user.id))
        if not profile:
            await interaction.followup.send("❌ Nemáš profil."); return
        store, idx = _find_storage_and_entry(profile, item)
        if store is None:
            await interaction.followup.send(f"❌ Nemáš item `{item}`."); return
        entry = store[idx]
        if entry.get("qty", 1) > 1:   # odděl 1 kus, ať se nepotře celý stack
            entry["qty"] -= 1
            entry = {"type": "registered", "id": item, "qty": 1}
            store.insert(idx + 1, entry)
        entry["coating"] = {"status": status, "hits_left": max(1, hits), "rounds_left": max(1, rounds)}
        _save_profiles(profiles)
        s = load_statuses()[status]
        await interaction.followup.send(
            f"🧪 **{item}** potřeno: {s.get('emoji','•')} **{s['name']}** "
            f"— vydrží {max(1,hits)} zásahy nebo {max(1,rounds)} kola.")


async def setup(bot):
    await bot.add_cog(BlacksmithCog(bot))