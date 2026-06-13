"""Tierlist Cog – Arion Bot
Community tierlists with voting that moves items between tiers.
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import json
import os

# ── Config ────────────────────────────────────────────────────────────────────

try:
    from src.utils.paths import TIERLISTS as DATA_PATH
except Exception:
    DATA_PATH = os.path.join("src", "database", "data", "tierlists.json")

VOTE_THRESHOLD = 3          # kolik hlasů posouvá o tier (±3)
DEFAULT_TIERS = ["S+", "S", "A", "B", "C", "D", "E", "F"]

TIER_COLORS = {
    "S+": 0xFF69B4, "S": 0xFF4500, "A": 0xFF8C00, "B": 0xFFD700,
    "C": 0x32CD32,  "D": 0x1E90FF, "E": 0x9370DB, "F": 0x808080,
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

# ── Vote helpers ───────────────────────────────────────────────────────────────

def get_vote_data(tl: dict, item_name: str) -> dict:
    """Vrátí vote data pro položku (vytvoří pokud neexistuje)."""
    item_key = item_name.lower()
    if "votes" not in tl:
        tl["votes"] = {}
    if item_key not in tl["votes"]:
        tl["votes"][item_key] = {"up": [], "down": [], "score": 0}
    return tl["votes"][item_key]

def net_score(vote_data: dict) -> int:
    return len(vote_data.get("up", [])) - len(vote_data.get("down", []))

def format_item(tl: dict, item_name: str) -> str:
    """Formátuje položku — přidá [+N]/[-N] pokud má hlasy."""
    vd = tl.get("votes", {}).get(item_name.lower())
    if not vd:
        return f"`{item_name}`"
    score = net_score(vd)
    if score == 0:
        return f"`{item_name}`"
    sign = "+" if score > 0 else ""
    return f"`{item_name} [{sign}{score}]`"

def _find_item(tl: dict, item_name: str) -> tuple[str | None, str | None]:
    """Vrátí (tier, přesný název) bez ohledu na velikost písmen."""
    for tier, items in tl.get("tiers", {}).items():
        for i in items:
            if i.lower() == item_name.lower():
                return tier, i
    return None, None

def _tier_dot(tier: str) -> str:
    return {"S+": "🩷", "S": "🔴", "A": "🟠", "B": "🟡",
            "C": "🟢", "D": "🔵", "E": "🟣", "F": "⚫"}.get(tier, "⚪")

def _apply_vote_and_check_move(tl: dict, exact_name: str) -> str | None:
    """
    Přidá hlas a zkontroluje jestli položka překročila threshold.
    Vrátí zprávu o přesunu pokud k němu došlo, jinak None.
    """
    tier_order = tl.get("tier_order", DEFAULT_TIERS)
    current_tier, _ = _find_item(tl, exact_name)
    if not current_tier:
        return None

    vd = get_vote_data(tl, exact_name)
    score = net_score(vd)
    tier_idx = tier_order.index(current_tier) if current_tier in tier_order else -1
    move_msg = None

    if score >= VOTE_THRESHOLD and tier_idx > 0:
        # Posun nahoru (S+ je index 0 = nejlepší)
        new_tier = tier_order[tier_idx - 1]
        tl["tiers"][current_tier].remove(exact_name)
        tl["tiers"][new_tier].append(exact_name)
        tl["votes"][exact_name.lower()] = {"up": [], "down": [], "score": 0}
        move_msg = f"⬆️ **{exact_name}** dosáhl **+{VOTE_THRESHOLD}** hlasů → přesunut do **{new_tier}**! *(skóre resetováno)*"

    elif score <= -VOTE_THRESHOLD and tier_idx < len(tier_order) - 1:
        # Posun dolů
        new_tier = tier_order[tier_idx + 1]
        tl["tiers"][current_tier].remove(exact_name)
        tl["tiers"][new_tier].append(exact_name)
        tl["votes"][exact_name.lower()] = {"up": [], "down": [], "score": 0}
        move_msg = f"⬇️ **{exact_name}** dosáhl **-{VOTE_THRESHOLD}** hlasů → přesunut do **{new_tier}**! *(skóre resetováno)*"

    return move_msg

# ── Embed builder ──────────────────────────────────────────────────────────────

def build_tierlist_embed(name: str, tl: dict) -> discord.Embed:
    tiers = tl.get("tiers", {})
    tier_order = tl.get("tier_order", DEFAULT_TIERS)

    embed = discord.Embed(title=f"🏆 Tierlist: {name}", color=0xFFD700)
    embed.set_footer(text=f"By {tl.get('author', '?')} • /tierlist vote — {VOTE_THRESHOLD} votes moves item up/down")

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

# ── Cog ───────────────────────────────────────────────────────────────────────

class TierlistCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    tierlist = app_commands.Group(name="tierlist", description="Tierlist management")

    # ── /tierlist create ──────────────────────────────────────────────────────

    @tierlist.command(name="create", description="Create a new tierlist.")
    @app_commands.describe(
        name="Tierlist name",
        tiers="Optional custom tiers separated by commas (e.g. 'S+,S,A,B,C,F')",
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
            description=f"**{name}** is ready.\nTiers: {' › '.join(tier_order)}\n\n"
                        f"*Voting threshold: ±{VOTE_THRESHOLD} votes moves an item up/down a tier.*",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed)

    # ── /tierlist add ─────────────────────────────────────────────────────────

    @tierlist.command(name="add", description="Add an item to a tier.")
    @app_commands.describe(name="Tierlist name", item="Item to add", tier="Which tier (e.g. S, A, B…)")
    async def add(self, interaction: discord.Interaction, name: str, item: str, tier: str):
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
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tier **{tier}** doesn't exist.\nAvailable: `{', '.join(tl['tier_order'])}`",
                    color=0xFF4444,
                ),
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
        save_tierlists(data)

        dot = _tier_dot(tier_upper)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ **{item}** added to {dot} **{tier_upper}** in **{tl['name']}**!",
                color=TIER_COLORS.get(tier_upper, 0x5865F2),
            )
        )

    # ── /tierlist vote ────────────────────────────────────────────────────────

    @tierlist.command(name="vote", description="Vote to move an item up or down the tierlist.")
    @app_commands.describe(
        name="Tierlist name",
        item="Item to vote on",
        direction="Vote up ⬆️ or down ⬇️",
    )
    @app_commands.choices(direction=[
        app_commands.Choice(name="⬆️ Up", value="up"),
        app_commands.Choice(name="⬇️ Down", value="down"),
    ])
    async def vote(self, interaction: discord.Interaction, name: str, item: str, direction: str):
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

        vd = get_vote_data(tl, exact_name)
        user_id = interaction.user.id
        opposite = "down" if direction == "up" else "up"

        # Odeber případný opačný hlas
        if user_id in vd[opposite]:
            vd[opposite].remove(user_id)

        if user_id in vd[direction]:
            # Toggle — odeber stávající hlas
            vd[direction].remove(user_id)
            score = net_score(vd)
            sign = "+" if score > 0 else ""
            score_str = f"{sign}{score}" if score != 0 else "0"
            save_tierlists(data)
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"↩️ Removed your {'⬆️' if direction == 'up' else '⬇️'} vote from **{exact_name}**.\nCurrent score: **[{score_str}]**",
                    color=0x808080,
                ),
                ephemeral=True,
            )
            return

        # Přidej hlas
        vd[direction].append(user_id)
        score = net_score(vd)
        sign = "+" if score > 0 else ""
        score_str = f"{sign}{score}" if score != 0 else "0"

        # Zkontroluj threshold a případně posuň
        move_msg = _apply_vote_and_check_move(tl, exact_name)
        save_tierlists(data)

        arrow = "⬆️" if direction == "up" else "⬇️"
        desc = f"{arrow} Voted **{direction}** for **{exact_name}**!\nCurrent score: **[{score_str}]** *(±{VOTE_THRESHOLD} = auto-move)*"
        if move_msg:
            desc += f"\n\n{move_msg}"

        await interaction.response.send_message(
            embed=discord.Embed(description=desc, color=0x2ECC71 if direction == "up" else 0xFF4444),
            ephemeral=True,
        )

    # ── /tierlist move ────────────────────────────────────────────────────────

    @tierlist.command(name="move", description="Manually move an item to a different tier.")
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
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tier **{tier}** doesn't exist.\nAvailable: `{', '.join(tl['tier_order'])}`",
                    color=0xFF4444,
                ),
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
        # Reset hlasů po manuálním přesunu
        tl.get("votes", {}).pop(exact_name.lower(), None)
        save_tierlists(data)

        dot = _tier_dot(tier_upper)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🔀 **{exact_name}** moved from **{old_tier}** → {dot} **{tier_upper}** *(votes reset)*",
                color=TIER_COLORS.get(tier_upper, 0x5865F2),
            )
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
                len(v.get("up", [])) + len(v.get("down", []))
                for v in tl.get("votes", {}).values()
            )
            embed.add_field(
                name=f"🏆 {tl['name']}",
                value=f"Tiers: `{'` `'.join(tier_order)}`\nItems: **{total_items}** • Votes cast: **{total_votes}** • Author: {tl['author']}",
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
            embed=discord.Embed(description=f"🗑️ **{exact_name}** removed from **{tl['name']}**.", color=0x2ECC71)
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
        if tl.get("author_id") != interaction.user.id and not interaction.user.guild_permissions.manage_guild:
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