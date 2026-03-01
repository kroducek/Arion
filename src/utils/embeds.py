"""
Moduly pro vytváření Discord Embed zpráv
"""
import discord
from typing import Optional


def _add_watermark(embed: discord.Embed) -> discord.Embed:
    """Přidá watermark Aurionimu do footeru embedu"""
    embed.set_footer(text="✨ Aurionis ✨")
    return embed


def create_error_embed(title: str, description: str, color: int = 0xFF0000) -> discord.Embed:
    """Vytvoří chybový embed"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    return _add_watermark(embed)


def create_success_embed(title: str, description: str, color: int = 0x00FF00) -> discord.Embed:
    """Vytvoří úspěšný embed"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    return _add_watermark(embed)


def create_info_embed(title: str, description: str, color: int = 0x0000FF) -> discord.Embed:
    """Vytvoří informační embed"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )
    return _add_watermark(embed)


def create_party_embed(
    party_name: str,
    quest: str,
    members: list,
    leader_id: int,
    is_private: bool = False,
    color: int = 0xFFD700,
    emoji: Optional[str] = None
) -> discord.Embed:
    """Vytvoří embed pro družinu"""
    member_list = "\n".join(
        [f"{'👑' if m == leader_id else '🗡️'} <@{m}>" for m in members]
    )
    
    privacy_badge = "🔒 Soukromá" if is_private else "🔓 Veřejná"
    title = f"{emoji} {party_name}" if emoji else f"⚔️ {party_name}"
    
    embed = discord.Embed(
        title=title,
        description=f"**Cíl:** `{quest}`\n**Status:** {privacy_badge}",
        color=color
    )
    embed.add_field(name=f"Členové ({len(members)})", value=member_list, inline=False)
    return _add_watermark(embed)


def create_parties_list_embed(parties: dict, color: int = 0xFFD700) -> discord.Embed:
    """Vytvoří embed se seznamem všech družin"""
    embed = discord.Embed(
        title="📜 Všechny družiny",
        color=color
    )
    
    if not parties:
        embed.description = "Zatím žádné družiny neexistují!"
        return _add_watermark(embed)
    
    for party_name, data in parties.items():
        member_count = len(data["members"])
        quest = data.get("quest", "Neznámý cíl")
        privacy_badge = "🔒" if data.get("is_private", False) else "🔓"
        emoji_prefix = data.get("emoji", "")
        display_name = f"{emoji_prefix} {party_name}" if emoji_prefix else party_name
        embed.add_field(
            name=f"{privacy_badge} {display_name}",
            value=f"Členů: {member_count}\nCíl: `{quest}`",
            inline=False
        )
    
    return _add_watermark(embed)
