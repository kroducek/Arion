"""
Blacksmith / Rune systém — Aurionis

Runy jsou status-efektové vylepšení ZBRANÍ. Jsou oddělené od zbraně a od
databáze itemů: žijí ve vlastním registru (runes.json) a zapisují se na
KONKRÉTNÍ instanci itemu v profilu hráče (pole ``runes`` na dané položce
inventáře/úložiště).

DM uděluje runy hráči "u kováře" přes ``/blacksmith engrave``. Runy lze
vytvářet vlastní přes ``/blacksmith rune-create``.

Combat integrace
-----------------
Tento modul runy jen DEFINUJE a PŘIPISUJE. Aplikaci efektu v boji (bonus dmg,
stun, jed přes kola) musí provést bojový kód — ten si runy itemu přečte přes
``get_item_runes(entry)`` a definice přes ``load_runes()``. Každá runa nese
``bonus_dmg`` (kostky), ``effect`` (stun/poison/burn/…), ``effect_roll`` (hod
na proc, např. 1d20) a ``duration`` (počet kol u DoT efektů).
"""
import os
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.paths import PROFILES as PROFILES_FILE
from src.utils.json_utils import load_json, save_json

logger = logging.getLogger(__name__)

ARION_NAME   = "Aurionis"
RUNE_COLOR   = 0x5b8cb0
MAX_RUNES_PER_ITEM = 3
DM_ROLE_NAME = "DM"

# runes.json drž vedle profiles.json (stejný datový adresář, žádný nový path konstant)
RUNES_FILE = os.path.join(os.path.dirname(PROFILES_FILE), "runes.json")

# Výchozí runy nasazené při prvním načtení (lze mazat/přidávat za běhu).
DEFAULT_RUNES: dict[str, dict] = {
    "led_1": {
        "name":        "Led I.",
        "emoji":       "❄️",
        "desc":        "1d5 dmg + šance na stun (hod 1d20).",
        "bonus_dmg":   "1d5",
        "effect":      "stun",
        "effect_roll": "1d20",
        "duration":    0,
    },
    "jed_1": {
        "name":        "Jed I.",
        "emoji":       "🧪",
        "desc":        "1d5 dmg po dobu 3 kol (jed).",
        "bonus_dmg":   "1d5",
        "effect":      "poison",
        "effect_roll": "",
        "duration":    3,
    },
}

EFFECT_CHOICES = ["stun", "poison", "burn", "bleed", "slow", "weaken", "none"]


# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def load_runes() -> dict:
    """Načte registr run. Při prvním běhu nasadí výchozí runy."""
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
# HELPERY PRO COMBAT / INVENTORY
# ══════════════════════════════════════════════════════════════════════════════

def get_item_runes(entry: dict) -> list[str]:
    """Vrátí seznam rune-id zapsaných na dané instanci itemu (entry)."""
    runes = entry.get("runes")
    return list(runes) if isinstance(runes, list) else []

def describe_runes(entry: dict, registry: Optional[dict] = None) -> str:
    """Lidsky čitelný výpis run itemu pro embed (prázdný string pokud žádné)."""
    rids = get_item_runes(entry)
    if not rids:
        return ""
    reg = registry if registry is not None else load_runes()
    parts = []
    for rid in rids:
        r = reg.get(rid)
        if r:
            parts.append(f"{r.get('emoji', '🔹')} {r['name']}")
        else:
            parts.append(f"🔹 {rid}")
    return " · ".join(parts)


def _iter_item_entries(profile: dict):
    """Projde všechny instance itemů hráče (inventář + všechna úložiště)."""
    for entry in profile.get("inventory", []):
        yield entry
    for stor in profile.get("storages", {}).values():
        for entry in stor:
            yield entry

def _find_storage_and_entry(profile: dict, item_id: str):
    """Najde (storage_list, index) první registrované instance itemu dle id."""
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
# UTIL
# ══════════════════════════════════════════════════════════════════════════════

def _is_dm(interaction: discord.Interaction) -> bool:
    if isinstance(interaction.user, discord.Member):
        if any(r.name == DM_ROLE_NAME for r in interaction.user.roles):
            return True
        if interaction.user.guild_permissions.administrator:
            return True
    return False

def _rune_embed(registry: dict) -> discord.Embed:
    embed = discord.Embed(
        title="⚒️ Kovárna — Runy",
        description="*Kovář rozžhaví výheň a ukáže ti runové vzory...*",
        color=RUNE_COLOR,
    )
    if not registry:
        embed.description += "\n\n*Žádné runy zatím nejsou.*"
        return embed
    for rid, r in registry.items():
        dmg = f"  +{r['bonus_dmg']} dmg" if r.get("bonus_dmg") else ""
        eff = r.get("effect") or "—"
        dur = f" ({r['duration']} kol)" if r.get("duration") else ""
        roll = f", proc {r['effect_roll']}" if r.get("effect_roll") else ""
        embed.add_field(
            name=f"{r.get('emoji', '🔹')} {r['name']}  ·  `{rid}`",
            value=f"{r.get('desc', '—')}\n-# {dmg} · efekt: {eff}{dur}{roll}".strip(),
            inline=False,
        )
    embed.set_footer(text=f"⚒️ {ARION_NAME} · runy se zapisují na konkrétní zbraň")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════════════

async def _ac_rune(interaction: discord.Interaction, current: str):
    reg = load_runes()
    cur = current.lower()
    out = []
    for rid, r in reg.items():
        label = f"{r.get('emoji','🔹')} {r['name']} ({rid})"
        if cur in rid.lower() or cur in r.get("name", "").lower():
            out.append(app_commands.Choice(name=label[:100], value=rid))
    return out[:25]

async def _ac_member_item(interaction: discord.Interaction, current: str):
    """Itemy cílového hráče (z parametru 'member') — registrované instance."""
    member = getattr(interaction.namespace, "member", None)
    if member is None:
        return []
    profile = _load_profiles().get(str(member.id))
    if not profile:
        return []
    cur  = current.lower()
    seen = set()
    out  = []
    for e in _iter_item_entries(profile):
        if e.get("type") != "registered":
            continue
        iid = e.get("id", "")
        if iid in seen:
            continue
        if cur in iid.lower():
            seen.add(iid)
            out.append(app_commands.Choice(name=iid[:100], value=iid))
    return out[:25]


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class BlacksmithCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    blacksmith = app_commands.Group(name="blacksmith", description="Kovárna — runy a vylepšení zbraní.")

    # ── /blacksmith runes ─────────────────────────────────────────────────────
    @blacksmith.command(name="runes", description="Zobraz dostupné runy v kovárně.")
    async def runes_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_rune_embed(load_runes()), ephemeral=True)

    # ── /blacksmith rune-create ───────────────────────────────────────────────
    @blacksmith.command(name="rune-create", description="[DM] Vytvoř vlastní runu.")
    @app_commands.describe(
        rune_id="Krátké ID (např. led_2).",
        name="Název (např. Led II.).",
        desc="Popis efektu.",
        bonus_dmg="Bonusové poškození kostkami (např. 1d5, prázdné = žádné).",
        effect="Status efekt.",
        effect_roll="Hod na proc efektu (např. 1d20, prázdné = vždy).",
        duration="Počet kol u efektů přes čas (jed/hoření; 0 = okamžitý).",
        emoji="Emoji runy.",
    )
    @app_commands.choices(effect=[app_commands.Choice(name=e, value=e) for e in EFFECT_CHOICES])
    async def rune_create(
        self, interaction: discord.Interaction,
        rune_id: str, name: str, desc: str,
        bonus_dmg: Optional[str] = None,
        effect: Optional[str] = None,
        effect_roll: Optional[str] = None,
        duration: int = 0,
        emoji: Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Runy může tvořit jen DM.")
            return
        rid = rune_id.strip().lower().replace(" ", "_")
        reg = load_runes()
        existed = rid in reg
        reg[rid] = {
            "name":        name.strip(),
            "emoji":       (emoji or "🔹").strip(),
            "desc":        desc.strip(),
            "bonus_dmg":   (bonus_dmg or "").strip(),
            "effect":      (effect or "none"),
            "effect_roll": (effect_roll or "").strip(),
            "duration":    max(0, duration),
        }
        save_runes(reg)
        verb = "upravena" if existed else "vytvořena"
        await interaction.followup.send(
            f"⚒️ Runa **{name}** `{rid}` {verb}.")

    # ── /blacksmith rune-delete ───────────────────────────────────────────────
    @blacksmith.command(name="rune-delete", description="[DM] Smaž runu z registru.")
    @app_commands.describe(rune="Runa ke smazání.")
    @app_commands.autocomplete(rune=_ac_rune)
    async def rune_delete(self, interaction: discord.Interaction, rune: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        reg = load_runes()
        if rune not in reg:
            await interaction.followup.send(f"❌ Runa `{rune}` neexistuje.")
            return
        nm = reg[rune]["name"]
        del reg[rune]
        save_runes(reg)
        await interaction.followup.send(
            f"🗑️ Runa **{nm}** `{rune}` smazána z registru.\n"
            "-# (Už zapsané runy na zbraních hráčů zůstávají.)")

    # ── /blacksmith engrave ───────────────────────────────────────────────────
    @blacksmith.command(name="engrave", description="[DM] Vyryj runu na zbraň hráče.")
    @app_commands.describe(member="Hráč.", item="ID itemu hráče.", rune="Runa.")
    @app_commands.autocomplete(item=_ac_member_item, rune=_ac_rune)
    async def engrave(self, interaction: discord.Interaction,
                      member: discord.Member, item: str, rune: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Runy ryje jen DM.")
            return
        reg = load_runes()
        if rune not in reg:
            await interaction.followup.send(f"❌ Runa `{rune}` neexistuje.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        store, idx = _find_storage_and_entry(profile, item)
        if store is None:
            await interaction.followup.send(
                f"❌ **{member.display_name}** nemá item `{item}`.")
            return
        entry = store[idx]
        existing = get_item_runes(entry)
        if rune in existing:
            await interaction.followup.send("ℹ️ Tahle runa už na zbrani je.")
            return
        if len(existing) >= MAX_RUNES_PER_ITEM:
            await interaction.followup.send(
                f"❌ Item má max počet run ({MAX_RUNES_PER_ITEM}).")
            return

        # Pokud je item ve stacku (qty>1), odděl jednu kopii — runa patří jedné zbrani
        if entry.get("qty", 1) > 1:
            entry["qty"] -= 1
            new_entry = {"type": "registered", "id": item, "qty": 1,
                         "runes": existing + [rune]}
            store.insert(idx + 1, new_entry)
        else:
            entry["runes"] = existing + [rune]

        _save_profiles(profiles)
        r = reg[rune]
        await interaction.followup.send(
            f"⚒️ Na **{item}** ({member.display_name}) vyryta runa "
            f"{r.get('emoji','🔹')} **{r['name']}**.")

    # ── /blacksmith unengrave ─────────────────────────────────────────────────
    @blacksmith.command(name="unengrave", description="[DM] Odstraň runu ze zbraně hráče.")
    @app_commands.describe(member="Hráč.", item="ID itemu hráče.", rune="Runa.")
    @app_commands.autocomplete(item=_ac_member_item, rune=_ac_rune)
    async def unengrave(self, interaction: discord.Interaction,
                        member: discord.Member, item: str, rune: str):
        await interaction.response.defer(ephemeral=True)
        if not _is_dm(interaction):
            await interaction.followup.send("❌ Jen DM.")
            return
        profiles = _load_profiles()
        profile  = profiles.get(str(member.id))
        if not profile:
            await interaction.followup.send(f"❌ **{member.display_name}** nemá profil.")
            return
        # najdi instanci s touhle runou
        target = None
        for entry in _iter_item_entries(profile):
            if (entry.get("type") == "registered" and entry.get("id") == item
                    and rune in get_item_runes(entry)):
                target = entry
                break
        if target is None:
            await interaction.followup.send("❌ Tahle runa na daném itemu není.")
            return
        target["runes"] = [r for r in get_item_runes(target) if r != rune]
        if not target["runes"]:
            target.pop("runes", None)
        _save_profiles(profiles)
        await interaction.followup.send(f"🧹 Runa `{rune}` odstraněna z **{item}**.")


async def setup(bot):
    await bot.add_cog(BlacksmithCog(bot))