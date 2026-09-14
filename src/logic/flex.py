"""/flex — veřejné ukázání lootu, perku, vzpomínky nebo průkazu.

Inventář i profil jsou skryté (ephemeral), takže tohle je jediná cesta,
jak něco ze svých věcí ukázat ostatním v kanálu.
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.core.dnd.perks import (
    _get_player as _perk_player,
    build_perk_detail_embed,
    load_perks,
    load_player_perks,
)
from src.database.characters import pkey
from src.database.profiles import load_items, load_profiles, profile_key
from src.logic.inventory import (
    _available_storages,
    _build_inspect_embed,
    _ensure_inv_fields,
    _item_display_name,
    _migrate_storages,
)
from src.logic.memory import _get_memories, _memories_embed
from src.logic.profile import _build_prukaz_embed, _ensure_player_fields

EMBED_DESC_LIMIT = 4096


def _get_profile(user_id: int) -> Optional[dict]:
    profiles = load_profiles()
    return profiles.get(profile_key(profiles, user_id))


def _owned_entries(profile: dict, items_db: Optional[dict] = None) -> list[dict]:
    """Všechny itemy hráče — inventář, dostupná úložiště i to, co má na sobě."""
    _ensure_inv_fields(profile)
    _migrate_storages(profile)
    if items_db is None:
        items_db = load_items()
    storages = profile.get("storages", {}) or {}
    entries  = list(profile.get("inventory", []))
    # Jen úložiště, která hráč reálně vlastní — osiřelé seznamy po odebraném
    # kontejneru nejsou v inventáři vidět, takže se nesmí dát ani flexit.
    for key in _available_storages(profile, items_db):
        if key == "inventory":
            continue
        entries.extend(storages.get(key, []))
    for item_id in (profile.get("equipment", {}) or {}).values():
        if item_id:
            entries.append({"type": "registered", "id": item_id})
    return entries


def _find_owned(profile: dict, key: str, items_db: Optional[dict] = None) -> Optional[dict]:
    key_low = key.lower()
    for entry in _owned_entries(profile, items_db):
        if entry.get("type") == "registered":
            if entry.get("id", "").lower() == key_low:
                return entry
        elif entry.get("name", "").lower() == key_low:
            return entry
    return None


def _custom_item_embed(entry: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎁  {entry.get('name', 'Neznámý předmět')}",
        description=entry.get("desc") or "*Bez popisu.*",
        color=0xC9A227,
    )
    return embed


def _flex_footer(embed: discord.Embed, author: discord.abc.User) -> discord.Embed:
    embed.set_footer(text=f"💪 Flex {author.display_name}")
    return embed


async def _ac_flex_item(interaction: discord.Interaction, current: str):
    profile = _get_profile(interaction.user.id)
    if not profile:
        return []
    items_db = load_items()
    cur      = current.lower()
    seen: set[str] = set()
    choices: list[app_commands.Choice[str]] = []
    for entry in _owned_entries(profile, items_db):
        name = _item_display_name(entry, items_db)
        key  = entry["id"] if entry.get("type") == "registered" else entry.get("name", "")
        if not key or key in seen:
            continue
        if cur in name.lower() or cur in key.lower():
            choices.append(app_commands.Choice(name=name, value=key))
            seen.add(key)
    return choices[:25]


async def _ac_flex_perk(interaction: discord.Interaction, current: str):
    all_perks = load_perks()
    player    = _perk_player(pkey(interaction.user.id), load_player_perks())
    cur       = current.lower()
    return [
        app_commands.Choice(
            name=f"{all_perks[pid]['name']} ({pid})" if pid in all_perks else pid,
            value=pid,
        )
        for pid in player["perks"]
        if cur in pid.lower()
        or (pid in all_perks and cur in all_perks[pid].get("name", "").lower())
    ][:25]


class FlexCog(commands.Cog):
    """Veřejné ukázání vlastních věcí."""

    def __init__(self, bot):
        self.bot = bot

    flex = app_commands.Group(name="flex", description="Ukaž ostatním svůj loot, perk nebo průkaz.")

    # ── /flex item ────────────────────────────────────────────────────────────
    @flex.command(name="item", description="Ukaž v kanálu předmět ze svého inventáře.")
    @app_commands.describe(item="Předmět, kterým se chceš pochlubit.")
    @app_commands.autocomplete(item=_ac_flex_item)
    async def flex_item(self, interaction: discord.Interaction, item: str):
        profile = _get_profile(interaction.user.id)
        if not profile:
            await interaction.response.send_message("❌ Nemáš profil.", ephemeral=True)
            return
        items_db = load_items()
        entry    = _find_owned(profile, item, items_db)
        if not entry:
            await interaction.response.send_message(
                f"❌ **{item}** nemáš u sebe — flexit jde jen to, co vlastníš.", ephemeral=True)
            return

        if entry.get("type") == "registered":
            embed = _build_inspect_embed(entry["id"], items_db, profile)
            if embed is None:
                await interaction.response.send_message(
                    f"❌ Předmět `{entry['id']}` už není v databázi.", ephemeral=True)
                return
        else:
            embed = _custom_item_embed(entry)

        await interaction.response.send_message(embed=_flex_footer(embed, interaction.user))

    # ── /flex perk ────────────────────────────────────────────────────────────
    @flex.command(name="perk", description="Ukaž v kanálu jeden ze svých perků.")
    @app_commands.describe(perk_id="Perk, který chceš ukázat.")
    @app_commands.autocomplete(perk_id=_ac_flex_perk)
    async def flex_perk(self, interaction: discord.Interaction, perk_id: str):
        perks  = load_perks()
        player = _perk_player(pkey(interaction.user.id), load_player_perks())
        if perk_id not in player["perks"]:
            await interaction.response.send_message(
                f"❌ Perk `{perk_id}` nemáš.", ephemeral=True)
            return
        if perk_id not in perks:
            await interaction.response.send_message(
                f"❌ Perk `{perk_id}` už není v databázi.", ephemeral=True)
            return
        embed = build_perk_detail_embed(perk_id, perks[perk_id])
        embed.title = f"💪 {interaction.user.display_name} se chlubí perkem"
        await interaction.response.send_message(embed=embed)

    # ── /flex profile ─────────────────────────────────────────────────────────
    @flex.command(name="profile", description="Ukaž v kanálu svůj dobrodružný průkaz.")
    async def flex_profile(self, interaction: discord.Interaction):
        profiles = load_profiles()
        profile  = profiles.get(profile_key(profiles, interaction.user.id))
        if not profile:
            await interaction.response.send_message(
                "❌ Zatím nemáš průkaz dobrodruha.", ephemeral=True)
            return
        _ensure_player_fields(profile)
        embed = _build_prukaz_embed(interaction.user, profile)
        await interaction.response.send_message(embed=_flex_footer(embed, interaction.user))

    # ── /flex memory ──────────────────────────────────────────────────────────
    @flex.command(name="memory", description="Ukaž v kanálu svoje vzpomínky (nebo jednu z nich).")
    @app_commands.describe(cislo="Pořadí vzpomínky (bez čísla se ukážou všechny).")
    async def flex_memory(self, interaction: discord.Interaction, cislo: Optional[int] = None):
        memories = _get_memories(pkey(interaction.user.id))
        if not memories:
            await interaction.response.send_message(
                "❌ Nemáš žádné vzpomínky.", ephemeral=True)
            return
        if cislo is None:
            embed = _memories_embed(interaction.user, memories)
            if len(embed.description or "") > EMBED_DESC_LIMIT:
                await interaction.response.send_message(
                    f"❌ Máš moc vzpomínek na jeden embed — vyber jednu přes "
                    f"`/flex memory cislo:1`–`{len(memories)}`.", ephemeral=True)
                return
        else:
            if not 1 <= cislo <= len(memories):
                await interaction.response.send_message(
                    f"❌ Vzpomínka č. {cislo} neexistuje (máš jich {len(memories)}).",
                    ephemeral=True)
                return
            embed = _memories_embed(interaction.user, [memories[cislo - 1]])
        await interaction.response.send_message(embed=_flex_footer(embed, interaction.user))


async def setup(bot):
    await bot.add_cog(FlexCog(bot))
