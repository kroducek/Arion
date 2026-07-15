"""
battleships.py — Lodě (Battleships) pro Aurionis.

Cesta: src/core/bot/battleships.py
Přidej do cog listu ArionBOTa (main_bot.py):  "src.core.bot.battleships"
A do minigames_hub.py GAME_INFO (už dodáno v aktualizovaném hubu).

1v1 na tahy. Vyzyvatel otevře stůl, druhý přijme výzvu. Flotila se rozmístí
náhodně (3× přeházení), pak se střílí přes souřadnice (J6). Volitelná sázka —
oba vsadí stejně, vítěz bere pot, remíza vrací.
"""
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

logger = logging.getLogger("Battleships")

# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTY
# ══════════════════════════════════════════════════════════════════════════════

GRID   = 10
CELLS  = GRID * GRID
ROWS   = "ABCDEFGHIJ"

# (název, velikost) — dohromady 17 políček
SHIPS = [
    ("Nosič letadel",  5),
    ("Bitevní loď",    4),
    ("Křižník",        3),
    ("Křižník",        3),
    ("Torpédoborec",   2),
]
TOTAL_SHIP_CELLS = sum(s for _, s in SHIPS)   # 17

MAX_REROLLS  = 3
TURN_TIMEOUT = 120       # vteřin — po nečinnosti může soupeř nárokovat výhru

# ── Grid emoji (barevné čtverce → čistě zarovnaný grid) ──
E_UNK   = "🟦"   # neprozkoumaná voda (zaměřovací pohled)
E_MISS  = "⬜"   # minul
E_HIT   = "🟥"   # zásah
E_SUNK  = "🟪"   # potopená loď
E_WATER = "🟦"   # vlastní voda
E_SHIP  = "🟩"   # vlastní loď

# záhlaví — písmena řádků a čísla sloupců
ROW_EMOJI = ["🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯"]
COL_EMOJI = ["0️⃣", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
CORNER    = "⬛"

BS_COLOR = 0x1F6FEB


# ══════════════════════════════════════════════════════════════════════════════
# EKONOMIKA + LEADERBOARD  (stejný pattern jako blackjack)
# ══════════════════════════════════════════════════════════════════════════════

def _scores_file() -> str:
    from src.utils.paths import data
    return data("battleships_scores.json")

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
    rows   = []
    for uid, rec in scores.items():
        rows.append((uid, rec.get(f"profit_{currency}", 0),
                     rec.get("wins", 0), rec.get("games", 0)))
    rows.sort(key=lambda r: r[1], reverse=True)

    lines = []
    for i, (uid, profit, wins, games) in enumerate(rows[:10]):
        member = guild.get_member(int(uid)) if guild else None
        name   = member.display_name if member else f"Hráč {uid}"
        medal  = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
        sign   = "+" if profit >= 0 else ""
        lines.append(f"{medal} **{name}** — {sign}{profit} {icon}  ·  {wins}W/{games}")

    embed = discord.Embed(
        title="⚓  Lodě — žebříček",
        description="\n".join(lines) or "Zatím nikdo nehrál.",
        color=BS_COLOR,
    )
    embed.set_footer(text=f"Podle čistého profitu ({'zlato' if currency=='gold' else 'stříbro'})")
    return embed


class BSLeaderboardView(discord.ui.View):
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
# HERNÍ LOGIKA (bez závislostí — čistě data)
# ══════════════════════════════════════════════════════════════════════════════

def _place_fleet() -> tuple[list, list]:
    """Náhodně rozmístí flotilu. Vrací (fleet[100]=ship_id|None, ships[])."""
    fleet = [None] * CELLS
    ships = []
    for sid, (name, size) in enumerate(SHIPS):
        while True:
            horiz = random.random() < 0.5
            if horiz:
                r = random.randint(0, 9)
                c = random.randint(0, GRID - size)
                cells = [r * GRID + c + i for i in range(size)]
            else:
                r = random.randint(0, GRID - size)
                c = random.randint(0, 9)
                cells = [(r + i) * GRID + c for i in range(size)]
            if all(fleet[x] is None for x in cells):
                for x in cells:
                    fleet[x] = sid
                ships.append({"name": name, "size": size, "cells": cells, "hits": 0})
                break
    return fleet, ships


class Fighter:
    """Jeden hráč: flotila + přijaté výstřely."""

    def __init__(self, uid: int, name: str):
        self.uid   = uid
        self.name  = name
        self.rerolls = MAX_REROLLS
        self.shots: set[int] = set()          # políčka, na která PO NĚM soupeř vystřelil
        self.fleet, self.ships = _place_fleet()

    def reroll(self) -> bool:
        if self.rerolls <= 0:
            return False
        self.rerolls -= 1
        self.fleet, self.ships = _place_fleet()
        return True

    def receive_shot(self, idx: int) -> tuple[str, str | None]:
        """Soupeř střílí na políčko idx. → (výsledek, jméno lodi)."""
        if idx in self.shots:
            return "repeat", None
        self.shots.add(idx)
        sid = self.fleet[idx]
        if sid is None:
            return "miss", None
        ship = self.ships[sid]
        ship["hits"] += 1
        if ship["hits"] >= ship["size"]:
            return "sunk", ship["name"]
        return "hit", ship["name"]

    def all_sunk(self) -> bool:
        return all(s["hits"] >= s["size"] for s in self.ships)

    def ships_left(self) -> int:
        return sum(1 for s in self.ships if s["hits"] < s["size"])


def _sunk_cells(fighter: Fighter) -> set[int]:
    out = set()
    for s in fighter.ships:
        if s["hits"] >= s["size"]:
            out.update(s["cells"])
    return out


def _render(cell_emoji: list[str]) -> str:
    lines = [CORNER + "".join(COL_EMOJI)]
    for r in range(GRID):
        lines.append(ROW_EMOJI[r] + "".join(cell_emoji[r * GRID:(r + 1) * GRID]))
    return "\n".join(lines)


def render_targeting(target: Fighter) -> str:
    """Zaməřovací pohled: co střelec ví o soupeřově mapě (skryté lodě = voda)."""
    sunk = _sunk_cells(target)
    out  = []
    for idx in range(CELLS):
        if idx in target.shots:
            if target.fleet[idx] is not None:
                out.append(E_SUNK if idx in sunk else E_HIT)
            else:
                out.append(E_MISS)
        else:
            out.append(E_UNK)
    return _render(out)


def render_own(fighter: Fighter) -> str:
    """Vlastní mapa: vidíš svoje lodě i kam soupeř střílel."""
    sunk = _sunk_cells(fighter)
    out  = []
    for idx in range(CELLS):
        ship = fighter.fleet[idx] is not None
        shot = idx in fighter.shots
        if ship and shot:
            out.append(E_SUNK if idx in sunk else E_HIT)
        elif ship:
            out.append(E_SHIP)
        elif shot:
            out.append(E_MISS)
        else:
            out.append(E_WATER)
    return _render(out)


def parse_coord(raw: str) -> int | None:
    """'J6' / '6j' → index 0..99. None když neplatné."""
    s = (raw or "").strip().lower().replace(" ", "")
    if len(s) != 2:
        return None
    a, b = s[0], s[1]
    if a.isalpha() and b.isdigit():
        row, col = a, int(b)
    elif a.isdigit() and b.isalpha():
        row, col = b, int(a)
    else:
        return None
    if row not in "abcdefghij":
        return None
    return "abcdefghij".index(row) * GRID + col


# ══════════════════════════════════════════════════════════════════════════════
# STÁV HRY
# ══════════════════════════════════════════════════════════════════════════════

class Battle:
    def __init__(self, cog, channel_id: int, host: discord.Member, bet: int):
        self.cog        = cog
        self.channel_id = channel_id
        self.bet        = max(0, bet)
        self.currency   = get_minigame_currency()   # zamkni měnu na dobu hry
        self.phase      = "lobby"                    # lobby | playing | ended
        self.host       = Fighter(host.id, host.display_name)
        self.guest: Fighter | None = None
        self.fighters   = {host.id: self.host}
        self.turn       = host.id                    # kdo je na tahu
        self.last_action = time.time()
        self.message    = None
        self.summary    = ""                         # poslední hláška
        self.anted      = {host.id} if self.bet > 0 else set()  # kdo už vsadil

    # ── účastníci ──
    def is_player(self, uid: int) -> bool:
        return uid in self.fighters

    def opponent_of(self, uid: int) -> Fighter | None:
        for u, f in self.fighters.items():
            if u != uid:
                return f
        return None

    def current(self) -> Fighter:
        return self.fighters[self.turn]

    def waiting(self) -> Fighter | None:
        return self.opponent_of(self.turn)

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
                loser = self.opponent_of(winner_uid)
                _record_result(winner_uid, 0, True, self.currency)
                if loser:
                    _record_result(loser.uid, 0, False, self.currency)
            return

        if winner_uid is None:                       # remíza → vrať antem
            self.refund_all()
            for uid in self.fighters:
                _record_result(uid, 0, False, self.currency)
            return

        loser = self.opponent_of(winner_uid)
        _eco_add(winner_uid, self.pot())             # bere celý pot
        _record_result(winner_uid, self.bet, True, self.currency)
        if loser:
            _record_result(loser.uid, -self.bet, False, self.currency)
        self.anted.clear()

    # ── embed ──
    def build_embed(self) -> discord.Embed:
        coin = COIN_GOLD if self.currency == "gold" else COIN_SILVER

        if self.phase == "lobby":
            desc = [f"**{self.host.name}** vyzývá k námořní bitvě! ⚓"]
            if self.bet > 0:
                desc.append(f"Sázka **{self.bet}** {coin} od každého  ·  pot **{self.pot()}** {coin}")
            desc.append("")
            desc.append("🚢 " + (f"**{self.guest.name}** přijal výzvu!"
                                 if self.guest else "*Čeká se na vyzvatele…*"))
            desc.append("-# Než začnete, můžete si **přeházet flotilu** (3×).")
            embed = discord.Embed(title="⚓  Lodě — příprava",
                                  description="\n".join(desc), color=BS_COLOR)
            for f in self.fighters.values():
                embed.add_field(name=f.name,
                                value=f"🎲 zbývá přeházení: **{f.rerolls}**", inline=True)
            embed.set_footer(text="Vyplout může jen vyzyvatel · min. 2 kapitáni")
            return embed

        if self.phase == "playing":
            cur = self.current()
            tgt = self.waiting()
            embed = discord.Embed(
                title="⚓  Lodě — bitva",
                description=(f"### 🎯 Na tahu: **{cur.name}**\n"
                             + (f"-# {self.summary}\n" if self.summary else "")
                             + f"\n{render_targeting(tgt)}"),
                color=BS_COLOR,
            )
            embed.add_field(
                name="Flotily",
                value=(f"⚓ **{self.host.name}** — {self.host.ships_left()} lodí\n"
                       f"⚓ **{self.guest.name}** — {self.guest.ships_left()} lodí"),
                inline=False,
            )
            if self.bet > 0:
                embed.add_field(name="Pot", value=f"**{self.pot()}** {coin}", inline=False)
            embed.set_footer(text="🟥 zásah · ⬜ vedle · 🟪 potopeno · 🟦 neznámo")
            return embed

        # ended
        embed = discord.Embed(title="⚓  Lodě — konec",
                              description=self.summary, color=BS_COLOR)
        embed.set_footer(text=f"⭐ Aurionis")
        return embed


# ══════════════════════════════════════════════════════════════════════════════
# UI — LOBBY (příprava)
# ══════════════════════════════════════════════════════════════════════════════

class LobbyView(discord.ui.View):
    def __init__(self, battle: Battle):
        super().__init__(timeout=None)
        self.battle = battle

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.battle.build_embed(), view=self)

    @discord.ui.button(label="Přijmout výzvu", emoji="⚔️", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _b):
        b = self.battle
        if b.phase != "lobby":
            await interaction.response.send_message("Bitva už začala.", ephemeral=True)
            return
        if b.guest is not None:
            await interaction.response.send_message("Výzvu už někdo přijal.", ephemeral=True)
            return
        if interaction.user.id == b.host.uid:
            await interaction.response.send_message(
                "Nemůžeš přijmout vlastní výzvu.", ephemeral=True)
            return

        # sázka — vyzvatel musí složit stejné ante jako vyzyvatel
        if b.bet > 0:
            if not _eco_deduct(interaction.user.id, b.bet):
                await interaction.response.send_message(
                    f"❌ Nemáš dost — potřebuješ **{b.bet}** {minigame_coin()}.", ephemeral=True)
                return
            b.anted.add(interaction.user.id)

        b.guest = Fighter(interaction.user.id, interaction.user.display_name)
        b.fighters[interaction.user.id] = b.guest
        await self._refresh(interaction)

    @discord.ui.button(label="Přeházet flotilu", emoji="🎲", style=discord.ButtonStyle.secondary)
    async def reroll(self, interaction: discord.Interaction, _b):
        b = self.battle
        if not b.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle bitvě.", ephemeral=True)
            return
        if b.phase != "lobby":
            await interaction.response.send_message("Flotilu už měnit nelze.", ephemeral=True)
            return
        f = b.fighters[interaction.user.id]
        if not f.reroll():
            await interaction.response.send_message("Došla ti přeházení.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🎲 Nová flotila (zbývá **{f.rerolls}**):\n{render_own(f)}", ephemeral=True)
        # aktualizuj počet přeházení v hlavní zprávě
        if b.message:
            try:
                await b.message.edit(embed=b.build_embed(), view=self)
            except Exception:
                pass

    @discord.ui.button(label="Moje flotila", emoji="🚢", style=discord.ButtonStyle.secondary)
    async def my_fleet(self, interaction: discord.Interaction, _b):
        b = self.battle
        if not b.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle bitvě.", ephemeral=True)
            return
        f = b.fighters[interaction.user.id]
        await interaction.response.send_message(render_own(f), ephemeral=True)

    @discord.ui.button(label="Vyplout", emoji="🚀", style=discord.ButtonStyle.primary, row=1)
    async def start(self, interaction: discord.Interaction, _b):
        b = self.battle
        if interaction.user.id != b.host.uid:
            await interaction.response.send_message(
                "Vyplout může jen vyzyvatel.", ephemeral=True)
            return
        if b.guest is None:
            await interaction.response.send_message(
                "Ještě nikdo nepřijal výzvu.", ephemeral=True)
            return
        b.phase = "playing"
        b.turn  = random.choice(list(b.fighters.keys()))   # kdo začíná = náhoda
        b.last_action = time.time()
        b.summary = f"Bitva začíná! První pálí **{b.current().name}**."
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=b.build_embed(), view=PlayingView(b))

    @discord.ui.button(label="Zrušit", emoji="❌", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, _b):
        b = self.battle
        if interaction.user.id != b.host.uid and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Zrušit může jen vyzyvatel nebo admin.", ephemeral=True)
            return
        b.refund_all()
        b.phase = "ended"
        b.cog.games.pop(b.channel_id, None)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="🛑 Bitva zrušena, sázky vráceny.", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# UI — PALBA (modal se souřadnicí)
# ══════════════════════════════════════════════════════════════════════════════

class FireModal(discord.ui.Modal, title="🎯 Palba"):
    coord = discord.ui.TextInput(
        label="Souřadnice (např. J6)",
        placeholder="písmeno A–J + číslo 0–9",
        min_length=2, max_length=3,
    )

    def __init__(self, view: "PlayingView"):
        super().__init__()
        self.pview = view

    async def on_submit(self, interaction: discord.Interaction):
        await self.pview.do_fire(interaction, self.coord.value)


class PlayingView(discord.ui.View):
    def __init__(self, battle: Battle):
        super().__init__(timeout=None)
        self.battle = battle

    @discord.ui.button(label="Palba", emoji="🎯", style=discord.ButtonStyle.primary)
    async def fire(self, interaction: discord.Interaction, _b):
        b = self.battle
        if b.phase != "playing":
            await interaction.response.send_message("Bitva neběží.", ephemeral=True)
            return
        if not b.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle bitvě.", ephemeral=True)
            return
        if interaction.user.id != b.turn:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        await interaction.response.send_modal(FireModal(self))

    async def do_fire(self, interaction: discord.Interaction, raw: str):
        b = self.battle
        if b.phase != "playing" or interaction.user.id != b.turn:
            await interaction.response.send_message("Teď nemůžeš pálit.", ephemeral=True)
            return

        idx = parse_coord(raw)
        if idx is None:
            await interaction.response.send_message(
                "❌ Neplatná souřadnice. Příklad: **J6**.", ephemeral=True)
            return

        target = b.waiting()
        result, ship_name = target.receive_shot(idx)
        if result == "repeat":
            await interaction.response.send_message(
                "Sem už jsi střílel — zvol jiné políčko.", ephemeral=True)
            return

        shooter = b.current()
        coord_txt = f"{ROWS[idx // GRID]}{idx % GRID}"
        b.last_action = time.time()

        if result == "sunk" and target.all_sunk():
            b.summary = (f"💥 **{shooter.name}** potopil poslední loď "
                         f"(**{ship_name}**) na {coord_txt} a **VYHRÁVÁ**! ⚓")
            b.finish(shooter.uid)
            b.cog.games.pop(b.channel_id, None)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(embed=b.build_embed(), view=self)
            return

        if result == "sunk":
            b.summary = f"💥 **{shooter.name}** potopil {ship_name} na {coord_txt}! Střílí znovu."
        elif result == "hit":
            b.summary = f"🟥 Zásah na {coord_txt}! **{shooter.name}** střílí znovu."
        else:
            b.summary = f"⬜ **{shooter.name}** minul na {coord_txt}. Tah přechází."
            b.turn = target.uid                        # minul → střídání

        await interaction.response.edit_message(embed=b.build_embed(), view=self)

    @discord.ui.button(label="Moje flotila", emoji="🚢", style=discord.ButtonStyle.secondary)
    async def my_fleet(self, interaction: discord.Interaction, _b):
        b = self.battle
        if not b.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle bitvě.", ephemeral=True)
            return
        f = b.fighters[interaction.user.id]
        await interaction.response.send_message(
            f"**Tvá flotila** ({f.ships_left()} lodí):\n{render_own(f)}", ephemeral=True)

    @discord.ui.button(label="Vzdát se", emoji="🏳️", style=discord.ButtonStyle.danger)
    async def surrender(self, interaction: discord.Interaction, _b):
        b = self.battle
        if not b.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle bitvě.", ephemeral=True)
            return
        winner = b.opponent_of(interaction.user.id)
        b.summary = (f"🏳️ **{b.fighters[interaction.user.id].name}** se vzdal — "
                     f"vítězem je **{winner.name}**! ⚓")
        b.finish(winner.uid)
        b.cog.games.pop(b.channel_id, None)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=b.build_embed(), view=self)

    @discord.ui.button(label="Timeout", emoji="⏱️", style=discord.ButtonStyle.secondary)
    async def timeout_claim(self, interaction: discord.Interaction, _b):
        b = self.battle
        if not b.is_player(interaction.user.id):
            await interaction.response.send_message("Nejsi v téhle bitvě.", ephemeral=True)
            return
        if interaction.user.id == b.turn:
            await interaction.response.send_message(
                "Timeout může nárokovat jen ten, kdo čeká na soupeře.", ephemeral=True)
            return
        idle = time.time() - b.last_action
        if idle < TURN_TIMEOUT:
            await interaction.response.send_message(
                f"Soupeř má ještě **{int(TURN_TIMEOUT - idle)} s** na tah.", ephemeral=True)
            return
        winner = b.fighters[interaction.user.id]
        b.summary = (f"⏱️ **{b.current().name}** nehrál včas — "
                     f"vítězem je **{winner.name}**! ⚓")
        b.finish(winner.uid)
        b.cog.games.pop(b.channel_id, None)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=b.build_embed(), view=self)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class BattleshipsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self.games = {}          # channel_id → Battle

    group = app_commands.Group(name="battleships", description="Lodě — námořní bitva 1v1")

    async def _open(self, interaction: discord.Interaction, sazka: int = 0):
        cid = interaction.channel_id
        existing = self.games.get(cid)
        if existing and existing.phase != "ended":
            await interaction.response.send_message(
                "V tomhle kanálu už jedna bitva běží!", ephemeral=True)
            return

        if sazka < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True)
            return
        if sazka > 0 and not _eco_deduct(interaction.user.id, sazka):
            await interaction.response.send_message(
                f"❌ Nemáš dost — potřebuješ **{sazka}** {minigame_coin()}.", ephemeral=True)
            return

        battle = Battle(self, cid, interaction.user, sazka)
        self.games[cid] = battle
        await interaction.response.send_message(
            embed=battle.build_embed(), view=LobbyView(battle))
        battle.message = await interaction.original_response()

    # vstup z hubu
    async def bs_start(self, interaction: discord.Interaction, sazka: int = 0):
        await self._open(interaction, sazka)

    @group.command(name="lobby", description="Otevři námořní bitvu, kam někdo přijme výzvu")
    @app_commands.describe(sazka="Sázka od každého (0 = bez sázky)")
    async def lobby_cmd(self, interaction: discord.Interaction, sazka: int = 0):
        await self._open(interaction, sazka)

    @group.command(name="cancel", description="Zruš bitvu v tomto kanálu")
    async def cancel_cmd(self, interaction: discord.Interaction):
        b = self.games.get(interaction.channel_id)
        if not b:
            await interaction.response.send_message("Žádná bitva tu neběží.", ephemeral=True)
            return
        if b.host.uid != interaction.user.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Zrušit může jen zakladatel nebo admin.", ephemeral=True)
            return
        b.refund_all()
        b.phase = "ended"
        self.games.pop(interaction.channel_id, None)
        await interaction.response.send_message("🛑 Bitva zrušena, sázky vráceny.", ephemeral=True)

    @group.command(name="top", description="Žebříček Lodí podle profitu")
    async def top_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=_leaderboard_embed(interaction.guild, "silver"), view=BSLeaderboardView())


async def setup(bot: commands.Bot):
    await bot.add_cog(BattleshipsCog(bot))