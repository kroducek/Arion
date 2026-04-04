import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from src.utils.paths import PROFILES as PROFILES_FILE
from src.utils.json_utils import load_json, save_json

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load() -> dict:
    return load_json(PROFILES_FILE, default={})

def _save(data: dict) -> None:
    save_json(PROFILES_FILE, data)

def _get_memories(uid: str) -> list[str]:
    return _load().get(uid, {}).get("memories", [])

def _memories_embed(member: discord.Member, memories: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title=f"📜  Vzpomínky — {member.display_name}",
        color=0x6c5ce7,
    )
    if not memories:
        embed.description = (
            "*Prázdná stránka… jako by se minulost rozplynula v mlze.*\n\n"
            "-# Použij `/memory add` pro zapsání vzpomínky."
        )
    else:
        embed.description = "\n".join(f"`{i+1}.` {m}" for i, m in enumerate(memories))
        embed.set_footer(text=f"{len(memories)} vzpomínek  ·  ✨ Aurionis")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class MemoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    memory = app_commands.Group(name="memory", description="Správa vzpomínek tvé postavy.")

    # ── /memory show ──────────────────────────────────────────────────────────

    @memory.command(name="show", description="Zobraz vzpomínky své (nebo jiné) postavy.")
    @app_commands.describe(member="Hráč (výchozí: ty)")
    async def memory_show(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ):
        target   = member or interaction.user
        memories = _get_memories(str(target.id))
        embed    = _memories_embed(target, memories)
        await interaction.response.send_message(embed=embed, ephemeral=(member is None))

    # ── /memory add ───────────────────────────────────────────────────────────

    @memory.command(name="add", description="Zapiš novou vzpomínku.")
    @app_commands.describe(text="Text vzpomínky.")
    async def memory_add(self, interaction: discord.Interaction, text: str):
        data = _load()
        uid  = str(interaction.user.id)
        data.setdefault(uid, {}).setdefault("memories", [])
        data[uid]["memories"].append(text.strip())
        _save(data)
        count = len(data[uid]["memories"])
        await interaction.response.send_message(
            f"📜 Vzpomínka zapsána na řádek **{count}**.", ephemeral=True)
        if interaction.channel:
            await interaction.channel.send(
                f"📜 **{interaction.user.display_name}** si úspěšně vzpomněl/a."
            )

    # ── /memory remove ────────────────────────────────────────────────────────

    @memory.command(name="remove", description="Smaž vzpomínku na zadaném řádku.")
    @app_commands.describe(line="Číslo řádku (viz /memory show).")
    async def memory_remove(self, interaction: discord.Interaction, line: int):
        data     = _load()
        uid      = str(interaction.user.id)
        memories = data.get(uid, {}).get("memories", [])
        if line < 1 or line > len(memories):
            await interaction.response.send_message(
                f"❌ Řádek **{line}** neexistuje. Máš {len(memories)} vzpomínek.", ephemeral=True)
            return
        removed = memories.pop(line - 1)
        data.setdefault(uid, {})["memories"] = memories
        _save(data)
        await interaction.response.send_message(
            f"🗑️ Vzpomínka na řádku **{line}** smazána:\n> {removed}", ephemeral=True)

    # ── /memory edit ──────────────────────────────────────────────────────────

    @memory.command(name="edit", description="Uprav vzpomínku na zadaném řádku.")
    @app_commands.describe(line="Číslo řádku.", text="Nový text.")
    async def memory_edit(self, interaction: discord.Interaction, line: int, text: str):
        data     = _load()
        uid      = str(interaction.user.id)
        memories = data.get(uid, {}).get("memories", [])
        if line < 1 or line > len(memories):
            await interaction.response.send_message(
                f"❌ Řádek **{line}** neexistuje. Máš {len(memories)} vzpomínek.", ephemeral=True)
            return
        old = memories[line - 1]
        memories[line - 1] = text.strip()
        data.setdefault(uid, {})["memories"] = memories
        _save(data)
        embed = discord.Embed(title="✏️  Vzpomínka upravena", color=0x6c5ce7)
        embed.add_field(name="Bylo", value=f"> {old}",          inline=False)
        embed.add_field(name="Je",   value=f"> {text.strip()}", inline=False)
        embed.set_footer(text=f"Řádek {line}  ·  ✨ Aurionis")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /memory admin ─────────────────────────────────────────────────────────

    @memory.command(name="admin", description="[Admin] Zobraz nebo uprav vzpomínky hráče.")
    @app_commands.describe(
        member="Hráč",
        akce="Co chceš udělat.",
        line="Číslo řádku (pro remove/edit).",
        text="Text (pro add/edit).",
    )
    @app_commands.choices(akce=[
        app_commands.Choice(name="show",   value="show"),
        app_commands.Choice(name="add",    value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="edit",   value="edit"),
        app_commands.Choice(name="clear",  value="clear"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def memory_admin(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        akce: app_commands.Choice[str],
        line: Optional[int] = None,
        text: Optional[str] = None,
    ):
        data = _load()
        uid  = str(member.id)
        data.setdefault(uid, {}).setdefault("memories", [])
        memories: list = data[uid]["memories"]

        match akce.value:
            case "show":
                embed = _memories_embed(member, memories)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            case "add":
                if not text:
                    await interaction.response.send_message("❌ Zadej text.", ephemeral=True)
                    return
                memories.append(text.strip())
                msg = f"📜 Vzpomínka přidána ({member.mention}) na řádek **{len(memories)}**."
            case "remove":
                if not line or line < 1 or line > len(memories):
                    await interaction.response.send_message(
                        f"❌ Neplatný řádek. Hráč má {len(memories)} vzpomínek.", ephemeral=True)
                    return
                removed = memories.pop(line - 1)
                msg = f"🗑️ Smazána vzpomínka {member.mention} řádek **{line}**:\n> {removed}"
            case "edit":
                if not line or not text or line < 1 or line > len(memories):
                    await interaction.response.send_message(
                        "❌ Zadej platný řádek a text.", ephemeral=True)
                    return
                memories[line - 1] = text.strip()
                msg = f"✏️ Upravena vzpomínka {member.mention} řádek **{line}**."
            case "clear":
                memories.clear()
                msg = f"🗑️ Všechny vzpomínky hráče {member.mention} smazány."
            case _:
                return

        data[uid]["memories"] = memories
        _save(data)
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(MemoryCog(bot))
