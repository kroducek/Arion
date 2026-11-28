import asyncio
import random
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import (
    TAKEDOWNS,
)
from src.utils.json_utils import load_json, save_json
from src.database.characters import list_chars
from src.database.deaths import archive_account_characters
from src.utils.admin_gate import mark_admin

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

DM_ROLE_NAME = "DM"

def _is_dm(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return any(r.name == DM_ROLE_NAME for r in interaction.user.roles)

def _get_count() -> int:
    data = load_json(TAKEDOWNS, default={"count": 0})
    return data.get("count", 0)

def _increment_count() -> int:
    data = load_json(TAKEDOWNS, default={"count": 0})
    data["count"] = data.get("count", 0) + 1
    save_json(TAKEDOWNS, data)
    return data["count"]

def _bar(filled: int, total: int = 3) -> str:
    return "▰" * filled + "▱" * (total - filled)


def _glitch(text: str, intensity: float) -> str:
    """Rozloží jméno na glitch bloky. intensity 0.0-1.0."""
    blocks = "▓▒░#%&@"
    return "".join(
        random.choice(blocks) if (c != " " and random.random() < intensity) else c
        for c in text
    )


class TakedownConfirm(discord.ui.View):
    """Bod zvratu — potvrzení nevratného rozsudku."""

    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.result = None

    @discord.ui.button(label="VYKONAT", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def execute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Tohle není tvůj rozsudek.", ephemeral=True)
        self.result = True
        self.stop()
        await interaction.response.edit_message(
            content="⚔️ *Rozsudek padl. TAKEDOWN byl úspěšný🥳*", embed=None, view=None)

    @discord.ui.button(label="Ušetřit", emoji="🕊️", style=discord.ButtonStyle.secondary)
    async def spare(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("Tohle není tvůj rozsudek.", ephemeral=True)
        self.result = False
        self.stop()
        await interaction.response.edit_message(
            content="🕊️ *Arion odvrátila zrak.. pro tentokrát.*", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class TakedownCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="takedown", description="[DM] Arion provede Takedown na hráče.")
    @app_commands.describe(member="Hráč, který se zprotivil Arion")
    @mark_admin
    async def takedown(self, interaction: discord.Interaction, member: discord.Member):
        if not _is_dm(interaction):
            await interaction.response.send_message("❌ Nemáš oprávnění.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        ch  = interaction.channel
        uid = member.id
        chars = list_chars(uid)
        if not chars:
            await interaction.followup.send("Hráč nemá žádnou postavu k archivaci.", ephemeral=True)
            return
        targets = ", ".join(char.get("name", f"Slot {slot}") for slot, char in chars.items())
        name = member.display_name           # zachyť jméno DŘÍV, než zmizí

        # ── BOD ZVRATU — nevratný rozsudek se musí potvrdit ───────────────────
        judgment = discord.Embed(
            title="⚖️  ARION SOUDÍ",
            description=(f"**{member.mention}** se zprotivil/a Arion.\n\n"
                        "Následuje **Takedown**❗️\n"
                        f"Archivuje všechny uvedené postavy: **{targets}**."),
            color=_C_EMBER,
        )
        confirm = TakedownConfirm(interaction.user.id)
        await interaction.followup.send(embed=judgment, view=confirm, ephemeral=True)
        await confirm.wait()
        if confirm.result is not True:
            return   # ušetřeno nebo vypršel čas — nic se nestane

        try:
            archive_account_characters(uid, chars, "takedown")
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        # ── REŽIJNÍ HELPERY ──────────────────────────────────────────────────
        async def type_beat(seconds: float):
            """Ukáže 'Arion píše…' a chvíli počká — buduje napětí."""
            try:
                async with ch.typing():
                    await asyncio.sleep(seconds)
            except Exception:
                await asyncio.sleep(seconds)

        async def line(text: str, delay: float = 1.4, pre: float = 0.0):
            if pre:
                await type_beat(pre)
            try:
                await ch.send(text)
            except discord.HTTPException:
                pass
            if delay:
                await asyncio.sleep(delay)

        async def scene(title: str, desc: str, color: int, delay: float = 2.0, pre: float = 0.0):
            if pre:
                await type_beat(pre)
            try:
                await ch.send(embed=discord.Embed(title=title, description=desc, color=color))
            except discord.HTTPException:
                pass
            if delay:
                await asyncio.sleep(delay)

        # ── I. PROBUZENÍ (pomalu, zlověstně) ─────────────────────────────────
        await line("*Yeah, I saw your real face and its ugly as sin*", delay=2.4, pre=1.5)
        await line("*Its time to out you in your place cuz you’re rotten within*", delay=2.6, pre=2.0)

        # ── II. ROZSUDEK ─────────────────────────────────────────────────────
        await scene(
            "⚔️  TAKEDOWN",
            f"{member.mention} — When your patterns start to show, it makes the Hatred wanna grow outta my veins",
            _C_BLOOD, delay=2.4, pre=1.5,
        )

        # ── III. STUPŇOVÁNÍ (zrychluje) ──────────────────────────────────────
        await line("Takedown.. Takedown..", delay=1.0, pre=1.0)
        await line("Takedown.. Takedown..", delay=1.0, pre=0.8)
        await line("I wish you best luck gettin to our level", delay=1.6, pre=1.0)

        # ── IV. ROZKLAD (jeden embed, plní se lišta; jméno se rozpadá) ────────
        unmaking = await ch.send(embed=discord.Embed(
            title="⚙️  R O Z K L A D",
            description=f"```\n[{_bar(0)}]\n```\n*Arion vztáhla drápy na {name}.*",
            color=_C_EMBER))
        await asyncio.sleep(1.8)

        # drop 1 — inventář
        await type_beat(1.6)
        await unmaking.edit(embed=discord.Embed(
            title="🗑️  …Takedown❗️",
            description=(f"```\n[{_bar(1)}]\n```\n"
                        f"I’ll break you **{_glitch(name, 0.15)}** inti — pieces in the world of pain"),
            color=_C_BLOOD))
        await asyncio.sleep(2.4)

        await line("cuz you’re all the same", delay=1.4, pre=1.0)

        # drop 2 — profil
        await type_beat(1.6)
        await unmaking.edit(embed=discord.Embed(
            title="💀  …TAKEDOWN❗️",
            description=(f"```\n[{_bar(2)}]\n```\n"
                        f"**{_glitch(name, 0.55)}** Demon with no feelings dont deserve to live, its so obvious"),
            color=_C_CRIMSON))
        await asyncio.sleep(2.6)

        # ── V. ODPOČET (nevyhnutelnost) ──────────────────────────────────────
        cd = await ch.send(embed=discord.Embed(
            title="⚔️  3", description="*Ima gear up*", color=_C_CRIMSON))
        for nnum in (2, 1):
            await asyncio.sleep(1.0)
            try:
                await cd.edit(embed=discord.Embed(
                    title=f"⚔️  {nnum}", description="*And take you down!*", color=_C_CRIMSON))
            except discord.HTTPException:
                pass
        await asyncio.sleep(1.0)

        # ── VI. ÚDER (ban) ───────────────────────────────────────────────────
        try:
            await member.ban(reason=f"Takedown — provedl {interaction.user}")
            ban_ok = True
        except discord.Forbidden:
            ban_ok = False

        await unmaking.edit(embed=discord.Embed(
            title="🔨  …Arion Security system🛠️",
            description=(f"```\n[{_bar(3)}]\n```\n"
                        + ("**Brána se zavřela. Navždy.**" if ban_ok
                           else "*Ban selhal — Arion chybí oprávnění.*")),
            color=_C_FLARE))

        # ── VII. TICHO (ať to dosedne) ───────────────────────────────────────
        await asyncio.sleep(3.5)

        # ── VIII. ZÁVĚR ──────────────────────────────────────────────────────
        total = _increment_count()
        await scene(
            "✅  Takedown dokončen",
            f"Arion se protáhla a ulehla zpět.\n"
            f"-# Na svém kontě má už **{total}** Takedownů. *Ticho po bouři.*",
            _C_ASH, delay=0, pre=1.5,
        )


async def setup(bot):
    await bot.add_cog(TakedownCog(bot))
