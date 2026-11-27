import discord
from discord import app_commands, ui
from discord.ext import commands

from src.database.characters import pkey
from src.utils.paths import DIARIES, NOTES
from src.utils.json_utils import load_json, update_json

PAGE_SIZE = 5


class NotesView(ui.View):
    def __init__(self, lines: list[str]):
        super().__init__(timeout=300)
        self.lines = lines
        self.page = 0
        self.page_count = (len(lines) + PAGE_SIZE - 1) // PAGE_SIZE

    def embed(self) -> discord.Embed:
        start = self.page * PAGE_SIZE
        lines = self.lines[start:start + PAGE_SIZE]
        description = "\n".join(f"**{n}.** {line}" for n, line in enumerate(lines, start + 1))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page + 1 >= self.page_count
        embed = discord.Embed(title="Poznámky aktivní postavy", description=description)
        if self.page_count > 1:
            embed.set_footer(text=f"{self.page + 1} / {self.page_count}")
        return embed

    @ui.button(label="Zpět")
    async def previous(self, interaction: discord.Interaction, button: ui.Button):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @ui.button(label="Další")
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        self.page = min(self.page_count - 1, self.page + 1)
        await interaction.response.edit_message(embed=self.embed(), view=self)


class NotesCog(commands.Cog):
    notes = app_commands.Group(name="notes", description="Soukromé poznámky aktivní postavy")

    @notes.command(name="list", description="Zobraz poznámky aktivní postavy")
    async def list_notes(self, interaction: discord.Interaction):
        lines = load_json(NOTES, default={}).get(pkey(interaction.user.id), [])
        if not lines:
            await interaction.response.send_message(
                "Zatím nemáš žádné poznámky. Přidej první přes `/notes add`.", ephemeral=True)
            return
        view = NotesView(lines)
        await interaction.response.send_message(
            embed=view.embed(), view=view if view.page_count > 1 else discord.utils.MISSING,
            ephemeral=True)

    @notes.command(name="add", description="Přidej poznámku")
    async def add_note(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 600]):
        text = text.strip()
        if not text:
            await interaction.response.send_message("Poznámka je prázdná.", ephemeral=True)
            return
        key = pkey(interaction.user.id)

        def add(data):
            data.setdefault(key, []).append(text)

        saved = update_json(NOTES, add)
        await interaction.response.send_message(
            f"Přidána poznámka č. {len(saved[key])}.", ephemeral=True)

    async def change_note(self, interaction: discord.Interaction, cislo: int, text: str | None):
        if text is not None:
            text = text.strip()
            if not text:
                await interaction.response.send_message("Poznámka je prázdná.", ephemeral=True)
                return
        key = pkey(interaction.user.id)
        changed = False

        def change(data):
            nonlocal changed
            lines = data.get(key, [])
            changed = 1 <= cislo <= len(lines)
            if not changed:
                return
            if text is None:
                lines.pop(cislo - 1)
            else:
                lines[cislo - 1] = text

        update_json(NOTES, change)
        if not changed:
            message = f"Poznámka č. {cislo} neexistuje. Čísla najdeš v `/notes list`."
        else:
            message = f"Poznámka č. {cislo} byla {'smazána' if text is None else 'upravena'}."
        await interaction.response.send_message(message, ephemeral=True)

    @notes.command(name="edit", description="Uprav poznámku podle čísla")
    async def edit_note(self, interaction: discord.Interaction, cislo: app_commands.Range[int, 1],
                        text: app_commands.Range[str, 1, 600]):
        await self.change_note(interaction, cislo, text)

    @notes.command(name="remove", description="Smaž poznámku podle čísla")
    async def remove_note(self, interaction: discord.Interaction, cislo: app_commands.Range[int, 1]):
        await self.change_note(interaction, cislo, None)


async def setup(bot):
    await bot.add_cog(NotesCog())
    if bot.get_cog("QuestsCog") and load_json(DIARIES, default={}):
        update_json(DIARIES, lambda _: {})
