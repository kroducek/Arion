"""
Blackjack (21) — multiplayer stůl pro ArionBOT
==============================================
- Arion je krupiérka (TA kočka) — dobírá do 17, vyhodnocuje každého hráče zvlášť
- Lobby: /blackjack lobby — kdokoliv se připojí; kdo se připojí během hry,
  naskočí od dalšího kola
- Hraje se na kola. Před každým kolem každý hráč zadá svou sázku (modal).
- Tahy postupně po jednom: aktivní hráč má Hit / Stand / Double, ostatní čekají.
- Blackjack (přirozená 21) platí 3:2, krupiérka dobírá do 17.
- Karty z obrázků v src/assets (formát 4_of_spades, ace_of_hearts ...), s textovým
  fallbackem (A♠ K♥), když obrázek/PIL chybí.
- Persistentní leaderboard (čistý profit + výhry)

Příkazy:
  /blackjack lobby   – otevři stůl
  /blackjack top     – žebříček podle profitu
  /blackjack cancel  – [Admin] zruš stůl v kanálu
  Hub handler: bj_start(interaction, sazka=0)  – otevře lobby
"""

import os
import io
import glob
import random
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.json_utils import load_json, save_json
from src.utils.paths import ECONOMY as ECONOMY_FILE, ASSETS_DIR, data
from src.logic.economy import minigame_file, minigame_coin, get_minigame_currency, COIN_GOLD, COIN_SILVER

SCORES_FILE = data("blackjack_scores.json")
COIN = "<:goldcoin:1490171741237018795>"

MIN_PLAYERS = 1
MAX_PLAYERS = 7
BET_SECONDS = 60        # čas na sázení v kole
TURN_SECONDS = 45       # čas na tah jednoho hráče
DEALER_STANDS = 17

# ── Card image (volitelné) ────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except Exception:
    PIL_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# EKONOMIKA + LEADERBOARD
# ══════════════════════════════════════════════════════════════════════════════

def _load_eco() -> dict:        return load_json(minigame_file(), {})
def _save_eco(d: dict):         save_json(minigame_file(), d)
def _eco_get(uid: int) -> int:  return _load_eco().get(str(uid), 0)


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


def _load_scores() -> dict:  return load_json(SCORES_FILE, {})
def _save_scores(d: dict):   save_json(SCORES_FILE, d)


def _record_result(uid: int, profit: int, won: bool, currency: str = None):
    if currency is None:
        currency = get_minigame_currency()
    scores = _load_scores(); k = str(uid)
    rec = scores.get(k, {})
    # Migrace starého jednotného 'profit' → profit_silver (hry běžely na stříbro)
    if "profit" in rec and "profit_silver" not in rec:
        rec["profit_silver"] = rec.pop("profit")
    pkey = f"profit_{currency}"
    rec[pkey] = rec.get(pkey, 0) + profit
    rec["games"] = rec.get("games", 0) + 1
    if won:
        rec["wins"] = rec.get("wins", 0) + 1
    scores[k] = rec
    _save_scores(scores)


def _bj_profit(rec: dict, currency: str) -> int:
    """Profit hráče v dané měně (zvládne i starý jednotný 'profit' jako silver)."""
    if currency == "silver" and "profit_silver" not in rec and "profit" in rec:
        return rec.get("profit", 0)
    return rec.get(f"profit_{currency}", 0)


def _bj_leaderboard_embed(guild, currency: str = "silver") -> discord.Embed:
    icon = COIN_GOLD if currency == "gold" else COIN_SILVER
    cname = "Zlaťáky" if currency == "gold" else "Stříbrňáky"
    scores = _load_scores()
    ranked = sorted(scores.items(), key=lambda x: _bj_profit(x[1], currency), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, rec) in enumerate(ranked):
        medal = medals[i] if i < 3 else f"`{i + 1}.`"
        member = guild.get_member(int(uid)) if guild else None
        name = member.display_name if member else f"<@{uid}>"
        profit = _bj_profit(rec, currency)
        sign = "+" if profit >= 0 else ""
        lines.append(f"{medal} **{name}** — {sign}{profit} {icon} · {rec.get('wins', 0)}× výhra")
    desc = "\n".join(lines) if lines else "*Zatím nikdo nehrál.*"
    e = discord.Embed(title=f"🃏 Blackjack — Žebříček ({cname})", description=desc, color=0xF1C40F)
    e.set_footer(text="Podle čistého profitu")
    return e


class BJLeaderboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Zlaťáky", emoji="🟡", style=discord.ButtonStyle.secondary)
    async def gold_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_bj_leaderboard_embed(interaction.guild, "gold"), view=self)

    @discord.ui.button(label="Stříbrňáky", emoji="⚪", style=discord.ButtonStyle.secondary)
    async def silver_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_bj_leaderboard_embed(interaction.guild, "silver"), view=self)


# ══════════════════════════════════════════════════════════════════════════════
# KARTY — logika
# ══════════════════════════════════════════════════════════════════════════════

SUITS = ["spades", "hearts", "diamonds", "clubs"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "jack", "queen", "king", "ace"]
RANK_VALUE = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
              "10": 10, "jack": 10, "queen": 10, "king": 10, "ace": 11}
RANK_SHORT = {"2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8",
              "9": "9", "10": "10", "jack": "J", "queen": "Q", "king": "K", "ace": "A"}
SUIT_SYMBOL = {"spades": "♠", "hearts": "♥", "diamonds": "♦", "clubs": "♣"}


def _fresh_deck() -> list:
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def hand_value(cards: list) -> int:
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
        out.append("🂠" if (hide_first and i == 0) else f"{RANK_SHORT[r]}{SUIT_SYMBOL[s]}")
    return " ".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# KARTY — obrázky
# ══════════════════════════════════════════════════════════════════════════════

def _find_card_dir() -> str:
    candidates = [
        os.path.join(ASSETS_DIR, "poker_cards"),
        os.path.join(ASSETS_DIR, "cards"),
        ASSETS_DIR,
    ]
    for d in candidates:
        if glob.glob(os.path.join(d, "*_of_*")):
            return d
    return os.path.join(ASSETS_DIR, "poker_cards")


CARD_DIR = _find_card_dir()
_CARD_CACHE: dict = {}
ROW_HEIGHT = 230
CARD_GAP = 12
ROW_GAP = 34


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
    im = None
    if path:
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            im = None
    _CARD_CACHE[key] = im
    return im


def _back_tile():
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


def render_round_image(dealer: list, player: list, hide_hole: bool):
    """Krupiérka nahoře, aktuální hráč dole. None → text fallback."""
    if not PIL_OK or not dealer:
        return None
    d_row = _row_image(dealer, hide_first=hide_hole)
    if d_row is None:
        return None
    rows = [d_row]
    if player:
        p_row = _row_image(player, hide_first=False)
        if p_row is None:
            return None
        rows.append(p_row)
    pad = 18
    width = max(r.width for r in rows) + pad * 2
    height = sum(r.height for r in rows) + ROW_GAP * (len(rows) - 1) + pad * 2
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    y = pad
    for r in rows:
        canvas.paste(r, (pad + (width - pad * 2 - r.width) // 2, y), r)
        y += r.height + ROW_GAP
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════════════════════════
# STAV HRÁČE
# ══════════════════════════════════════════════════════════════════════════════

class Seat:
    def __init__(self, uid: int, name: str):
        self.uid = uid
        self.name = name
        self.bet = 0
        self.stake = 0            # bet, případně 2× při double
        self.hand = []
        self.done = False
        self.doubled = False
        self.outcome = None       # "win" | "loss" | "push" | "bj"

    def reset_round(self):
        self.bet = 0
        self.stake = 0
        self.hand = []
        self.done = False
        self.doubled = False
        self.outcome = None


# ══════════════════════════════════════════════════════════════════════════════
# SÁZKOVÝ MODAL
# ══════════════════════════════════════════════════════════════════════════════

class BetModal(discord.ui.Modal):
    amount = discord.ui.TextInput(
        label="Sázka v zlaťácích",
        placeholder="např. 50",
        required=True,
        max_length=9,
    )

    def __init__(self, table: "BlackjackTable", uid: int):
        super().__init__(title="🃏 Tvoje sázka")
        self.table = table
        self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.amount.value).strip()
        try:
            value = int(raw)
        except ValueError:
            await interaction.response.send_message("❌ Zadej platné číslo.", ephemeral=True)
            return
        if value <= 0:
            await interaction.response.send_message("❌ Sázka musí být kladná.", ephemeral=True)
            return

        ok, msg = self.table.place_bet(self.uid, value)
        await interaction.response.send_message(msg, ephemeral=True)
        if ok:
            await self.table.render(None)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW
# ══════════════════════════════════════════════════════════════════════════════

class TableView(discord.ui.View):
    def __init__(self, table: "BlackjackTable"):
        super().__init__(timeout=None)
        self.table = table
        self.rebuild()

    def _btn(self, label, style, action, emoji=None, disabled=False, row=0):
        b = discord.ui.Button(label=label, style=style, emoji=emoji, disabled=disabled, row=row)

        async def cb(interaction: discord.Interaction, _action=action):
            await self.table.on_action(interaction, _action)
        b.callback = cb
        self.add_item(b)

    def rebuild(self):
        self.clear_items()
        t = self.table
        if t.phase == "lobby":
            self._btn("Připojit se", discord.ButtonStyle.success, "join", "➕")
            self._btn("Odejít", discord.ButtonStyle.secondary, "leave", "➖")
            self._btn("Spustit stůl", discord.ButtonStyle.primary, "start", "▶️", row=1)
            self._btn("Zrušit", discord.ButtonStyle.danger, "end", "🛑", row=1)
        elif t.phase == "betting":
            self._btn("Vsadit", discord.ButtonStyle.success, "bet", "💰")
            self._btn("Připojit se", discord.ButtonStyle.secondary, "join", "➕")
            self._btn("Odejít", discord.ButtonStyle.secondary, "leave", "➖")
            self._btn("Rozdat", discord.ButtonStyle.primary, "deal", "🃏", row=1)
            self._btn("Ukončit stůl", discord.ButtonStyle.danger, "end", "🛑", row=1)
        elif t.phase == "playing":
            self._btn("Líznout", discord.ButtonStyle.primary, "hit", "🃏")
            self._btn("Stát", discord.ButtonStyle.success, "stand", "✋")
            self._btn("Zdvojit", discord.ButtonStyle.secondary, "double", "🔁")
            self._btn("Připojit se", discord.ButtonStyle.secondary, "join", "➕", row=1)
            self._btn("Ukončit stůl", discord.ButtonStyle.danger, "end", "🛑", row=1)


# ══════════════════════════════════════════════════════════════════════════════
# STŮL
# ══════════════════════════════════════════════════════════════════════════════

class BlackjackTable:
    def __init__(self, cog: "BlackjackCog", channel_id: int, host: discord.Member):
        self.cog = cog
        self.channel_id = channel_id
        self.host_id = host.id
        self.phase = "lobby"            # lobby | betting | playing | ended
        self.round = 0
        self.seats = {host.id: Seat(host.id, host.display_name)}
        self.order = [host.id]                 # pořadí míst
        self.pending = []                      # (uid, name) noví během hry → další kolo
        self.active = []                       # hráči s platnou sázkou v kole
        self.turn_idx = 0
        self.deck = []
        self.dealer = []
        self.last_summary = ""                 # výsledky minulého kola
        self.message = None
        self.view = TableView(self)
        self._bet_token = 0
        self._turn_token = 0

    # ── pomocné ────────────────────────────────────────────────────────────────
    def _draw(self):
        if not self.deck:
            self.deck = _fresh_deck()
        return self.deck.pop()

    def _current_uid(self):
        if 0 <= self.turn_idx < len(self.active):
            return self.active[self.turn_idx]
        return None

    def is_host(self, uid: int) -> bool:
        return uid == self.host_id

    # ── seating ─────────────────────────────────────────────────────────────────
    def add_player(self, member) -> str:
        uid = member.id
        if uid in self.seats:
            return "Už sedíš u stolu."
        if self.phase == "playing":
            if any(uid == p[0] for p in self.pending):
                return "Už čekáš na další kolo."
            if len(self.seats) + len(self.pending) >= MAX_PLAYERS:
                return "Stůl je plný."
            self.pending.append((uid, member.display_name))
            return f"➕ Přidám tě od **dalšího kola**, {member.display_name}."
        if len(self.seats) >= MAX_PLAYERS:
            return "Stůl je plný."
        self.seats[uid] = Seat(uid, member.display_name)
        self.order.append(uid)
        return f"➕ Sedáš si ke stolu, {member.display_name}."

    def remove_player(self, uid: int) -> str:
        if self.phase == "playing" and uid in self.active and not self.seats[uid].done:
            return "Můžeš odejít až po skončení kola."
        if self.phase == "betting" and uid in self.seats and self.seats[uid].bet > 0:
            _eco_add(uid, self.seats[uid].bet)
        self.pending = [p for p in self.pending if p[0] != uid]
        if uid in self.seats:
            del self.seats[uid]
            self.order = [u for u in self.order if u != uid]
            self.active = [u for u in self.active if u != uid]
            if uid == self.host_id:
                self.host_id = self.order[0] if self.order else 0
            return "➖ Odešel/odešla jsi od stolu."
        return "Nejsi u stolu."

    def _merge_pending(self):
        for uid, name in self.pending:
            if uid not in self.seats and len(self.seats) < MAX_PLAYERS:
                self.seats[uid] = Seat(uid, name)
                self.order.append(uid)
        self.pending = []

    # ── sázení ──────────────────────────────────────────────────────────────────
    def place_bet(self, uid: int, value: int):
        if self.phase != "betting":
            return False, "Sázet můžeš jen ve fázi sázení."
        if uid not in self.seats:
            return False, "Nejsi u stolu — nejdřív se připoj."
        seat = self.seats[uid]
        prev = seat.bet
        if prev > 0:
            _eco_add(uid, prev)
        if _eco_get(uid) < value:
            if prev > 0:
                _eco_deduct(uid, prev)
            return False, f"❌ Nemáš dost! Potřebuješ **{value}** {minigame_coin()}."
        _eco_deduct(uid, value)
        seat.bet = value
        seat.stake = value
        return True, f"✅ Vsazeno **{value}** {minigame_coin()}."

    def _refund_all_bets(self):
        for seat in self.seats.values():
            if seat.bet > 0:
                _eco_add(seat.uid, seat.bet)
                seat.bet = 0
                seat.stake = 0

    # ── fáze: spuštění / sázení ──────────────────────────────────────────────────
    def start_betting(self):
        self._merge_pending()
        self.round += 1
        self.phase = "betting"
        self.active = []
        self.dealer = []
        self.turn_idx = 0
        for seat in self.seats.values():
            seat.reset_round()
        self._bet_token += 1
        self.cog.bot.loop.create_task(self._bet_timeout(self._bet_token))

    async def _bet_timeout(self, token: int):
        await asyncio.sleep(BET_SECONDS)
        if self.phase != "betting" or self._bet_token != token:
            return
        if any(s.bet > 0 for s in self.seats.values()):
            self.deal()
            await self.render(None)
        else:
            self.phase = "ended"
            self.last_summary = "⏳ Nikdo nevsadil — Arion zavírá stůl."
            await self.render(None)
            self.cog.tables.pop(self.channel_id, None)

    # ── fáze: rozdání ─────────────────────────────────────────────────────────────
    def deal(self):
        self._bet_token += 1
        self.active = [uid for uid in self.order if self.seats[uid].bet > 0]
        if not self.active:
            return
        self.deck = _fresh_deck()
        self.dealer = [self._draw(), self._draw()]
        for uid in self.active:
            self.seats[uid].hand = [self._draw(), self._draw()]
            if is_blackjack(self.seats[uid].hand):
                self.seats[uid].done = True
        self.phase = "playing"

        if is_blackjack(self.dealer):
            self._resolve_round()
            return
        self.turn_idx = -1
        self._advance_turn()

    # ── tahy ──────────────────────────────────────────────────────────────────────
    def _advance_turn(self):
        n = len(self.active)
        idx = self.turn_idx + 1
        while idx < n and self.seats[self.active[idx]].done:
            idx += 1
        self.turn_idx = idx
        if idx >= n:
            self._dealer_play_and_resolve()
        else:
            self._turn_token += 1
            self.cog.bot.loop.create_task(self._turn_timeout(self._turn_token))

    async def _turn_timeout(self, token: int):
        await asyncio.sleep(TURN_SECONDS)
        if self.phase != "playing" or self._turn_token != token:
            return
        uid = self._current_uid()
        if uid is None:
            return
        self.seats[uid].done = True
        self._advance_turn()
        await self.render(None)

    def player_hit(self, uid: int):
        seat = self.seats[uid]
        seat.hand.append(self._draw())
        if hand_value(seat.hand) > 21:
            seat.done = True
            self._advance_turn()

    def player_stand(self, uid: int):
        self.seats[uid].done = True
        self._advance_turn()

    def player_double(self, uid: int) -> str:
        seat = self.seats[uid]
        if len(seat.hand) != 2 or seat.doubled:
            return "Zdvojit jde jen na začátku tahu."
        if seat.bet <= 0:
            return "Nemáš sázku."
        if not _eco_deduct(uid, seat.bet):
            return f"❌ Nemáš dalších **{seat.bet}** {minigame_coin()} na zdvojení."
        seat.stake += seat.bet
        seat.doubled = True
        seat.hand.append(self._draw())
        seat.done = True
        self._advance_turn()
        return ""

    # ── krupiérka + vyhodnocení ───────────────────────────────────────────────────
    def _dealer_play_and_resolve(self):
        while hand_value(self.dealer) < DEALER_STANDS:
            self.dealer.append(self._draw())
        self._resolve_round()

    def _resolve_round(self):
        dv = hand_value(self.dealer)
        d_bj = is_blackjack(self.dealer)
        lines = []
        for uid in self.active:
            seat = self.seats[uid]
            pv = hand_value(seat.hand)
            p_bj = is_blackjack(seat.hand)

            if pv > 21:
                seat.outcome = "loss"
            elif p_bj and not d_bj:
                seat.outcome = "bj"
            elif d_bj and not p_bj:
                seat.outcome = "loss"
            elif d_bj and p_bj:
                seat.outcome = "push"
            elif dv > 21 or pv > dv:
                seat.outcome = "win"
            elif pv == dv:
                seat.outcome = "push"
            else:
                seat.outcome = "loss"

            if seat.outcome == "bj":
                payout = seat.stake + (3 * seat.bet) // 2
            elif seat.outcome == "win":
                payout = 2 * seat.stake
            elif seat.outcome == "push":
                payout = seat.stake
            else:
                payout = 0
            if payout > 0:
                _eco_add(uid, payout)
            profit = payout - seat.stake
            _record_result(uid, profit, won=seat.outcome in ("win", "bj"))

            icon = {"bj": "🃏", "win": "✅", "push": "➖", "loss": "❌"}[seat.outcome]
            label = {"bj": f"BLACKJACK +{payout - seat.stake}", "win": f"+{payout - seat.stake}",
                     "push": "vráceno", "loss": f"−{seat.stake}"}[seat.outcome]
            lines.append(f"{icon} **{seat.name}** ({pv}) — {label} {minigame_coin()}")

        self.last_summary = (f"🎩 **Arion** dobrala na **{dv}**"
                             + (" (BLACKJACK)" if d_bj else "") + "\n" + "\n".join(lines))
        self.start_betting()

    # ── akce z tlačítek ───────────────────────────────────────────────────────────
    async def on_action(self, interaction: discord.Interaction, action: str):
        uid = interaction.user.id

        if action == "join":
            member = (interaction.guild.get_member(uid) if interaction.guild else None) or interaction.user
            msg = self.add_player(member)
            await interaction.response.send_message(msg, ephemeral=True)
            await self.render(None)
            return

        if action == "leave":
            msg = self.remove_player(uid)
            await interaction.response.send_message(msg, ephemeral=True)
            if not self.seats:
                self.phase = "ended"
                self.cog.tables.pop(self.channel_id, None)
            await self.render(None)
            return

        if action == "end":
            if not self.is_host(uid) and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("Stůl může ukončit jen zakladatel nebo admin.", ephemeral=True)
                return
            self._refund_all_bets()
            self.phase = "ended"
            self.last_summary = "🛑 Stůl byl ukončen."
            self.cog.tables.pop(self.channel_id, None)
            await self.render(interaction)
            return

        if action == "start":
            if not self.is_host(uid):
                await interaction.response.send_message("Stůl spouští jen zakladatel.", ephemeral=True)
                return
            if self.phase != "lobby":
                await interaction.response.defer()
                return
            self.start_betting()
            await self.render(interaction)
            return

        if action == "bet":
            if uid not in self.seats:
                await interaction.response.send_message("Nejsi u stolu — klikni nejdřív na *Připojit se*.", ephemeral=True)
                return
            if self.phase != "betting":
                await interaction.response.send_message("Teď se nesází.", ephemeral=True)
                return
            await interaction.response.send_modal(BetModal(self, uid))
            return

        if action == "deal":
            if not self.is_host(uid):
                await interaction.response.send_message("Rozdává jen zakladatel.", ephemeral=True)
                return
            if self.phase != "betting":
                await interaction.response.defer()
                return
            if not any(s.bet > 0 for s in self.seats.values()):
                await interaction.response.send_message("Nikdo zatím nevsadil.", ephemeral=True)
                return
            self.deal()
            await self.render(interaction)
            return

        if action in ("hit", "stand", "double"):
            if self.phase != "playing":
                await interaction.response.defer()
                return
            cur = self._current_uid()
            if uid != cur:
                await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
                return
            if action == "hit":
                self.player_hit(uid)
            elif action == "stand":
                self.player_stand(uid)
            else:
                err = self.player_double(uid)
                if err:
                    await interaction.response.send_message(err, ephemeral=True)
                    return
            await self.render(interaction)
            return

        await interaction.response.defer()

    # ── vykreslení ────────────────────────────────────────────────────────────────
    def _embed_and_file(self):
        if self.phase == "lobby":
            return self._lobby_embed(), None
        if self.phase == "ended":
            e = discord.Embed(title="🃏 Blackjack — stůl uzavřen",
                              description=self.last_summary or "Arion sklízí karty.",
                              color=0x95A5A6)
            e.set_footer(text="ArionBOT · Blackjack")
            return e, None
        if self.phase == "betting":
            return self._betting_embed(), None
        return self._playing_embed()

    def _lobby_embed(self):
        names = "\n".join(f"• {self.seats[u].name}" + (" 👑" if u == self.host_id else "")
                          for u in self.order) or "*zatím prázdno*"
        e = discord.Embed(
            title="🃏 Blackjack — stůl Arion",
            description="🐾 *Arion zamíchala balíček a čeká, kdo si sedne ke stolu.*",
            color=0x5865F2,
        )
        e.add_field(name=f"Hráči ({len(self.order)}/{MAX_PLAYERS})", value=names, inline=False)
        e.add_field(name="\u200b",
                    value="Zakladatel spustí stůl tlačítkem **▶️ Spustit**.\nHraje se na kola, před každým kolem se sází.",
                    inline=False)
        e.set_footer(text="ArionBOT · Blackjack · 21")
        return e

    def _scoreboard(self, current=None):
        rows = []
        for uid in self.active:
            seat = self.seats[uid]
            pv = hand_value(seat.hand)
            if seat.outcome:
                st = {"bj": "🃏 BJ", "win": "✅", "push": "➖", "loss": "❌"}[seat.outcome]
            elif pv > 21:
                st = "💥 přetažení"
            elif seat.done:
                st = "✋ stojí"
            elif uid == current:
                st = "▶️ na tahu"
            else:
                st = "⏳"
            dbl = " 🔁" if seat.doubled else ""
            rows.append(f"{st} **{seat.name}** — {hand_text(seat.hand)} = **{pv}** "
                        f"· {seat.stake}{minigame_coin()}{dbl}")
        return "\n".join(rows) or "*nikdo nehraje*"

    def _betting_embed(self):
        e = discord.Embed(
            title=f"🃏 Blackjack — sázky (kolo {self.round})",
            description="🐾 *Arion poklepe tlapkou na stůl — sázejte!*",
            color=0xF1C40F,
        )
        if self.last_summary:
            e.add_field(name="📜 Minulé kolo", value=self.last_summary, inline=False)
        bets = []
        for uid in self.order:
            seat = self.seats[uid]
            tag = f"💰 {seat.bet} {minigame_coin()}" if seat.bet > 0 else "⏳ čeká na sázku"
            bets.append(f"• **{seat.name}** — {tag}")
        e.add_field(name=f"Sázky ({len(self.order)} hráčů)",
                    value="\n".join(bets) or "*prázdno*", inline=False)
        if self.pending:
            e.add_field(name="➕ Naskočí příští kolo",
                        value=", ".join(n for _, n in self.pending), inline=False)
        e.set_footer(text=f"Vsaď tlačítkem 💰 · zakladatel rozdá 🃏 · {BET_SECONDS}s")
        return e

    def _playing_embed(self):
        cur = self._current_uid()
        seat_cur = self.seats.get(cur) if cur else None
        dv_shown = hand_value(self.dealer)
        e = discord.Embed(
            title=f"🃏 Blackjack — kolo {self.round}",
            description=(f"🐾 *Na tahu je* **{seat_cur.name}** *— líznout, stát, nebo zdvojit?*"
                        if seat_cur else "🐾 *Arion dobírá své karty...*"),
            color=0x5865F2,
        )
        e.add_field(name=f"🎩 Arion (krupiérka) — **{dv_shown}+?**",
                    value=hand_text(self.dealer, hide_first=True), inline=False)
        e.add_field(name="🪑 Stůl", value=self._scoreboard(current=cur), inline=False)
        e.set_footer(text=f"Na tahu má {TURN_SECONDS}s · ArionBOT · Blackjack")

        buf = render_round_image(self.dealer, seat_cur.hand if seat_cur else None, hide_hole=True)
        file = None
        if buf is not None:
            file = discord.File(buf, filename="bj.png")
            e.set_image(url="attachment://bj.png")
        return e, file

    async def render(self, interaction):
        embed, file = self._embed_and_file()
        self.view.rebuild()
        view = None if self.phase == "ended" else self.view
        attachments = [file] if file else []
        try:
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=view, attachments=attachments)
            elif self.message is not None:
                await self.message.edit(embed=embed, view=view, attachments=attachments)
        except discord.HTTPException:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class BlackjackCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tables = {}

    group = app_commands.Group(name="blackjack", description="Blackjack (21) — stůl proti Arion")

    async def _open_lobby(self, interaction: discord.Interaction):
        cid = interaction.channel_id
        existing = self.tables.get(cid)
        if existing and existing.phase != "ended":
            await interaction.response.send_message("V tomhle kanálu už jeden stůl běží!", ephemeral=True)
            return
        table = BlackjackTable(self, cid, interaction.user)
        self.tables[cid] = table
        embed, file = table._embed_and_file()
        kwargs = {"embed": embed, "view": table.view}
        if file:
            kwargs["file"] = file
        await interaction.response.send_message(**kwargs)
        table.message = await interaction.original_response()

    @group.command(name="lobby", description="Otevři stůl Blackjacku, kam se ostatní připojí")
    async def lobby_cmd(self, interaction: discord.Interaction):
        await self._open_lobby(interaction)

    async def bj_start(self, interaction: discord.Interaction, sazka: int = 0):
        await self._open_lobby(interaction)

    @group.command(name="cancel", description="[Admin] Zruš stůl Blackjacku v tomto kanálu")
    async def cancel_cmd(self, interaction: discord.Interaction):
        table = self.tables.get(interaction.channel_id)
        if not table:
            await interaction.response.send_message("Žádný stůl tu neběží.", ephemeral=True)
            return
        if table.host_id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Zrušit může jen zakladatel nebo admin.", ephemeral=True)
            return
        table._refund_all_bets()
        table.phase = "ended"
        table.last_summary = "🛑 Stůl byl zrušen."
        self.tables.pop(interaction.channel_id, None)
        await table.render(None)
        await interaction.response.send_message("🛑 Stůl zrušen, sázky vráceny.", ephemeral=True)

    @group.command(name="top", description="Žebříček Blackjacku podle profitu")
    async def top_cmd(self, interaction: discord.Interaction):
        scores = _load_scores()
        if not scores:
            await interaction.response.send_message("Zatím nikdo nehrál.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=_bj_leaderboard_embed(interaction.guild, "silver"),
            view=BJLeaderboardView(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BlackjackCog(bot))