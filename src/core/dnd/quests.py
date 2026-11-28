import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import unicodedata
from uuid import uuid4
from datetime import datetime

from src.utils.paths import QUESTS as QUESTS_FILE, QUEST_LOG as QUEST_LOG_FILE
from src.utils.json_utils import load_json, save_json
from src.core.dnd.ranks import (
    DIFFICULTY, DEFAULT_DIFFICULTY, award_rank_to_profile, quest_points, sync_rank_role,
)
from src.utils.audit import log_action, get_recent
from src.logic.stats import award_xp_to_profile, _profile
from src.database import db
from src.database.characters import character_id, get_active_slot, get_char
from src.utils.admin_gate import admin_only

ARION_NAME = "Aurionis"

# ── Status a kategorie ────────────────────────────────────────────────────────

class Status:
    ACTIVE    = "aktivní"
    COMPLETED = "dokončený"
    FAILED    = "neúspěšný"
    REMOVED   = "odebraný"

class Category:
    MAIN = "main"
    SIDE = "side"
    SOLO = "solo"

STATUS_META = {
    Status.ACTIVE:    {"emoji": "🟢", "color": 0x2E6B3E},
    Status.COMPLETED: {"emoji": "✅", "color": 0x2E86C1},
    Status.FAILED:    {"emoji": "❌", "color": 0x922B21},
    Status.REMOVED:   {"emoji": "🗃️", "color": 0x786C60},
}

CATEGORY_META = {
    Category.MAIN: {"emoji": "⚔️",  "label": "Main Quest"},
    Category.SIDE: {"emoji": "🗺️", "label": "Side Quest"},
    Category.SOLO: {"emoji": "🎯", "label": "Solo Quest"},
}

# ── Destinace z tutoriálu → side quest větve "Volání hvězdy" ──────────────────
# Hráč si v tutoriálu vybere jednu ze tří destinací a podle ní dostane JEN
# odpovídající side quest (ne všechny tři) — viz assign_destination_quest níž.
# Klíče jsou bez diakritiky a malými písmeny, porovnává se přes _normalize_destination.

DESTINATION_SIDE_QUEST = {
    "lumenie":      "Stíny v srdci",
    "aquion":       "Šampion podsvětí",
    "draci skala":  "Draci",
    "dracia skala": "Draci",   # alternativní zápis, pro jistotu
}


def _normalize_destination(text: str) -> str:
    """Odstraní diakritiku, sjednotí oddělovače a převede na malá písmena —
    tolerantní porovnání jak lidsky psaného názvu ('Dračí skála'), tak
    interního klíče ('draci_skala')."""
    nfkd = unicodedata.normalize("NFKD", text.strip().lower())
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.replace("_", " ").replace("-", " ")


def resolve_destination_quest(destination: str) -> str | None:
    """Najde jméno side questu podle tutoriálové destinace, nebo None když neznámá."""
    return DESTINATION_SIDE_QUEST.get(_normalize_destination(destination))


# ── Pomocné funkce ─────────────────────────────────────────────────────────────

def load_quests() -> dict:
    return load_json(QUESTS_FILE)

def save_quests(data: dict):
    save_json(QUESTS_FILE, data)

def load_quest_log() -> list:
    raw = load_json(QUEST_LOG_FILE, [])
    # Ochrana: pokud soubor obsahuje dict místo listu (starý formát), vrať prázdný list
    return raw if isinstance(raw, list) else []

def save_quest_log(data: list):
    save_json(QUEST_LOG_FILE, data)

def today() -> str:
    return datetime.now().strftime("%d.%m.")

def _parse_xp(xp_str) -> int:
    """Parsuje XP zápis ('160 000', '2 500 XP', 12000) na int. 0 = nečitelné."""
    if not xp_str:
        return 0
    if isinstance(xp_str, (int, float)):
        return max(0, int(xp_str))
    text = str(xp_str).strip().lower()
    for suffix in ("xp", "exp"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    # Pryč s libovolnými mezerami (i nezlomitelnou) a oddělovači tisíců
    digits = "".join(c for c in text if not c.isspace() and c not in ",.'\u00a0")
    try:
        return int(digits)
    except ValueError:
        return 0

def _xp_warning(xp) -> str:
    """Varování pro admina, když je XP vyplněné, ale nedá se z něj udělat číslo."""
    if xp and _parse_xp(xp) <= 0:
        return f"\n⚠️ XP `{xp}` nejde přečíst jako číslo — při dokončení se nikomu nic nepřipíše."
    return ""


# ── Postavy: quest si pamatuje, které postavě patří ──────────────────────────
# Per-postava data (XP, ranky) se klíčují '<uid>:<slot>'. Quest členy
# eviduje jako čisté Discord ID, takže slot postavy se ukládá zvlášť.

def _remember_slot(quest_data: dict, uid: int, slot: str | None = None) -> str:
    slot = str(slot or get_active_slot(uid))
    quest_data.setdefault("id", uuid4().hex)
    identity = character_id(uid, slot)
    if identity is not None:
        quest_data.setdefault("assignments", {})[identity] = {"uid": uid, "slot": slot}
    members = quest_data.setdefault("members", [])
    if uid not in members:
        members.append(uid)
    quest_data.setdefault("member_slots", {})[str(uid)] = slot
    return slot


def _assigned_character(quest, uid, slot):
    identity = (get_char(uid, slot) or {}).get("id")
    if identity is not None and identity in quest.get("assignments", {}):
        return True
    return ("assignments" not in quest and uid in quest.get("members", [])
            and str((quest.get("member_slots") or {}).get(str(uid)) or "1") == slot)


def _current_assignments(quest, registry):
    slots = {}
    for uid in {entry["uid"] for entry in quest.get("assignments", {}).values()}:
        for slot, char in registry.get(str(uid), {}).get("chars", {}).items():
            if char.get("id"):
                slots[char["id"]] = (uid, slot, char.get("name") or f"Slot {slot}")
    return {identity: slots[identity] for identity in quest.get("assignments", {}) if identity in slots}


def _sync_legacy_members(quest, assignments):
    quest["members"] = list(dict.fromkeys(uid for uid, _, _ in assignments.values()))
    quest["member_slots"] = {str(uid): slot for uid, slot, _ in assignments.values()}


def _status_line(added: str, closed: str | None) -> str:
    """Malý řádek s datumy dole pod questem."""
    pin = "📌"
    if closed:
        return f"-# {pin} Quest získán: **{added}**  {pin} Quest dokončen: **{closed}**"
    return f"-# {pin} Quest získán: **{added}**"


def _parse_member_mentions(text: str, guild: discord.Guild, exclude_ids: set[int] | None = None) -> list[int]:
    """Parsuje Discord @zmínky ze stringu. Volitelně vynechá ID která jsou už v listu."""
    exclude = set(exclude_ids or set())
    ids = []
    for word in text.split():
        uid_str = word.strip("<@!>")
        if uid_str.isdigit():
            m = guild.get_member(int(uid_str))
            if m and m.id not in exclude:
                ids.append(m.id)
                exclude.add(m.id)
    return ids


async def _notify_assignment(
    guild: discord.Guild,
    member_ids: list[int],
    quest_name: str,
    quest_info: str,
    category: str,
    xp: str | None,
) -> list[str]:
    """Pošle hráčům oznámení o přiřazení questu."""
    cat_meta = CATEGORY_META.get(category, CATEGORY_META[Category.SIDE])
    errors: list[str] = []
    for uid in member_ids:
        member = guild.get_member(uid)
        if member:
            try:
                dm = discord.Embed(
                    title=f"{cat_meta['emoji']}  Nový quest",
                    description=f"**{quest_name}**" + (f"\n{quest_info}" if quest_info else ""),
                    color=STATUS_META[Status.ACTIVE]["color"],
                )
                if xp:
                    dm.add_field(name="✨ Odměna", value=xp, inline=True)
                dm.set_footer(text=f"⭐ {ARION_NAME}  ·  Najdeš ho v /quests")
                await member.send(embed=dm)
            except discord.Forbidden:
                errors.append(member.display_name)
    return errors

def format_main_block(name: str, data: dict, guild: discord.Guild | None,
                      side_quests: list[tuple], status: str = Status.ACTIVE) -> str:
    """
    Naformátuje jeden main quest + jeho side questy jako textový blok do embedu.
    Vrátí string pro description.
    """
    meta   = STATUS_META.get(status, STATUS_META[Status.ACTIVE])
    xp     = data.get("xp")
    info   = data.get("info", "")
    added  = data.get("added", "?")
    closed = data.get("closed")

    # Hlavička main questu
    status_suffix = f"  {meta['emoji']}" if status != Status.ACTIVE else ""
    lines = [f"📜 **(main)**{status_suffix}  **{name}**"]
    lines.append(f"*{info}*")
    if xp:
        lines.append(f"⭐ xp: {xp}")
    lines.append(_status_line(added, closed))

    # Side questy
    for side_name, side_data, side_status in side_quests:
        s_meta   = STATUS_META.get(side_status, STATUS_META[Status.ACTIVE])
        s_xp     = side_data.get("xp")
        s_info   = side_data.get("info", "")
        s_added  = side_data.get("added", "?")
        s_closed = side_data.get("closed")
        s_suffix = f"  {s_meta['emoji']}" if side_status != Status.ACTIVE else ""

        lines.append(f"╠ 📜 **(side)**{s_suffix}  **{side_name}**")
        if s_info:
            lines.append(f"╠ *{s_info}*")
        if s_xp:
            lines.append(f"╠ ⭐ xp: {s_xp}")
        if s_closed:
            lines.append(f"-# ╚ 📌 Quest získán: **{s_added}**  📌 Quest dokončen: **{s_closed}**")
        else:
            lines.append(f"-# ╚ 📌 Quest získán: **{s_added}**")

    return "\n".join(lines)

MAX_DESC = 4000   # limit popisu embedu je 4096 — necháváme si rezervu

def _pages(blocks: list[str], per_page: int) -> list[list[str]]:
    """Rozdělí bloky na stránky podle počtu i délky, ať se popis vejde do embedu."""
    pages: list[list[str]] = []
    current: list[str]     = []
    length                 = 0
    for block in blocks:
        if len(block) > MAX_DESC:
            block = block[:MAX_DESC - 1] + "…"
        if current and (len(current) >= per_page or length + len(block) + 2 > MAX_DESC):
            pages.append(current)
            current, length = [], 0
        current.append(block)
        length += len(block) + 2
    if current:
        pages.append(current)
    return pages


def format_side_block(name: str, data: dict, status: str = Status.ACTIVE) -> str:
    """Quest jako samostatný blok."""
    meta   = STATUS_META.get(status, STATUS_META[Status.ACTIVE])
    xp     = data.get("xp")
    info   = data.get("info", "")
    added  = data.get("added", "?")
    closed = data.get("closed")

    s_suffix = f"  {meta['emoji']}" if status != Status.ACTIVE else ""
    category = data.get("category", Category.SIDE)
    lines = [f"📜 **({category})**{s_suffix}  **{name}**"]
    if info:
        lines.append(f"*{info}*")
    if xp:
        lines.append(f"⭐ xp: {xp}")
    lines.append(_status_line(added, closed))
    return "\n".join(lines)

BOARD_SOURCE = "board"


def _visible_quests(quests: dict, uid: int, slot: str, *, mine: bool) -> dict:
    if mine:
        return {
            name: data for name, data in quests.items()
            if _assigned_character(data, uid, slot)
        }
    return {name: data for name, data in quests.items()
            if data.get("source") != BOARD_SOURCE
            and (data.get("category") != Category.SOLO or _assigned_character(data, uid, slot))}


class QuestListView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.page = 0
        self.pages = []
        self.mine = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    def load(self, *, mine: bool):
        self.mine = mine
        self.page = 0
        quests = _visible_quests(load_quests(), self.user_id, get_active_slot(self.user_id), mine=mine)
        self.pages = _pages([format_side_block(name, data) for name, data in quests.items()], 8)

    def embed(self) -> discord.Embed:
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page + 1 >= len(self.pages)
        self.my_quests.style = discord.ButtonStyle.primary if self.mine else discord.ButtonStyle.secondary
        self.all_quests.style = discord.ButtonStyle.secondary if self.mine else discord.ButtonStyle.primary
        empty = "Aktivní postava nemá žádné aktivní questy." if self.mine else "Žádné aktivní questy."
        embed = discord.Embed(
            title="Moje questy" if self.mine else "Všechny questy",
            description="\n\n".join(self.pages[self.page]) if self.pages else empty,
            color=STATUS_META[Status.ACTIVE]["color"],
        )
        if len(self.pages) > 1:
            embed.set_footer(text=f"{self.page + 1} / {len(self.pages)}")
        return embed

    @discord.ui.button(label="Moje questy")
    async def my_quests(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.load(mine=True)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Všechny questy")
    async def all_quests(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.load(mine=False)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Zpět", row=1)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Další", row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(max(0, len(self.pages) - 1), self.page + 1)
        await interaction.response.edit_message(embed=self.embed(), view=self)


# ── Migrace — seed nových questů při startu ────────────────────────────────────

_SEED_QUESTS = {
    # ── Král hvězdy ───────────────────────────────────────────────────────────
    "Volání hvězdy": {
        "info":         "Velký turnaj se blíží a brzy přiletí hvězda, která změní osud všech.",
        "xp":           "160 000",
        "category":     Category.MAIN,
        "parent_quest": None,
        "everyone":     True,   # jediný main quest, co jde automaticky úplně všem
        "members":      [],
        "added":        "06.05.",
    },
    "Stíny v srdci": {
        "info":         "Zločinecká síť Vládce stínu rozložila Lumenii na kusy. Je na čase mu to vrátit. Odpor. Vzpoura. Obnova.",
        "xp":           "150 000",
        "category":     Category.SIDE,
        "parent_quest": "Volání hvězdy",
        "members":      [],
        "added":        "06.05.",
    },
    "Šampion podsvětí": {
        "info":         "V baru pod Aquionem existuje podsvětí, kde si může vylhat cestu každý. Kontakty, závody žraloků, peníze a riziko.",
        "xp":           "150 000",
        "category":     Category.SIDE,
        "parent_quest": "Volání hvězdy",
        "members":      [],
        "added":        "06.05.",
    },
    "Draci": {
        "info":         "Draci jsou naživu a Alice je chce všechny osvobodit. Alice má momentálně dva draky a dalších devět zbývá.",
        "xp":           "150 000",
        "category":     Category.SIDE,
        "parent_quest": "Volání hvězdy",
        "members":      [],
        "added":        "06.05.",
    },
    # ── Aurelionská hlavní linka ───────────────────────────────────────────────
    "Poslední Aurelion": {
        "info":         "Quest navazuje na knihu Act II.",
        "xp":           "200 000",
        "category":     Category.MAIN,
        "parent_quest": None,
        "members":      [],
        "added":        "06.05.",
    },
    "Zmrtvýchvstání": {
        "info":         "Alice se probudila po útoku Kultu smrti, ale něco je s ní špatně.",
        "xp":           "35 000",
        "category":     Category.SIDE,
        "parent_quest": "Poslední Aurelion",
        "members":      [],
        "added":        "06.05.",
    },
    "Cesta ke světlu": {
        "info":         "Paladin Reinhard uzavřel katedrálu. Něco se chystá.",
        "xp":           "35 000",
        "category":     Category.SIDE,
        "parent_quest": "Poslední Aurelion",
        "members":      [],
        "added":        "06.05.",
    },
    # ── Noxarath ──────────────────────────────────────────────────────────────
    "Pomsta": {
        "info":         "Bohyně temnoty a čarodějka smrti Noxarath se zdá být velmi zainteresovaná v určité vyvolené. O co jí jde?",
        "xp":           "120 500",
        "category":     Category.MAIN,
        "parent_quest": None,
        "members":      [],
        "added":        "06.05.",
    },
    "Kontrakt s čarodějnicí": {
        "info":         "",
        "xp":           "50 000",
        "category":     Category.SIDE,
        "parent_quest": "Pomsta",
        "members":      [],
        "added":        "06.05.",
    },
}

_SYNC_FIELDS = {"info", "xp", "category", "parent_quest", "everyone"}
# Otisk hodnot, které do questu naposledy zapsal seed — podle něj poznáme,
# co admin změnil ručně a co se smí dotáhnout z kódu.
_SEED_STAMP = "_seed"

def _sync_seed_fields(quest: dict, seed: dict) -> bool:
    """Dotažení metadat ze seedu, ale bez přepisování ručních úprav.

    Pole se přepíše jen tehdy, když ho od posledního seedu nikdo nezměnil
    (aktuální hodnota == otisk). První běh jen vyrobí otisk z toho, co je
    v datech teď — aby migrace nesmazala úpravy z `/quest edit`.
    """
    stamp   = quest.get(_SEED_STAMP)
    first   = not isinstance(stamp, dict)
    stamp   = {} if first else dict(stamp)
    changed = False

    for field in _SYNC_FIELDS:
        current = quest.get(field)
        if first or field not in stamp:
            stamp[field] = current
            continue
        if current != stamp[field]:      # admin to změnil ručně → necháváme
            stamp[field] = current
            continue
        if current != seed.get(field):   # změnil se seed v kódu → dotažeme
            quest[field] = seed.get(field)
            stamp[field] = seed.get(field)
            changed = True

    if quest.get(_SEED_STAMP) != stamp:
        quest[_SEED_STAMP] = stamp
        changed = True
    return changed


def _migrate_quests():
    """Při startu přidá chybějící questy, synchronizuje metadata a opraví pořadí."""
    quests  = load_quests()
    changed = False

    # Oprav rodiče bez ztráty účastníků starého questu.
    if "Stíny v srdci" in quests and quests["Stíny v srdci"].get("parent_quest") not in ("Volání hvězdy", None):
        quests["Stíny v srdci"]["parent_quest"] = "Volání hvězdy"
        changed = True

    closed_names = {entry.get("name") for entry in load_quest_log()}
    # Přidej chybějící + synchronizuj metadata
    for name, seed in _SEED_QUESTS.items():
        if name not in quests:
            if name in closed_names:
                continue
            quests[name] = {**seed, _SEED_STAMP: {f: seed.get(f) for f in _SYNC_FIELDS}}
            changed = True
        elif _sync_seed_fields(quests[name], seed):
            changed = True

    for quest in quests.values():
        if "id" not in quest:
            quest["id"] = uuid4().hex
            changed = True
        if "assignments" not in quest:
            quest["assignments"] = {}
            for uid in quest.get("members", []):
                slot = (quest.get("member_slots") or {}).get(str(uid)) or get_active_slot(uid)
                _remember_slot(quest, uid, slot)
            changed = True

    # Oprav pořadí: ne-seedované questy napřed (Chapter I atd.), pak seedované v seed pořadí
    non_seed  = {n: d for n, d in quests.items() if n not in _SEED_QUESTS}
    seeded    = {n: quests[n] for n in _SEED_QUESTS if n in quests}
    new_order = {**non_seed, **seeded}
    if list(quests.keys()) != list(new_order.keys()):
        quests  = new_order
        changed = True

    if changed:
        save_quests(quests)
        print("[quests] Migrace dokončena.")


# ── Quests Cog ────────────────────────────────────────────────────────────────

class QuestsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _migrate_quests()

    quest_group = app_commands.Group(name="quest", description="Správa questů")

    # ── /quests ───────────────────────────────────────────────────────────────

    @app_commands.command(name="quests", description="Zobraz svoje nebo všechny aktivní questy")
    async def quests_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = QuestListView(interaction.user.id)
        view.load(mine=True)
        await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

    # ── /quest add ────────────────────────────────────────────────────────────

    @quest_group.command(name="add", description="Vytvoř a přiřaď nový quest")
    @admin_only()
    @app_commands.describe(
        name="Název questu",
        info="Popis / zadání questu",
        category="Typ questu",
        xp="Odměna za splnění (volitelné)",
        members="Hráči oddělení mezerou (@zmínka) — povinné, pokud nezaškrtneš everyone",
        parent_quest="Main quest ke kterému patří (jen pro side questy)",
        difficulty="Obtížnost — určuje rank body za splnění.",
        everyone="Jen Main: dát opravdu úplně všem hned teď? (výchozí: ne — přiřaď přes members)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="⚔️ Main Quest — hlavní dějová linka", value=Category.MAIN),
        app_commands.Choice(name="🗺️ Side Quest — pro vybrané (s hlavním questem)", value=Category.SIDE),
        app_commands.Choice(name="🏃 Solo Quest — pro vybrané (bez hlavního questu)", value=Category.SOLO),
    ])
    @app_commands.choices(difficulty=[
        app_commands.Choice(name=f"{m['label']} — +{m['points']} rank bodů", value=d)
        for d, m in DIFFICULTY.items()
    ])
    async def quest_add(
        self,
        interaction: discord.Interaction,
        name: str,
        info: str,
        category: str = Category.SIDE,
        xp: str | None = None,
        difficulty: str = DEFAULT_DIFFICULTY,
        members: str | None = None,
        parent_quest: str | None = None,
        everyone: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name in quests:
            await interaction.followup.send(
                f"Quest **{name}** již existuje.", ephemeral=True
            )
            return

        # Validace parent_quest — jen pro Side questy
        if category == Category.SIDE:
            if parent_quest is None:
                await interaction.followup.send(
                    "Side quest MUSÍ mít nadřazený Main quest (`parent_quest:`).", ephemeral=True
                )
                return
            if parent_quest not in quests:
                await interaction.followup.send(
                    f"Main quest **{parent_quest}** neexistuje.", ephemeral=True
                )
                return
            if quests[parent_quest].get("category") != Category.MAIN:
                await interaction.followup.send(
                    f"**{parent_quest}** není Main Quest — parent lze přiřadit jen k main questům.", ephemeral=True
                )
                return
        elif category == Category.MAIN and parent_quest is not None:
            await interaction.followup.send(
                "Main quest nemůže mít nadřazený quest.", ephemeral=True
            )
            return

        guild = interaction.guild

        if category == Category.MAIN and everyone:
            # Main quest s everyone=True → automaticky všichni non-bot členové
            # (tohle by měl mít jen jeden quest v celé kampani — "Volání hvězdy").
            member_ids = [m.id for m in guild.members if not m.bot]
        else:
            # Main quest bez everyone (i Side/Solo) → povinný members parametr
            quest_type = {Category.MAIN: "Main", Category.SIDE: "Side", Category.SOLO: "Solo"}[category]
            if not members:
                await interaction.followup.send(
                    f"Pro {quest_type} quest bez `everyone:True` musíš zadat `members:` (@zmínka hráčů).",
                    ephemeral=True,
                )
                return
            member_ids = _parse_member_mentions(members, guild)
            if not member_ids:
                await interaction.followup.send(
                    "Nepodařilo se najít žádné platné členy. Použij @zmínku.", ephemeral=True
                )
                return

        quests[name] = {
            "id":           uuid4().hex,
            "info":         info,
            "xp":           xp,
            "category":     category,
            "difficulty":   difficulty,
            "parent_quest": parent_quest,
            "everyone":     bool(category == Category.MAIN and everyone),
            "members":      member_ids,
            "added":        today(),
        }
        for uid in member_ids:
            _remember_slot(quests[name], uid)
        save_quests(quests)
        dm_errors = await _notify_assignment(guild, member_ids, name, info, category, xp)

        cat_meta = CATEGORY_META[category]
        if category == Category.MAIN and everyone:
            assign_str = f"@everyone  ({len(member_ids)} hráčů)"
        else:
            assign_str = "  ·  ".join(
                guild.get_member(uid).mention if guild.get_member(uid) else f"<@{uid}>"
                for uid in member_ids
            )

        announce = discord.Embed(
            title="📜  Nový quest přijat",
            description=f"### {cat_meta['emoji']} {name}\n*{info}*",
            color=STATUS_META[Status.ACTIVE]["color"],
        )
        announce.add_field(name="🏷️ Typ",       value=cat_meta["label"], inline=True)
        announce.add_field(name="📅 Zadáno",     value=today(),           inline=True)
        if xp:
            announce.add_field(name="✨ Odměna", value=xp,               inline=True)
        announce.add_field(name="👥 Přiřazeno",  value=assign_str,        inline=False)
        announce.set_footer(text=f"⭐ {ARION_NAME}  ·  Přiřazené questy najdeš v /quests")
        await interaction.channel.send(embed=announce)

        msg = f"✅ Quest **{name}** přidán a přiřazen {len(member_ids)} hráčům." + _xp_warning(xp)
        if dm_errors:
            msg += f"\n⚠️ DM se nepodařilo odeslat: {', '.join(dm_errors)}."
        await interaction.followup.send(msg, ephemeral=True)

    # ── on_member_join — nový hráč dostane hlavní main quest (everyone=True) ──

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        quests = load_quests()
        # Jen main questy s příznakem everyone=True (aktuálně "Volání hvězdy").
        # Ostatní main questy (Poslední Aurelion, Pomsta...) jsou dějové linky
        # pro konkrétní hráče — přiřazují se ručně přes /quest add nebo /quest give.
        main_quests = {
            n: d for n, d in quests.items()
            if d.get("category") == Category.MAIN and d.get("everyone")
        }
        if not main_quests:
            return

        for qdata in main_quests.values():
            if member.id not in qdata.get("members", []):
                qdata.setdefault("members", []).append(member.id)
            _remember_slot(qdata, member.id)

        save_quests(quests)

        # DM nováčkovi
        try:
            embed = discord.Embed(
                title="⚔️  Vítej ve světě Aurionis",
                description="Tvůj příběh právě začíná. Své úkoly najdeš v /quests.",
                color=STATUS_META[Status.ACTIVE]["color"],
            )
            for qname, qdata in main_quests.items():
                embed.add_field(
                    name=f"📜 {qname}",
                    value=f"*{qdata.get('info', '')}*",
                    inline=False,
                )
            embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Napiš /quests")
            await member.send(embed=embed)
        except discord.Forbidden:
            pass

    # ── Volání z tutoriálu — přiřazení side questu podle zvolené destinace ────

    async def assign_destination_quest(self, member: discord.Member, destination: str,
                                       *, notify: bool = True):
        """
        Zavolej z tutoriálu, jakmile si hráč vybere svou počáteční destinaci
        (Lumenie / Aquion / Dračí skála) — přiřadí mu JEN odpovídající side
        quest větve "Volání hvězdy" (ne všechny tři najednou).

        notify=False potlačí DM (hodí se, když si volající staví vlastní
        uvítací zprávu a nechce hráči poslat oznámení o questu dvakrát).

        Vrací (quest_name, quest_data) při novém přiřazení, jinak None
        (neznámá destinace, quest chybí v databázi, nebo ho hráč už měl).
        """
        quest_name = resolve_destination_quest(destination)
        if quest_name is None:
            return None

        quests = load_quests()
        quest_data = quests.get(quest_name)
        if quest_data is None:
            return None

        if _assigned_character(quest_data, member.id, get_active_slot(member.id)):
            return None
        _remember_slot(quest_data, member.id)
        save_quests(quests)

        if notify:
            try:
                embed = discord.Embed(
                    title="📜  Nový quest",
                    description=f"**{quest_name}**\n{quest_data.get('info', '')}",
                    color=STATUS_META[Status.ACTIVE]["color"],
                )
                if quest_data.get("xp"):
                    embed.add_field(name="✨ Odměna", value=quest_data["xp"], inline=True)
                embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Podle tvé zvolené destinace")
                await member.send(embed=embed)
            except discord.Forbidden:
                pass

        return quest_name, quest_data

    async def _confirm_quest_action(self, interaction, message, label):
        view = discord.ui.View(timeout=60)
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.danger)
        confirmed = False

        async def confirm(click):
            nonlocal confirmed
            if click.user.id != interaction.user.id or confirmed:
                await click.response.send_message("Potvrzení už není dostupné.", ephemeral=True)
                return
            confirmed = True
            view.stop()
            await click.response.edit_message(view=None)

        button.callback = confirm
        view.add_item(button)
        prompt = await interaction.followup.send(message, ephemeral=True, view=view, wait=True,
                                                 allowed_mentions=discord.AllowedMentions.none())
        await view.wait()
        if not confirmed:
            await prompt.edit(content="Potvrzení vypršelo.", view=None)
        return confirmed

    # ── /quest status ─────────────────────────────────────────────────────────

    @quest_group.command(name="status", description="Změň stav questu")
    @admin_only()
    @app_commands.describe(
        name="Název questu", status="Nový stav",
        winner="Jen u ZÁVODNÍCH zakázek: kdo splnil první. Ostatní dostanou nesplněno.",
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="🟢 Aktivní",   value=Status.ACTIVE),
        app_commands.Choice(name="✅ Dokončený", value=Status.COMPLETED),
        app_commands.Choice(name="❌ Neúspěšný", value=Status.FAILED),
    ])
    async def quest_status(self, interaction: discord.Interaction, name: str, status: str,
                           winner: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name not in quests:
            # Uzavřený quest už v quests.json není — tohle je jediná cesta, jak ho
            # vrátit z logu mezi aktivní (např. když se admin ukliknul).
            if status == Status.ACTIVE and await self._reopen_quest(interaction, name):
                return
            await interaction.followup.send(f"Quest **{name}** neexistuje.", ephemeral=True)
            return

        quest_data = quests[name]
        if quest_data.get("status", Status.ACTIVE) == status:
            await interaction.followup.send(f"Quest **{name}** už má stav **{status}**.", ephemeral=True)
            return

        guild      = interaction.guild
        member_ids = quest_data.get("members", [])
        if not isinstance(member_ids, list):
            member_ids = []
        meta       = STATUS_META[status]

        # ── Závodní zakázka: vítěz bere vše, ostatní mají smůlu ──────────────
        if winner is not None:
            if status != Status.COMPLETED:
                await interaction.followup.send(
                    "❌ Vítěze lze vyhlásit jen u stavu **dokončený**.", ephemeral=True)
                return
            if winner.id not in member_ids:
                await interaction.followup.send(
                    f"❌ {winner.mention} tuhle zakázku nemá vzatou.", ephemeral=True)
                return
        winner_id = winner.id if winner else None

        if status in (Status.COMPLETED, Status.FAILED):
            assignments = _current_assignments(quest_data, db.load_doc("characters.json", {}))
            recipients = [(uid, slot, char_name) for identity, (uid, slot, char_name) in assignments.items()
                          if status == Status.COMPLETED and (winner_id is None or uid == winner_id)
                          and identity not in quest_data.get("rewarded", [])]
            if quest_data.get("legacy_rewards_paid"):
                recipients = []
            preview = ", ".join(f"{char_name} (<@{uid}>, slot {slot})" for uid, slot, char_name in recipients)
            if not await self._confirm_quest_action(
                interaction,
                f"Uzavřít **{name}** jako **{status}**?\n"
                f"Odměna: {quest_data.get('xp') or '0'} XP + rank body\n"
                f"Příjemci: {preview[:1200] or 'nikdo'}",
                "Uzavřít quest",
            ):
                return

            def close(docs):
                active = docs["quests.json"]
                if active.get(name) != quest_data:
                    raise ValueError("Quest se mezitím změnil. Otevři nové potvrzení.")
                current = _current_assignments(quest_data, docs["characters.json"])
                if current != assignments:
                    raise ValueError("Postavy se mezitím změnily. Otevři nové potvrzení.")
                archive = docs["quest_log.json"]
                if not isinstance(archive, list):
                    archive = docs["quest_log.json"] = []
                record = {**active.pop(name), "name": name, "status": status, "closed": today()}
                rewarded = list(record.get("rewarded", []))
                results = []
                points = quest_points(record.get("difficulty", DEFAULT_DIFFICULTY))
                amount = _parse_xp(record.get("xp"))
                for identity, (uid, slot, char_name) in current.items():
                    if (status != Status.COMPLETED or record.get("legacy_rewards_paid")
                            or identity in rewarded or (winner_id is not None and uid != winner_id)):
                        continue
                    profiles = docs["profiles.json"]
                    key = f"{uid}:{slot}"
                    if key not in profiles:
                        continue
                    profile = _profile(profiles, key)
                    xp_result = award_xp_to_profile(profile, amount, f"Quest: {name}") if amount else None
                    rank_result = award_rank_to_profile(profile, points) if points else None
                    rewarded.append(identity)
                    results.append((uid, slot, char_name, amount, xp_result, rank_result))
                record["rewarded"] = rewarded
                archive.append(record)
                return results

            try:
                results = db.update_documents(
                    ["quests.json", "quest_log.json", "characters.json", "profiles.json"], close)
            except ValueError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            for uid, slot, char_name, amount, xp, rank in results:
                member = guild.get_member(uid)
                if member is None:
                    continue
                message = f"✅ **{char_name}** dokončil/a **{name}**. Odměna: **{amount} XP**."
                if xp and xp["leveled_up"]:
                    message += f" Nový level: **{xp['new_level']}**."
                if rank and rank["ranked_up"]:
                    message += f" Nový rank: **{rank['new_rank']}**."
                    if get_active_slot(uid) == slot:
                        await sync_rank_role(member, rank["new_rank"])
                try:
                    await member.send(message)
                except discord.HTTPException:
                    pass

            # Oznámení do kanálu
            mentions    = [guild.get_member(uid).mention if guild.get_member(uid) else f"<@{uid}>" for uid in member_ids]
            status_line = "✅ Dokončeno" if status == Status.COMPLETED else "❌ Neúspěch"
            announce    = discord.Embed(
                title=f"{meta['emoji']}  Quest uzavřen",
                description=(
                    f"### {name}\n"
                    f"*{quest_data.get('info', '')}*"
                ),
                color=meta["color"],
            )
            announce.add_field(name="📋 Výsledek",  value=status_line,              inline=True)
            announce.add_field(name="📅 Uzavřeno",  value=today(),                  inline=True)
            if quest_data.get("xp") and status == Status.COMPLETED:
                announce.add_field(name="✨ Odměna", value=quest_data["xp"],        inline=True)
            announce.add_field(name="👥 Účastníci", value="  ·  ".join(mentions),   inline=False)
            announce.set_footer(text=f"⭐ {ARION_NAME}  ·  Quest přesunut do logu")
            await interaction.channel.send(embed=announce)

            await interaction.followup.send(
                f"{meta['emoji']} Quest **{name}** označen jako **{status}** a přesunut do logu.",
                ephemeral=True,
            )
        else:
            # Zpět na aktivní
            quest_data["status"] = Status.ACTIVE
            quest_data.pop("closed", None)
            quests[name] = quest_data
            save_quests(quests)
            await interaction.followup.send(f"🟢 Quest **{name}** označen jako **aktivní**.", ephemeral=True)

    async def _reopen_quest(self, interaction: discord.Interaction, name: str) -> bool:
        def reopen(docs):
            active, archive = docs["quests.json"], docs["quest_log.json"]
            if name in active or not isinstance(archive, list):
                return False
            idx = next((i for i in range(len(archive) - 1, -1, -1)
                        if archive[i].get("name") == name), None)
            if idx is None:
                return False
            entry = archive.pop(idx)
            quest = {key: value for key, value in entry.items() if key not in {"name", "closed"}}
            quest["status"] = Status.ACTIVE
            if "assignments" not in quest:
                quest["assignments"] = {}
                if entry.get("status") == Status.COMPLETED:
                    quest["legacy_rewards_paid"] = True
            _sync_legacy_members(quest, _current_assignments(quest, docs["characters.json"]))
            active[name] = quest
            return True

        if not db.update_documents(["quests.json", "quest_log.json", "characters.json"], reopen):
            return False
        await interaction.followup.send(
            f"🟢 Quest **{name}** je znovu aktivní. Už vyplacené odměny se neopakují. "
            "U starých záznamů bez ID postav přiřaď účastníky znovu.",
            ephemeral=True)
        return True

    # ── /quest log ────────────────────────────────────────────────────────────

    @quest_group.command(name="log", description="Zobraz historii všech questů (aktivní i uzavřené)")
    @app_commands.describe(status="Filtrovat podle výsledku", category="Filtrovat podle kategorie")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="🟢 Aktivní",   value=Status.ACTIVE),
            app_commands.Choice(name="✅ Dokončené", value=Status.COMPLETED),
            app_commands.Choice(name="❌ Neúspěšné", value=Status.FAILED),
            app_commands.Choice(name="🗃️ Odebrané", value=Status.REMOVED),
        ],
        category=[
            app_commands.Choice(name="⚔️ Main Quest", value=Category.MAIN),
            app_commands.Choice(name="🗺️ Side Quest", value=Category.SIDE),
        ],
    )
    async def quest_log(
        self,
        interaction: discord.Interaction,
        status: str | None = None,
        category: str | None = None,
    ):
        # Spoj aktivní questy + archiv do jednoho seznamu
        active_quests = load_quests()
        archived      = load_quest_log()

        # Aktivní questy — přidej status pole pro jednotnost
        all_quests = []
        for qname, qdata in active_quests.items():
            all_quests.append({"name": qname, "status": Status.ACTIVE, **qdata})
        # Archivní — nejnovější nahoře
        for entry in reversed(archived):
            all_quests.append(entry)

        # Filtrování
        if status:
            all_quests = [q for q in all_quests if q.get("status") == status]
        uid = interaction.user.id
        slot = get_active_slot(uid)
        if not interaction.user.guild_permissions.administrator:
            all_quests = [q for q in all_quests if q.get("category") != Category.SOLO
                          or ((q.get("status") == Status.ACTIVE or "assignments" in q)
                              and _assigned_character(q, uid, slot))]
        if category:
            all_quests = [q for q in all_quests if q.get("category") == category]

        # Titulek
        parts = []
        if status:
            parts.append(STATUS_META[status]["emoji"] + " " + status.capitalize())
        if category:
            parts.append(CATEGORY_META[category]["label"])
        title = "📚  Quest Log" + (f"  —  {' · '.join(parts)}" if parts else "")

        if not all_quests:
            embed = discord.Embed(title=title, description="*Žádné záznamy neodpovídají filtru.*", color=0x5D6D7E)
            embed.set_footer(text=f"⭐ {ARION_NAME}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Sestav blokový přehled — stejný styl jako /quests, main + side pod ním
        # Nejdřív seskup: main questy s jejich side questy
        mains = {q["name"]: q for q in all_quests if q.get("category") == Category.MAIN}
        sides = [q for q in all_quests if q.get("category") == Category.SIDE]

        blocks     = []
        used_sides = set()

        for main_name, main_data in mains.items():
            main_status = main_data.get("status", Status.ACTIVE)
            # Najdi side questy patřící pod tento main (podle parent_quest)
            children = [
                (s.get("name", "?"), s, s.get("status", Status.ACTIVE))
                for s in sides
                if s.get("parent_quest") == main_name and s.get("name")
            ]
            for sn, _, _ in children:
                used_sides.add(sn)
            blocks.append(format_main_block(main_name, main_data, interaction.guild, children, main_status))

        # Side questy bez rodiče (nebo rodič není v aktuálním filtru)
        for s in sides:
            if s.get("name") not in used_sides and s.get("name"):
                blocks.append(format_side_block(s["name"], s, s.get("status", Status.ACTIVE)))

        blocks.extend(format_side_block(q["name"], q, q.get("status", Status.ACTIVE))
                      for q in all_quests if q.get("category") == Category.SOLO)

        # Rozděl na stránky — podle počtu bloků i podle délky popisu (limit embedu)
        pages   = _pages(blocks, per_page=8)
        total   = len(all_quests)
        # V jedné zprávě smí být maximálně 10 embedů — zbytek radši zařízne filtr
        dropped = max(0, len(pages) - 10)
        pages   = pages[:10]
        n_pages = len(pages)

        embeds = []
        for pi, page_blocks in enumerate(pages, 1):
            desc = "\n\n".join(page_blocks)
            embed = discord.Embed(
                title=title if pi == 1 else f"📚  Quest Log  —  strana {pi}/{n_pages}",
                description=desc,
                color=0x5D6D7E,
            )
            footer = f"⭐ {ARION_NAME}  ·  {total} questů celkem"
            if n_pages > 1:
                footer += f"  ·  strana {pi}/{n_pages}"
            if dropped and pi == n_pages:
                footer += "  ·  zbytek se nevlezl, zuž filtr"
            embed.set_footer(text=footer)
            embeds.append(embed)

        await interaction.response.send_message(embed=embeds[0], ephemeral=True)
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /quest remove ─────────────────────────────────────────────────────────

    @quest_group.command(name="remove", description="Odeber quest z databáze")
    @admin_only()
    @app_commands.describe(name="Název questu k odebrání")
    async def quest_remove(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name not in quests:
            await interaction.followup.send(f"Quest **{name}** neexistuje.", ephemeral=True)
            return

        expected = quests[name]
        if not await self._confirm_quest_action(
            interaction, f"Přesunout **{name}** z aktivních questů do historie?", "Odebrat quest",
        ):
            return

        def remove(docs):
            active = docs["quests.json"]
            if active.get(name) != expected:
                raise ValueError("Quest se mezitím změnil.")
            archived = docs["quest_log.json"]
            if not isinstance(archived, list):
                archived = docs["quest_log.json"] = []
            archived.append({**active.pop(name), "name": name, "status": Status.REMOVED, "closed": today()})

        try:
            db.update_documents(["quests.json", "quest_log.json"], remove)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        log_action("quest_remove", interaction.user.display_name, name)
        await interaction.followup.send(
            f"🗑️ Quest **{name}** přesunut do historie. Obnovíš ho přes /quest status.",
            ephemeral=True,
        )

    # ── /quest give ───────────────────────────────────────────────────────────

    @quest_group.command(name="give", description="Přiřaď existující quest hráčům")
    @admin_only()
    @app_commands.describe(name="Název questu", members="Hráči oddělení mezerou (@zmínka)")
    async def quest_give(self, interaction: discord.Interaction, name: str, members: str):
        await interaction.response.defer(ephemeral=True)
        quests = load_quests()
        if name not in quests:
            await interaction.followup.send(f"Quest **{name}** neexistuje.", ephemeral=True)
            return
        quest_data = quests[name]
        guild      = interaction.guild

        new_ids = _parse_member_mentions(members, guild, exclude_ids={uid for uid in quest_data.get("members", [])
                            if _assigned_character(quest_data, uid, get_active_slot(uid))})
        if not new_ids:
            await interaction.followup.send("Žádní noví hráči k přiřazení.", ephemeral=True)
            return

        for uid in new_ids:
            _remember_slot(quest_data, uid)
        save_quests(quests)

        dm_errors = await _notify_assignment(
            guild, new_ids, name,
            quest_data.get("info", ""), quest_data.get("category", Category.SIDE), quest_data.get("xp"),
        )

        mentions = [guild.get_member(uid).mention if guild.get_member(uid) else f"<@{uid}>" for uid in new_ids]
        cat_meta = CATEGORY_META[quest_data.get("category", Category.SIDE)]
        announce = discord.Embed(
            title="📜  Quest přiřazen",
            description=f"### {cat_meta['emoji']} {name}\n*{quest_data.get('info', '')}*",
            color=STATUS_META[Status.ACTIVE]["color"],
        )
        announce.add_field(name="👥 Přiřazeno", value="  ·  ".join(mentions), inline=False)
        if quest_data.get("xp"):
            announce.add_field(name="✨ Odměna", value=quest_data["xp"], inline=True)
        announce.set_footer(text=f"⭐ {ARION_NAME}  ·  Přiřazené questy najdeš v /quests")
        await interaction.channel.send(embed=announce)

        members_str = ", ".join(guild.get_member(uid).display_name if guild.get_member(uid) else str(uid) for uid in new_ids)
        log_action("quest_give", interaction.user.display_name, name, members_str)
        msg = f"✅ Quest **{name}** přiřazen {len(new_ids)} hráčům." + _xp_warning(quest_data.get("xp"))
        if dm_errors:
            msg += f"\n⚠️ DM se nepodařilo odeslat: {', '.join(dm_errors)}."
        await interaction.followup.send(msg, ephemeral=True)

    # ── /quest-pokrok ─────────────────────────────────────────────────────────

    @app_commands.command(name="quest-pokrok", description="Oznám pokrok v questu — embed do kanálu (admin)")
    @app_commands.default_permissions(administrator=True)
    @admin_only()
    @app_commands.describe(name="Název questu", note="Volitelná poznámka zobrazená v embedu")
    async def quest_pokrok(self, interaction: discord.Interaction, name: str, note: str | None = None):
        await interaction.response.defer(ephemeral=True)
        quests = load_quests()
        if name not in quests:
            await interaction.followup.send(f"Quest **{name}** neexistuje.", ephemeral=True)
            return

        quest_data = quests[name]
        category   = quest_data.get("category", Category.SIDE)
        parent     = quest_data.get("parent_quest")

        cat_label = "main" if category == Category.MAIN else "side"
        desc = f"📜 **Pokrok v questu: {name}** *({cat_label})*"
        if parent:
            desc += f"\n╠  main: {parent}"
        if note:
            desc += f"\n\n{note}"

        embed = discord.Embed(description=desc, color=STATUS_META[Status.ACTIVE]["color"])
        embed.set_footer(text=f"⭐ {ARION_NAME}")
        await interaction.channel.send(embed=embed)

        log_action("quest_pokrok", interaction.user.display_name, name, note or "")
        await interaction.followup.send("✅ Pokrok oznámen v kanálu.", ephemeral=True)

    @quest_remove.autocomplete("name")
    @quest_give.autocomplete("name")
    @quest_pokrok.autocomplete("name")
    async def quest_name_autocomplete(self, interaction: discord.Interaction, current: str):
        quests = load_quests()
        return [
            app_commands.Choice(name=n, value=n)
            for n in quests if current.lower() in n.lower()
        ][:25]

    @quest_status.autocomplete("name")
    async def quest_status_autocomplete(self, interaction: discord.Interaction, current: str):
        """Aktivní questy + nedávno uzavřené, ať jde quest vrátit zpět na aktivní."""
        needle  = current.lower()
        choices = [app_commands.Choice(name=n, value=n)
                   for n in load_quests() if needle in n.lower()]

        seen = {c.value for c in choices}
        for entry in reversed(load_quest_log()):
            n = entry.get("name")
            if not n or n in seen or needle not in n.lower():
                continue
            seen.add(n)
            meta = STATUS_META.get(entry.get("status", Status.COMPLETED), STATUS_META[Status.COMPLETED])
            choices.append(app_commands.Choice(name=f"{meta['emoji']} {n} (v logu)"[:100], value=n))
        return choices[:25]

    @quest_add.autocomplete("parent_quest")
    async def parent_quest_autocomplete(self, interaction: discord.Interaction, current: str):
        quests = load_quests()
        return [
            app_commands.Choice(name=n, value=n)
            for n, d in quests.items()
            if d.get("category") == Category.MAIN and current.lower() in n.lower()
        ][:25]

    # ── Audit log ─────────────────────────────────────────────────────────────

    @app_commands.command(name="audit-log", description="Zobrazí posledních 20 admin akcí (jen DM)")
    @app_commands.default_permissions(administrator=True)
    @admin_only()
    async def audit_log_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        entries = get_recent(20)
        if not entries:
            await interaction.followup.send("Audit log je prázdný.", ephemeral=True)
            return
        lines = []
        for e in reversed(entries):
            detail = f" — `{e['detail']}`" if e.get("detail") else ""
            lines.append(f"`{e['ts']}` **{e['action']}** · {e['actor']} → {e['target']}{detail}")
        embed = discord.Embed(
            title="📋 Audit log",
            description="\n".join(lines),
            color=0x95A5A6,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(QuestsCog(bot))
