import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime

# Tlačítko QUESTY se importuje za běhu, aby se předešlo cyklickým importům.
def _get_quest_view(user_id: int):
    try:
        from quests import DiaryQuestView
        return DiaryQuestView(user_id)
    except Exception:
        return None

DIARY_FILE = "diaries.json"
MAX_ENTRIES = 50       # maximalni pocet zaznamu na hrace
MAX_ENTRY_LEN = 300    # maximalni delka jednoho zaznamu


# ── Pomocné funkce ─────────────────────────────────────────────────────────────

def load_diaries() -> dict:
    if os.path.exists(DIARY_FILE):
        try:
            with open(DIARY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_diaries(data: dict):
    with open(DIARY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_entries(user_id: int) -> list:
    data = load_diaries()
    return data.get(str(user_id), [])

def today() -> str:
    return datetime.now().strftime("%d.%m.")

def format_diary(entries: list, name: str) -> list[discord.Embed]:
    """Vrati seznam Embedu (strankovani po 20 zaznamech)."""
    if not entries:
        embed = discord.Embed(
            title="📔 Soukromy denik",
            description=(
                "*Stranky jsou prazdne...*\n\n"
                "Zacni psat prikazem:\n"
                "`/diary add [text]`"
            ),
            color=0x8B6914
        )
        embed.set_footer(text=name)
        return [embed]

    pages = []
    chunk_size = 20
    total = len(entries)
    chunks = [entries[i:i+chunk_size] for i in range(0, total, chunk_size)]

    for page_num, chunk in enumerate(chunks, 1):
        start_idx = (page_num - 1) * chunk_size
        lines = "\n".join(
            f"`[{start_idx + i + 1}]` {entry}"
            for i, entry in enumerate(chunk)
        )
        embed = discord.Embed(
            title="📔 Soukromy denik",
            description=f"{lines}\n\n-# Pouzij `/diary edit line:X` nebo `/diary remove line:X`",
            color=0x8B6914
        )
        if len(chunks) > 1:
            embed.set_footer(text=f"{name}  •  Strana {page_num}/{len(chunks)}  •  Celkem {total} zaznamu")
        else:
            embed.set_footer(text=f"{name}  •  {total} zaznamu")
        pages.append(embed)

    return pages


# ── Diary Modal (pro pridani / editaci) ───────────────────────────────────────

class DiaryEntryModal(discord.ui.Modal):
    text = discord.ui.TextInput(
        label="Zapis do deniku",
        style=discord.TextStyle.paragraph,
        placeholder="Co se dnes stalo...",
        max_length=MAX_ENTRY_LEN,
        required=True
    )

    def __init__(self, user_id: int, edit_line: int = None):
        title = f"Upravit zaznam [{edit_line}]" if edit_line else "Novy zaznam do deniku"
        super().__init__(title=title)
        self.user_id = user_id
        self.edit_line = edit_line

    async def on_submit(self, interaction: discord.Interaction):
        data = load_diaries()
        uid = str(self.user_id)
        entries = data.get(uid, [])
        entry_text = f"{today()} - {self.text.value.strip()}"

        if self.edit_line is not None:
            # Editace existujiciho zaznamu
            idx = self.edit_line - 1
            if idx < 0 or idx >= len(entries):
                await interaction.response.send_message(
                    f"Radek [{self.edit_line}] neexistuje.", ephemeral=True
                )
                return
            entries[idx] = entry_text
            data[uid] = entries
            save_diaries(data)
            await interaction.response.send_message(
                f"✏️ Zaznam `[{self.edit_line}]` byl upraven.", ephemeral=True
            )
        else:
            # Novy zaznam
            if len(entries) >= MAX_ENTRIES:
                await interaction.response.send_message(
                    f"Tvuj denik je plny! ({MAX_ENTRIES} zaznamu). Nektere smaz prikazem `/diary remove`.",
                    ephemeral=True
                )
                return
            entries.append(entry_text)
            data[uid] = entries
            save_diaries(data)
            await interaction.response.send_message(
                f"📝 Zaznam pridan jako `[{len(entries)}]`.", ephemeral=True
            )


# ── Diary Cog ─────────────────────────────────────────────────────────────────

class DiaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Skupiny prikazu
    diary_group = app_commands.Group(name="diary", description="Tvuj soukromy denik")
    admin_diary_group = app_commands.Group(name="admin_diary", description="Admin: sprava deniku hracu")

    # ── /diary add ────────────────────────────────────────────────────────────

    @diary_group.command(name="add", description="Pridej novy zaznam do deniku")
    async def diary_add(self, interaction: discord.Interaction):
        modal = DiaryEntryModal(user_id=interaction.user.id)
        await interaction.response.send_modal(modal)

    # ── /diary show ───────────────────────────────────────────────────────────

    @diary_group.command(name="show", description="Zobraz svuj soukromy denik")
    async def diary_show(self, interaction: discord.Interaction):
        entries = get_entries(interaction.user.id)
        pages = format_diary(entries, interaction.user.display_name)

        view = _get_quest_view(interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
        for page in pages[1:]:
            await interaction.followup.send(embed=page, ephemeral=True)

    # ── /diary edit ───────────────────────────────────────────────────────────

    @diary_group.command(name="edit", description="Uprav zaznam na danem radku")
    @app_commands.describe(line="Cislo radku (viz /diary show)")
    async def diary_edit(self, interaction: discord.Interaction, line: int):
        entries = get_entries(interaction.user.id)
        if not entries:
            await interaction.response.send_message("Tvuj denik je prazdny.", ephemeral=True)
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Radek [{line}] neexistuje. Mas {len(entries)} zaznamu.", ephemeral=True
            )
            return
        modal = DiaryEntryModal(user_id=interaction.user.id, edit_line=line)
        await interaction.response.send_modal(modal)

    # ── /diary remove ─────────────────────────────────────────────────────────

    @diary_group.command(name="remove", description="Smaz zaznam na danem radku")
    @app_commands.describe(line="Cislo radku (viz /diary show)")
    async def diary_remove(self, interaction: discord.Interaction, line: int):
        data = load_diaries()
        uid = str(interaction.user.id)
        entries = data.get(uid, [])

        if not entries:
            await interaction.response.send_message("Tvuj denik je prazdny.", ephemeral=True)
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Radek [{line}] neexistuje. Mas {len(entries)} zaznamu.", ephemeral=True
            )
            return

        removed = entries.pop(line - 1)
        data[uid] = entries
        save_diaries(data)

        # Zobraz preview smazaneho zaznamu (prvnich 60 znaku)
        preview = removed[:60] + "..." if len(removed) > 60 else removed
        await interaction.response.send_message(
            f"🗑️ Zaznam `[{line}]` byl smazan.\n-# *{preview}*",
            ephemeral=True
        )

    # ── /admin_diary view ─────────────────────────────────────────────────────

    @admin_diary_group.command(name="view", description="Zobraz denik daneho hrace")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hrac, jehoz denik chces zobrazit")
    async def admin_diary_view(self, interaction: discord.Interaction, member: discord.Member):
        entries = get_entries(member.id)
        pages = format_diary(entries, f"Denik: {member.display_name}")

        # Admin vidi bez ephemeral (nebo s - zmenitelne)
        await interaction.response.send_message(embed=pages[0], ephemeral=True)
        for page in pages[1:]:
            await interaction.followup.send(embed=page, ephemeral=True)

    # ── /admin_diary edit ─────────────────────────────────────────────────────

    @admin_diary_group.command(name="edit", description="Uprav zaznam v deniku hrace")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hrac", line="Cislo radku", new_text="Novy text zaznamu")
    async def admin_diary_edit(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        line: int,
        new_text: str
    ):
        if len(new_text) > MAX_ENTRY_LEN:
            await interaction.response.send_message(
                f"Text je prilis dlouhy (max {MAX_ENTRY_LEN} znaku).", ephemeral=True
            )
            return

        data = load_diaries()
        uid = str(member.id)
        entries = data.get(uid, [])

        if not entries:
            await interaction.response.send_message(
                f"{member.display_name} ma prazdny denik.", ephemeral=True
            )
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Radek [{line}] neexistuje. Hrac ma {len(entries)} zaznamu.", ephemeral=True
            )
            return

        entries[line - 1] = f"{today()} - {new_text.strip()}"
        data[uid] = entries
        save_diaries(data)

        await interaction.response.send_message(
            f"✏️ Zaznam `[{line}]` v deniku hrace **{member.display_name}** byl upraven.",
            ephemeral=True
        )

    # ── /admin_diary remove ───────────────────────────────────────────────────

    @admin_diary_group.command(name="remove", description="Smaz konkretni zaznam z deniku hrace")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hrac", line="Cislo radku")
    async def admin_diary_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        line: int
    ):
        data = load_diaries()
        uid = str(member.id)
        entries = data.get(uid, [])

        if not entries:
            await interaction.response.send_message(
                f"{member.display_name} ma prazdny denik.", ephemeral=True
            )
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Radek [{line}] neexistuje.", ephemeral=True
            )
            return

        removed = entries.pop(line - 1)
        data[uid] = entries
        save_diaries(data)

        preview = removed[:60] + "..." if len(removed) > 60 else removed
        await interaction.response.send_message(
            f"🗑️ Zaznam `[{line}]` v deniku **{member.display_name}** byl smazan.\n-# *{preview}*",
            ephemeral=True
        )

    # ── /admin_diary clear ────────────────────────────────────────────────────

    @admin_diary_group.command(name="clear", description="Kompletne vymaze denik hrace")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hrac, jehoz denik chces smazat")
    async def admin_diary_clear(self, interaction: discord.Interaction, member: discord.Member):
        data = load_diaries()
        uid = str(member.id)
        count = len(data.get(uid, []))

        if count == 0:
            await interaction.response.send_message(
                f"{member.display_name} uz ma prazdny denik.", ephemeral=True
            )
            return

        data[uid] = []
        save_diaries(data)

        await interaction.response.send_message(
            f"🗑️ Denik hrace **{member.display_name}** byl vycisten ({count} zaznamu smazano).",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(DiaryCog(bot))