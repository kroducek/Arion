"""Tierlist Cog – Arion Bot
Hráči si mohou vytvářet tierlistry, přidávat položky a řadit je do tierů.
"""

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import json
import os

# ── Cesta k datům ─────────────────────────────────────────────────────────────

try:
    from src.utils import paths as _paths
    DATA_PATH = _paths.data("tierlists.json")
except Exception:
    DATA_PATH = "src/database/data/tierlists.json"

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

# ── Embed builder ──────────────────────────────────────────────────────────────

def build_tierlist_embed(name: str, tierlist: dict) -> discord.Embed:
    tiers = tierlist.get("tiers", {})
    tier_order = tierlist.get("tier_order", DEFAULT_TIERS)

    embed = discord.Embed(
        title=f"🏆 Tierlist: {name}",
        color=0xFFD700,
    )
    embed.set_footer(text=f"Vytvořil: {tierlist.get('author', '?')} • Položky lze přidávat přes /tierlist pridat")

    has_any = False
    for tier in tier_order:
        items = tiers.get(tier, [])
        if items:
            has_any = True
        color_dot = _tier_dot(tier)
        embed.add_field(
            name=f"{color_dot} **{tier}**",
            value=", ".join(f"`{i}`" for i in items) if items else "*prázdný*",
            inline=False,
        )

    if not has_any:
        embed.description = "*Tierlist je zatím prázdný. Přidej položky přes `/tierlist pridat`.*"

    return embed

def _tier_dot(tier: str) -> str:
    dots = {
        "S+": "🩷", "S": "🔴", "A": "🟠", "B": "🟡",
        "C": "🟢", "D": "🔵", "E": "🟣", "F": "⚫",
    }
    return dots.get(tier, "⚪")

# ── Cog ───────────────────────────────────────────────────────────────────────

class TierlistCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    tierlist = app_commands.Group(
        name="tierlist",
        description="Správa tierlistů",
    )

    # ── /tierlist vytvorit ─────────────────────────────────────────────────────

    @tierlist.command(name="vytvorit", description="Vytvoří nový tierlist.")
    @app_commands.describe(
        nazev="Název tierlistu (např. 'gaming' nebo 'nas skvely tierlist')",
        tiery="Volitelné vlastní tiery oddělené čárkou (např. 'S+,S,A,B,C,F'). Výchozí: S+,S,A,B,C,D,E,F",
    )
    async def vytvorit(
        self,
        interaction: discord.Interaction,
        nazev: str,
        tiery: Optional[str] = None,
    ):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, nazev)

        if key in data:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tierlist **{nazev}** již existuje!",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        tier_order = [t.strip() for t in tiery.split(",")] if tiery else DEFAULT_TIERS
        tier_order = [t for t in tier_order if t]

        data[key] = {
            "name": nazev,
            "author": interaction.user.display_name,
            "author_id": interaction.user.id,
            "tier_order": tier_order,
            "tiers": {tier: [] for tier in tier_order},
        }
        save_tierlists(data)

        embed = discord.Embed(
            title="✅ Tierlist vytvořen!",
            description=f"**{nazev}** je připraven.\nTiery: {' › '.join(tier_order)}",
            color=0x2ECC71,
        )
        embed.set_footer(text="Přidej položky přes /tierlist pridat")
        await interaction.response.send_message(embed=embed)

    # ── /tierlist pridat ───────────────────────────────────────────────────────

    @tierlist.command(name="pridat", description="Přidá položku do tieru.")
    @app_commands.describe(
        nazev="Název tierlistu",
        polozka="Co chceš přidat (např. 'Minecraft' nebo 'Pizza')",
        tier="Do jakého tieru zařadit (např. S, A, B…)",
    )
    async def pridat(
        self,
        interaction: discord.Interaction,
        nazev: str,
        polozka: str,
        tier: str,
    ):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, nazev)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tierlist **{nazev}** neexistuje. Vytvoř ho přes `/tierlist vytvorit`.",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        tl = data[key]
        tier_upper = tier.upper()

        if tier_upper not in tl["tiers"]:
            dostupne = ", ".join(tl["tier_order"])
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tier **{tier}** neexistuje.\nDostupné tiery: `{dostupne}`",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        for t, items in tl["tiers"].items():
            if polozka.lower() in [i.lower() for i in items]:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"⚠️ **{polozka}** už je v tieru **{t}**!",
                        color=0xFFA500,
                    ),
                    ephemeral=True,
                )
                return

        tl["tiers"][tier_upper].append(polozka)
        save_tierlists(data)

        dot = _tier_dot(tier_upper)
        embed = discord.Embed(
            description=f"✅ **{polozka}** přidán/a do tieru {dot} **{tier_upper}** v tierlistu **{tl['name']}**!",
            color=TIER_COLORS.get(tier_upper, 0x5865F2),
        )
        await interaction.response.send_message(embed=embed)

    # ── /tierlist presunout ────────────────────────────────────────────────────

    @tierlist.command(name="presunout", description="Přesune položku do jiného tieru.")
    @app_commands.describe(
        nazev="Název tierlistu",
        polozka="Položka kterou chceš přesunout",
        tier="Nový tier",
    )
    async def presunout(
        self,
        interaction: discord.Interaction,
        nazev: str,
        polozka: str,
        tier: str,
    ):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, nazev)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{nazev}** neexistuje.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        tier_upper = tier.upper()

        if tier_upper not in tl["tiers"]:
            dostupne = ", ".join(tl["tier_order"])
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tier **{tier}** neexistuje.\nDostupné: `{dostupne}`",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        stary_tier = None
        for t, items in tl["tiers"].items():
            for i in items:
                if i.lower() == polozka.lower():
                    stary_tier = t
                    items.remove(i)
                    break
            if stary_tier:
                break

        if not stary_tier:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Položka **{polozka}** nebyla nalezena v tierlistu **{tl['name']}**.",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        tl["tiers"][tier_upper].append(polozka)
        save_tierlists(data)

        dot = _tier_dot(tier_upper)
        embed = discord.Embed(
            description=f"🔀 **{polozka}** přesunut/a z **{stary_tier}** → {dot} **{tier_upper}**",
            color=TIER_COLORS.get(tier_upper, 0x5865F2),
        )
        await interaction.response.send_message(embed=embed)

    # ── /tierlist zobrazit ─────────────────────────────────────────────────────

    @tierlist.command(name="zobrazit", description="Zobrazí tierlist.")
    @app_commands.describe(nazev="Název tierlistu")
    async def zobrazit(self, interaction: discord.Interaction, nazev: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, nazev)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Tierlist **{nazev}** neexistuje.",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        embed = build_tierlist_embed(nazev, data[key])
        await interaction.response.send_message(embed=embed)

    # ── /tierlist seznam ───────────────────────────────────────────────────────

    @tierlist.command(name="seznam", description="Zobrazí všechny tierlistry na tomto serveru.")
    async def seznam(self, interaction: discord.Interaction):
        data = load_tierlists()
        prefix = f"{interaction.guild_id}:"
        server_lists = {k: v for k, v in data.items() if k.startswith(prefix)}

        if not server_lists:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="📭 Na tomto serveru zatím nejsou žádné tierlistry.\nVytvoř první přes `/tierlist vytvorit`!",
                    color=0x5865F2,
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📋 Tierlistry na tomto serveru", color=0x5865F2)
        for k, tl in server_lists.items():
            tier_order = tl.get("tier_order", DEFAULT_TIERS)
            total_items = sum(len(v) for v in tl["tiers"].values())
            embed.add_field(
                name=f"🏆 {tl['name']}",
                value=f"Tiery: `{'` `'.join(tier_order)}`\nPoložek: **{total_items}** • Autor: {tl['author']}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ── /tierlist smazat_polozku ───────────────────────────────────────────────

    @tierlist.command(name="smazat_polozku", description="Odebere položku z tierlistu.")
    @app_commands.describe(
        nazev="Název tierlistu",
        polozka="Položka kterou chceš odebrat",
    )
    async def smazat_polozku(
        self,
        interaction: discord.Interaction,
        nazev: str,
        polozka: str,
    ):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, nazev)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{nazev}** neexistuje.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        nalezeno = False
        for t, items in tl["tiers"].items():
            for i in items:
                if i.lower() == polozka.lower():
                    items.remove(i)
                    nalezeno = True
                    break
            if nalezeno:
                break

        if not nalezeno:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"❌ Položka **{polozka}** nebyla nalezena.",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        save_tierlists(data)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🗑️ **{polozka}** odebrán/a z tierlistu **{tl['name']}**.",
                color=0x2ECC71,
            )
        )

    # ── /tierlist smazat ──────────────────────────────────────────────────────

    @tierlist.command(name="smazat", description="Smaže celý tierlist (pouze autor nebo admin).")
    @app_commands.describe(nazev="Název tierlistu který chceš smazat")
    async def smazat(self, interaction: discord.Interaction, nazev: str):
        data = load_tierlists()
        key = tierlist_key(interaction.guild_id, nazev)

        if key not in data:
            await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Tierlist **{nazev}** neexistuje.", color=0xFF4444),
                ephemeral=True,
            )
            return

        tl = data[key]
        is_author = tl.get("author_id") == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild

        if not is_author and not is_admin:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ Tierlist může smazat pouze jeho autor nebo admin.",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        del data[key]
        save_tierlists(data)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🗑️ Tierlist **{nazev}** byl smazán.",
                color=0x2ECC71,
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TierlistCog(bot))