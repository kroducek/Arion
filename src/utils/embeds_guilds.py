"""
Guild embedy — přidej tyto funkce na konec src/utils/embeds.py.
Používají stejný _add_watermark a styl jako party embedy.
"""
import discord
from typing import Optional


# Odznaky režimu náboru
_RECRUITMENT_BADGE = {
    "open": "🟢 Otevřená",
    "apply": "🟡 Na přihlášku",
    "closed": "🔴 Uzavřená",
}


def create_guild_embed(
    guild_name: str,
    quest: str,
    members: list,
    guildmaster_id: int,
    officers: Optional[list] = None,
    tag: Optional[str] = None,
    description: Optional[str] = None,
    recruitment: str = "open",
    capacity: int = 50,
    color: int = 0xFFD700,
    emoji: Optional[str] = None,
) -> discord.Embed:
    """Vytvoří embed pro guildu (3 úrovně hodností)."""
    officers = officers or []

    # Členy řadíme podle hodnosti: vůdce → důstojníci → členové
    def _rank_icon(uid: int) -> str:
        if uid == guildmaster_id:
            return "👑"
        if uid in officers:
            return "🛡️"
        return "⚔️"

    def _rank_order(uid: int) -> int:
        if uid == guildmaster_id:
            return 0
        if uid in officers:
            return 1
        return 2

    ordered = sorted(members, key=_rank_order)
    member_list = "\n".join(f"{_rank_icon(m)} <@{m}>" for m in ordered) or "*Prázdná guilda*"

    tag_prefix = f"[{tag}] " if tag else ""
    base_title = f"{emoji} {guild_name}" if emoji else f"🏰 {guild_name}"
    title = f"{tag_prefix}{base_title}"

    recruit_badge = _RECRUITMENT_BADGE.get(recruitment, "🟢 Otevřená")

    desc_parts = [f"**Motto:** `{quest}`", f"**Nábor:** {recruit_badge}"]
    if description:
        desc_parts.insert(0, description)

    embed = discord.Embed(
        title=title,
        description="\n".join(desc_parts),
        color=color,
    )
    embed.add_field(
        name=f"Členové ({len(members)}/{capacity})",
        value=member_list,
        inline=False,
    )
    embed.set_footer(text="✨ Aurionis ✨")
    return embed


def create_guilds_list_embed(guilds: dict, color: int = 0xFFD700) -> discord.Embed:
    """Vytvoří embed se seznamem všech guild."""
    embed = discord.Embed(title="🏰 Všechny guildy", color=color)

    if not guilds:
        embed.description = "Zatím žádné guildy neexistují!"
        embed.set_footer(text="✨ Aurionis ✨")
        return embed

    for guild_name, data in guilds.items():
        members = data.get("members", [])
        capacity = data.get("capacity", 50)
        quest = data.get("quest", "Neznámé motto")
        recruit_badge = _RECRUITMENT_BADGE.get(data.get("recruitment", "open"), "🟢")
        tag = data.get("tag")
        emoji_prefix = data.get("emoji", "")

        tag_prefix = f"[{tag}] " if tag else ""
        display_name = f"{emoji_prefix} {guild_name}" if emoji_prefix else guild_name

        embed.add_field(
            name=f"{tag_prefix}{display_name}",
            value=f"{recruit_badge} • Členů: {len(members)}/{capacity}\nMotto: `{quest}`",
            inline=False,
        )

    embed.set_footer(text="✨ Aurionis ✨")
    return embed