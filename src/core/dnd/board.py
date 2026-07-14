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

ARION_NAME  = "Aurionis"
BOARD_COLOR = 0xC9A227

# ══════════════════════════════════════════════════════════════════════════════
# LADĚNÍ
# ══════════════════════════════════════════════════════════════════════════════

OFFER_COUNT      = 3     # kolik questů visí na nástěnce naráz
MAX_BOARD_QUESTS = 1     # kolik questů z nástěnky smí mít hráč rozdělaných

# Značka, podle které poznáme quest vzatý z nástěnky. Díky ní NEPOTŘEBUJEME
# druhý stav — limit se odvodí z quests.json a po uzavření questu se uvolní SÁM.
BOARD_SOURCE = "board"

# Data vedle ostatních JSONů (stejný adresář jako quests.json).
_DATA_DIR        = os.path.dirname(QUESTS_FILE)
QUEST_POOL_FILE  = os.path.join(_DATA_DIR, "quest_pool.json")
QUEST_BOARD_FILE = os.path.join(_DATA_DIR, "quest_board.json")

# ══════════════════════════════════════════════════════════════════════════════
# ÚLOŽIŠTĚ
# ══════════════════════════════════════════════════════════════════════════════

def load_pool() -> dict:
    return load_json(QUEST_POOL_FILE, default={})

def save_pool(data: dict):
    save_json(QUEST_POOL_FILE, data)

def load_board() -> dict:
    b = load_json(QUEST_BOARD_FILE, default={})
    b.setdefault("channel_id", None)
    b.setdefault("message_id", None)
    b.setdefault("offers", [])
    return b

def save_board(data: dict):
    save_json(QUEST_BOARD_FILE, data)


def _is_dm(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


# ══════════════════════════════════════════════════════════════════════════════
# LOGIKA
# ══════════════════════════════════════════════════════════════════════════════

def player_board_quests(user_id: int) -> list[str]:
    """Rozdělané questy z nástěnky. Odvozeno z quests.json — žádný extra stav."""
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
        return False, (f"Už máš rozdělaný quest z nástěnky: **{active[0]}**.\n"
                       f"-# Dokonči ho, než si vezmeš další.")

    rank, _ = get_rank(user_id)
    min_rank = quest.get("min_rank", STARTING_RANK)
    if rank_index(rank) < rank_index(min_rank):
        return False, (f"Na tenhle quest potřebuješ rank **{min_rank}** "
                       f"(máš **{rank}**).")
    return True, ""


def reroll_offers(pool: dict, keep: list[str] | None = None) -> list[str]:
    """Vylosuje novou nabídku. Questy, co si někdo vzal, se znovu nelosují."""
    taken = {
        n for n, q in load_quests().items()
        if q.get("source") == BOARD_SOURCE and q.get("status", Status.ACTIVE) == Status.ACTIVE
    }
    available = [n for n in pool if n not in taken]
    random.shuffle(available)
    return available[:OFFER_COUNT]


def board_embed(offers: list[str], pool: dict) -> discord.Embed:
    embed = discord.Embed(
        title="📌  Nástěnka dobrodruhů",
        description=("Zakázky vyvěšené v guildě. Vezmi si jednu — a vrať se s vítězstvím.\n"
                     f"-# Naráz můžeš mít rozdělaný **{MAX_BOARD_QUESTS}** quest z nástěnky."),
        color=BOARD_COLOR,
    )
    if not offers:
        embed.add_field(
            name="— prázdná —",
            value="Momentálně tu nic nevisí. Zeptej se později.",
            inline=False,
        )
    for i, name in enumerate(offers):
        q    = pool.get(name, {})
        diff = DIFFICULTY.get(q.get("difficulty", DEFAULT_DIFFICULTY), {})
        xp   = q.get("xp")
        mr   = q.get("min_rank", STARTING_RANK)

        meta = [f"{diff.get('label', '?')}  ·  **{mr}+**"]
        if xp:
            meta.append(f"⭐ {xp} XP")
        embed.add_field(
            name=f"{i + 1}.  {name}",
            value=f"*{q.get('info', '')}*\n-# {'  ·  '.join(meta)}",
            inline=False,
        )
    embed.set_footer(text=f"⭐ {ARION_NAME}")
    return embed


# ══════════════════════════════════════════════════════════════════════════════
# VIEW — persistent (tlačítka musí přežít restart bota!)
# ══════════════════════════════════════════════════════════════════════════════

class BoardView(discord.ui.View):
    """Persistent view. Tlačítka mají PEVNÉ custom_id, takže fungují i po deployi.

    Nabídku nečteme z paměti, ale ze souboru při každém kliknutí — proto tlačítka
    fungují i po restartu, kdy je view zaregistrované bez znalosti aktuální nabídky.
    """

    def __init__(self):
        super().__init__(timeout=None)          # timeout=None → persistent

    @discord.ui.button(label="1", style=discord.ButtonStyle.success,
                       emoji="📜", custom_id="board:take:0")
    async def take_0(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await self._take(interaction, 0)

    @discord.ui.button(label="2", style=discord.ButtonStyle.success,
                       emoji="📜", custom_id="board:take:1")
    async def take_1(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await self._take(interaction, 1)

    @discord.ui.button(label="3", style=discord.ButtonStyle.success,
                       emoji="📜", custom_id="board:take:2")
    async def take_2(self, interaction: discord.Interaction, _b: discord.ui.Button):
        await self._take(interaction, 2)

    async def _take(self, interaction: discord.Interaction, idx: int):
        await interaction.response.defer(ephemeral=True)
        try:
            board  = load_board()
            pool   = load_pool()
            offers = board.get("offers", [])

            if idx >= len(offers):
                await interaction.followup.send(
                    "Tahle zakázka už na nástěnce nevisí.", ephemeral=True)
                return

            name = offers[idx]
            q    = pool.get(name)
            if not q:
                await interaction.followup.send(
                    f"Quest **{name}** už v zásobníku není.", ephemeral=True)
                return

            uid = interaction.user.id

            # má vůbec postavu?
            from src.utils.json_utils import load_json as _lj
            from src.utils.paths import PROFILES as _PF
            if pkey(uid) not in _lj(_PF, default={}):
                await interaction.followup.send(
                    "Nemáš průkaz dobrodruha — projdi nejdřív tutoriálem.", ephemeral=True)
                return

            ok, why = can_take(uid, q)
            if not ok:
                await interaction.followup.send(f"❌ {why}", ephemeral=True)
                return

            quests = load_quests()
            if name in quests:
                await interaction.followup.send(
                    "Tuhle zakázku už si někdo vzal.", ephemeral=True)
                return

            # zapiš jako běžný aktivní quest (dál to jede stávajícím systémem)
            quests[name] = {
                "info":         q.get("info", ""),
                "xp":           q.get("xp"),
                "category":     Category.SOLO,
                "difficulty":   q.get("difficulty", DEFAULT_DIFFICULTY),
                "parent_quest": None,
                "members":      [uid],
                "added":        today(),
                "source":       BOARD_SOURCE,
            }
            save_quests(quests)

            # deník + DM (recyklujeme helper z quests.py)
            diaries = load_diaries()
            await _assign_and_notify(
                interaction.guild, [uid], diaries, name,
                q.get("info", ""), Category.SOLO, q.get("xp"),
            )
            save_diaries(diaries)

            # sundej z nabídky a překresli nástěnku
            board["offers"] = [n for n in offers if n != name]
            save_board(board)
            await refresh_board(interaction.client, board)

            log_action("board_take", interaction.user.display_name,
                       interaction.user.display_name, name)
            await interaction.followup.send(
                f"📜 Vzal/a jsi zakázku **{name}**.\n"
                f"-# Zapsáno do deníku. Dokonči ji, než si vezmeš další.",
                ephemeral=True)
        except Exception:
            logger.exception("[board] převzetí questu selhalo")
            try:
                await interaction.followup.send("❌ Něco se pokazilo.", ephemeral=True)
            except Exception:
                pass


async def refresh_board(bot, board: dict | None = None) -> str | None:
    """Překreslí vyvěšenou nástěnku. Vrací text chyby, nebo None."""
    board = board or load_board()
    ch_id, msg_id = board.get("channel_id"), board.get("message_id")
    if not ch_id or not msg_id:
        return "Nástěnka není vyvěšená — použij `/nastenka post`."
    try:
        channel = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
        message = await channel.fetch_message(msg_id)
        await message.edit(embed=board_embed(board.get("offers", []), load_pool()),
                           view=BoardView())
        return None
    except discord.NotFound:
        return "Zpráva s nástěnkou už neexistuje — vyvěs ji znovu `/nastenka post`."
    except Exception:
        logger.exception("[board] refresh selhal")
        return "Překreslení nástěnky selhalo."


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class BoardCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    nastenka = app_commands.Group(name="nastenka", description="Arion nástěnka")

    # ── Vyvěšení ─────────────────────────────────────────────────────────────

    @nastenka.command(name="post", description="[DM] Vyvěsí nástěnku do tohoto kanálu.")
    @app_commands.checks.has_permissions(administrator=True)
    async def board_post(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        board = load_board()
        pool  = load_pool()
        if not board.get("offers"):
            board["offers"] = reroll_offers(pool)

        msg = await interaction.channel.send(
            embed=board_embed(board["offers"], pool), view=BoardView())
        board["channel_id"] = interaction.channel.id
        board["message_id"] = msg.id
        save_board(board)
        await interaction.followup.send(
            f"📌 Nástěnka vyvěšena ({len(board['offers'])} zakázek).", ephemeral=True)

    @nastenka.command(name="reload",
                      description="[DM] Vymění zakázky na nástěnce za nové z poolu.")
    @app_commands.checks.has_permissions(administrator=True)
    async def board_reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        pool = load_pool()
        if not pool:
            await interaction.followup.send(
                "Zásobník je prázdný — přidej questy `/nastenka add`.", ephemeral=True)
            return

        board = load_board()
        board["offers"] = reroll_offers(pool)
        save_board(board)

        err = await refresh_board(self.bot, board)
        log_action("board_reload", interaction.user.display_name, "—",
                   ",".join(board["offers"]))

        running = sum(
            1 for q in load_quests().values()
            if q.get("source") == BOARD_SOURCE
            and q.get("status", Status.ACTIVE) == Status.ACTIVE
        )
        msg = f"♻️ Nástěnka obnovena — **{len(board['offers'])}** nových zakázek."
        if running:
            msg += f"\n-# Rozdělané questy hráčů ({running}) běží dál, nesahal jsem na ně."
        if err:
            msg += f"\n⚠️ {err}"
        await interaction.followup.send(msg, ephemeral=True)

    # ── Zásobník ─────────────────────────────────────────────────────────────

    @nastenka.command(name="add", description="[DM] Přidá quest do zásobníku nástěnky.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        name="Název zakázky.",
        info="Zadání / popis.",
        difficulty="Obtížnost — určuje rank body za splnění.",
        xp="Odměna XP (volitelné).",
        min_rank="Minimální rank pro převzetí (výchozí F3).",
    )
    @app_commands.choices(difficulty=[
        app_commands.Choice(name=f"{m['label']} — +{m['points']} rank bodů", value=d)
        for d, m in DIFFICULTY.items()
    ])
    async def board_add(self, interaction: discord.Interaction,
                        name: str, info: str,
                        difficulty: str = DEFAULT_DIFFICULTY,
                        xp: str | None = None,
                        min_rank: str = STARTING_RANK):
        await interaction.response.defer(ephemeral=True)
        if min_rank not in RANK_LADDER:
            await interaction.followup.send(f"❌ Rank `{min_rank}` neexistuje.", ephemeral=True)
            return

        pool = load_pool()
        existed = name in pool
        pool[name] = {
            "info":       info,
            "xp":         xp,
            "difficulty": difficulty,
            "min_rank":   min_rank,
        }
        save_pool(pool)
        log_action("board_add", interaction.user.display_name, "—", name)
        await interaction.followup.send(
            f"✅ Zakázka **{name}** {'upravena' if existed else 'přidána'} do zásobníku "
            f"({len(pool)} celkem).\n-# Na nástěnku se dostane při `/nastenka reload`.",
            ephemeral=True)

    @nastenka.command(name="remove", description="[DM] Odebere quest ze zásobníku.")
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

        board = load_board()
        if name in board.get("offers", []):
            board["offers"] = [n for n in board["offers"] if n != name]
            save_board(board)
            await refresh_board(self.bot, board)

        log_action("board_remove", interaction.user.display_name, "—", name)
        await interaction.followup.send(f"🗑️ **{name}** odebrána ze zásobníku.", ephemeral=True)

    @nastenka.command(name="pool", description="[DM] Vypíše celý zásobník.")
    @app_commands.checks.has_permissions(administrator=True)
    async def board_pool(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        pool = load_pool()
        if not pool:
            await interaction.followup.send(
                "Zásobník je prázdný. Přidej questy `/nastenka add`.", ephemeral=True)
            return

        offers = set(load_board().get("offers", []))
        taken  = {
            n for n, q in load_quests().items()
            if q.get("source") == BOARD_SOURCE
            and q.get("status", Status.ACTIVE) == Status.ACTIVE
        }

        lines = []
        for name, q in pool.items():
            diff = DIFFICULTY.get(q.get("difficulty", DEFAULT_DIFFICULTY), {})
            mark = "📌" if name in offers else ("⏳" if name in taken else "·")
            lines.append(f"{mark} **{name}**  —  {diff.get('label','?')}  ·  "
                         f"{q.get('min_rank', STARTING_RANK)}+"
                         + (f"  ·  ⭐ {q['xp']}" if q.get("xp") else ""))

        # 4096 limit na description — radši osekat viditelně než tiše
        desc = ("📌 = visí na nástěnce  ·  ⏳ = někdo ji má rozdělanou\n\n"
                + "\n".join(lines))
        if len(desc) > 4000:
            desc = desc[:3990].rsplit("\n", 1)[0] + "\n-# …"

        embed = discord.Embed(title=f"📚  Zásobník zakázek ({len(pool)})",
                              description=desc, color=BOARD_COLOR)
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
    bot.add_view(BoardView())          # ← registrace persistent view (přežije restart)
    await bot.add_cog(BoardCog(bot))