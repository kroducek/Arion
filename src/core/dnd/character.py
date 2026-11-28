"""
character.py — /character cog: správa postav (multi-character systém).

Cesta:  src/core/dnd/character.py
Přidej do DND_COGS v main_dnd.py (sekce „D&D core"):
        "src.core.dnd.character",

Subpříkazy:
  /character list            — výpis postav + která je aktivní
  /character create <jmeno>  — vytvoří novou postavu (max 2) a spustí tutoriál
  /character switch <slot>   — přepne aktivní postavu (+ přejmenuje v rosteru)
  /character archive       — DM archivuje postavu a uvolní její slot
"""
import discord
from discord import app_commands
from discord.ext import commands

from src.database.characters import (
    list_chars, char_count, active_name, get_active_slot,
    create_char, switch_char, approve_rp,
    MAX_CHARS,
)
from src.database import db
from src.database.deaths import ARCHIVE, archive_character, restore_character
from src.utils.admin_gate import admin_only


class ConfirmArchiveView(discord.ui.View):
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

    @discord.ui.button(label="Archivovat", style=discord.ButtonStyle.danger, emoji="📦")
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

    async def _rename_roster(self, member: discord.Member, name):
        """Přejmenuje hráče v guild/party rosteru = nastaví Discord nick na aktivní postavu."""
        if not name:
            return
        try:
            await member.edit(nick=name)
        except Exception:
            # chybí práva (Manage Nicknames) nebo je to majitel serveru — nevadí
            pass

    async def _resync_rank_role(self, member: discord.Member):
        """Rank role sedí na Discord UŽIVATELI, ale rank je PER POSTAVA — po přepnutí
        (nebo smazání) aktivní postavy je proto nutné roli přerovnat na její rank."""
        try:
            from src.core.dnd.ranks import get_rank, sync_rank_role
            rank, _ = get_rank(member.id)
            await sync_rank_role(member, rank)
        except Exception:
            pass          # rank cog nemusí být načtený / chybí role — nevadí

    async def _slot_autocomplete(self, interaction: discord.Interaction, current: str):
        """Nabídne sloty hráče jako '1 · Kaiser ⭐' místo ručního psaní čísla."""
        uid = interaction.user.id
        chars = list_chars(uid)
        active = get_active_slot(uid)
        cur = (current or "").lower().strip()
        choices = []
        for slot in sorted(chars.keys()):
            name = chars[slot].get("name", f"Postava {slot}")
            if cur and cur not in slot.lower() and cur not in name.lower():
                continue
            label = f"{slot} · {name}" + ("  ⭐" if slot == active else "")
            choices.append(app_commands.Choice(name=label[:100], value=int(slot)))
        return choices[:25]

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
            pending = " · čeká na schválení RP" if ch.get("rp_pending") else ""
            lines.append(f"**{slot}.**  {ch.get('name', f'Postava {slot}')}{mark}{pending}")
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
                f"Požádej DM o archivaci některé postavy.",
                ephemeral=True,
            )
            return
        jmeno = jmeno.strip()
        if not jmeno:
            await interaction.response.send_message("Zadej jméno postavy.", ephemeral=True)
            return

        slot = create_char(uid, jmeno, request_rp_approval=True)  # nastaví nový slot jako aktivní → pkey teď míří na něj
        if slot is None:
            await interaction.response.send_message(
                "Nepodařilo se vytvořit postavu (plno).", ephemeral=True
            )
            return

        await self._rename_roster(interaction.user, jmeno)

        # achievement za druhou postavu (účtový — 2+ postavy na účtu)
        try:
            from src.core.dnd.achievements import check_two_characters_achievement
            await check_two_characters_achievement(
                interaction.user, interaction.channel, char_count(uid))
        except Exception:
            pass

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
            embed=embed, view=TutorialPartOneView(uid), ephemeral=True
        )

    # ──────────────────────────────────────────────────────────────────────────
    @character.command(name="switch", description="Přepne aktivní postavu")
    @app_commands.describe(slot="Číslo slotu z /character list")
    @app_commands.autocomplete(slot=_slot_autocomplete)
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
        await self._rename_roster(interaction.user, name)
        await self._resync_rank_role(interaction.user)
        await interaction.response.send_message(
            f"⭐ Přepnuto na **{name}** (slot {slot}).", ephemeral=True
        )

    # ──────────────────────────────────────────────────────────────────────────
    @character.command(name="approve", description="[DM] Schval postavě vstup do RP.")
    @admin_only()
    async def approve_cmd(self, interaction: discord.Interaction, hrac: discord.Member, slot: int):
        try:
            approve_rp(hrac.id, slot)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Postava ve slotu {slot} hráče {hrac.mention} může dokončit vstup do RP.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @character.command(name="archive", description="[DM] Archivuj postavu a uvolni její slot.")
    @admin_only()
    async def archive_cmd(self, interaction: discord.Interaction, hrac: discord.Member, slot: int,
                          duvod: app_commands.Range[str, 1, 200]):
        char = list_chars(hrac.id).get(str(slot))
        if char is None:
            await interaction.response.send_message("Tento slot je prázdný.", ephemeral=True)
            return
        view = ConfirmArchiveView(interaction.user.id)
        await interaction.response.send_message(
            f"Archivovat **{char.get('name', 'Postava')}** hráče {hrac.mention} ze slotu {slot}?",
            view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        await view.wait()
        if not view.value:
            await interaction.edit_original_response(content="Archivace zrušena.", view=None)
            return
        try:
            character_id = archive_character(hrac.id, slot, char, duvod.strip() or "rozhodnutí DM")
        except ValueError as exc:
            await interaction.edit_original_response(content=str(exc), view=None)
            return
        await interaction.edit_original_response(
            content=f"Postava archivována. ID: {character_id}.", view=None)
        await self._rename_roster(hrac, active_name(hrac.id))
        await self._resync_rank_role(hrac)

    @character.command(name="archives", description="[DM] Zobraz archivované postavy a jejich ID.")
    @admin_only()
    async def archives_cmd(self, interaction: discord.Interaction,
                           hrac: discord.Member | None = None, strana: app_commands.Range[int, 1] = 1):
        await interaction.response.defer(ephemeral=True)
        archives = db.load_doc(ARCHIVE, {})
        rows = [(key, data) for key, data in archives.items()
                if hrac is None or data["uid"] == str(hrac.id)]
        rows.sort(key=lambda row: row[1]["archived_at"], reverse=True)
        offset = (strana - 1) * 10
        lines = []
        for key, data in rows[offset:offset + 10]:
            status = " · obnovena" if data.get("restored_at") else ""
            lines.append(f"**{data['character'].get('name', 'Postava')}** · <@{data['uid']}>"
                         f" · <t:{data['archived_at']}:d>{status}\n"
                         f"{key} · {data['reason'][:200]}")
        if not lines:
            await interaction.followup.send("Na této stránce nejsou žádné archivované postavy.", ephemeral=True)
            return
        embed = discord.Embed(title="Archiv postav", description="\n\n".join(lines))
        embed.set_footer(text=f"Strana {strana} / {(len(rows) + 9) // 10}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @character.command(name="restore", description="[DM] Obnov archivovanou postavu původnímu hráči.")
    @admin_only()
    async def restore_cmd(self, interaction: discord.Interaction, id_postavy: str):
        await interaction.response.defer(ephemeral=True)
        try:
            uid, slot, char, skipped = restore_character(id_postavy.strip())
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        message = f"**{char.get('name', 'Postava')}** obnovena hráči <@{uid}> do slotu {slot}."
        if skipped:
            message += f" {len(skipped)} questů už neexistuje nebo je má jiná postava hráče."
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        member = interaction.guild.get_member(int(uid))
        if member is not None:
            await self._rename_roster(member, active_name(uid))
            await self._resync_rank_role(member)


async def setup(bot):
    await bot.add_cog(CharacterCog(bot))
