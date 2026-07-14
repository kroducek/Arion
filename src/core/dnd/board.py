import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import random

from src.utils.paths import QUESTS as QUESTS_FILE
from src.utils.json_utils import load_json, save_json
from src.utils.audit import log_action
from src.database.characters import pkey

from src.core.dnd.quests import (
    load_quests, save_quests, today, Category, Status,
    _assign_and_notify, load_diaries, save_diaries,
)
from src.core.dnd.ranks import (
    DIFFICULTY, DEFAULT_DIFFICULTY, RANK_LADDER, STARTING_RANK,
    rank_index, get_rank,
)

logger = logging.getLogger("Board")

# Destinace bereme z onboardu — jediný zdroj pravdy. Přidáš tam město → naskočí i tady.
try:
    from src.logic.onboard import DESTINATIONS
except Exception:                     # kdyby se onboard nenačetl, nástěnka nesmí spadnout
    logger.exception("[board] import DESTINATIONS selhal")
    DESTINATIONS = {}

ARION_NAME  = "Aurionis"
BOARD_COLOR = 0xC9A227

# ══════════════════════════════════════════════════════════════════════════════
# LADĚNÍ
# ══════════════════════════════════════════════════════════════════════════════

OFFER_COUNT      = 3     # kolik zakázek visí na JEDNÉ nástěnce
MAX_BOARD_QUESTS = 1     # kolik questů z nástěnky smí mít hráč rozdělaných

ANYWHERE = "kdekoliv"    # zakázka bez konkrétní destinace — visí na VŠECH nástěnkách

# ── Druhy zakázek ─────────────────────────────────────────────────────────────
class QType:
    EXCLUSIVE = "exclusive"   # kdo dřív klikne — zmizí z nástěnky
    RACE      = "race"        # závod: může vzít víc lidí, VISÍ DÁL, vyhraje kdo splní první
    GROUP     = "group"       # skupinová: vůdce vezme, ostatní potvrdí, jdou na to spolu

QTYPE_META: dict[str, dict] = {
    QType.EXCLUSIVE: {"emoji": "📜", "label": "Zakázka",
                      "desc": "Vezme si ji první, kdo klikne."},
    QType.RACE:      {"emoji": "🏁", "label": "Závod",
                      "desc": "Může vzít víc dobrodruhů. Vyhrává, kdo splní první."},
    QType.GROUP:     {"emoji": "🛡️", "label": "Skupinová",
                      "desc": "Vezme ji vůdce party, členové potvrdí."},
}
DEFAULT_QTYPE = QType.EXCLUSIVE

MIN_GROUP_SIZE  = 2      # kolik dobrodruhů minimálně na skupinovou zakázku
GROUP_TIMEOUT   = 600    # kolik vteřin má parta na sesbírání (10 min)

# Značka, podle které poznáme quest vzatý z nástěnky. Díky ní NEPOTŘEBUJEME
# druhý stav — limit se odvodí z quests.json a po uzavření questu se uvolní SÁM.
BOARD_SOURCE = "board"

# Data vedle ostatních JSONů (stejný adresář jako quests.json).
_DATA_DIR        = os.path.dirname(QUESTS_FILE)
QUEST_POOL_FILE  = os.path.join(_DATA_DIR, "quest_pool.json")
QUEST_BOARD_FILE = os.path.join(_DATA_DIR, "quest_board.json")


def board_keys() -> list[str]:
    """Všechny možné nástěnky: každé město + obecná."""
    return list(DESTINATIONS.keys()) + [ANYWHERE]

def dest_label(key: str | None) -> str:
    """'aquion' → '🌊 Aquion'.  None / 'kdekoliv' → '🗺️ Kdekoliv'."""
    if not key or key == ANYWHERE:
        return "🗺️ Kdekoliv"
    d = DESTINATIONS.get(key)
    return f"{d['emoji']} {d['name']}" if d else key

def dest_color(key: str | None) -> int:
    d = DESTINATIONS.get(key or "")
    return d.get("color", BOARD_COLOR) if d else BOARD_COLOR


# ══════════════════════════════════════════════════════════════════════════════
# ÚLOŽIŠTĚ
# ══════════════════════════════════════════════════════════════════════════════

def load_pool() -> dict:
    return load_json(QUEST_POOL_FILE, default={})

def save_pool(data: dict):
    save_json(QUEST_POOL_FILE, data)


def load_boards() -> dict:
    """{dest_key: {channel_id, message_id, offers}}  — jedna nástěnka na destinaci."""
    raw = load_json(QUEST_BOARD_FILE, default={})

    # Migrace ze starého formátu (jedna globální nástěnka na top-levelu).
    if "offers" in raw or "channel_id" in raw:
        raw = {ANYWHERE: {
            "channel_id": raw.get("channel_id"),
            "message_id": raw.get("message_id"),
            "offers":     raw.get("offers", []),
        }}
        save_json(QUEST_BOARD_FILE, raw)
        logger.info("[board] migrace: jedna nástěnka → nástěnka podle destinace")

    for key in board_keys():
        b = raw.setdefault(key, {})
        b.setdefault("channel_id", None)
        b.setdefault("message_id", None)
        b.setdefault("offers", [])
    return raw

def save_boards(data: dict):
    save_json(QUEST_BOARD_FILE, data)


# ══════════════════════════════════════════════════════════════════════════════
# LOGIKA
# ══════════════════════════════════════════════════════════════════════════════

def taken_names() -> set[str]:
    """Zakázky, které si někdo vzal a tím je STÁHL z nástěnky.

    ZÁVOD se sem NEPOČÍTÁ — ten visí dál a může se do něj přidat kdokoli další.
    """
    return {
        n for n, q in load_quests().items()
        if q.get("source") == BOARD_SOURCE
        and q.get("status", Status.ACTIVE) == Status.ACTIVE
        and q.get("qtype", DEFAULT_QTYPE) != QType.RACE
    }

def race_counts() -> dict[str, int]:
    """{název závodní zakázky: kolik lidí závodí}"""
    return {
        n: len(q.get("members") or [])
        for n, q in load_quests().items()
        if q.get("source") == BOARD_SOURCE
        and q.get("qtype") == QType.RACE
        and q.get("status", Status.ACTIVE) == Status.ACTIVE
    }

def player_board_quests(user_id: int) -> list[str]:
    """Rozdělané questy hráče z nástěnky. Odvozeno z quests.json — žádný extra stav."""
    return [
        name for name, q in load_quests().items()
        if q.get("source") == BOARD_SOURCE
        and user_id in (q.get("members") or [])
        and q.get("status", Status.ACTIVE) == Status.ACTIVE
    ]

def can_take(user_id: int, quest: dict) -> tuple[bool, str]:
    """Smí hráč vzít tenhle quest? → (ano, důvod když ne)."""
    active = player_board_quests(user_id)
    if len(active) >= MAX_BOARD_QUESTS:
        return False, (f"Už máš rozdělanou zakázku: **{active[0]}**.\n"
                       f"-# Dokonči ji, než si vezmeš další.")

    rank, _ = get_rank(user_id)
    min_rank = quest.get("min_rank", STARTING_RANK)
    if rank_index(rank) < rank_index(min_rank):
        return False, f"Na tuhle zakázku potřebuješ rank **{min_rank}** (máš **{rank}**)."
    return True, ""


def pool_for(dest: str, pool: dict) -> list[str]:
    """Zakázky vhodné pro nástěnku dané destinace.

    Nástěnka města  → zakázky toho města + univerzální ('kdekoliv').
    Obecná nástěnka → jen univerzální.
    """
    out = []
    for name, q in pool.items():
        qd = q.get("destination", ANYWHERE)
        if qd == dest or (dest != ANYWHERE and qd == ANYWHERE):
            out.append(name)
    return out


def reroll_offers(dest: str, pool: dict) -> list[str]:
    """Vylosuje novou nabídku pro jednu nástěnku. Rozdělané zakázky se nelosují."""
    taken     = taken_names()
    available = [n for n in pool_for(dest, pool) if n not in taken]
    random.shuffle(available)
    return available[:OFFER_COUNT]


def board_embed(dest: str, offers: list[str], pool: dict) -> discord.Embed:
    title = ("📌  Nástěnka dobrodruhů" if dest == ANYWHERE
             else f"📌  Nástěnka — {dest_label(dest)}")
    embed = discord.Embed(
        title=title,
        description=("Zakázky vyvěšené v guildě. Vezmi si jednu — a vrať se s vítězstvím.\n"
                     f"-# Naráz můžeš mít rozdělanou **{MAX_BOARD_QUESTS}** zakázku."),
        color=dest_color(dest),
    )
    if not offers:
        embed.add_field(name="— prázdná —",
                        value="Momentálně tu nic nevisí. Zeptej se později.",
                        inline=False)
    races = race_counts()
    for i, name in enumerate(offers):
        q    = pool.get(name, {})
        diff = DIFFICULTY.get(q.get("difficulty", DEFAULT_DIFFICULTY), {})
        xp   = q.get("xp")
        mr   = q.get("min_rank", STARTING_RANK)

        qt   = q.get("qtype", DEFAULT_QTYPE)
        qm   = QTYPE_META.get(qt, QTYPE_META[DEFAULT_QTYPE])

        meta = [f"{diff.get('label', '?')}", f"**{mr}+**"]
        # na městské nástěnce dává smysl označit jen ty univerzální
        if q.get("destination", ANYWHERE) == ANYWHERE and dest != ANYWHERE:
            meta.insert(0, "🗺️ Kdekoliv")
        if xp:
            meta.append(f"⭐ {xp} XP")

        head = f"{qm['emoji']} {i + 1}.  {name}"
        body = [f"*{q.get('info', '')}*"]
        if qt == QType.RACE:
            n_racers = races.get(name, 0)
            body.append(f"-# 🏁 **Závod** — kdo splní první, bere odměnu."
                        + (f"  ·  závodí **{n_racers}**" if n_racers else ""))
        elif qt == QType.GROUP:
            body.append(f"-# 🛡️ **Skupinová** — bere ji **vůdce party** "
                        f"(min. {MIN_GROUP_SIZE} dobrodruzi).")
        body.append(f"-# {'  ·  '.join(meta)}")

        embed.add_field(name=head, value="\n".join(body), inline=False)
    embed.set_footer(text=f"⭐ {ARION_NAME}")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# VIEW — persistent (tlačítka musí přežít restart bota!)
# ══════════════════════════════════════════════════════════════════════════════

class BoardView(discord.ui.View):
    """Jedna view na destinaci. custom_id = 'board:<dest>:<idx>' → tlačítko ví,
    ke které nástěnce patří, a funguje i po restartu bota.

    Nabídku čteme ze souboru při KAŽDÉM kliknutí — proto view nemusí nic pamatovat.
    """

    def __init__(self, dest: str):
        super().__init__(timeout=None)          # timeout=None → persistent
        self.dest = dest
        for i in range(OFFER_COUNT):
            btn = discord.ui.Button(
                label=str(i + 1),
                style=discord.ButtonStyle.success,
                emoji="📜",
                custom_id=f"board:{dest}:{i}",
            )
            btn.callback = self._make_cb(i)
            self.add_item(btn)

    def _make_cb(self, idx: int):
        async def cb(interaction: discord.Interaction):
            await self._take(interaction, idx)
        return cb

    async def _take(self, interaction: discord.Interaction, idx: int):
        await interaction.response.defer(ephemeral=True)
        try:
            boards = load_boards()
            pool   = load_pool()
            offers = boards.get(self.dest, {}).get("offers", [])

            if idx >= len(offers):
                await interaction.followup.send(
                    "Tahle zakázka už na nástěnce nevisí.", ephemeral=True)
                return

            name = offers[idx]
            q    = pool.get(name)
            if not q:
                await interaction.followup.send(
                    f"Zakázka **{name}** už v zásobníku není.", ephemeral=True)
                return

            uid   = interaction.user.id
            qtype = q.get("qtype", DEFAULT_QTYPE)

            # má vůbec postavu?
            from src.utils.paths import PROFILES as _PF
            if pkey(uid) not in load_json(_PF, default={}):
                await interaction.followup.send(
                    "Nemáš průkaz dobrodruha — projdi nejdřív tutoriálem.", ephemeral=True)
                return

            ok, why = can_take(uid, q)
            if not ok:
                await interaction.followup.send(f"❌ {why}", ephemeral=True)
                return

            quests = load_quests()
            existing = quests.get(name)

            # ── ZÁVOD: zakázku může vzít víc lidí a VISÍ DÁL ─────────────────
            if qtype == QType.RACE:
                if existing:
                    if uid in existing.get("members", []):
                        await interaction.followup.send(
                            "Tuhle zakázku už závodíš.", ephemeral=True)
                        return
                    existing.setdefault("members", []).append(uid)
                else:
                    quests[name] = _new_quest(q, [uid], qtype)
                save_quests(quests)

                await _write_diary(interaction.guild, [uid], name, q)
                await refresh_all_boards(interaction.client, boards)   # jen přepočet počtu

                racers = len(quests[name]["members"])
                log_action("board_race", interaction.user.display_name,
                           interaction.user.display_name, name)
                await interaction.followup.send(
                    f"🏁 Vstoupil/a jsi do závodu o **{name}**.\n"
                    f"-# Závodí {racers} dobrodruhů. Kdo splní první, bere odměnu.",
                    ephemeral=True)
                return

            # ── SKUPINOVÁ: bere ji jen VŮDCE PARTY, členové potvrdí ──────────
            if qtype == QType.GROUP:
                if existing:
                    await interaction.followup.send(
                        "Tuhle zakázku už si někdo vzal.", ephemeral=True)
                    return

                leads = led_parties(uid)
                if not leads:
                    await interaction.followup.send(
                        "🛡️ Skupinovou zakázku může vzít **jen vůdce party**.\n"
                        "-# Založ partu (`/party create`), nebo ať ji vezme tvůj vůdce.",
                        ephemeral=True)
                    return

                # parta musí mít dost lidí, aby to vůbec šlo dotáhnout
                big_enough = [(n, p) for n, p in leads
                              if len(p.get("members", [])) >= MIN_GROUP_SIZE]
                if not big_enough:
                    await interaction.followup.send(
                        f"🛡️ Tvoje parta má málo členů — potřebuješ aspoň "
                        f"**{MIN_GROUP_SIZE}** dobrodruhy.", ephemeral=True)
                    return

                if len(big_enough) > 1:
                    # vede víc part → ať si vybere
                    pick = PartyPickView(self.dest, name, interaction.user, big_enough)
                    await interaction.followup.send(
                        f"Vedeš víc part — se kterou vezmeš **{name}**?",
                        view=pick, ephemeral=True)
                    return

                pname, party = big_enough[0]
                view = GroupTakeView(self.dest, name, interaction.user, pname, party)
                msg  = await interaction.channel.send(
                    embed=view.build_embed(pool), view=view)
                view.message = msg
                await interaction.followup.send(
                    f"🛡️ Svolal/a jsi partu **{pname}** na **{name}**.\n"
                    f"-# Ať členové kliknou *Potvrdit*. Pak dej *Vyrazit*.",
                    ephemeral=True)
                return

            # ── EXKLUZIVNÍ: první bere, mizí ─────────────────────────────────
            if existing:
                await interaction.followup.send(
                    "Tuhle zakázku už si někdo vzal.", ephemeral=True)
                return

            quests[name] = _new_quest(q, [uid], qtype)
            save_quests(quests)
            await _write_diary(interaction.guild, [uid], name, q)

            # Univerzální zakázka visí na VÍC nástěnkách → sundej ji ze všech
            # a všechny překresli, ať si ji nikdo nezkusí vzít podruhé.
            _drop_from_boards(boards, name)
            save_boards(boards)
            await refresh_all_boards(interaction.client, boards)

            log_action("board_take", interaction.user.display_name,
                       interaction.user.display_name, f"{name} ({self.dest})")
            await interaction.followup.send(
                f"📜 Vzal/a jsi zakázku **{name}**.\n"
                f"-# Zapsáno do deníku. Dokonči ji, než si vezmeš další.",
                ephemeral=True)
        except Exception:
            logger.exception(f"[board] převzetí zakázky selhalo ({self.dest}/{idx})")
            try:
                await interaction.followup.send("❌ Něco se pokazilo.", ephemeral=True)
            except Exception:
                pass


def _new_quest(q: dict, members: list[int], qtype: str) -> dict:
    """Záznam do quests.json — dál to jede stávajícím systémem."""
    return {
        "info":         q.get("info", ""),
        "xp":           q.get("xp"),
        "category":     Category.SOLO,
        "difficulty":   q.get("difficulty", DEFAULT_DIFFICULTY),
        "destination":  q.get("destination", ANYWHERE),
        "qtype":        qtype,
        "parent_quest": None,
        "members":      list(members),
        "added":        today(),
        "source":       BOARD_SOURCE,
    }


async def _write_diary(guild, member_ids: list[int], name: str, q: dict) -> None:
    """Zápis do deníku + DM (recyklujeme helper z quests.py)."""
    _dest = q.get("destination")
    _info = q.get("info", "")
    if _dest and _dest != ANYWHERE:
        _info = f"{_info}\n📍 {dest_label(_dest)}".strip()
    diaries = load_diaries()
    await _assign_and_notify(
        guild, member_ids, diaries, name, _info, Category.SOLO, q.get("xp"))
    save_diaries(diaries)


def _drop_from_boards(boards: dict, name: str) -> None:
    for b in boards.values():
        if name in b.get("offers", []):
            b["offers"] = [n for n in b["offers"] if n != name]


# ══════════════════════════════════════════════════════════════════════════════
# SKUPINOVÁ ZAKÁZKA — bere ji VŮDCE PARTY, členové potvrdí
# ══════════════════════════════════════════════════════════════════════════════

# parties.json čteme přímo (stejný tvar jako PartyManager) — žádný import navíc.
def load_parties() -> dict:
    from src.utils.paths import PARTIES
    return load_json(PARTIES, default={})

def led_parties(user_id: int) -> list[tuple[str, dict]]:
    """Party, kterým je hráč VŮDCEM. (Hráč jich může mít až 3.)"""
    return [(n, p) for n, p in load_parties().items()
            if p.get("leader") == user_id]


class GroupTakeView(discord.ui.View):
    """Vůdce svolá partu na zakázku, členové potvrdí, vůdce vyrazí.

    Krátkodobá view (10 min) — nepřežije restart, a nemusí: když bot spadne,
    zakázka na nástěnce pořád visí a parta se svolá znovu.
    """

    def __init__(self, dest: str, quest_name: str, leader: discord.Member,
                 party_name: str, party: dict):
        super().__init__(timeout=GROUP_TIMEOUT)
        self.dest       = dest
        self.name       = quest_name
        self.leader     = leader
        self.party_name = party_name
        # členové party kromě vůdce — ti musí potvrdit
        self.roster     = [m for m in party.get("members", []) if m != leader.id]
        self.confirmed  = {leader.id}          # vůdce je potvrzený automaticky
        self.message    = None

    def build_embed(self, pool: dict | None = None) -> discord.Embed:
        pool = pool if pool is not None else load_pool()
        q    = pool.get(self.name, {})
        diff = DIFFICULTY.get(q.get("difficulty", DEFAULT_DIFFICULTY), {})

        embed = discord.Embed(
            title=f"🛡️  Skupinová zakázka — {self.name}",
            description=(f"*{q.get('info', '')}*\n\n"
                         f"**{self.leader.display_name}** svolává partu "
                         f"**{self.party_name}**.\n"
                         f"-# {diff.get('label','?')}  ·  "
                         f"{q.get('min_rank', STARTING_RANK)}+  ·  "
                         f"{dest_label(q.get('destination'))}"),
            color=dest_color(self.dest),
        )
        rows = [f"👑 <@{self.leader.id}>  ✅"]
        for m in self.roster:
            rows.append(f"• <@{m}>  " + ("✅" if m in self.confirmed else "⏳"))
        embed.add_field(
            name=f"Parta ({len(self.confirmed)}/{len(self.roster) + 1} potvrzeno)",
            value="\n".join(rows),
            inline=False,
        )
        embed.set_footer(
            text=f"Min. {MIN_GROUP_SIZE} dobrodruzi  ·  vyrazit může jen vůdce  ·  ⭐ {ARION_NAME}")
        return embed

    @discord.ui.button(label="Potvrdit", style=discord.ButtonStyle.primary, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, _b: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.roster:
            await interaction.response.send_message(
                f"Nejsi členem party **{self.party_name}**.", ephemeral=True)
            return
        if uid in self.confirmed:
            await interaction.response.send_message("Už jsi potvrdil/a.", ephemeral=True)
            return

        pool = load_pool()
        q    = pool.get(self.name)
        if not q:
            await interaction.response.send_message("Zakázka už neexistuje.", ephemeral=True)
            return

        from src.utils.paths import PROFILES as _PF
        if pkey(uid) not in load_json(_PF, default={}):
            await interaction.response.send_message(
                "Nemáš průkaz dobrodruha.", ephemeral=True)
            return

        ok, why = can_take(uid, q)
        if not ok:
            await interaction.response.send_message(f"❌ {why}", ephemeral=True)
            return

        self.confirmed.add(uid)
        await interaction.response.edit_message(embed=self.build_embed(pool), view=self)

    @discord.ui.button(label="Vyrazit", style=discord.ButtonStyle.success, emoji="🚀")
    async def start(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if interaction.user.id != self.leader.id:
            await interaction.response.send_message(
                "Vyrazit může jen vůdce party.", ephemeral=True)
            return
        if len(self.confirmed) < MIN_GROUP_SIZE:
            await interaction.response.send_message(
                f"Potřebujete aspoň **{MIN_GROUP_SIZE}** potvrzené dobrodruhy "
                f"(zatím {len(self.confirmed)}).", ephemeral=True)
            return

        await interaction.response.defer()
        pool   = load_pool()
        q      = pool.get(self.name)
        quests = load_quests()
        if not q or self.name in quests:
            await interaction.followup.send("Zakázka už není dostupná.", ephemeral=True)
            return

        members = list(self.confirmed)
        quests[self.name] = _new_quest(q, members, QType.GROUP)
        quests[self.name]["party"] = self.party_name
        save_quests(quests)
        await _write_diary(interaction.guild, members, self.name, q)

        boards = load_boards()
        _drop_from_boards(boards, self.name)
        save_boards(boards)
        await refresh_all_boards(interaction.client, boards)

        log_action("board_group", self.leader.display_name, self.party_name,
                   f"{self.name} ({len(members)} členů)")

        done = discord.Embed(
            title=f"🛡️  Parta {self.party_name} vyrazila — {self.name}",
            description="\n".join(f"• <@{m}>" for m in members),
            color=dest_color(self.dest),
        )
        done.set_footer(text=f"⭐ {ARION_NAME}")
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(embed=done, view=self)
        self.stop()

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if interaction.user.id != self.leader.id:
            await interaction.response.send_message(
                "Zrušit může jen vůdce party.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="❌ Svolávání party zrušeno.", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⌛ Parta se nesešla včas.", embed=None, view=self)
            except Exception:
                pass


class PartyPickView(discord.ui.View):
    """Vůdce vede víc part (limit 3) → ať si vybere, se kterou na to jde."""

    def __init__(self, dest: str, quest_name: str, leader: discord.Member,
                 parties: list[tuple[str, dict]]):
        super().__init__(timeout=120)
        self.dest   = dest
        self.name   = quest_name
        self.leader = leader

        select = discord.ui.Select(
            placeholder="Se kterou partou na to jdeš?",
            options=[
                discord.SelectOption(
                    label=pname,
                    description=f"{len(p.get('members', []))} členů",
                    emoji=p.get("emoji") or "🛡️",
                )
                for pname, p in parties[:25]
            ],
        )
        select.callback = self._picked
        self.add_item(select)
        self._parties = dict(parties)

    async def _picked(self, interaction: discord.Interaction):
        pname = interaction.data["values"][0]
        party = self._parties.get(pname, {})
        view  = GroupTakeView(self.dest, self.name, self.leader, pname, party)
        msg   = await interaction.channel.send(embed=view.build_embed(), view=view)
        view.message = msg
        await interaction.response.edit_message(
            content=f"🛡️ Svolal/a jsi partu **{pname}** na **{self.name}**.", view=None)



async def refresh_board(bot, dest: str, boards: dict | None = None) -> str | None:
    """Překreslí JEDNU nástěnku. Vrací text chyby, nebo None."""
    boards = boards if boards is not None else load_boards()
    b = boards.get(dest, {})
    ch_id, msg_id = b.get("channel_id"), b.get("message_id")
    if not ch_id or not msg_id:
        return f"Nástěnka {dest_label(dest)} není vyvěšená — `/nastenka post`."
    try:
        channel = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
        message = await channel.fetch_message(msg_id)
        await message.edit(embed=board_embed(dest, b.get("offers", []), load_pool()),
                           view=BoardView(dest))
        return None
    except discord.NotFound:
        return f"Zpráva nástěnky {dest_label(dest)} už neexistuje — vyvěs ji znovu."
    except Exception:
        logger.exception(f"[board] refresh {dest} selhal")
        return f"Překreslení nástěnky {dest_label(dest)} selhalo."


async def refresh_all_boards(bot, boards: dict | None = None) -> list[str]:
    """Překreslí všechny VYVĚŠENÉ nástěnky. Vrací seznam chyb."""
    boards = boards if boards is not None else load_boards()
    errors = []
    for dest, b in boards.items():
        if not b.get("message_id"):
            continue                    # nevyvěšená → přeskoč
        err = await refresh_board(bot, dest, boards)
        if err:
            errors.append(err)
    return errors


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

def _dest_choices(include_anywhere: bool = True) -> list[app_commands.Choice]:
    out = [app_commands.Choice(name=f"{d['emoji']} {d['name']}", value=k)
           for k, d in DESTINATIONS.items()]
    if include_anywhere:
        out.append(app_commands.Choice(name="🗺️ Kdekoliv / obecná", value=ANYWHERE))
    return out


class BoardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    nastenka = app_commands.Group(name="nastenka", description="Arion nástěnka")

    # ── Vyvěšení ─────────────────────────────────────────────────────────────

    @nastenka.command(name="post",
                      description="[DM] Vyvěsí nástěnku dané destinace do tohoto kanálu.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(destination="Které město (nebo obecná nástěnka).")
    @app_commands.choices(destination=_dest_choices())
    async def board_post(self, interaction: discord.Interaction, destination: str):
        await interaction.response.defer(ephemeral=True)
        boards = load_boards()
        pool   = load_pool()
        b      = boards.setdefault(destination, {"channel_id": None,
                                                 "message_id": None, "offers": []})
        if not b["offers"]:
            b["offers"] = reroll_offers(destination, pool)

        msg = await interaction.channel.send(
            embed=board_embed(destination, b["offers"], pool),
            view=BoardView(destination))
        b["channel_id"] = interaction.channel.id
        b["message_id"] = msg.id
        save_boards(boards)

        log_action("board_post", interaction.user.display_name, "—", destination)
        await interaction.followup.send(
            f"📌 Nástěnka {dest_label(destination)} vyvěšena "
            f"({len(b['offers'])} zakázek).", ephemeral=True)

    @nastenka.command(name="reload",
                      description="[DM] Vymění zakázky na nástěnce (prázdné = všechny).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(destination="Která nástěnka (prázdné = všechny vyvěšené).")
    @app_commands.choices(destination=_dest_choices())
    async def board_reload(self, interaction: discord.Interaction,
                           destination: str | None = None):
        await interaction.response.defer(ephemeral=True)
        pool = load_pool()
        if not pool:
            await interaction.followup.send(
                "Zásobník je prázdný — přidej zakázky `/nastenka add`.", ephemeral=True)
            return

        boards  = load_boards()
        targets = [destination] if destination else [
            d for d, b in boards.items() if b.get("message_id")
        ]
        if not targets:
            await interaction.followup.send(
                "Žádná nástěnka není vyvěšená — `/nastenka post`.", ephemeral=True)
            return

        lines = []
        for dest in targets:
            b = boards.setdefault(dest, {"channel_id": None,
                                         "message_id": None, "offers": []})
            b["offers"] = reroll_offers(dest, pool)
            lines.append(f"{dest_label(dest)} — **{len(b['offers'])}** zakázek")
        save_boards(boards)

        errors = []
        for dest in targets:
            err = await refresh_board(self.bot, dest, boards)
            if err:
                errors.append(err)

        log_action("board_reload", interaction.user.display_name, "—", ",".join(targets))

        running = len(taken_names())
        msg = "♻️ Nástěnky obnoveny:\n" + "\n".join(f"-# {l}" for l in lines)
        if running:
            msg += f"\n-# Rozdělané zakázky hráčů ({running}) běží dál, nesahal jsem na ně."
        if errors:
            msg += "\n⚠️ " + "\n⚠️ ".join(errors)
        await interaction.followup.send(msg[:1900], ephemeral=True)

    # ── Zásobník ─────────────────────────────────────────────────────────────

    @nastenka.command(name="add", description="[DM] Přidá zakázku do zásobníku.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Název zakázky.",
        info="Zadání / popis.",
        difficulty="Obtížnost — určuje rank body za splnění.",
        destination="Kde se zakázka odehrává (určuje, na které nástěnce visí).",
        qtype="Druh: exkluzivní / závod / skupinová.",
        xp="Odměna XP (volitelné).",
        min_rank="Minimální rank pro převzetí (výchozí F3).",
    )
    @app_commands.choices(difficulty=[
        app_commands.Choice(name=f"{m['label']} — +{m['points']} rank bodů", value=d)
        for d, m in DIFFICULTY.items()
    ])
    @app_commands.choices(destination=_dest_choices())
    @app_commands.choices(qtype=[
        app_commands.Choice(name=f"{m['emoji']} {m['label']} — {m['desc']}", value=k)
        for k, m in QTYPE_META.items()
    ])
    async def board_add(self, interaction: discord.Interaction,
                        name: str, info: str,
                        difficulty: str = DEFAULT_DIFFICULTY,
                        destination: str = ANYWHERE,
                        qtype: str = DEFAULT_QTYPE,
                        xp: str | None = None,
                        min_rank: str = STARTING_RANK):
        await interaction.response.defer(ephemeral=True)
        if min_rank not in RANK_LADDER:
            await interaction.followup.send(f"❌ Rank `{min_rank}` neexistuje.", ephemeral=True)
            return

        pool = load_pool()
        existed = name in pool
        pool[name] = {
            "info":        info,
            "xp":          xp,
            "difficulty":  difficulty,
            "min_rank":    min_rank,
            "destination": destination,
            "qtype":       qtype,
        }
        save_pool(pool)
        log_action("board_add", interaction.user.display_name, "—", name)

        where = ("na všech nástěnkách" if destination == ANYWHERE
                 else f"na nástěnce {dest_label(destination)}")
        qm = QTYPE_META.get(qtype, QTYPE_META[DEFAULT_QTYPE])
        await interaction.followup.send(
            f"✅ Zakázka **{name}** {'upravena' if existed else 'přidána'} "
            f"({len(pool)} v zásobníku).\n"
            f"-# {qm['emoji']} {qm['label']} · visí {where}.\n"
            f"-# Na nástěnku se dostane při `/nastenka reload`.",
            ephemeral=True)

    @nastenka.command(name="remove", description="[DM] Odebere zakázku ze zásobníku.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(name="Zakázka k odebrání.")
    async def board_remove(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        pool = load_pool()
        if name not in pool:
            await interaction.followup.send(f"❌ **{name}** v zásobníku není.", ephemeral=True)
            return
        del pool[name]
        save_pool(pool)

        boards  = load_boards()
        changed = False
        for b in boards.values():
            if name in b.get("offers", []):
                b["offers"] = [n for n in b["offers"] if n != name]
                changed = True
        if changed:
            save_boards(boards)
            await refresh_all_boards(self.bot, boards)

        log_action("board_remove", interaction.user.display_name, "—", name)
        await interaction.followup.send(f"🗑️ **{name}** odebrána ze zásobníku.", ephemeral=True)

    @nastenka.command(name="pool", description="[DM] Vypíše zásobník zakázek.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(destination="Filtr podle destinace (volitelné).")
    @app_commands.choices(destination=_dest_choices())
    async def board_pool(self, interaction: discord.Interaction,
                         destination: str | None = None):
        await interaction.response.defer(ephemeral=True)
        pool = load_pool()
        if destination:
            pool = {n: q for n, q in pool.items()
                    if q.get("destination", ANYWHERE) == destination}
        if not pool:
            await interaction.followup.send(
                "Zásobník je prázdný. Přidej zakázky `/nastenka add`.", ephemeral=True)
            return

        boards   = load_boards()
        on_board = {n for b in boards.values() for n in b.get("offers", [])}
        taken    = taken_names()

        lines = []
        for name, q in pool.items():
            diff = DIFFICULTY.get(q.get("difficulty", DEFAULT_DIFFICULTY), {})
            mark = "📌" if name in on_board else ("⏳" if name in taken else "·")
            qm = QTYPE_META.get(q.get("qtype", DEFAULT_QTYPE), QTYPE_META[DEFAULT_QTYPE])
            lines.append(f"{mark} {qm['emoji']} **{name}**  —  "
                         f"{dest_label(q.get('destination'))}  ·  "
                         f"{diff.get('label','?')}  ·  "
                         f"{q.get('min_rank', STARTING_RANK)}+"
                         + (f"  ·  ⭐ {q['xp']}" if q.get("xp") else ""))

        # 4096 limit na description — radši osekat viditelně než tiše
        desc = ("📌 = visí na nástěnce  ·  ⏳ = někdo ji má rozdělanou\n\n"
                + "\n".join(lines))
        if len(desc) > 4000:
            desc = desc[:3990].rsplit("\n", 1)[0] + "\n-# …"

        title = f"📚  Zásobník zakázek ({len(pool)})"
        if destination:
            title += f" — {dest_label(destination)}"
        embed = discord.Embed(title=title, description=desc, color=dest_color(destination))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @board_remove.autocomplete("name")
    async def _ac_pool(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=n, value=n)
                for n in load_pool() if current.lower() in n.lower()][:25]

    @board_add.autocomplete("min_rank")
    async def _ac_rank(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=r, value=r)
                for r in RANK_LADDER if current.upper() in r.upper()][:25]


async def setup(bot):
    # persistent view pro KAŽDOU nástěnku (jinak tlačítka po restartu umřou)
    for dest in board_keys():
        bot.add_view(BoardView(dest))
    await bot.add_cog(BoardCog(bot))