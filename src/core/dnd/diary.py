import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
from datetime import datetime

# Tlačítko QUESTY se importuje za běhu, aby se předešlo cyklickým importům.
def _get_quest_view(user_id: int):
    try:
        from src.core.dnd.quests import DiaryQuestView
        return DiaryQuestView(user_id)
    except Exception:
        return None

# ── Konstanty ─────────────────────────────────────────────────────────────────

from src.utils.paths import DIARIES as DIARY_FILE
from src.utils.json_utils import load_json, save_json
MAX_ENTRIES   = 50    # maximální počet záznamů na hráče
MAX_ENTRY_LEN = 300   # maximální délka jednoho záznamu
PAGE_SIZE     = 10    # záznamů na stránku (méně = přehlednější)

DIARY_COLOR   = 0x5C4033   # teplá tmavě hnědá — jako kůže deníku
PIN_EMOJI     = "⭐"
EMOJI_RE      = re.compile(
    r"(\U0001F300-\U0001F9FF"   # různé emoji bloky
    r"|\U00002600-\U000027BF"
    r"|\U0001FA00-\U0001FA9F"
    r"|\u2300-\u23FF"
    r"|\u2B50|\u2B55"
    r"|\U0001F004|\U0001F0CF)",
    re.UNICODE
)

# ── Datová vrstva ──────────────────────────────────────────────────────────────
#
# Formát záznamu v JSON:
#   {
#     "text":   "dd.mm. - obsah záznamu",
#     "pinned": false,
#     "tag":    "🔥"   (nebo null)
#   }
#
# Starý formát (prostý string) je při načtení automaticky migrován.

def load_diaries() -> dict:
    return load_json(DIARY_FILE)

def save_diaries(data: dict):
    save_json(DIARY_FILE, data)

def migrate_entry(raw) -> dict:
    """Převede starý string formát na nový dict formát."""
    if isinstance(raw, dict):
        return raw
    return {"text": str(raw), "pinned": False, "tag": None}

def get_entries(user_id: int) -> list[dict]:
    data = load_diaries()
    raw  = data.get(str(user_id), [])
    return [migrate_entry(e) for e in raw]

def today() -> str:
    return datetime.now().strftime("%d.%m.")

def extract_first_emoji(text: str) -> str | None:
    """Najde první emoji v textu a vrátí ho, nebo None."""
    # Zkus Unicode emoji
    for char in text:
        cp = ord(char)
        if (0x1F300 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF) or cp in (0x2B50, 0x2B55, 0x1F004, 0x1F0CF):
            return char
    return None

def entry_display(entry: dict, number: int) -> str:
    """Naformátuje jeden záznam pro výpis."""
    pin    = f"{PIN_EMOJI} " if entry.get("pinned") else ""
    tag    = f"{entry['tag']} " if entry.get("tag") else ""
    text   = entry.get("text", "")
    return f"`[{number}]` {pin}{tag}{text}"

# ── Stránkovací View ───────────────────────────────────────────────────────────

class DiaryPageView(discord.ui.View):
    """Interaktivní stránkování deníku — ◀ ▶ tlačítka na jedné zprávě."""

    def __init__(self, pages: list[discord.Embed], user_id: int, timeout: int = 180):
        super().__init__(timeout=timeout)
        self.pages   = pages
        self.user_id = user_id
        self.current = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current == 0
        self.next_btn.disabled = self.current >= len(self.pages) - 1

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Tohle není tvůj deník!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.current -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        self.current += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current], view=self)

    async def on_timeout(self):
        # Odstraň tlačítka po vypršení
        for item in self.children:
            item.disabled = True

# ── Formátování embedů ────────────────────────────────────────────────────────

def _make_embed(title: str, description: str, footer: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=DIARY_COLOR)
    embed.set_footer(text=footer)
    return embed

def format_diary(
    entries: list[dict],
    name: str,
    filter_tag: str | None = None,
    pinned_only: bool = False,
) -> list[discord.Embed]:
    """
    Vrátí seznam Embedů (stránky).
    Volitelně filtruje podle tagu nebo jen oblíbené.
    Čísla řádků vždy odpovídají skutečné pozici v deníku.
    """
    # Filtrování — čísla zachováme podle originálu
    indexed = list(enumerate(entries, 1))   # [(1, entry), (2, entry), ...]

    if pinned_only:
        indexed = [(n, e) for n, e in indexed if e.get("pinned")]
    elif filter_tag:
        indexed = [(n, e) for n, e in indexed if e.get("tag") == filter_tag]

    title = "📔 Soukromý deník"
    if pinned_only:
        title = f"⭐ Oblíbené záznamy"
    elif filter_tag:
        title = f"{filter_tag}  Záznamy s tagem"

    if not indexed:
        if pinned_only:
            desc = "*Žádné oblíbené záznamy.*\n\n-# Přidej je pomocí `/diary pin line:X`"
        elif filter_tag:
            desc = f"*Žádné záznamy s tagem {filter_tag}.*"
        else:
            desc = (
                "*Stránky jsou prázdné...*\n\n"
                "Začni psát příkazem:\n"
                "`/diary add`"
            )
        return [_make_embed(title, desc, name)]

    total   = len(indexed)
    chunks  = [indexed[i:i + PAGE_SIZE] for i in range(0, total, PAGE_SIZE)]
    pages   = []

    for page_num, chunk in enumerate(chunks, 1):
        lines = "\n".join(entry_display(e, n) for n, e in chunk)
        desc  = f"{lines}\n\n-# `/diary edit` · `/diary remove` · `/diary pin` · `/diary tag`"

        if len(chunks) > 1:
            footer = f"{name}  ·  Strana {page_num}/{len(chunks)}  ·  {total} záznamů"
        else:
            count_label = "1 záznam" if total == 1 else f"{total} záznamů"
            footer = f"{name}  ·  {count_label}"

        pages.append(_make_embed(title, desc, footer))

    return pages

# ── Modály ────────────────────────────────────────────────────────────────────

class DiaryAddModal(discord.ui.Modal, title="Nový záznam do deníku"):
    text = discord.ui.TextInput(
        label="Zápis",
        style=discord.TextStyle.paragraph,
        placeholder="Co se dnes stalo...",
        max_length=MAX_ENTRY_LEN,
        required=True,
    )

    def __init__(self, user_id: int, tag: str | None = None):
        super().__init__()
        self.user_id = user_id
        self.tag     = tag   # předáno z příkazu, už validované emoji

    async def on_submit(self, interaction: discord.Interaction):
        data    = load_diaries()
        uid     = str(self.user_id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]

        if len(entries) >= MAX_ENTRIES:
            await interaction.response.send_message(
                f"Tvůj deník je plný! ({MAX_ENTRIES} záznamů) — nejdřív něco smaž přes `/diary remove`.",
                ephemeral=True,
            )
            return

        entry = {"text": f"{today()} — {self.text.value.strip()}", "pinned": False, "tag": self.tag}
        entries.append(entry)
        data[uid] = entries
        save_diaries(data)

        tag_info = f" s tagem {self.tag}" if self.tag else ""
        await interaction.response.send_message(
            f"📝 Záznam přidán jako `[{len(entries)}]`{tag_info}.",
            ephemeral=True,
        )


class DiaryEditModal(discord.ui.Modal):
    text = discord.ui.TextInput(
        label="Nový text záznamu",
        style=discord.TextStyle.paragraph,
        max_length=MAX_ENTRY_LEN,
        required=True,
    )

    def __init__(self, user_id: int, line: int, current_text: str):
        super().__init__(title=f"Upravit záznam [{line}]")
        self.user_id = user_id
        self.line    = line
        # Předvyplň pole původním textem (bez datumu)
        self.text.default = current_text

    async def on_submit(self, interaction: discord.Interaction):
        data    = load_diaries()
        uid     = str(self.user_id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]
        idx     = self.line - 1

        if idx < 0 or idx >= len(entries):
            await interaction.response.send_message(
                f"Záznam [{self.line}] již neexistuje.", ephemeral=True
            )
            return

        # Zachovej původní datum, přepiš jen text — přidej "(upraveno)"
        original_date = entries[idx]["text"].split("—")[0].strip() if "—" in entries[idx]["text"] else today()
        entries[idx]["text"] = f"{original_date} — {self.text.value.strip()} *(upraveno)*"
        data[uid] = entries
        save_diaries(data)

        await interaction.response.send_message(
            f"✏️ Záznam `[{self.line}]` byl upraven.",
            ephemeral=True,
        )

# ── Diary Cog ─────────────────────────────────────────────────────────────────

class DiaryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    diary_group       = app_commands.Group(name="diary",       description="Tvůj soukromý deník")
    admin_diary_group = app_commands.Group(name="admin_diary", description="Admin: správa deníků hráčů")

    # ── /diary add ────────────────────────────────────────────────────────────

    @diary_group.command(name="add", description="Přidej nový záznam do deníku")
    @app_commands.describe(tag="Emoji tag záznamu (volitelné) — vyber přímo z Discord emoji pickeru")
    async def diary_add(self, interaction: discord.Interaction, tag: str | None = None):
        # Validace tagu — musí být emoji, ne text jako ":sob:"
        tag_value = None
        if tag:
            tag_value = extract_first_emoji(tag.strip())
            if not tag_value:
                await interaction.response.send_message(
                    "Tag musí být emoji — vyber ho přímo z Discord emoji pickeru 😊",
                    ephemeral=True,
                )
                return
        await interaction.response.send_modal(DiaryAddModal(user_id=interaction.user.id, tag=tag_value))

    # ── /diary show ───────────────────────────────────────────────────────────

    @diary_group.command(name="show", description="Zobraz svůj soukromý deník")
    @app_commands.describe(tag="Filtrovat záznamy podle emoji tagu (volitelné)")
    async def diary_show(self, interaction: discord.Interaction, tag: str | None = None):
        entries = get_entries(interaction.user.id)

        # Validace tagu
        filter_tag = None
        if tag:
            first = extract_first_emoji(tag.strip())
            if not first:
                await interaction.response.send_message(
                    "Tag musí být emoji, například 🔥 nebo ✨", ephemeral=True
                )
                return
            filter_tag = first

        pages = format_diary(entries, interaction.user.display_name, filter_tag=filter_tag)
        view  = DiaryPageView(pages, interaction.user.id)

        # Přidej quest tlačítko pokud existuje (pouze na první stránce)
        quest_view = _get_quest_view(interaction.user.id)
        if quest_view and not filter_tag:
            for item in quest_view.children:
                view.add_item(item)

        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    # ── /diary pinned ─────────────────────────────────────────────────────────

    @diary_group.command(name="pinned", description="Zobraz své oblíbené záznamy")
    async def diary_pinned(self, interaction: discord.Interaction):
        entries = get_entries(interaction.user.id)
        pages   = format_diary(entries, interaction.user.display_name, pinned_only=True)
        view    = DiaryPageView(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    # ── /diary pin ────────────────────────────────────────────────────────────

    @diary_group.command(name="pin", description="Přidej/odeber záznam z oblíbených")
    @app_commands.describe(line="Číslo řádku (viz /diary show)")
    async def diary_pin(self, interaction: discord.Interaction, line: int):
        data    = load_diaries()
        uid     = str(interaction.user.id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]

        if not entries:
            await interaction.response.send_message("Tvůj deník je prázdný.", ephemeral=True)
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Záznam [{line}] neexistuje. Máš {len(entries)} záznamů.", ephemeral=True
            )
            return

        entries[line - 1]["pinned"] = not entries[line - 1]["pinned"]
        pinned = entries[line - 1]["pinned"]
        data[uid] = entries
        save_diaries(data)

        action = f"{PIN_EMOJI} Přidáno do oblíbených" if pinned else "Odebráno z oblíbených"
        await interaction.response.send_message(
            f"{action}: záznam `[{line}]`.", ephemeral=True
        )

    # ── /diary tag ────────────────────────────────────────────────────────────

    @diary_group.command(name="tag", description="Nastav emoji tag záznamu (nebo ho odeber)")
    @app_commands.describe(line="Číslo řádku", tag="Emoji tag (nech prázdné pro odebrání)")
    async def diary_tag(self, interaction: discord.Interaction, line: int, tag: str | None = None):
        data    = load_diaries()
        uid     = str(interaction.user.id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]

        if not entries:
            await interaction.response.send_message("Tvůj deník je prázdný.", ephemeral=True)
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Záznam [{line}] neexistuje. Máš {len(entries)} záznamů.", ephemeral=True
            )
            return

        if tag:
            first = extract_first_emoji(tag.strip())
            if not first:
                await interaction.response.send_message(
                    "Tag musí být emoji, například 🔥 nebo 💭", ephemeral=True
                )
                return
            entries[line - 1]["tag"] = first
            msg = f"{first} Tag nastaven na záznamu `[{line}]`."
        else:
            entries[line - 1]["tag"] = None
            msg = f"Tag záznamu `[{line}]` byl odebrán."

        data[uid] = entries
        save_diaries(data)
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /diary edit ───────────────────────────────────────────────────────────

    @diary_group.command(name="edit", description="Uprav záznam na daném řádku")
    @app_commands.describe(line="Číslo řádku (viz /diary show)")
    async def diary_edit(self, interaction: discord.Interaction, line: int):
        entries = get_entries(interaction.user.id)

        if not entries:
            await interaction.response.send_message("Tvůj deník je prázdný.", ephemeral=True)
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Záznam [{line}] neexistuje. Máš {len(entries)} záznamů.", ephemeral=True
            )
            return

        # Předvyplň modal textem bez datumové části
        raw_text = entries[line - 1]["text"]
        current  = raw_text.split("—", 1)[1].strip() if "—" in raw_text else raw_text
        # Odstraň případné "(upraveno)" z předchozích editací
        current  = current.replace(" *(upraveno)*", "").strip()

        await interaction.response.send_modal(
            DiaryEditModal(user_id=interaction.user.id, line=line, current_text=current)
        )

    # ── /diary remove ─────────────────────────────────────────────────────────

    @diary_group.command(name="remove", description="Smaž záznam na daném řádku")
    @app_commands.describe(line="Číslo řádku (viz /diary show)")
    async def diary_remove(self, interaction: discord.Interaction, line: int):
        data    = load_diaries()
        uid     = str(interaction.user.id)
        entries = [migrate_entry(e) for e in data.get(uid, [])]

        if not entries:
            await interaction.response.send_message("Tvůj deník je prázdný.", ephemeral=True)
            return
        if line < 1 or line > len(entries):
            await interaction.response.send_message(
                f"Záznam [{line}] neexistuje. Máš {len(entries)} záznamů.", ephemeral=True
            )
            return

        removed = entries.pop(line - 1)
        data[uid] = entries
        save_diaries(data)

        preview = removed["text"][:60] + "…" if len(removed["text"]) > 60 else removed["text"]
        await interaction.response.send_message(
            f"🗑️ Záznam `[{line}]` byl smazán.\n-# *{preview}*",
            ephemeral=True,
        )

    # ── /admin_diary view ─────────────────────────────────────────────────────

    @admin_diary_group.command(name="view", description="Zobraz deník daného hráče")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč, jehož deník chceš zobrazit")
    async def admin_diary_view(self, interaction: discord.Interaction, member: discord.Member):
        entries = get_entries(member.id)
        pages   = format_diary(entries, f"Deník: {member.display_name}")
        view    = DiaryPageView(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    # ── /admin_diary edit ─────────────────────────────────────────────────────

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
        uid     = str(member.id)
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

    # ── /admin_diary remove ───────────────────────────────────────────────────

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
        uid     = str(member.id)
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

    # ── /admin_diary clear ────────────────────────────────────────────────────

    @admin_diary_group.command(name="clear", description="Kompletně vymaže deník hráče")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(member="Hráč, jehož deník chceš smazat")
    async def admin_diary_clear(self, interaction: discord.Interaction, member: discord.Member):
        data  = load_diaries()
        uid   = str(member.id)
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
    await bot.add_cog(DiaryCog(bot))