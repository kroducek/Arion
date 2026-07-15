import discord
from discord import app_commands
from discord.ext import commands
import random
import time
import logging

from src.utils.json_utils import load_json, save_json
from src.logic.economy import (
    minigame_file, minigame_coin, get_minigame_currency, COIN_GOLD, COIN_SILVER,
)

logger = logging.getLogger("TicTacToe")

# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTY
# ══════════════════════════════════════════════════════════════════════════════

EMPTY = None
E_X   = "❌"
E_O   = "🟢"
E_BLANK = "⬛"

WIN_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),      # řádky
    (0, 3, 6), (1, 4, 7), (2, 5, 8),      # sloupce
    (0, 4, 8), (2, 4, 6),                 # diagonály
]

TURN_TIMEOUT = 100       # vteřin — po nečinnosti může soupeř nárokovat výhru
TTT_COLOR    = 0x9B59B6


# ══════════════════════════════════════════════════════════════════════════════
# EKONOMIKA + LEADERBOARD  (stejný pattern jako blackjack / battleships)
# ══════════════════════════════════════════════════════════════════════════════

def _scores_file() -> str:
    from src.utils.paths import data
    return data("tictactoe_scores.json")

def _load_eco() -> dict:        return load_json(minigame_file(), {})
def _save_eco(d: dict):         save_json(minigame_file(), d)

def _eco_add(uid: int, amount: int):
    eco = _load_eco(); k = str(uid)
    eco[k] = eco.get(k, 0) + amount
    _save_eco(eco)

def _eco_deduct(uid: int, amount: int) -> bool:
    eco = _load_eco(); k = str(uid)
    if eco.get(k, 0) < amount:
        return False
    eco[k] = eco.get(k, 0) - amount
    _save_eco(eco)
    return True


def _record_result(uid: int, profit: int, won: bool, currency: str | None = None):
    if currency is None:
        currency = get_minigame_currency()
    scores = load_json(_scores_file(), {}); k = str(uid)
    rec = scores.get(k, {})
    pk  = f"profit_{currency}"
    rec[pk]      = rec.get(pk, 0) + profit
    rec["games"] = rec.get("games", 0) + 1
    if won:
        rec["wins"] = rec.get("wins", 0) + 1
    scores[k] = rec
    save_json(_scores_file(), scores)


def _leaderboard_embed(guild, currency: str = "silver") -> discord.Embed:
    icon   = COIN_GOLD if currency == "gold" else COIN_SILVER
    scores = load_json(_scores_file(), {})
    rows   = [(uid, rec.get(f"profit_{currency}", 0), rec.get("wins", 0), rec.get("games", 0))
              for uid, rec in scores.items()]
    rows.sort(key=lambda r: r[1], reverse=True)

    lines = []
    for i, (uid, profit, wins, games) in enumerate(rows[:10]):
        member = guild.get_member(int(uid)) if guild else None
        name   = member.display_name if member else f"Hráč {uid}"
        medal  = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
        sign   = "+" if profit >= 0 else ""
        lines.append(f"{medal} **{name}** — {sign}{profit} {icon}  ·  {wins}W/{games}")

    embed = discord.Embed(
        title="⭕  Piškvorky — žebříček",
        description="\n".join(lines) or "Zatím nikdo nehrál.",
        color=TTT_COLOR,
    )
    embed.set_footer(text=f"Podle čistého profitu ({'zlato' if currency=='gold' else 'stříbro'})")
    return embed


class TTTLeaderboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Zlato", emoji="🟡", style=discord.ButtonStyle.secondary)
    async def gold(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(
            embed=_leaderboard_embed(interaction.guild, "gold"), view=self)

    @discord.ui.button(label="Stříbro", emoji="⚪", style=discord.ButtonStyle.secondary)
    async def silver(self, interaction: discord.Interaction, _b):
        await interaction.response.edit_message(
            embed=_leaderboard_embed(interaction.guild, "silver"), view=self)


# ══════════════════════════════════════════════════════════════════════════════
# STÁV HRY
# ══════════════════════════════════════════════════════════════════════════════

class Match:
    def __init__(self, cog, channel_id: int, host: discord.Member, bet: int):
        self.cog        = cog
        self.channel_id = channel_id
        self.bet        = max(0, bet)
        self.currency   = get_minigame_currency()   # zamkni měnu na dobu hry
        self.phase      = "lobby"                    # lobby | playing | ended
        self.host_id    = host.id
        self.names      = {host.id: host.display_name}
        self.guest_id: int | None = None
        self.board      = [EMPTY] * 9
        self.symbols    = {}                         # uid → "x"/"o"
        self.turn       = None                       # uid na tahu
        self.last_action = time.time()
        self.message    = None
        self.summary    = ""
        self.anted      = {host.id} if self.bet > 0 else set()

    # ── účastníci ──
    def players(self) -> list[int]:
        return [u for u in (self.host_id, self.guest_id) if u is not None]

    def is_player(self, uid: int) -> bool:
        return uid in self.players()

    def opponent_of(self, uid: int) -> int | None:
        for u in self.players():
            if u != uid:
                return u
        return None

    def emoji_of(self, uid: int) -> str:
        return E_X if self.symbols.get(uid) == "x" else E_O

    # ── start ──
    def begin(self):
        ids = self.players()
        random.shuffle(ids)
        self.symbols = {ids[0]: "x", ids[1]: "o"}    # ❌ začíná
        self.turn    = next(u for u, s in self.symbols.items() if s == "x")
        self.phase   = "playing"
        self.last_action = time.time()
        self.summary = f"Začíná **{self.names[self.turn]}** ({self.emoji_of(self.turn)})."

    # ── tahy ──
    def place(self, uid: int, pos: int) -> bool:
        if self.board[pos] is not EMPTY:
            return False
        self.board[pos] = self.symbols[uid]
        self.last_action = time.time()
        return True

    def winner_symbol(self) -> str | None:
        for a, b, c in WIN_LINES:
            line = self.board[a]
            if line is not EMPTY and line == self.board[b] == self.board[c]:
                return line
        return None

    def is_full(self) -> bool:
        return all(c is not EMPTY for c in self.board)

    # ── sázky ──
    def pot(self) -> int:
        return self.bet * 2

    def refund_all(self):
        for uid in list(self.anted):
            _eco_add(uid, self.bet)
        self.anted.clear()

    # ── konec ──
    def finish(self, winner_uid: int | None):
        """winner_uid=None → remíza."""
        self.phase = "ended"
        if self.bet <= 0:
            if winner_uid is not None:
                _record_result(winner_uid, 0, True, self.currency)
                lo = self.opponent_of(winner_uid)
                if lo:
                    _record_result(lo, 0, False, self.currency)
            else:
                for u in self.players():
                    _record_result(u, 0, False, self.currency)
            return

        if winner_uid is None:                       # remíza → vrať ante
            self.refund_all()
            for u in self.players():
                _record_result(u, 0, False, self.currency)
            return

        _eco_add(winner_uid, self.pot())
        _record_result(winner_uid, self.bet, True, self.currency)
        lo = self.opponent_of(winner_uid)
        if lo:
            _record_result(lo, -self.bet, False, self.currency)
        self.anted.clear()

    # ── embed ──
    def build_embed(self) -> discord.Embed:
        coin = COIN_GOLD if self.currency == "gold" else COIN_SILVER

        if self.phase == "lobby":
            desc = [f"**{self.names[self.host_id]}** vyzývá k piškvorkám! ⭕"]
            if self.bet > 0:
                desc.append(f"Sázka **{self.bet}** {coin} od každého  ·  pot **{self.pot()}** {coin}")
            desc.append("")
            desc.append("🎮 " + (f"**{self.names.get(self.guest_id)}** přijal výzvu!"
                                 if self.guest_id else "*Čeká se na vyzvatele…*"))
            embed = discord.Embed(title="⭕  Piškvorky — příprava",
                                  description="\n".join(desc), color=TTT_COLOR)
            embed.set_footer(text="Začít může jen vyzyvatel · symboly a pořadí se losují")
            return embed

        if self.phase == "playing":
            embed = discord.Embed(
                title="⭕  Piškvorky",
                description=(f"### Na tahu: **{self.names[self.turn]}** {self.emoji_of(self.turn)}\n"
                             + (f"-# {self.summary}" if self.summary else "")),
                color=TTT_COLOR,
            )
            embed.add_field(
                name="Hráči",
                value="\n".join(f"{self.emoji_of(u)} **{self.names[u]}**" for u in self.players()),
                inline=True,
            )
            if self.bet > 0:
                embed.add_field(name="Pot", value=f"**{self.pot()}** {coin}", inline=True)
            return embed

        # ended
        return discord.Embed(title="⭕  Piškvorky — konec",
                             description=self.summary, color=TTT_COLOR)


# ══════════════════════════════════════════════════════════════════════════════
# UI — LOBBY
# ══════════════════════════════════════════════════════════════════════════════

class LobbyView(discord.ui.View):
    def __init__(self, match: Match):
        super().__init__(timeout=None)
        self.match = match

    @discord.ui.button(label="Přijmout výzvu", emoji="⚔️", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _b):
        m = self.match
        if m.phase != "lobby":
            await interaction.response.send_message("Hra už začala.", ephemeral=True)
            return
        if m.guest_id is not None:
            await interaction.response.send_message("Výzvu už někdo přijal.", ephemeral=True)
            return
        if interaction.user.id == m.host_id:
            await interaction.response.send_message(
                "Nemůžeš přijmout vlastní výzvu.", ephemeral=True)
            return

        if m.bet > 0:
            if not _eco_deduct(interaction.user.id, m.bet):
                await interaction.response.send_message(
                    f"❌ Nemáš dost — potřebuješ **{m.bet}** {minigame_coin()}.", ephemeral=True)
                return
            m.anted.add(interaction.user.id)

        m.guest_id = interaction.user.id
        m.names[interaction.user.id] = interaction.user.display_name
        await interaction.response.edit_message(embed=m.build_embed(), view=self)

    @discord.ui.button(label="Začít", emoji="🚀", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, _b):
        m = self.match
        if interaction.user.id != m.host_id:
            await interaction.response.send_message("Začít může jen vyzyvatel.", ephemeral=True)
            return
        if m.guest_id is None:
            await interaction.response.send_message("Ještě nikdo nepřijal výzvu.", ephemeral=True)
            return
        m.begin()
        await interaction.response.edit_message(embed=m.build_embed(), view=BoardView(m))

    @discord.ui.button(label="Zrušit", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _b):
        m = self.match
        if interaction.user.id != m.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Zrušit může jen vyzyvatel nebo admin.", ephemeral=True)
            return
        m.refund_all()
        m.phase = "ended"
        m.cog.games.pop(m.channel_id, None)
        await interaction.response.edit_message(
            content="🛑 Hra zrušena, sázky vráceny.", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# UI — HRACÍ MŘÍŽKA 3×3
# ══════════════════════════════════════════════════════════════════════════════

class CellButton(discord.ui.Button):
    def __init__(self, pos: int):
        super().__init__(label="\u200b", style=discord.ButtonStyle.secondary, row=pos // 3)
        self.pos = pos

    async def callback(self, interaction: discord.Interaction):
        await self.view.play(interaction, self.pos)


class BoardView(discord.ui.View):
    def __init__(self, match: Match):
        super().__init__(timeout=None)
        self.match = match
        for pos in range(9):
            self.add_item(CellButton(pos))
        self._sync_buttons()

    def _sync_buttons(self):
        """Popíše tlačítka podle desky (❌/🟢), obsazená deaktivuje."""
        m = self.match
        for item in self.children:
            if isinstance(item, CellButton):
                val = m.board[item.pos]
                if val == "x":
                    item.label, item.emoji, item.disabled = "\u200b", E_X, True
                    item.style = discord.ButtonStyle.danger
                elif val == "o":
                    item.label, item.emoji, item.disabled = "\u200b", E_O, True
                    item.style = discord.ButtonStyle.success
                else:
                    item.label, item.emoji = "\u200b", None
                    item.disabled = (m.phase != "playing")
                    item.style = discord.ButtonStyle.secondary

    def _lock_all(self):
        for item in self.children:
            item.disabled = True

    async def play(self, interaction: discord.Interaction, pos: int):
        m = self.match
        if m.phase != "playing":
            await interaction.response.send_message("Hra neběží.", ephemeral=True)
            return
        if not m.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle hře.", ephemeral=True)
            return
        if interaction.user.id != m.turn:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if not m.place(interaction.user.id, pos):
            await interaction.response.send_message("Tohle políčko je obsazené.", ephemeral=True)
            return

        # výhra?
        if m.winner_symbol() is not None:
            winner = interaction.user.id
            m.summary = (f"{m.emoji_of(winner)} **{m.names[winner]}** vyhrává! 🎉")
            m.finish(winner)
            m.cog.games.pop(m.channel_id, None)
            self._sync_buttons(); self._lock_all()
            await interaction.response.edit_message(embed=m.build_embed(), view=self)
            return

        # remíza?
        if m.is_full():
            m.summary = "🤝 Remíza — deska je plná."
            m.finish(None)
            m.cog.games.pop(m.channel_id, None)
            self._sync_buttons(); self._lock_all()
            await interaction.response.edit_message(embed=m.build_embed(), view=self)
            return

        # střídání
        m.turn = m.opponent_of(interaction.user.id)
        m.summary = f"Na tahu **{m.names[m.turn]}** {m.emoji_of(m.turn)}."
        self._sync_buttons()
        await interaction.response.edit_message(embed=m.build_embed(), view=self)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class TicTacToeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self.games = {}          # channel_id → Match

    group = app_commands.Group(name="tictactoe", description="Piškvorky — 1v1 na tahy")

    async def _open(self, interaction: discord.Interaction, sazka: int = 0):
        cid = interaction.channel_id
        existing = self.games.get(cid)
        if existing and existing.phase != "ended":
            await interaction.response.send_message(
                "V tomhle kanálu už jedna hra běží!", ephemeral=True)
            return
        if sazka < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True)
            return
        if sazka > 0 and not _eco_deduct(interaction.user.id, sazka):
            await interaction.response.send_message(
                f"❌ Nemáš dost — potřebuješ **{sazka}** {minigame_coin()}.", ephemeral=True)
            return

        match = Match(self, cid, interaction.user, sazka)
        self.games[cid] = match
        await interaction.response.send_message(
            embed=match.build_embed(), view=LobbyView(match))
        match.message = await interaction.original_response()

    # vstup z hubu
    async def ttt_start(self, interaction: discord.Interaction, sazka: int = 0):
        await self._open(interaction, sazka)

    @group.command(name="lobby", description="Otevři piškvorky, kam někdo přijme výzvu")
    @app_commands.describe(sazka="Sázka od každého (0 = bez sázky)")
    async def lobby_cmd(self, interaction: discord.Interaction, sazka: int = 0):
        await self._open(interaction, sazka)

    @group.command(name="cancel", description="Zruš piškvorky v tomto kanálu")
    async def cancel_cmd(self, interaction: discord.Interaction):
        m = self.games.get(interaction.channel_id)
        if not m:
            await interaction.response.send_message("Žádná hra tu neběží.", ephemeral=True)
            return
        if m.host_id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Zrušit může jen zakladatel nebo admin.", ephemeral=True)
            return
        m.refund_all()
        m.phase = "ended"
        self.games.pop(interaction.channel_id, None)
        await interaction.response.send_message("🛑 Hra zrušena, sázky vráceny.", ephemeral=True)

    @group.command(name="top", description="Žebříček piškvorek podle profitu")
    async def top_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=_leaderboard_embed(interaction.guild, "silver"), view=TTTLeaderboardView())


async def setup(bot: commands.Bot):
    await bot.add_cog(TicTacToeCog(bot))