import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime

from src.utils.paths import QUESTS as QUESTS_FILE, QUEST_LOG as QUEST_LOG_FILE, DIARIES as DIARY_FILE
from src.utils.json_utils import load_json, save_json
from src.utils.audit import log_action, get_recent

ARION_NAME = "Aurionis"
QUEST_TAG  = "📜"

# ── Status a kategorie ────────────────────────────────────────────────────────

class Status:
    ACTIVE    = "aktivní"
    COMPLETED = "dokončený"
    FAILED    = "neúspěšný"

class Category:
    MAIN = "main"
    SIDE = "side"

STATUS_META = {
    Status.ACTIVE:    {"emoji": "🟢", "color": 0x2E6B3E},
    Status.COMPLETED: {"emoji": "✅", "color": 0x2E86C1},
    Status.FAILED:    {"emoji": "❌", "color": 0x922B21},
}

CATEGORY_META = {
    Category.MAIN: {"emoji": "⚔️",  "label": "Main Quest"},
    Category.SIDE: {"emoji": "🗺️", "label": "Side Quest"},
}

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

def load_diaries() -> dict:
    return load_json(DIARY_FILE)

def save_diaries(data: dict):
    save_json(DIARY_FILE, data)

def today() -> str:
    return datetime.now().strftime("%d.%m.")

def _migrate_entries(raw) -> list:
    """Bezpečná migrace — vždy vrátí list bez ohledu na vstup."""
    if not isinstance(raw, list):
        return []
    return [e if isinstance(e, dict) else {"text": str(e), "pinned": False, "tag": None} for e in raw]

def make_diary_entry(quest_name: str, info: str, xp: str | None) -> dict:
    """Vytvoří nový quest záznam v deníku (dict formát kompatibilní s diary.py)."""
    xp_part = f"  ✨ {xp}" if xp else ""
    text    = f"{today()} — 📜 **{quest_name}** — {info}{xp_part}"
    return {"text": text, "pinned": False, "tag": QUEST_TAG}

def update_diary_quest_status(entries: list, quest_name: str, status: str) -> bool:
    """
    Najde existující quest záznam v deníku a upraví jeho text — přidá status badge.
    Vrátí True pokud byl záznam nalezen a upraven, False pokud ne (pak je třeba přidat nový).
    """
    meta    = STATUS_META[status]
    pattern = f"**{quest_name}**"   # hledáme podle názvu questu

    for entry in reversed(entries):   # hledáme od konce — nejnovější záznam tohoto questu
        text = entry.get("text", "") if isinstance(entry, dict) else str(entry)
        if QUEST_TAG in text and pattern in text:
            # Odstraň případný starý status badge a přidej nový
            for old_status, old_meta in STATUS_META.items():
                old_badge = f"  {old_meta['emoji']} {old_status.upper()}"
                text = text.replace(old_badge, "")
            text += f"  {meta['emoji']} {status.upper()}"
            if isinstance(entry, dict):
                entry["text"] = text
            return True

    return False

def _status_line(added: str, closed: str | None) -> str:
    """Malý řádek s datumy dole pod questem."""
    pin = "📌"
    if closed:
        return f"-# {pin} Quest získán: **{added}**  {pin} Quest dokončen: **{closed}**"
    return f"-# {pin} Quest získán: **{added}**"


def _parse_member_mentions(text: str, guild: discord.Guild, exclude_ids: set[int] | None = None) -> list[int]:
    """Parsuje Discord @zmínky ze stringu. Volitelně vynechá ID která jsou už v listu."""
    exclude = exclude_ids or set()
    ids = []
    for word in text.split():
        uid_str = word.strip("<@!>")
        if uid_str.isdigit():
            m = guild.get_member(int(uid_str))
            if m and m.id not in exclude:
                ids.append(m.id)
    return ids


async def _assign_and_notify(
    guild: discord.Guild,
    member_ids: list[int],
    diaries: dict,
    quest_name: str,
    quest_info: str,
    category: str,
    xp: str | None,
) -> list[str]:
    """Zapíše quest do deníků a pošle DM každému hráči. Vrátí jména kde DM selhalo."""
    entry    = make_diary_entry(quest_name, quest_info, xp)
    cat_meta = CATEGORY_META.get(category, CATEGORY_META[Category.SIDE])
    errors: list[str] = []
    for uid in member_ids:
        uid_str = str(uid)
        entries = _migrate_entries(diaries.get(uid_str, []))
        entries.append(entry)
        diaries[uid_str] = entries
        member = guild.get_member(uid)
        if member:
            try:
                dm = discord.Embed(
                    title=f"{cat_meta['emoji']}  Nový quest v deníku",
                    description=f"**{quest_name}**" + (f"\n{quest_info}" if quest_info else ""),
                    color=STATUS_META[Status.ACTIVE]["color"],
                )
                if xp:
                    dm.add_field(name="✨ Odměna", value=xp, inline=True)
                dm.set_footer(text=f"⭐ {ARION_NAME}  ·  Zapsáno do tvého deníku s tagem 📜")
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

def format_side_block(name: str, data: dict, status: str = Status.ACTIVE) -> str:
    """Side quest bez rodiče — samostatný blok."""
    meta   = STATUS_META.get(status, STATUS_META[Status.ACTIVE])
    xp     = data.get("xp")
    info   = data.get("info", "")
    added  = data.get("added", "?")
    closed = data.get("closed")

    s_suffix = f"  {meta['emoji']}" if status != Status.ACTIVE else ""
    lines = [f"📜 **(side)**{s_suffix}  **{name}**"]
    if info:
        lines.append(f"*{info}*")
    if xp:
        lines.append(f"⭐ xp: {xp}")
    lines.append(_status_line(added, closed))
    return "\n".join(lines)

def quest_embed(name: str, data: dict, guild: discord.Guild | None = None,
                status: str = Status.ACTIVE) -> discord.Embed:
    """Jednoduchý embed pro DiaryQuestView (tlačítko v deníku)."""
    meta     = STATUS_META.get(status, STATUS_META[Status.ACTIVE])
    cat      = data.get("category", Category.SIDE)
    cat_meta = CATEGORY_META.get(cat, CATEGORY_META[Category.SIDE])
    xp       = data.get("xp")
    added    = data.get("added", "?")
    closed   = data.get("closed")
    parent   = data.get("parent_quest")

    cat_label = f"{cat_meta['label']} (main)" if cat == Category.MAIN else f"{cat_meta['label']} (side)"
    status_suffix = f"  {meta['emoji']} *{status.capitalize()}*" if status != Status.ACTIVE else ""

    info = data.get("info", "")
    desc_parts = []
    if info:
        desc_parts.append(f"*{info}*")
    if xp:
        desc_parts.append(f"⭐ xp: {xp}")
    if parent:
        desc_parts.append(f"-# ↳ {parent}")
    desc_parts.append(_status_line(added, closed))

    embed = discord.Embed(
        title=f"📜  {name}  ({cat_label}){status_suffix}",
        description="\n".join(desc_parts),
        color=meta["color"],
    )
    embed.set_footer(text=f"⭐ {ARION_NAME}")
    return embed


# ── View: tlačítko QUESTY v deníku ────────────────────────────────────────────

class DiaryQuestView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="📜 Questy", style=discord.ButtonStyle.success)
    async def show_quests(self, interaction: discord.Interaction, button: discord.ui.Button):
        quests = load_quests()
        user_quests = {
            name: data for name, data in quests.items()
            if self.user_id in data.get("members", [])
        }
        if not user_quests:
            await interaction.response.send_message("Nemáš žádné aktivní questy.", ephemeral=True)
            return

        n     = len(user_quests)
        label = "aktivní quest" if n == 1 else "aktivní questy" if n <= 4 else "aktivních questů"
        header = discord.Embed(
            title="📜  Tvoje aktivní questy",
            description=f"Máš **{n}** {label}.",
            color=STATUS_META[Status.ACTIVE]["color"],
        )
        header.set_footer(text=f"⭐ {ARION_NAME}")
        embeds = [quest_embed(name, data) for name, data in user_quests.items()]
        await interaction.response.send_message(embeds=[header] + embeds[:9], ephemeral=True)


# ── Migrace — seed nových questů při startu ────────────────────────────────────

_SEED_QUESTS = {
    # ── Král hvězdy ───────────────────────────────────────────────────────────
    "Volání hvězdy": {
        "info":         "Velký turnaj se blíží a brzy přiletí hvězda, která změní osud všech.",
        "xp":           "160 000",
        "category":     Category.MAIN,
        "parent_quest": None,
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

_SYNC_FIELDS = {"info", "xp", "category", "parent_quest"}

def _migrate_quests():
    """Při startu přidá chybějící questy, synchronizuje metadata a opraví pořadí."""
    quests  = load_quests()
    changed = False

    # Odstraň starý "Stíny v srdci" se špatným parent_quest
    if "Stíny v srdci" in quests and quests["Stíny v srdci"].get("parent_quest") not in ("Volání hvězdy", None):
        del quests["Stíny v srdci"]
        changed = True

    # Přidej chybějící + synchronizuj metadata
    for name, seed in _SEED_QUESTS.items():
        if name not in quests:
            quests[name] = seed
            changed = True
        else:
            for field in _SYNC_FIELDS:
                if quests[name].get(field) != seed.get(field):
                    quests[name][field] = seed[field]
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

    @app_commands.command(name="quests", description="Zobraz všechny aktivní questy")
    async def quests_list(self, interaction: discord.Interaction):
        quests = load_quests()

        if not quests:
            embed = discord.Embed(
                title="📜  Aktivní questy",
                description="*Momentálně nejsou žádné aktivní questy.*",
                color=STATUS_META[Status.ACTIVE]["color"],
            )
            embed.set_footer(text=f"⭐ {ARION_NAME}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        mains = {n: d for n, d in quests.items() if d.get("category") == Category.MAIN}
        sides = {n: d for n, d in quests.items() if d.get("category") == Category.SIDE}

        blocks   = []
        used_sides = set()

        for main_name, main_data in mains.items():
            # Najdi side questy patřící pod tento main
            children = [
                (sn, sd, Status.ACTIVE)
                for sn, sd in sides.items()
                if sd.get("parent_quest") == main_name
            ]
            for sn, _, _ in children:
                used_sides.add(sn)
            blocks.append(format_main_block(main_name, main_data, interaction.guild, children))

        # Side questy bez rodiče
        for side_name, side_data in sides.items():
            if side_name not in used_sides:
                blocks.append(format_side_block(side_name, side_data))

        n     = len(quests)
        label = "quest" if n == 1 else "questy" if n <= 4 else "questů"
        embed = discord.Embed(
            title="📜  Aktivní questy",
            description="\n\n".join(blocks),
            color=STATUS_META[Status.ACTIVE]["color"],
        )
        embed.set_footer(text=f"⭐ {ARION_NAME}  ·  {n} {label} celkem")
        await interaction.response.send_message(embed=embed)

    # ── /quest add ────────────────────────────────────────────────────────────

    @quest_group.command(name="add", description="Vytvoř nový quest a přidej ho hráčům do deníků")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Název questu",
        info="Popis / zadání questu",
        category="Typ questu (Main = automaticky všichni hráči)",
        xp="Odměna za splnění (volitelné)",
        members="Hráči oddělení mezerou (@zmínka) — jen pro Side questy",
        parent_quest="Main quest ke kterému patří (jen pro side questy)",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="⚔️ Main Quest — pro všechny", value=Category.MAIN),
        app_commands.Choice(name="🗺️ Side Quest — pro vybrané", value=Category.SIDE),
    ])
    async def quest_add(
        self,
        interaction: discord.Interaction,
        name: str,
        info: str,
        category: str = Category.SIDE,
        xp: str | None = None,
        members: str | None = None,
        parent_quest: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name in quests:
            await interaction.followup.send(
                f"Quest **{name}** již existuje.", ephemeral=True
            )
            return

        # Validace parent_quest — musí existovat a být main quest
        if parent_quest is not None:
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
            if category == Category.MAIN:
                await interaction.followup.send(
                    "Main quest nemůže mít nadřazený quest.", ephemeral=True
                )
                return

        guild = interaction.guild

        if category == Category.MAIN:
            # Main quest → automaticky všichni non-bot členové
            member_ids = [m.id for m in guild.members if not m.bot]
        else:
            # Side quest → povinný members parametr
            if not members:
                await interaction.followup.send(
                    "Pro Side quest musíš zadat `members:` (@zmínka hráčů).", ephemeral=True
                )
                return
            member_ids = _parse_member_mentions(members, guild)
            if not member_ids:
                await interaction.followup.send(
                    "Nepodařilo se najít žádné platné členy. Použij @zmínku.", ephemeral=True
                )
                return

        quests[name] = {
            "info":         info,
            "xp":           xp,
            "category":     category,
            "parent_quest": parent_quest,
            "members":      member_ids,
            "added":        today(),
        }
        save_quests(quests)

        diaries   = load_diaries()
        dm_errors = await _assign_and_notify(guild, member_ids, diaries, name, info, category, xp)
        save_diaries(diaries)

        cat_meta = CATEGORY_META[category]
        if category == Category.MAIN:
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
        announce.set_footer(text=f"⭐ {ARION_NAME}  ·  Quest byl zapsán do deníků hráčů")
        await interaction.channel.send(embed=announce)

        msg = f"✅ Quest **{name}** přidán a zapsán do {len(member_ids)} deníků."
        if dm_errors:
            msg += f"\n⚠️ DM se nepodařilo odeslat: {', '.join(dm_errors)}."
        await interaction.followup.send(msg, ephemeral=True)

    # ── on_member_join — nový hráč dostane všechny aktivní main questy ────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        quests = load_quests()
        main_quests = {n: d for n, d in quests.items() if d.get("category") == Category.MAIN}
        if not main_quests:
            return

        diaries = load_diaries()
        uid_str = str(member.id)
        entries = _migrate_entries(diaries.get(uid_str, []))

        # Přidej každý aktivní main quest do deníku nového hráče
        for qname, qdata in main_quests.items():
            # Zapiš do deníku
            entries.append(make_diary_entry(qname, qdata.get("info", ""), qdata.get("xp")))
            # Přidej hráče do member listu questu
            if member.id not in qdata.get("members", []):
                qdata.setdefault("members", []).append(member.id)

        diaries[uid_str] = entries
        save_diaries(diaries)
        save_quests(quests)

        # DM nováčkovi
        try:
            embed = discord.Embed(
                title="⚔️  Vítej ve světě Aurionis",
                description="Tvůj příběh právě začíná. Záznamy byly přidány do tvého deníku.",
                color=STATUS_META[Status.ACTIVE]["color"],
            )
            for qname, qdata in main_quests.items():
                embed.add_field(
                    name=f"📜 {qname}",
                    value=f"*{qdata.get('info', '')}*",
                    inline=False,
                )
            embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Napiš /diary show")
            await member.send(embed=embed)
        except discord.Forbidden:
            pass

    # ── /quest status ─────────────────────────────────────────────────────────

    @quest_group.command(name="status", description="Změň stav questu")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Název questu", status="Nový stav")
    @app_commands.choices(status=[
        app_commands.Choice(name="🟢 Aktivní",   value=Status.ACTIVE),
        app_commands.Choice(name="✅ Dokončený", value=Status.COMPLETED),
        app_commands.Choice(name="❌ Neúspěšný", value=Status.FAILED),
    ])
    async def quest_status(self, interaction: discord.Interaction, name: str, status: str):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name not in quests:
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

        if status in (Status.COMPLETED, Status.FAILED):
            quest_data["status"] = status
            quest_data["closed"] = today()

            log = load_quest_log()
            log.append({"name": name, **quest_data})
            save_quest_log(log)

            del quests[name]
            save_quests(quests)

            diaries  = load_diaries()
            dm_embed = discord.Embed(
                title=f"{meta['emoji']}  Quest {status}",
                description=f"**{name}**",
                color=meta["color"],
            )
            dm_embed.set_footer(text=f"⭐ {ARION_NAME}  ·  Zapsáno do tvého deníku")
            for uid in member_ids:
                uid_str = str(uid)
                entries = _migrate_entries(diaries.get(uid_str, []))
                if not update_diary_quest_status(entries, name, status):
                    entries.append({
                        "text":   f"{today()} — {meta['emoji']} **{name}** — {status.upper()}",
                        "pinned": False,
                        "tag":    QUEST_TAG,
                    })
                diaries[uid_str] = entries
                member = guild.get_member(uid)
                if member:
                    try:
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        pass
            save_diaries(diaries)

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

    # ── /quest log ────────────────────────────────────────────────────────────

    @quest_group.command(name="log", description="Zobraz historii všech questů (aktivní i uzavřené)")
    @app_commands.describe(status="Filtrovat podle výsledku", category="Filtrovat podle kategorie")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="🟢 Aktivní",   value=Status.ACTIVE),
            app_commands.Choice(name="✅ Dokončené", value=Status.COMPLETED),
            app_commands.Choice(name="❌ Neúspěšné", value=Status.FAILED),
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

        # Rozděl na stránky — každý blok může mít 3-5 řádků, bezpečný limit je 8 bloků/stránku
        page_size = 8
        pages     = [blocks[i:i + page_size] for i in range(0, len(blocks), page_size)]
        total     = len(all_quests)
        n_pages   = len(pages)

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
            embed.set_footer(text=footer)
            embeds.append(embed)

        await interaction.response.send_message(embeds=embeds[:10], ephemeral=True)

    # ── /quest remove ─────────────────────────────────────────────────────────

    @quest_group.command(name="remove", description="Odeber quest z databáze a ze všech deníků")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Název questu k odebrání")
    async def quest_remove(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        quests = load_quests()
        if name not in quests:
            await interaction.followup.send(f"Quest **{name}** neexistuje.", ephemeral=True)
            return

        member_ids = quests[name].get("members", [])
        del quests[name]
        save_quests(quests)

        diaries = load_diaries()
        removed_from = 0
        for uid in member_ids:
            uid_str = str(uid)
            if uid_str not in diaries:
                continue
            before   = len(diaries[uid_str])
            filtered = []
            for e in diaries[uid_str]:
                text = e["text"] if isinstance(e, dict) else str(e)
                if QUEST_TAG in text and f"**{name}**" in text:
                    continue
                filtered.append(e)
            diaries[uid_str] = filtered
            if len(filtered) < before:
                removed_from += 1

        save_diaries(diaries)
        log_action("quest_remove", interaction.user.display_name, name)
        await interaction.followup.send(
            f"🗑️ Quest **{name}** odebrán z databáze a smazán z {removed_from} deníků.",
            ephemeral=True,
        )

    # ── /quest give ───────────────────────────────────────────────────────────

    @quest_group.command(name="give", description="Přiřaď existující quest hráčům")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Název questu", members="Hráči oddělení mezerou (@zmínka)")
    async def quest_give(self, interaction: discord.Interaction, name: str, members: str):
        await interaction.response.defer(ephemeral=True)
        quests = load_quests()
        if name not in quests:
            await interaction.followup.send(f"Quest **{name}** neexistuje.", ephemeral=True)
            return
        quest_data = quests[name]
        guild      = interaction.guild

        new_ids = _parse_member_mentions(members, guild, exclude_ids=set(quest_data.get("members", [])))
        if not new_ids:
            await interaction.followup.send("Žádní noví hráči k přiřazení.", ephemeral=True)
            return

        quest_data.setdefault("members", []).extend(new_ids)
        save_quests(quests)

        diaries   = load_diaries()
        dm_errors = await _assign_and_notify(
            guild, new_ids, diaries, name,
            quest_data.get("info", ""), quest_data.get("category", Category.SIDE), quest_data.get("xp"),
        )
        save_diaries(diaries)

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
        announce.set_footer(text=f"⭐ {ARION_NAME}  ·  Quest byl zapsán do deníků hráčů")
        await interaction.channel.send(embed=announce)

        members_str = ", ".join(guild.get_member(uid).display_name if guild.get_member(uid) else str(uid) for uid in new_ids)
        log_action("quest_give", interaction.user.display_name, name, members_str)
        msg = f"✅ Quest **{name}** přiřazen {len(new_ids)} hráčům."
        if dm_errors:
            msg += f"\n⚠️ DM se nepodařilo odeslat: {', '.join(dm_errors)}."
        await interaction.followup.send(msg, ephemeral=True)

    # ── Autocomplete (sdílené pro remove + status + give) ─────────────────────

    @quest_remove.autocomplete("name")
    @quest_status.autocomplete("name")
    @quest_give.autocomplete("name")
    async def quest_name_autocomplete(self, interaction: discord.Interaction, current: str):
        quests = load_quests()
        return [
            app_commands.Choice(name=n, value=n)
            for n in quests if current.lower() in n.lower()
        ][:25]

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