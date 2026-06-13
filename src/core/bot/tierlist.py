"""Tierlist Cog – Arion Bot
Hráči si mohou vytvářet tierlistry, přidávat položky, řadit je do tierů a hlasovat.
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import json
import os

# ── Cesta k datům ─────────────────────────────────────────────────────────────

try:
    from src.utils.paths import TIERLISTS as DATA_PATH
except Exception:
    DATA_PATH = os.path.join("src", "database", "data", "tierlists.json")

DEFAULT_TIERS = ["S+", "S", "A", "B", "C", "D", "E", "F"]

TIER_COLORS = {
    "S+": 0xFF69B4,
    "S":  0xFF4500,
    "A":  0xFF8C00,
    "B":  0xFFD700,
    "C":  0x32CD32,
    "D":  0x1E90FF,
    "E":  0x9370DB,
    "F":  0x808080,
}

# ── JSON helpers ───────────────────────────────────────────────────────────────

def load_tierlists() -> dict:
    if not os.path.exists(DATA_PATH):
        return {}
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tierlists(data: dict):
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def tierlist_key(guild_id: int, name: str) -> str:
    return f"{guild_id}:{name.lower()}"

def get_votes(tl: dict, item_name: str) -> int:
    """Vrátí počet hlasů pro danou položku."""
    return len(tl.get("votes", {}).get(item_name.lower(), {}).get("voters", []))

def format_item(tl: dict, item_name: str) -> str:
    """Formátuje položku pro embed — přidá [N] pokud má hlasy."""
    votes = get_votes(tl, item_name)
    return f"`{item_name} [{votes}]`" if votes else f"`{item_name}`"

# ── Embed builder ──────────────────────────────────────────────────────────────

def build_tierlist_embed(name: str, tl: dict) -> discord.Embed:
    tiers = tl.get("tiers", {})
    tier_order = tl.get("tier_order", DEFAULT_TIERS)

    embed = discord.Embed(title=f"🏆 Tierlist: {name}", color=0xFFD700)
    embed.set_footer(text=f"Vytvořil: {tl.get('author', '?')} • /tierlist add | /tierlist vote")

    has_any = False
    for tier in tier_order:
        items = tiers.get(tier, [])
        if items:
            has_any = True
        dot = _tier_dot(tier)
        value = ", ".join(format_item(tl, i) for i in items) if items else "*empty*"
        embed.add_field(name=f"{dot} **{tier}**", value=value, inline=False)

    if not has_any:
        embed.description = "*Tierlist is empty. Add items via `/tierlist add`.*"

    return embed

def _tier_dot(tier: str) -> str:
    return {
        "S+": "🩷", "S": "🔴", "A": "🟠", "B": "🟡",
        "C": "🟢", "D": "🔵", "E": "🟣", "F": "⚫",
    }.get(tier, "⚪")

def _find_item(tl: dict, item_name: str) -> tuple[str | None, str | None]:
    """Najde položku v tierlistu bez ohledu na velikost písmen. Vrátí (tier, přesný název)."""
    for tier, items in tl.get("tiers", {}).items():
        for i in items:
            if i.lower() == item_name.lower():
                return tier, i
    return None, None

# ── Cog ───────────────────────────────────────────────────────────────────────

class TierlistCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    tierlist = app_commands.Group(name="tierlist", description="Tierlist management")

    # ── /tierlist create ──────────────────────────────────────────────────────

    @tierlist.command(name="create", description="Create a new tierlist.")
    @app_commands.describe(
        name="Tierlist name (e.g. 'gaming' or 'best movies')",
        tiers="Optional custom tiers separated by commas (e.g. 'S+,S,A,B,C,F'). Default: S+,S,A,B,C,D,E,F",
    )
    async def create(self, interaction: discord.Interaction, name: str, tiers: Optional[str] = None):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** already exists!", color=0xFF4444),
                ephemeral=True,
            )
            return

        tier_order = [t.strip() for t in tiers.split(",")] if tiers else DEFAULT_TIERS
        tier_order = [t for t in tier_order if t]

        data[key] = {
            "name": name,
            "author": interaction.user.display_name,
            "author_id": interaction.user.id,
            "tier_order": tier_order,
            "tiers": {tier: [] for tier in tier_order},
            "votes": {},
        }
        save_tierlists(data)

        embed = discord.Embed(
            title="✅ Tierlist created!",
            description=f"**{name}** is ready.\nTiers: {' › '.join(tier_order)}",
            color=0x2ECC71,
        )
        embed.set_footer(text="Add items via /tierlist add")
        await interaction.response.send_message(embed=embed)

    # ── /tierlist add ─────────────────────────────────────────────────────────

    @tierlist.command(name="add", description="Add an item to a tier.")
    @app_commands.describe(
        name="Tierlist name",
        item="Item to add (e.g. 'Minecraft' or 'Pizza')",
        tier="Which tier to place it in (e.g. S, A, B…)",
    )
    async def add(self, interaction: discord.Interaction, name: str, item: str, tier: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** doesn't exist. Create it via `/tierlist create`.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        tier_upper = tier.upper()

        if tier_upper not in tl["tiers"]:
            available = ", ".join(tl["tier_order"])
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tier **{tier}** doesn't exist.\nAvailable: `{available}`", color=0xFF4444),
                ephemeral=True,
            )
            return

        existing_tier, _ = _find_item(tl, item)
        if existing_tier:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"⚠️ **{item}** is already in tier **{existing_tier}**!", color=0xFFA500),
                ephemeral=True,
            )
            return

        tl["tiers"][tier_upper].append(item)
        if "votes" not in tl:
            tl["votes"] = {}
        save_tierlists(data)

        dot = _tier_dot(tier_upper)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ **{item}** added to {dot} **{tier_upper}** in **{tl['name']}**!",
                color=TIER_COLORS.get(tier_upper, 0x5865F2),
            )
        )

    # ── /tierlist move ────────────────────────────────────────────────────────

    @tierlist.command(name="move", description="Move an item to a different tier.")
    @app_commands.describe(name="Tierlist name", item="Item to move", tier="New tier")
    async def move(self, interaction: discord.Interaction, name: str, item: str, tier: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** doesn't exist.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        tier_upper = tier.upper()

        if tier_upper not in tl["tiers"]:
            available = ", ".join(tl["tier_order"])
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tier **{tier}** doesn't exist.\nAvailable: `{available}`", color=0xFF4444),
                ephemeral=True,
            )
            return

        old_tier, exact_name = _find_item(tl, item)
        if not old_tier:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Item **{item}** not found in **{tl['name']}**.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl["tiers"][old_tier].remove(exact_name)
        tl["tiers"][tier_upper].append(exact_name)
        save_tierlists(data)

        dot = _tier_dot(tier_upper)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🔀 **{exact_name}** moved from **{old_tier}** → {dot} **{tier_upper}**",
                color=TIER_COLORS.get(tier_upper, 0x5865F2),
            )
        )

    # ── /tierlist vote ────────────────────────────────────────────────────────

    @tierlist.command(name="vote", description="Vote for an item in a tierlist.")
    @app_commands.describe(
        name="Tierlist name",
        item="Item you want to vote for",
    )
    async def vote(self, interaction: discord.Interaction, name: str, item: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** doesn't exist.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        _, exact_name = _find_item(tl, item)

        if not exact_name:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Item **{item}** not found in **{tl['name']}**.", color=0xFF4444),
                ephemeral=True,
            )
            return

        if "votes" not in tl:
            tl["votes"] = {}

        item_key = exact_name.lower()
        if item_key not in tl["votes"]:
            tl["votes"][item_key] = {"voters": []}

        voters = tl["votes"][item_key]["voters"]
        user_id = interaction.user.id

        if user_id in voters:
            # Unvote
            voters.remove(user_id)
            save_tierlists(data)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"🗳️ Removed your vote from **{exact_name}**. *(now {len(voters)} votes)*",
                    color=0x808080,
                ),
                ephemeral=True,
            )
        else:
            voters.append(user_id)
            save_tierlists(data)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"✅ Voted for **{exact_name}**! *(now {len(voters)} votes)*",
                    color=0x2ECC71,
                ),
                ephemeral=True,
            )

    # ── /tierlist show ────────────────────────────────────────────────────────

    @tierlist.command(name="show", description="Show a tierlist.")
    @app_commands.describe(name="Tierlist name")
    async def show(self, interaction: discord.Interaction, name: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** doesn't exist.", color=0xFF4444),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=build_tierlist_embed(name, data[key]))

    # ── /tierlist list ────────────────────────────────────────────────────────

    @tierlist.command(name="list", description="Show all tierlists on this server.")
    async def list_tierlists(self, interaction: discord.Interaction):
        data = load_tierlists()
        prefix = f"{interaction.guild_id}:"
        server_lists = {k: v for k, v in data.items() if k.startswith(prefix)}

        if not server_lists:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="📭 No tierlists on this server yet.\nCreate one via `/tierlist create`!",
                    color=0x5865F2,
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📋 Tierlists on this server", color=0x5865F2)
        for k, tl in server_lists.items():
            tier_order = tl.get("tier_order", DEFAULT_TIERS)
            total_items = sum(len(v) for v in tl["tiers"].values())
            total_votes = sum(
                len(v.get("voters", [])) for v in tl.get("votes", {}).values()
            )
            embed.add_field(
                name=f"🏆 {tl['name']}",
                value=f"Tiers: `{'` `'.join(tier_order)}`\nItems: **{total_items}** • Votes: **{total_votes}** • Author: {tl['author']}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ── /tierlist remove ──────────────────────────────────────────────────────

    @tierlist.command(name="remove", description="Remove an item from a tierlist.")
    @app_commands.describe(name="Tierlist name", item="Item to remove")
    async def remove(self, interaction: discord.Interaction, name: str, item: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** doesn't exist.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        old_tier, exact_name = _find_item(tl, item)

        if not old_tier:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Item **{item}** not found.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl["tiers"][old_tier].remove(exact_name)
        tl.get("votes", {}).pop(exact_name.lower(), None)
        save_tierlists(data)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🗑️ **{exact_name}** removed from **{tl['name']}**.",
                color=0x2ECC71,
            )
        )

    # ── /tierlist delete ──────────────────────────────────────────────────────

    @tierlist.command(name="delete", description="Delete an entire tierlist (author or admin only).")
    @app_commands.describe(name="Tierlist name to delete")
    async def delete(self, interaction: discord.Interaction, name: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, name)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{name}** doesn't exist.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        is_author = tl.get("author_id") == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild

        if not is_author and not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Only the author or an admin can delete this tierlist.", color=0xFF4444),
                ephemeral=True,
            )
            return

        del data[key]
        save_tierlists(data)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"🗑️ Tierlist **{name}** deleted.", color=0x2ECC71)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TierlistCog(bot))