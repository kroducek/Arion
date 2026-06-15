"""
Blackjack (21) — jednoduchá casino minihra pro ArionBOT
========================================================
- Hráč vs Arion (krupiér), solo
- Sázky v zlaťácích (economy integrace přes economy.json)
- Akce: Hit / Stand / Double Down
- Blackjack (přirozená 21) platí 3:2, krupiér dobírá do 17
- Karty se renderují z obrázků v src/assets (formát: 4_of_spades, ace_of_hearts ...)
  Když obrázky/PIL chybí, spadne to na textovou variantu (A♠ K♥).
- Persistentní leaderboard (čistý profit + výhry)

Spuštění:
  /blackjack [sazka]            – přímé spuštění
  /blackjack_top               – žebříček podle profitu
  Hub: handler `bj_start(interaction, sazka=0)` (volá MinigamesHub)
"""

import os
import io
import glob
import random

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.json_utils import load_json, save_json
from src.utils.paths import ECONOMY as ECONOMY_FILE, ASSETS_DIR, data

# Leaderboard přes centrální data() helper (stejný mechanismus jako paths.py)
SCORES_FILE = data("blackjack_scores.json")

COIN = "<:goldcoin:1490171741237018795>"

# ── Card image (volitelné, degraduje na text) ─────────────────────────────────
try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except Exception:
    PIL_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_eco() -> dict:        return load_json(ECONOMY_FILE, {})
def _save_eco(data_: dict):     save_json(ECONOMY_FILE, data_)
def _eco_get(uid: int) -> int:  return _load_eco().get(str(uid), 0)


def _eco_add(uid: int, amount: int):
    eco = _load_eco()
    k = str(uid)
    eco[k] = eco.get(k, 0) + amount
    _save_eco(eco)


def _eco_deduct(uid: int, amount: int) -> bool:
    eco = _load_eco()
    k = str(uid)
    if eco.get(k, 0) < amount:
        return False
    eco[k] = eco.get(k, 0) - amount
    _save_eco(eco)
    return True


def _load_scores() -> dict:     return load_json(SCORES_FILE, {})
def _save_scores(d: dict):      save_json(SCORES_FILE, d)


def _record_result(uid: int, profit: int, won: bool):
    scores = _load_scores()
    k = str(uid)
    rec = scores.get(k, {"profit": 0, "wins": 0, "games": 0})
    rec["profit"] = rec.get("profit", 0) + profit
    rec["games"]  = rec.get("games", 0) + 1
    if won:
        rec["wins"] = rec.get("wins", 0) + 1
    scores[k] = rec
    _save_scores(scores)


# ══════════════════════════════════════════════════════════════════════════════
# KARTY — logika
# ══════════════════════════════════════════════════════════════════════════════

SUITS = ["spades", "hearts", "diamonds", "clubs"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "jack", "queen", "king", "ace"]

RANK_VALUE = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "jack": 10, "queen": 10, "king": 10, "ace": 11,
}
RANK_SHORT = {
    "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8",
    "9": "9", "10": "10", "jack": "J", "queen": "Q", "king": "K", "ace": "A",
}
SUIT_SYMBOL = {"spades": "♠", "hearts": "♥", "diamonds": "♦", "clubs": "♣"}


def _fresh_deck() -> list:
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def hand_value(cards: list) -> int:
    """Součet ruky s měkkými esy (es = 11, sníží na 1 při přetažení)."""
    total = sum(RANK_VALUE[r] for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "ace")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_soft(cards: list) -> bool:
    total = sum(RANK_VALUE[r] for r, _ in cards)
    aces = sum(1 for r, _ in cards if r == "ace")
    used = 0
    while total > 21 and used < aces:
        total -= 10
        used += 1
    return aces - used > 0 and total <= 21


def is_blackjack(cards: list) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def hand_text(cards: list, hide_first: bool = False) -> str:
    out = []
    for i, (r, s) in enumerate(cards):
        if hide_first and i == 0:
            out.append("🂠")
        else:
            out.append(f"{RANK_SHORT[r]}{SUIT_SYMBOL[s]}")
    return " ".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# KARTY — obrázky
# ══════════════════════════════════════════════════════════════════════════════

def _find_card_dir() -> str:
    """Najde složku s kartami (src/assets nebo src/assets/cards)."""
    for d in (ASSETS_DIR, os.path.join(ASSETS_DIR, "cards")):
        if glob.glob(os.path.join(d, "*_of_*")):
            return d
    return ASSETS_DIR


CARD_DIR = _find_card_dir()
_CARD_CACHE: dict = {}
ROW_HEIGHT = 240          # cílová výška karty v px
CARD_GAP = 12             # mezera mezi kartami
ROW_GAP = 34              # mezera mezi krupiérem a hráčem


def _card_file(rank: str, suit: str):
    base = f"{rank}_of_{suit}"
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = os.path.join(CARD_DIR, base + ext)
        if os.path.exists(p):
            return p
    hits = glob.glob(os.path.join(CARD_DIR, base + ".*"))
    return hits[0] if hits else None


def _load_card_img(rank: str, suit: str):
    if not PIL_OK:
        return None
    key = (rank, suit)
    if key in _CARD_CACHE:
        return _CARD_CACHE[key]
    path = _card_file(rank, suit)
    if not path:
        _CARD_CACHE[key] = None
        return None
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        im = None
    _CARD_CACHE[key] = im
    return im


def _back_tile():
    """Rub karty — obrázek pokud existuje, jinak nakreslený placeholder."""
    if not PIL_OK:
        return None
    for name in ("back", "card_back", "back_of_card", "cardback"):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            p = os.path.join(CARD_DIR, name + ext)
            if os.path.exists(p):
                try:
                    return Image.open(p).convert("RGBA")
                except Exception:
                    pass
    W, H = 165, 240
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([1, 1, W - 2, H - 2], radius=16, fill=(38, 28, 74, 255),
                         outline=(190, 170, 245, 255), width=4)
    dr.rounded_rectangle([14, 14, W - 15, H - 15], radius=11,
                         outline=(120, 100, 200, 255), width=3)
    for gx in range(28, W - 20, 22):
        dr.line([(gx, 22), (gx, H - 22)], fill=(90, 72, 168, 120), width=2)
    return im


def _scaled(im):
    w = max(1, int(im.width * ROW_HEIGHT / im.height))
    return im.resize((w, ROW_HEIGHT))


def _row_image(cards: list, hide_first: bool = False):
    tiles = []
    for i, (r, s) in enumerate(cards):
        im = _back_tile() if (hide_first and i == 0) else _load_card_img(r, s)
        if im is None:
            return None
        tiles.append(_scaled(im))
    if not tiles:
        return None
    total_w = sum(t.width for t in tiles) + CARD_GAP * (len(tiles) - 1)
    row = Image.new("RGBA", (total_w, ROW_HEIGHT), (0, 0, 0, 0))
    x = 0
    for t in tiles:
        row.paste(t, (x, 0), t)
        x += t.width + CARD_GAP
    return row


def render_table(dealer: list, player: list, hide_hole: bool):
    """Složí obrázek stolu (krupiér nahoře, hráč dole). None když nelze."""
    if not PIL_OK:
        return None
    d_row = _row_image(dealer, hide_first=hide_hole)
    p_row = _row_image(player, hide_first=False)
    if d_row is None or p_row is None:
        return None
    pad = 18
    width = max(d_row.width, p_row.width) + pad * 2
    height = d_row.height + p_row.height + ROW_GAP + pad * 2
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(d_row, (pad + (width - pad * 2 - d_row.width) // 2, pad), d_row)
    canvas.paste(p_row, (pad + (width - pad * 2 - p_row.width) // 2,
                         pad + d_row.height + ROW_GAP), p_row)
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════════════════════════
# HERNÍ VIEW
# ══════════════════════════════════════════════════════════════════════════════

class BlackjackView(discord.ui.View):
    def __init__(self, cog: "BlackjackCog", player: discord.User, bet: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.player = player
        self.bet = bet           # základní sázka
        self.stake = bet         # celkem vsazeno (zdvojnásobí se při Double)
        self.doubled = False
        self.finished = False
        self.outcome = None      # "player_bj" | "win" | "push" | "loss"
        self.message = None

        self.deck = _fresh_deck()
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

        # Přirozený blackjack hned vyhodnotí
        if is_blackjack(self.player_hand) or is_blackjack(self.dealer_hand):
            self._reveal_and_settle(natural=True)

    # ── ovládání jen hráčem ───────────────────────────────────────────────────
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message(
                "🐾 *Tohle je rozehraná partie někoho jiného.* Spusť si vlastní přes `/blackjack`.",
                ephemeral=True,
            )
            return False
        return True

    # ── stav tlačítek ──────────────────────────────────────────────────────────
    def _refresh_buttons(self):
        can_double = (
            len(self.player_hand) == 2
            and not self.doubled
            and self.bet > 0
            and _eco_get(self.player.id) >= self.bet
        )
        for child in self.children:
            cid = getattr(child, "custom_id", "")
            if self.finished:
                child.disabled = True
            elif cid == "bj_double":
                child.disabled = not can_double
            else:
                child.disabled = False

    # ── herní akce ──────────────────────────────────────────────────────────────
    def _player_hit(self):
        self.player_hand.append(self.deck.pop())
        if hand_value(self.player_hand) > 21:
            self.outcome = "loss"
            self.finished = True

    def _dealer_play(self):
        while hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())

    def _settle_after_stand(self):
        self._dealer_play()
        pv = hand_value(self.player_hand)
        dv = hand_value(self.dealer_hand)
        if dv > 21 or pv > dv:
            self.outcome = "win"
        elif pv == dv:
            self.outcome = "push"
        else:
            self.outcome = "loss"
        self.finished = True
        self._payout()

    def _reveal_and_settle(self, natural: bool = False):
        """Vyhodnocení přirozeného blackjacku (po rozdání)."""
        p_bj = is_blackjack(self.player_hand)
        d_bj = is_blackjack(self.dealer_hand)
        if p_bj and d_bj:
            self.outcome = "push"
        elif p_bj:
            self.outcome = "player_bj"
        else:  # jen krupiér má BJ
            self.outcome = "loss"
        self.finished = True
        self._payout()

    def _payout(self):
        """Připíše výhru zpět do ekonomiky a zaznamená leaderboard."""
        if self.bet <= 0:
            return
        if self.outcome == "player_bj":
            payout = self.stake + (3 * self.bet) // 2
        elif self.outcome == "win":
            payout = 2 * self.stake
        elif self.outcome == "push":
            payout = self.stake
        else:
            payout = 0
        if payout > 0:
            _eco_add(self.player.id, payout)
        profit = payout - self.stake
        _record_result(self.player.id, profit, won=self.outcome in ("win", "player_bj"))

    # ── vykreslení stavu ─────────────────────────────────────────────────────────
    def _build_state(self):
        hide_hole = not self.finished
        pv = hand_value(self.player_hand)
        dv_shown = (hand_value(self.dealer_hand) if self.finished
                    else RANK_VALUE[self.dealer_hand[1][0]])

        color = 0x5865F2
        title = "🃏 Blackjack — partie proti Arionovi"
        flavor = "*Arion zamíchá balíček a rozdá karty...*"
        if self.finished:
            if self.outcome in ("win", "player_bj"):
                color, flavor = 0x2ECC71, "🐾 *Arion uznale přikývne — vyhráváš!*"
            elif self.outcome == "push":
                color, flavor = 0x95A5A6, "🐾 *Remíza. Arion ti vrací sázku.*"
            else:
                color, flavor = 0xE74C3C, "🐾 *Arion vítězně mávne ocasem.*"

        embed = discord.Embed(title=title, description=flavor, color=color)

        dealer_total = f"**{dv_shown}**" if self.finished else f"**{dv_shown}+?**"
        embed.add_field(
            name=f"🎩 Arion (krupiér) — {dealer_total}",
            value=hand_text(self.dealer_hand, hide_first=hide_hole),
            inline=False,
        )
        soft = " (soft)" if (not self.finished and is_soft(self.player_hand)) else ""
        embed.add_field(
            name=f"🧑 {self.player.display_name} — **{pv}**{soft}",
            value=hand_text(self.player_hand),
            inline=False,
        )

        if self.bet > 0:
            bet_line = f"Sázka: **{self.stake}** {COIN}"
            if self.doubled:
                bet_line += "  · 🔁 zdvojeno"
            embed.add_field(name="\u200b", value=bet_line, inline=False)

        if self.finished and self.bet > 0:
            if self.outcome == "player_bj":
                won = self.stake + (3 * self.bet) // 2
                embed.add_field(name="💰 Výsledek",
                                value=f"BLACKJACK! Získáváš **{won}** {COIN} (3:2)", inline=False)
            elif self.outcome == "win":
                embed.add_field(name="💰 Výsledek",
                                value=f"Získáváš **{2 * self.stake}** {COIN}", inline=False)
            elif self.outcome == "push":
                embed.add_field(name="💰 Výsledek",
                                value=f"Vráceno **{self.stake}** {COIN}", inline=False)
            else:
                embed.add_field(name="💰 Výsledek",
                                value=f"Ztrácíš **{self.stake}** {COIN}", inline=False)
            embed.add_field(name="\u200b",
                            value=f"Zůstatek: **{_eco_get(self.player.id)}** {COIN}", inline=False)

        embed.set_footer(text="ArionBOT · Blackjack" +
                         ("" if self.finished else " · Hit / Stand / Double"))

        buf = render_table(self.dealer_hand, self.player_hand, hide_hole)
        file = None
        if buf is not None:
            file = discord.File(buf, filename="bj.png")
            embed.set_image(url="attachment://bj.png")
        return embed, file

    async def _update(self, interaction: discord.Interaction):
        self._refresh_buttons()
        embed, file = self._build_state()
        attachments = [file] if file else []
        await interaction.response.edit_message(embed=embed, view=self, attachments=attachments)
        if self.finished:
            self.stop()

    # ── tlačítka ─────────────────────────────────────────────────────────────────
    @discord.ui.button(label="Líznout", emoji="🃏", style=discord.ButtonStyle.primary, custom_id="bj_hit")
    async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            await interaction.response.defer()
            return
        self._player_hit()
        if self.finished:               # bust
            self._reveal_dealer_on_bust()
        await self._update(interaction)

    @discord.ui.button(label="Stát", emoji="✋", style=discord.ButtonStyle.success, custom_id="bj_stand")
    async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            await interaction.response.defer()
            return
        self._settle_after_stand()
        await self._update(interaction)

    @discord.ui.button(label="Zdvojit", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="bj_double")
    async def double_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished or len(self.player_hand) != 2 or self.doubled:
            await interaction.response.defer()
            return
        if self.bet > 0:
            if not _eco_deduct(self.player.id, self.bet):
                await interaction.response.send_message(
                    f"❌ Nemáš dalších **{self.bet}** {COIN} na zdvojení.", ephemeral=True)
                return
            self.stake += self.bet
        self.doubled = True
        self.player_hand.append(self.deck.pop())
        if hand_value(self.player_hand) > 21:
            self.outcome = "loss"
            self.finished = True
            self._reveal_dealer_on_bust()
            self._payout()
        else:
            self._settle_after_stand()
        await self._update(interaction)

    def _reveal_dealer_on_bust(self):
        """Při bustu hráče už krupiér nedobírá, jen odhalí ruku."""
        self.outcome = "loss"
        # leaderboard/payout řeší volající (stand/double) nebo zde u hit
        if not self.doubled:
            self._payout()

    async def on_timeout(self):
        if self.finished or self.message is None:
            return
        # Vypršel čas → automaticky „Stát"
        self._settle_after_stand()
        self._refresh_buttons()
        embed, file = self._build_state()
        embed.set_footer(text="ArionBOT · Blackjack · ⏳ vypršel čas — automaticky stát")
        try:
            attachments = [file] if file else []
            await self.message.edit(embed=embed, view=self, attachments=attachments)
        except discord.HTTPException:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class BlackjackCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: set = set()    # user_id právě hrajících

    async def _start(self, interaction: discord.Interaction, sazka: int = 0):
        uid = interaction.user.id

        if sazka < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True)
            return
        if uid in self.active:
            await interaction.response.send_message(
                "Už máš rozehranou partii — nejdřív ji dohraj.", ephemeral=True)
            return
        if sazka > 0 and _eco_get(uid) < sazka:
            await interaction.response.send_message(
                f"❌ Nemáš dost zlaťáků! Potřebuješ **{sazka}** {COIN}.", ephemeral=True)
            return

        # Stáhni sázku dopředu
        if sazka > 0 and not _eco_deduct(uid, sazka):
            await interaction.response.send_message(
                f"❌ Nemáš dost zlaťáků! Potřebuješ **{sazka}** {COIN}.", ephemeral=True)
            return

        view = BlackjackView(self, interaction.user, sazka)
        if not view.finished:
            self.active.add(uid)
        view._refresh_buttons()
        embed, file = view._build_state()
        kwargs = {"embed": embed, "view": view}
        if file:
            kwargs["file"] = file
        await interaction.response.send_message(**kwargs)
        view.message = await interaction.original_response()

        # Pokud skončila hned (přirozený BJ), uvolni slot
        if view.finished:
            self.active.discard(uid)
        else:
            # uvolnění slotu po dohrání hlídá stop() přes wait
            self.bot.loop.create_task(self._await_finish(view, uid))

    async def _await_finish(self, view: BlackjackView, uid: int):
        await view.wait()
        self.active.discard(uid)

    # Handler volaný z MinigamesHub (přes BetModal → sazka)
    async def bj_start(self, interaction: discord.Interaction, sazka: int = 0):
        await self._start(interaction, sazka)

    @app_commands.command(name="blackjack", description="Zahraj si Blackjack (21) proti Arionovi")
    @app_commands.describe(sazka="Sázka v zlaťácích (0 = bez sázky)")
    async def blackjack_cmd(self, interaction: discord.Interaction, sazka: int = 0):
        await self._start(interaction, sazka)

    @app_commands.command(name="blackjack_top", description="Žebříček Blackjacku podle profitu")
    async def blackjack_top(self, interaction: discord.Interaction):
        scores = _load_scores()
        if not scores:
            await interaction.response.send_message("Zatím nikdo nehrál.", ephemeral=True)
            return
        ranked = sorted(scores.items(), key=lambda x: x[1].get("profit", 0), reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, rec) in enumerate(ranked[:10]):
            medal = medals[i] if i < 3 else f"`{i + 1}.`"
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            name = member.display_name if member else f"<@{uid}>"
            profit = rec.get("profit", 0)
            wins = rec.get("wins", 0)
            sign = "+" if profit >= 0 else ""
            lines.append(f"{medal} **{name}** — {sign}{profit} {COIN} · {wins}× výhra")
        embed = discord.Embed(
            title="🃏 Blackjack — Žebříček",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        embed.set_footer(text="Podle čistého profitu")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackCog(bot))