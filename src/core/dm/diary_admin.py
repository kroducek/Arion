"""Admin správa deníků hráčů — běží v ArionDM.

Datová vrstva i vykreslování zůstávají v `src.core.dnd.diary`, aby se hráčská
a adminská část nerozešly.
"""
import discord
from discord import app_commands
from discord.ext import commands

from src.core.dnd.diary import (
    MAX_ENTRY_LEN,
    DiaryPageView,
    format_diary,
    get_entries,
    load_diaries,
    migrate_entry,
    save_diaries,
    today,
)
from src.database.characters import pkey


class DiaryAdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    admin_diary_group = app_commands.Group(name="admin_diary", description="Admin: správa deníků hráčů")

    @admin_diary_group.command(name="view", description="Zobraz deník daného hráče")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč, jehož deník chceš zobrazit")
    async def admin_diary_view(self, interaction: discord.Interaction, member: discord.Member):
        entries = get_entries(member.id)
        pages   = format_diary(entries, f"Deník: {member.display_name}")
        view    = DiaryPageView(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    @admin_diary_group.command(name="edit", description="Uprav záznam v deníku hráče")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč", line="Číslo řádku", new_text="Nový text záznamu")
    async def admin_diary_edit(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        line: int,
        new_text: str,
    ):
        if len(new_text) > MAX_ENTRY_LEN:
            await interaction.response.send_message(
                f"Text je příliš dlouhý (max {MAX_ENTRY_LEN} znaků).", ephemeral=True
            )
            return

        data    = load_diaries()
        uid     = pkey(member.id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]

        if not entries:
            await interaction.response.send_message(
                f"{member.display_name} má prázdný deník.", ephemeral=True
            )
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Záznam [{line}] neexistuje. Hráč má {len(entries)} záznamů.", ephemeral=True
            )
            return

        original_date = entries[line - 1]["text"].split("—")[0].strip() if "—" in entries[line - 1]["text"] else today()
        entries[line - 1]["text"] = f"{original_date} — {new_text.strip()} *(admin)*"
        data[uid] = entries
        save_diaries(data)

        await interaction.response.send_message(
            f"✏️ Záznam `[{line}]` v deníku **{member.display_name}** byl upraven.",
            ephemeral=True,
        )

    @admin_diary_group.command(name="remove", description="Smaž konkrétní záznam z deníku hráče")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč", line="Číslo řádku")
    async def admin_diary_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        line: int,
    ):
        data    = load_diaries()
        uid     = pkey(member.id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]

        if not entries:
            await interaction.response.send_message(
                f"{member.display_name} má prázdný deník.", ephemeral=True
            )
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Záznam [{line}] neexistuje.", ephemeral=True
            )
            return

        removed = entries.pop(line - 1)
        data[uid] = entries
        save_diaries(data)

        preview = removed["text"][:60] + "…" if len(removed["text"]) > 60 else removed["text"]
        await interaction.response.send_message(
            f"🗑️ Záznam `[{line}]` v deníku **{member.display_name}** byl smazán.\n-# *{preview}*",
            ephemeral=True,
        )

    @admin_diary_group.command(name="clear", description="Kompletně vymaže deník hráče")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč, jehož deník chceš smazat")
    async def admin_diary_clear(self, interaction: discord.Interaction, member: discord.Member):
        data  = load_diaries()
        uid   = pkey(member.id)
        count = len(data.get(uid, []))

        if count == 0:
            await interaction.response.send_message(
                f"{member.display_name} už má prázdný deník.", ephemeral=True
            )
            return

        data[uid] = []
        save_diaries(data)

        await interaction.response.send_message(
            f"🗑️ Deník hráče **{member.display_name}** byl vyčištěn ({count} záznamů smazáno).",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(DiaryAdminCog(bot))
