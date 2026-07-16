"""
lore.py — pool lore střípků měst s rotací á 12 h.

Cesta: src/core/dnd/lore.py
Přidej do main_dnd.py DND_COGS:  "src.core.dnd.lore"

Každé město má vlastní pool. Zobrazený střípek se přepíná podle času —
každých 12 h se ukáže další z poolu (deterministicky, bez cronu), takže se
hráčům při návratu do hubu objeví nový a všem stejný.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import time

from src.utils.paths import QUESTS as QUESTS_FILE
from src.utils.json_utils import load_json, save_json
from src.utils.audit import log_action

logger = logging.getLogger("Lore")

try:
    from src.logic.onboard import DESTINATIONS
except Exception:
    logger.exception("[lore] import DESTINATIONS selhal")
    DESTINATIONS = {}

ROTATION_SECONDS = 12 * 3600           # střípek se mění každých 12 h
LORE_COLOR = 0x6C5CE7

_DATA_DIR  = os.path.dirname(QUESTS_FILE)
LORE_FILE  = os.path.join(_DATA_DIR, "lore_pool.json")


def load_lore() -> dict:
    """{dest_key: [ "střípek", ... ]}"""
    return load_json(LORE_FILE, default={})

def save_lore(data: dict):
    save_json(LORE_FILE, data)


def dest_label(key: str | None) -> str:
    d = DESTINATIONS.get(key or "")
    return f"{d['emoji']} {d['name']}" if d else (key or "—")


def current_fragment(location: str, pool: dict | None = None) -> str | None:
    """Střípek pro danou lokaci v aktuálním 12h okně. None když je pool prázdný.

    Index se počítá z času — deterministicky, takže všem hráčům ukáže tentýž
    střípek a po 12 h se posune na další. Žádný stav se neukládá.
    """
    pool = pool if pool is not None else load_lore()
    frags = pool.get(location, [])
    if not frags:
        return None
    window = int(time.time() // ROTATION_SECONDS)
    return frags[window % len(frags)]


def seconds_to_next_rotation() -> int:
    now = time.time()
    return int(ROTATION_SECONDS - (now % ROTATION_SECONDS))


class LoreCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    lore = app_commands.Group(name="lore", description="Lore střípky měst (admin)")

    def _dest_choices():
        return [app_commands.Choice(name=f"{d['emoji']} {d['name']}", value=k)
                for k, d in DESTINATIONS.items()]

    @lore.command(name="add", description="[Admin] Přidá lore střípek do poolu města.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(mesto="Které město.", text="Text střípku.")
    @app_commands.choices(mesto=_dest_choices())
    async def lore_add(self, interaction: discord.Interaction, mesto: str, text: str):
        await interaction.response.defer(ephemeral=True)
        pool = load_lore()
        pool.setdefault(mesto, []).append(text.strip())
        save_lore(pool)
        log_action("lore_add", interaction.user.display_name, mesto, text[:60])
        await interaction.followup.send(
            f"✅ Střípek přidán do {dest_label(mesto)} "
            f"(celkem **{len(pool[mesto])}**).", ephemeral=True)

    @lore.command(name="list", description="[Admin] Vypíše střípky města.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(mesto="Které město.")
    @app_commands.choices(mesto=_dest_choices())
    async def lore_list(self, interaction: discord.Interaction, mesto: str):
        await interaction.response.defer(ephemeral=True)
        frags = load_lore().get(mesto, [])
        if not frags:
            await interaction.followup.send(
                f"{dest_label(mesto)} zatím nemá žádné střípky.", ephemeral=True)
            return
        cur = current_fragment(mesto)
        lines = []
        for i, f in enumerate(frags):
            mark = "▶️" if f == cur else f"{i+1}."
            lines.append(f"{mark} {f[:150]}")
        desc = "\n".join(lines)
        if len(desc) > 3900:
            desc = desc[:3900] + "\n-# …"
        embed = discord.Embed(
            title=f"📖 Lore střípky — {dest_label(mesto)} ({len(frags)})",
            description=desc, color=LORE_COLOR)
        embed.set_footer(text="▶️ = právě zobrazený střípek")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @lore.command(name="remove", description="[Admin] Odebere střípek podle čísla z /lore list.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(mesto="Které město.", cislo="Pořadí střípku (z /lore list).")
    @app_commands.choices(mesto=_dest_choices())
    async def lore_remove(self, interaction: discord.Interaction, mesto: str, cislo: int):
        await interaction.response.defer(ephemeral=True)
        pool = load_lore()
        frags = pool.get(mesto, [])
        if not (1 <= cislo <= len(frags)):
            await interaction.followup.send(
                f"❌ Neplatné číslo (1–{len(frags)}).", ephemeral=True)
            return
        removed = frags.pop(cislo - 1)
        save_lore(pool)
        log_action("lore_remove", interaction.user.display_name, mesto, removed[:60])
        await interaction.followup.send(
            f"🗑️ Odebráno z {dest_label(mesto)}: *{removed[:80]}*", ephemeral=True)

    @lore.command(name="next", description="[Admin] Ručně posune střípek na další (napříč městy).")
    @app_commands.checks.has_permissions(administrator=True)
    async def lore_next(self, interaction: discord.Interaction):
        # Rotace je časová (deterministická), takže "posun" uděláme přes board refresh —
        # tady jen řekneme, za jak dlouho se přepne sama, a nabídneme ruční překreslení.
        await interaction.response.defer(ephemeral=True)
        secs = seconds_to_next_rotation()
        h, m = secs // 3600, (secs % 3600) // 60
        msg = f"⏳ Další střípek se objeví sám za **{h} h {m} min**."
        try:
            from src.core.dnd.board import refresh_all_boards
            errs = await refresh_all_boards(self.bot)
            msg += "\n-# Nástěnky překresleny (aktuální okno)."
            if errs:
                msg += "\n⚠️ " + " · ".join(errs[:3])
        except Exception:
            pass
        await interaction.followup.send(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LoreCog(bot))