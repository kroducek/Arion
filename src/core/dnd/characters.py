"""
character.py — /character cog: správa postav (multi-character systém).

Cesta:  src/core/dnd/character.py
Přidej do DND_COGS v main_dnd.py (sekce „D&D core"):
        "src.core.dnd.character",

Subpříkazy:
  /character list            — výpis postav + která je aktivní
  /character create <jmeno>  — vytvoří novou postavu (max 2) a spustí tutoriál
  /character switch <slot>   — přepne aktivní postavu (+ přejmenuje v rosteru)
  /character delete <slot>   — smaže postavu (musí zůstat ≥1) + vyčistí její data
"""
import discord
from discord import app_commands
from discord.ext import commands

from src.database.characters import (
    list_chars, char_count, active_name, get_active_slot,
    create_char, switch_char, delete_char, ckey,
    MAX_CHARS,
)
from src.utils.paths import PROFILES, ECONOMY, DIARIES, PLAYER_PERKS, REPUTATION
from src.utils.json_utils import load_json, save_json


# ══════════════════════════════════════════════════════════════════════════════
# Purge per-postava dat (při mazání postavy)
# ══════════════════════════════════════════════════════════════════════════════

def _purge_character_data(uid, slot) -> list:
    """
    Smaže VŠECHNA per-postava data na klíči '<uid>:<slot>'.
    Účtové soubory (silver, stardust, achievementy, guilds, parties) NESAHÁ.
    Vrátí seznam toho, co se reálně smazalo (pro report).
    """
    key = ckey(uid, slot)
    hit = []
    for label, path in (
        ("profil", PROFILES),
        ("zlaté", ECONOMY),
        ("deník", DIARIES),
        ("perky", PLAYER_PERKS),
    ):
        try:
            d = load_json(path, default={})
            if key in d:
                del d[key]
                save_json(path, d)
                hit.append(label)
        except Exception:
            pass

    # reputace má tvar {gid: {players: {key: ...}}}
    try:
        rep = load_json(REPUTATION, default={})
        changed = False
        for gid, gdata in rep.items():
            if not isinstance(gdata, dict):
                continue
            players = gdata.get("players", {})
            if key in players:
                del players[key]
                changed = True
        if changed:
            save_json(REPUTATION, rep)
            hit.append("reputace")
    except Exception:
        pass

    return hit


# ══════════════════════════════════════════════════════════════════════════════
# Potvrzovací view pro mazání
# ══════════════════════════════════════════════════════════════════════════════

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Tohle není tvoje volba.", ephemeral=True)
            return False
        return True

    def _disable(self):
        for c in self.children:
            c.disabled = True

    @discord.ui.button(label="Smazat", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self._disable()
        self.stop()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self._disable()
        self.stop()
        await interaction.response.edit_message(view=self)


# ══════════════════════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════════════════════

class CharacterCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    character = app_commands.Group(name="character", description="Správa tvých postav (max 2)")

    async def _rename_roster(self, interaction: discord.Interaction, name):
        """Přejmenuje hráče v guild/party rosteru = nastaví Discord nick na aktivní postavu."""
        if not name:
            return
        try:
            await interaction.user.edit(nick=name)
        except Exception:
            # chybí práva (Manage Nicknames) nebo je to majitel serveru — nevadí
            pass

    # ──────────────────────────────────────────────────────────────────────────
    @character.command(name="list", description="Zobrazí tvé postavy")
    async def list_cmd(self, interaction: discord.Interaction):
        uid = interaction.user.id
        chars = list_chars(uid)
        if not chars:
            await interaction.response.send_message(
                "Zatím nemáš žádnou postavu. Vytvoř ji přes `/character create`.",
                ephemeral=True,
            )
            return
        active = get_active_slot(uid)
        lines = []
        for slot in sorted(chars.keys()):
            ch = chars[slot]
            mark = "   ⭐ **aktivní**" if slot == active else ""
            lines.append(f"**{slot}.**  {ch.get('name', f'Postava {slot}')}{mark}")
        embed = discord.Embed(
            title="📜 Tvé postavy",
            description="\n".join(lines),
            color=0xFFD700,
        )
        embed.set_footer(text=f"{len(chars)}/{MAX_CHARS} slotů · přepínání přes /character switch")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ──────────────────────────────────────────────────────────────────────────
    @character.command(name="create", description="Vytvoří novou postavu a spustí tutoriál")
    @app_commands.describe(jmeno="Jméno nové postavy")
    async def create_cmd(self, interaction: discord.Interaction, jmeno: str):
        uid = interaction.user.id
        if char_count(uid) >= MAX_CHARS:
            await interaction.response.send_message(
                f"Máš už maximální počet postav (**{MAX_CHARS}**). "
                f"Nejdřív nějakou smaž přes `/character delete`.",
                ephemeral=True,
            )
            return
        jmeno = jmeno.strip()
        if not jmeno:
            await interaction.response.send_message("Zadej jméno postavy.", ephemeral=True)
            return

        slot = create_char(uid, jmeno)  # nastaví nový slot jako aktivní → pkey teď míří na něj
        if slot is None:
            await interaction.response.send_message(
                "Nepodařilo se vytvořit postavu (plno).", ephemeral=True
            )
            return

        await self._rename_roster(interaction, jmeno)

        # spusť onboarding pro nový slot (lazy import kvůli pořadí načítání cogů)
        from src.logic.onboard import TutorialPartOneView
        embed = discord.Embed(
            title="✨ Nová postava",
            description=(
                f"Vytvořil/a sis novou postavu **{jmeno}** (slot {slot}).\n\n"
                "Teď ji provedeš tutoriálem — dostane příběh, statistiky a startovní vybavení. "
                "Tvoje původní postava zůstává v bezpečí, kdykoliv se k ní vrátíš přes "
                "`/character switch`."
            ),
            color=0xFFD700,
        )
        await interaction.response.send_message(
            embed=embed, view=TutorialPartOneView(), ephemeral=True
        )

    # ──────────────────────────────────────────────────────────────────────────
    @character.command(name="switch", description="Přepne aktivní postavu")
    @app_commands.describe(slot="Číslo slotu z /character list")
    async def switch_cmd(self, interaction: discord.Interaction, slot: int):
        uid = interaction.user.id
        slot_s = str(slot)
        chars = list_chars(uid)
        if slot_s not in chars:
            await interaction.response.send_message(
                f"Slot **{slot}** neexistuje. Mrkni na `/character list`.", ephemeral=True
            )
            return
        if get_active_slot(uid) == slot_s:
            await interaction.response.send_message(
                f"Postava **{chars[slot_s].get('name', f'Postava {slot}')}** "
                f"(slot {slot}) už je aktivní.",
                ephemeral=True,
            )
            return
        switch_char(uid, slot_s)
        name = active_name(uid)
        await self._rename_roster(interaction, name)
        await interaction.response.send_message(
            f"⭐ Přepnuto na **{name}** (slot {slot}).", ephemeral=True
        )

    # ──────────────────────────────────────────────────────────────────────────
    @character.command(name="delete", description="Smaže postavu — NEVRATNÉ!")
    @app_commands.describe(slot="Číslo slotu ke smazání")
    async def delete_cmd(self, interaction: discord.Interaction, slot: int):
        uid = interaction.user.id
        slot_s = str(slot)
        chars = list_chars(uid)
        if slot_s not in chars:
            await interaction.response.send_message(
                f"Slot **{slot}** neexistuje.", ephemeral=True
            )
            return
        if len(chars) <= 1:
            await interaction.response.send_message(
                "Tohle je tvoje jediná postava — musí ti zůstat aspoň jedna. "
                "Vytvoř nejdřív druhou, teprve pak můžeš tuhle smazat.",
                ephemeral=True,
            )
            return

        name = chars[slot_s].get("name", f"Postava {slot}")
        view = ConfirmDeleteView(uid)
        embed = discord.Embed(
            title="🗑️ Smazat postavu?",
            description=(
                f"Chystáš se **nevratně** smazat **{name}** (slot {slot}) "
                "i všechna její data — profil, zlaté, deník, perky a reputaci.\n\n"
                "_Stříbro, hvězdný prach a achievementy zůstanou (jsou účtové)._"
            ),
            color=0xE74C3C,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if view.value is not True:
            msg = "Mazání zrušeno." if view.value is False else "Vypršel čas — mazání zrušeno."
            await interaction.edit_original_response(content=msg, embed=None, view=None)
            return

        hit = _purge_character_data(uid, slot_s)
        delete_char(uid, slot_s)  # smaže z registru + přepne aktivní na zbývající
        new_name = active_name(uid)
        await self._rename_roster(interaction, new_name)

        smazano = ", ".join(hit) if hit else "nic (postava byla prázdná)"
        await interaction.edit_original_response(
            content=(
                f"✅ Postava **{name}** smazána. Vyčištěno: {smazano}.\n"
                f"Aktivní je teď **{new_name}**."
            ),
            embed=None,
            view=None,
        )


async def setup(bot):
    await bot.add_cog(CharacterCog(bot))