"""
Kostky (Farkle) minihra pro ArionBot
- Hráči házejí pomocí /roll XdY (kompatibilní s roll.py)
- Nastavitelný cíl skóre
- Arion NPC boss mode
- Magické kostky (X2, HOT DICE, SAFE) - Plně implementováno s UI
- Odměny formou Truhel
- Sázky (economy integrace)
- Persistentní leaderboard (výhry + profit)
"""

import discord
import re
import random
import asyncio
import json
import os
import sys
from discord.ext import commands
from discord import app_commands
from itertools import combinations
from collections import Counter

# ── DICE IMAGE (volitelné) ────────────────────────────────────────────────────

try:
    from src.utils.dice_image import build_dice_image
    DICE_IMAGES_ENABLED = True
except Exception:
    DICE_IMAGES_ENABLED = False

# ── ECONOMY INTEGRACE ─────────────────────────────────────────────────────────

from src.utils.paths import ECONOMY as ECONOMY_PATH, KOSTKY_LB as STATS_PATH, KOSTKY_MAGIC as MAGIC_DICE_PATH

def _econ_load() -> dict:
    try:
        with open(ECONOMY_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}

def _econ_save(data: dict):
    try:
        with open(ECONOMY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[kostky] economy save chyba: {e}")

def econ_get(user_id: int) -> int:
    return _econ_load().get(str(user_id), 0)

def econ_add(user_id: int, amount: int):
    data = _econ_load()
    uid  = str(user_id)
    data[uid] = data.get(uid, 0) + amount
    _econ_save(data)

def econ_deduct(user_id: int, amount: int) -> bool:
    """Odečte amount od hráče. Vrátí False pokud nemá dost."""
    data = _econ_load()
    uid  = str(user_id)
    bal  = data.get(uid, 0)
    if bal < amount:
        return False
    data[uid] = bal - amount
    _econ_save(data)
    return True

# ── STATS (persistentní výhry + profit) ──────────────────────────────────────


def _stats_load() -> dict:
    try:
        with open(os.path.abspath(STATS_PATH), "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}

def _stats_save(data: dict):
    try:
        with open(os.path.abspath(STATS_PATH), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[kostky] stats save chyba: {e}")

def record_win(guild_id: int, user_id: int, profit: int = 0):
    """Zaznamená výhru a přičte zisk k profitu."""
    data = _stats_load()
    gid  = str(guild_id)
    uid  = str(user_id)
    data.setdefault(gid, {}).setdefault(uid, {"wins": 0, "profit": 0})
    data[gid][uid]["wins"]   += 1
    data[gid][uid]["profit"] += profit
    _stats_save(data)

def record_loss(guild_id: int, user_id: int, sazka: int = 0):
    """Zaznamená prohru — odečte sázku z profitu (může jít do minusu)."""
    if sazka <= 0:
        return
    data = _stats_load()
    gid  = str(guild_id)
    uid  = str(user_id)
    data.setdefault(gid, {}).setdefault(uid, {"wins": 0, "profit": 0})
    data[gid][uid]["profit"] -= sazka
    _stats_save(data)

def get_all_stats(guild_id: int) -> dict:
    """Vrátí {uid_str: {wins, profit}} pro daný guild."""
    return _stats_load().get(str(guild_id), {})

def wins_word(n: int) -> str:
    if n == 1: return "výhra"
    if n <= 4: return "výhry"
    return "výher"

# ── KONFIGURACE ───────────────────────────────────────────────────────────────

DEFAULT_WINNING_SCORE = 5000
MIN_FIRST_SCORE       = 350
MAX_PLAYERS           = 6
ARION_ID              = -1   # speciální ID pro Arion NPC

DICE_EMOJI = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

# ── MAGICKÉ KOSTKY ────────────────────────────────────────────────────────────

class MagicDie:
    X2       = "x2"        # zdvojnásobí body z aktuálního hodu
    HOT_DICE = "hot_dice"  # hned hod všemi 6
    SAFE     = "safe"      # zachrání od Farklu

MAGIC_DIE_INFO = {
    MagicDie.X2:       {"emoji": "🟥", "name": "X2 Kostka",   "desc": "Zdvojnásobí body z aktuálního hodu."},
    MagicDie.HOT_DICE: {"emoji": "🟦", "name": "Hot Dice",    "desc": "Okamžitě hodíš znovu všemi 6 kostkami."},
    MagicDie.SAFE:     {"emoji": "🟩", "name": "SAFE Kostka", "desc": "Zachrání tě před Farklem — jednou."},
}
ALL_MAGIC_TYPES = list(MAGIC_DIE_INFO.keys())

# Trvalé úložiště magických kostek (JSON)

def _mdice_load() -> dict:
    try:
        with open(os.path.abspath(MAGIC_DICE_PATH), "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}

def _mdice_save(data: dict):
    try:
        with open(os.path.abspath(MAGIC_DICE_PATH), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[kostky] magic_dice save chyba: {e}")

def get_magic_dice(guild_id: int, user_id: int) -> list:
    return _mdice_load().get(str(guild_id), {}).get(str(user_id), [])

def add_magic_die(guild_id: int, user_id: int, die_type: str):
    data = _mdice_load()
    data.setdefault(str(guild_id), {}).setdefault(str(user_id), []).append(die_type)
    _mdice_save(data)

def remove_magic_die(guild_id: int, user_id: int, die_type: str) -> bool:
    data = _mdice_load()
    inv  = data.get(str(guild_id), {}).get(str(user_id), [])
    if die_type in inv:
        inv.remove(die_type)
        _mdice_save(data)
        return True
    return False

# ── ARION KOMENTÁŘE ───────────────────────────────────────────────────────────

ARION_ROLL_COMMENTS = [
    "🐾 *Arion hodí kostkami s elegancí zkušené hráčky...*",
    "🐾 *Arion přimhouří oči a hodí...*",
    "🐾 *'Mňau' — Arion hodí kostkami bez jakékoliv námahy*",
    "🐾 *Arion si olízne tlapku a hodí...*",
    "🐾 *'Tohle bude zajímavý...' zamumlá Arion.*",
]
ARION_GOOD_ROLL = [
    "🐾 *'Přesně jak jsem čekala' Arion se usmívá.*",
    "🐾 *Arion spokojeně přede*",
    "🐾 *'Ani jsem se nemusela snažit'*",
    "🐾 *Arion mrká spokojeně*",
]
ARION_BAD_ROLL = [
    "🐾 *'Hm. Tohle se nestává často' Arion vypadá překvapeně.*",
    "🐾 *Arion zamračeně zírá na kostky*",
    "🐾 *'Nevadí. Příště' Arion si hladí fousky*",
]
ARION_BANK_COMMENTS = [
    "🐾 *Arion si zapíše body zlatým perem*",
    "🐾 *'Prozatím stačí' Arion odloží kostky*",
    "🐾 *Arion přikývne a uloží svůj zisk*",
]
ARION_WIN_COMMENTS = [
    "🐾 *Arion vítězně zamává ocasem.*\n*'Říkala jsem, že budete potřebovat štěstí. Příště přijďte připravenější'*",
    "🐾 *Arion sklapne knihu.*\n*'Porazit mě? Milá myšlenka. Ale ne dnes'*",
]
ARION_LOSE_COMMENTS = [
    "😾 *Arion překvapeně zírá na skóre.*\n*'Neuvěřitelné... Zasloužená výhra. Tentokrát'*",
    "😾 *Arion pomalu přikývne.*\n*'Dobře hráno. Ale příště budu připravenější'*",
]

# ── POMOCNÉ FUNKCE ────────────────────────────────────────────────────────────

def make_dice_file(dice: list):
    if not DICE_IMAGES_ENABLED or not dice:
        return None
    try:
        buf = build_dice_image(dice)
        return discord.File(buf, filename="dice.png")
    except Exception as e:
        print(f"[kostky] dice image chyba: {e}")
        return None

def dice_to_str(dice: list) -> str:
    return "  ".join(DICE_EMOJI[d] for d in dice)

def score_bar(pts: int, target: int) -> str:
    filled = min(10, int((pts / target) * 10))
    return "█" * filled + "░" * (10 - filled)

def dice_word(n: int) -> str:
    if n == 1: return "kostku"
    if n <= 4: return "kostky"
    return "kostek"

# ── SKÓROVÁNÍ ─────────────────────────────────────────────────────────────────

def score_selection(dice: list) -> int:
    if not dice:
        return 0
    counts      = Counter(dice)
    sorted_dice = sorted(dice)
    n           = len(dice)

    if n == 6 and sorted_dice == [1, 2, 3, 4, 5, 6]:
        return 1500
    if n == 6 and len(counts) == 3 and all(v == 2 for v in counts.values()):
        return 750
    if n == 6 and len(counts) == 2 and all(v == 3 for v in counts.values()):
        return 1500

    total = 0
    for face, count in counts.items():
        if count >= 3:
            base   = 1000 if face == 1 else face * 100
            total += base * (2 ** (count - 3))
        else:
            if face == 1:   total += count * 100
            elif face == 5: total += count * 50
    return total

def is_valid_selection(dice: list) -> bool:
    if not dice:
        return False
    base_score  = score_selection(dice)
    if base_score == 0:
        return False
    sorted_dice = sorted(dice)
    counts      = Counter(dice)
    n           = len(dice)
    if n == 6 and sorted_dice == [1, 2, 3, 4, 5, 6]:
        return True
    if n == 6 and len(counts) == 3 and all(v == 2 for v in counts.values()):
        return True
    if n == 6 and len(counts) == 2 and all(v == 3 for v in counts.values()):
        return True
    for i in range(n):
        without = dice[:i] + dice[i+1:]
        if score_selection(without) >= base_score:
            return False
    return True

def find_all_scoring_combos(dice: list) -> list:
    results = []
    seen    = set()
    for r in range(1, len(dice) + 1):
        for combo in combinations(range(len(dice)), r):
            selected = [dice[i] for i in combo]
            key      = tuple(sorted(selected))
            if key in seen:
                continue
            seen.add(key)
            if is_valid_selection(selected):
                results.append((selected, score_selection(selected)))
    results.sort(key=lambda x: -x[1])
    return results

# ── ARION AI ──────────────────────────────────────────────────────────────────

def arion_should_bank(turn_score: int, remaining_dice: int, arion_total: int,
                      winning_score: int, best_opponent_score: int) -> bool:
    """
    Rozhodne jestli má Arion bankovat.
    Logika: risk/reward podle zbývajících kostek + situace ve hře.
    """
    needed_to_win = winning_score - arion_total
    opponent_lead = best_opponent_score - arion_total  # kladné = soupeř vede

    # Vyhraje tímto bankem?
    if turn_score >= needed_to_win:
        return True

    # Soupeř je blízko výhře (do 1000 od cíle) — hraj agresivněji
    under_pressure = (winning_score - best_opponent_score) < 1000

    # Pravděpodobnost Farklu podle počtu kostek (empirické hodnoty Farkle)
    farkle_prob = {1: 0.67, 2: 0.44, 3: 0.28, 4: 0.17, 5: 0.09, 6: 0.04}
    risk = farkle_prob.get(remaining_dice, 0.15)

    # Hodnota bankování: turn_score * (1 - pravděpodobnost ztráty)
    # vs hodnota pokračování: odhadovaný přínos dalšího hodu
    # S málo kostkami je riziko příliš vysoké

    if remaining_dice <= 1:
        return turn_score >= 300   # s 1 kostkou bankuj skoro vždy

    if remaining_dice == 2:
        threshold = 600 if not under_pressure else 900
        return turn_score >= threshold

    if remaining_dice == 3:
        threshold = 800 if not under_pressure else 1200
        return turn_score >= threshold

    # 4+ kostek — pokračuj pokud nemáš slušný základ
    if remaining_dice >= 4:
        if under_pressure:
            return turn_score >= 1500   # pod tlakem bankuj až při velkém tahu
        return turn_score >= 1000

    return False


def arion_decide(rolled: list, turn_score: int, remaining_dice: int,
                 winning_score: int, arion_total: int,
                 best_opponent_score: int = 0) -> tuple:
    """
    Arion rozhodne co udělat po hodu.
    Vrátí (selected_combo, should_bank).
    """
    combos = find_all_scoring_combos(rolled)
    if not combos:
        return None, False   # FARKLE

    best_combo, best_pts = combos[0]
    new_turn      = turn_score + best_pts
    new_remaining = remaining_dice - len(best_combo)
    if new_remaining == 0:
        new_remaining = 6   # Hot Dice / všechny kostky bodovaly

    should_bank = arion_should_bank(
        new_turn, new_remaining, arion_total, winning_score, best_opponent_score
    )
    return best_combo, should_bank

# ── HERNÍ STAV ────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self, leader_id: int, channel_id: int, winning_score: int = DEFAULT_WINNING_SCORE, sazka: int = 0):
        self.leader_id     = leader_id
        self.channel_id    = channel_id
        self.winning_score = winning_score
        self.sazka         = sazka        # 0 = bez sázky
        self.players       = [leader_id]
        self.scores        = {leader_id: 0}
        self.started       = False
        self.has_arion     = False

        self.current_idx      = 0
        self.turn_score       = 0
        self.remaining_dice   = 6
        self.collected_rolls  = []
        self.kept_total       = []
        self.waiting_for_roll = False
        self.game_message     = None
        self.used_magic_this_game: dict[int, set] = {}  # uid -> {die_type, ...} použité tuto hru

    @property
    def current_player(self) -> int:
        return self.players[self.current_idx]

    def is_arion_turn(self) -> bool:
        return self.current_player == ARION_ID

    def add_arion(self):
        self.players.append(ARION_ID)
        self.scores[ARION_ID] = 0
        self.has_arion = True

    def next_player(self):
        self.current_idx      = (self.current_idx + 1) % len(self.players)
        self.turn_score       = 0
        self.remaining_dice   = 6
        self.collected_rolls  = []
        self.kept_total       = []
        self.waiting_for_roll = False

    def start_roll_phase(self):
        self.collected_rolls  = []
        self.waiting_for_roll = True

    def add_roll_result(self, value: int) -> bool:
        self.collected_rolls.append(value)
        if len(self.collected_rolls) >= self.remaining_dice:
            self.waiting_for_roll = False
            return True
        return False

    def keep(self, selected: list) -> int:
        pts = score_selection(selected)
        self.turn_score     += pts
        self.remaining_dice -= len(selected)
        self.kept_total.extend(selected)
        if self.remaining_dice == 0:
            self.remaining_dice = 6
            self.kept_total     = []
        return pts

    def bank(self) -> int:
        uid = self.current_player
        self.scores[uid] = self.scores.get(uid, 0) + self.turn_score
        return self.scores[uid]

    def player_name(self, uid: int, guild) -> str:
        if uid == ARION_ID:
            return "🐾 Arion"
        m = guild.get_member(uid)
        return m.display_name if m else str(uid)

    def leaderboard(self, guild, highlight_current: bool = True) -> str:
        lines = []
        for uid, pts in sorted(self.scores.items(), key=lambda x: -x[1]):
            name   = self.player_name(uid, guild)
            marker = " 👑" if pts >= self.winning_score else ""
            arrow  = "🎯 " if (highlight_current and uid == self.current_player) else "   "
            bar    = score_bar(pts, self.winning_score)
            lines.append(f"{arrow}**{name}**{marker}\n`{bar}` {pts}/{self.winning_score}")
        return "\n".join(lines) if lines else "—"

# ── AKTIVNÍ HRY ───────────────────────────────────────────────────────────────

active_games: dict[int, GameState] = {}   # guild_id -> GameState

# ── EMBEDY ────────────────────────────────────────────────────────────────────

ARION_LOBBY_TAUNTS = [
    '🐾 *„Vážně? Chcete hrát kostky? Proti mě?"*',
    '🐾 *„Zajímavá volba. Doufám, že umíte prohrávat"*',
    '🐾 *„Přistoupím na tuto hru. Jen abyste věděli.. já nevím, co je to prohra"*',
    '🐾 *„Kostky? Můj oblíbený způsob jak zklamat ostatní"*',
    '🐾 *„Budu milosrdná. Nechám vás přemýšlet než budu vyhrávat"*',
]

def lobby_embed(game: GameState, guild) -> discord.Embed:
    taunt = random.choice(ARION_LOBBY_TAUNTS) if game.has_arion else "🐾 *Arion rozkládá kostky na stůl a přimhouří oči...*"

    sazka_line = ""
    if game.sazka > 0:
        total_pool = game.sazka * (len([p for p in game.players if p != ARION_ID]) + (1 if game.has_arion else 0))
        sazka_line = f"\n💰 **Sázka:** {game.sazka} <:goldcoin:1490171741237018795> na hráče  ·  pool: **{total_pool}** <:goldcoin:1490171741237018795>"

    embed = discord.Embed(
        title="🎲 Kostky (Farkle)",
        description=(
            f"{taunt}\n\n"
            f"🏁 **Cíl:** {game.winning_score} bodů\n"
            f"📋 **Zápis od:** {MIN_FIRST_SCORE} bodů"
            f"{sazka_line}"
        ),
        color=0xFF8C00
    )

    # Hráči jako mentions
    player_lines = []
    for uid in game.players:
        if uid == ARION_ID:
            continue
        m      = guild.get_member(uid)
        crown  = " 👑" if uid == game.leader_id else ""
        mention = m.mention if m else f"<@{uid}>"
        player_lines.append(f"{mention}{crown}")

    if game.has_arion:
        player_lines.append("🐾 **Arion** *(NPC Boss)*")

    player_text = "\n".join(player_lines) if player_lines else "—"
    embed.add_field(
        name=f"👥 Hráči  {len(game.players)}/{MAX_PLAYERS}",
        value=player_text,
        inline=False
    )

    embed.set_footer(text=f"⭐ Aurionis  •  Leader spustí hru tlačítkem ▶️")
    return embed


def waiting_roll_embed(game: GameState, guild, extra_msg: str = "") -> discord.Embed:
    name = game.player_name(game.current_player, guild)
    need = game.remaining_dice

    if game.is_arion_turn():
        desc  = (f"{extra_msg}\n\n" if extra_msg else "") + f"🐾 **Arion** hází {need} {dice_word(need)}..."
        color = 0x9b59b6
    else:
        desc  = (f"{extra_msg}\n\n" if extra_msg else "") + f"🎲 **{name}** je na tahu!\n\nHoď `/roll {need}d6`"
        color = 0x3498db

    embed = discord.Embed(title="🎲 Kostky", description=desc, color=color)
    embed.add_field(name="💰 Body v tahu",      value=f"**{game.turn_score}**", inline=True)
    embed.add_field(name="🎲 Zbývající kostky", value=f"**{need}**",            inline=True)
    embed.add_field(name="\u200b",              value="\u200b",                 inline=True)
    embed.add_field(name="📊 Skóre",            value=game.leaderboard(guild),  inline=False)
    embed.set_footer(text=f"⭐ Aurionis  •  Cíl: {game.winning_score} bodů  •  Zápis od {MIN_FIRST_SCORE} bodů")
    return embed


def combo_embed(game: GameState, guild, rolled: list, extra_desc: str = "") -> discord.Embed:
    combos = find_all_scoring_combos(rolled)
    embed  = discord.Embed(title="🎲 Kostky — Vyber kombinaci", color=0x5865F2)
    embed.set_image(url="attachment://dice.png")

    if extra_desc:
        embed.description = extra_desc

    if combos:
        combo_text = "\n".join(
            f"{'  '.join(DICE_EMOJI[d] for d in s)}  ➜  **{p} b**"
            for s, p in combos[:5]
        )
        embed.add_field(name="✨ Dostupné kombinace", value=combo_text, inline=False)
    else:
        embed.add_field(name="💀 FARKLE!", value="Žádná bodovaná kombinace!", inline=False)
        embed.color = discord.Color.red()

    embed.add_field(name="💰 Body v tahu",      value=f"**{game.turn_score}**",     inline=True)
    embed.add_field(name="🎲 Zbývající kostky", value=f"**{game.remaining_dice}**", inline=True)
    embed.add_field(name="\u200b",              value="\u200b",                      inline=True)
    embed.add_field(name="📊 Skóre",            value=game.leaderboard(guild),       inline=False)
    embed.set_footer(text=f"⭐ Aurionis  •  Cíl: {game.winning_score} bodů")
    return embed


def farkle_embed(game: GameState, guild, farkle_player_name: str, extra_msg: str = "") -> discord.Embed:
    next_name = game.player_name(game.current_player, guild)
    embed = discord.Embed(
        title="💀 FARKLE!",
        description=(
            f"**{farkle_player_name}** nemá žádnou bodovanou kombinaci!\n"
            f"Všechny body z tohoto tahu jsou ztraceny.\n\n"
            + (f"{extra_msg}\n\n" if extra_msg else "")
        ),
        color=0xe74c3c
    )
    embed.add_field(name="📊 Skóre",  value=game.leaderboard(guild), inline=False)
    embed.set_footer(text=f"⭐ Aurionis  •  Na tahu: {next_name}  •  Cíl: {game.winning_score} bodů")
    return embed


def win_embed(game: GameState, guild, win_name: str, total: int, payout: int = 0) -> discord.Embed:
    parts = [f"🎉 **{win_name}** dosáhl **{total}** bodů a vyhrál!"]

    if game.has_arion:
        parts.append(random.choice(ARION_LOSE_COMMENTS))
        parts.append("*🐾 Arion tleská tlapkami a zapisuje jméno zlatým inkoustem...*")

    if payout > 0:
        parts.append(f"💰 **Výhra ze sázky: +{payout} <:goldcoin:1490171741237018795>**")

    embed = discord.Embed(
        title="🏆 VÍTĚZ!",
        description="\n\n".join(parts),
        color=discord.Color.gold()
    )
    embed.add_field(name="📊 Konečné skóre", value=game.leaderboard(guild, highlight_current=False), inline=False)
    embed.set_footer(text="⭐ Aurionis")
    return embed

# ── TRUHLY (ODměna po výhře) ──────────────────────────────────────────────────

class ChestRewardView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.user_id = user_id
        self.winning_chest = random.randint(0, 2)

    async def _handle_chest(self, interaction: discord.Interaction, index: int):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Toto není tvá odměna!", ephemeral=True)
        
        for child in self.children:
            child.disabled = True
            
        if index == self.winning_chest:
            die = random.choice(ALL_MAGIC_TYPES)
            add_magic_die(self.guild_id, self.user_id, die)
            info = MAGIC_DIE_INFO[die]
            res = f"✨ **Úspěch! Otevřel jsi správnou truhlu.**\nZískáváš magickou kostku: {info['emoji']} **{info['name']}**"
        else:
            res = "💨 **Tato truhla byla prázdná...**\nSnad budeš mít víc štěstí příště!"
            
        await interaction.response.edit_message(content=res, view=self)

    @discord.ui.button(label="📦 Truhla 1", style=discord.ButtonStyle.secondary)
    async def chest1(self, i: discord.Interaction, b: discord.ui.Button): await self._handle_chest(i, 0)
    
    @discord.ui.button(label="📦 Truhla 2", style=discord.ButtonStyle.secondary)
    async def chest2(self, i: discord.Interaction, b: discord.ui.Button): await self._handle_chest(i, 1)
    
    @discord.ui.button(label="📦 Truhla 3", style=discord.ButtonStyle.secondary)
    async def chest3(self, i: discord.Interaction, b: discord.ui.Button): await self._handle_chest(i, 2)

# ── SDÍLENÁ LOGIKA BANK ───────────────────────────────────────────────────────

async def _do_bank(interaction: discord.Interaction, game: GameState, view: discord.ui.View):
    total     = game.bank()
    guild     = interaction.guild
    prev_uid  = game.current_player
    prev_name = game.player_name(prev_uid, guild)

    if total >= game.winning_score:
        # Výplata sázky vítězi — všichni soupeři platí (včetně Arion jako +1 slot)
        payout = 0
        if game.sazka > 0 and prev_uid != ARION_ID:
            human_losers = [p for p in game.players if p != prev_uid and p != ARION_ID]
            arion_bonus  = 1 if game.has_arion else 0  # Arion přispívá do poolu jako hráč
            payout       = game.sazka * (len(human_losers) + arion_bonus)
            if payout > 0:
                econ_add(prev_uid, payout)

        # Zaznamenat stats — výhra vítězi, ztráta poraženým
        if prev_uid != ARION_ID:
            record_win(guild.id, prev_uid, profit=payout)
        if game.sazka > 0:
            for loser_uid in game.players:
                if loser_uid != prev_uid and loser_uid != ARION_ID:
                    record_loss(guild.id, loser_uid, sazka=game.sazka)

        emb = win_embed(game, guild, prev_name, total, payout=payout)
        del active_games[guild.id]
        view.stop()
        await interaction.response.defer()
        await interaction.channel.send(embed=emb)

        # Truhly
        if prev_uid != ARION_ID:
            await interaction.channel.send(
                f"🎁 **{prev_name}**, jako vítěz si můžeš vybrat jednu ze tří truhel:",
                view=ChestRewardView(guild.id, prev_uid)
            )
        return

    game.next_player()

    if game.is_arion_turn():
        view.stop()
        await interaction.response.defer()
        emb = waiting_roll_embed(game, guild, extra_msg=f"💰 **{prev_name}** uložil celkem **{total}** bodů.")
        game.game_message = await interaction.channel.send(embed=emb)
        await asyncio.sleep(1)
        await arion_take_turn(game, interaction.channel, guild)
        return

    game.start_roll_phase()
    emb      = waiting_roll_embed(game, guild, extra_msg=f"💰 **{prev_name}** uložil celkem **{total}** bodů.")
    new_view = RollWaitView(game)
    view.stop()
    await interaction.response.defer()
    game.game_message = await interaction.channel.send(embed=emb, view=new_view)

# ── ARION NPC TAH ─────────────────────────────────────────────────────────────

async def arion_take_turn(game: GameState, channel: discord.TextChannel, guild):
    """Arion odehraje celý svůj tah automaticky."""
    await asyncio.sleep(1.5)

    # Arion může použít každý typ magické kostky jednou za hru
    arion_used = game.used_magic_this_game.get(ARION_ID, set())

    while True:
        rolled  = [random.randint(1, 6) for _ in range(game.remaining_dice)]
        comment = random.choice(ARION_ROLL_COMMENTS)
        combos  = find_all_scoring_combos(rolled)
        f       = make_dice_file(rolled)

        # Nejlepší skóre soupeřů pro situační rozhodování
        best_opponent = max(
            (v for uid, v in game.scores.items() if uid != ARION_ID),
            default=0
        )

        if not combos:
            bad_comment     = random.choice(ARION_BAD_ROLL)
            game.turn_score = 0
            game.next_player()
            game.start_roll_phase()

            emb  = farkle_embed(
                game, guild,
                farkle_player_name="Arion",
                extra_msg=f"{comment}\n🎲 Hodila: {dice_to_str(rolled)}\n\n{bad_comment}"
            )
            view = RollWaitView(game)
            if f:
                game.game_message = await channel.send(embed=emb, view=view, file=f)
            else:
                game.game_message = await channel.send(embed=emb, view=view)
            return

        selected, should_bank = arion_decide(
            rolled, game.turn_score, game.remaining_dice,
            game.winning_score, game.scores.get(ARION_ID, 0),
            best_opponent_score=best_opponent
        )

        pts          = game.keep(selected)
        good_comment = random.choice(ARION_GOOD_ROLL)

        # ── Magické kostky Arion ──────────────────────────────────────────────
        magic_msg = ""

        # HOT DICE: použije pokud má málo bodů v tahu a zbývají 3+ kostky
        if (MagicDie.HOT_DICE not in arion_used
                and game.remaining_dice >= 3
                and game.turn_score < 600
                and random.random() < 0.55):
            arion_used.add(MagicDie.HOT_DICE)
            game.used_magic_this_game[ARION_ID] = arion_used
            game.remaining_dice  = 6
            game.collected_rolls = []
            magic_msg = "\n🟦 *Arion přiloží lesklou kostku ke stolu — Hot Dice. Hází znovu.*"

        # X2: použije pokud má solidní tah a bude bankovat
        elif (MagicDie.X2 not in arion_used
                and should_bank
                and game.turn_score >= 600
                and random.random() < 0.65):
            arion_used.add(MagicDie.X2)
            game.used_magic_this_game[ARION_ID] = arion_used
            game.turn_score *= 2
            magic_msg = "\n🟥 *Arion zdvihne rudou kostku a usmívá se — X2. Body zdvojnásobeny.*"

        # ─────────────────────────────────────────────────────────────────────

        if should_bank:
            bank_comment = random.choice(ARION_BANK_COMMENTS)
            total        = game.bank()

            if total >= game.winning_score:
                win_comment = random.choice(ARION_WIN_COMMENTS)
                emb = discord.Embed(
                    title="🏆 Arion vyhrála!",
                    description=(
                        f"*Hodila: {dice_to_str(rolled)}*\n"
                        f"Vybrala: {dice_to_str(selected)} = **+{pts} b**"
                        f"{magic_msg}\n\n"
                        f"{win_comment}"
                    ),
                    color=discord.Color.gold()
                )
                emb.add_field(name="📊 Konečné skóre", value=game.leaderboard(guild, highlight_current=False), inline=False)
                emb.set_footer(text="⭐ Aurionis")
                if game.sazka > 0:
                    for loser_uid in game.players:
                        if loser_uid != ARION_ID:
                            record_loss(guild.id, loser_uid, sazka=game.sazka)
                del active_games[guild.id]
                if f:
                    await channel.send(embed=emb, file=f)
                else:
                    await channel.send(embed=emb)
                return

            game.next_player()
            game.start_roll_phase()

            emb = waiting_roll_embed(
                game, guild,
                extra_msg=(
                    f"{comment}\n🎲 Hodila: {dice_to_str(rolled)}\n"
                    f"Vybrala: {dice_to_str(selected)} = **+{pts} b** | {good_comment}"
                    f"{magic_msg}\n"
                    f"💰 {bank_comment} Arion uložila celkem **{total}** bodů."
                )
            )
            view = RollWaitView(game)
            if f:
                game.game_message = await channel.send(embed=emb, view=view, file=f)
            else:
                game.game_message = await channel.send(embed=emb, view=view)
            return

        # Pokračuje v hodu
        emb = discord.Embed(
            title="🐾 Arion pokračuje...",
            description=(
                f"{comment}\n"
                f"🎲 Hodila: {dice_to_str(rolled)}\n"
                f"Vybrala: {dice_to_str(selected)} = **+{pts} b** | {good_comment}"
                f"{magic_msg}\n\n"
                "*Arion chce více...*"
            ),
            color=0x9b59b6
        )
        emb.add_field(name="💰 Body v tahu",      value=f"**{game.turn_score}**",     inline=True)
        emb.add_field(name="🎲 Zbývající kostky", value=f"**{game.remaining_dice}**", inline=True)
        emb.add_field(name="\u200b",              value="\u200b",                      inline=True)
        emb.add_field(name="📊 Skóre",            value=game.leaderboard(guild),       inline=False)
        emb.set_footer(text=f"⭐ Aurionis  •  Cíl: {game.winning_score} bodů")
        if f:
            await channel.send(embed=emb, file=f)
        else:
            await channel.send(embed=emb)

        await asyncio.sleep(2)

# ── VIEWS ─────────────────────────────────────────────────────────────────────

class LobbyView(discord.ui.View):
    def __init__(self, game: GameState):
        super().__init__(timeout=300)
        self.game = game

    @discord.ui.button(label="✋ Připojit se", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid in self.game.players:
            return await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
        if len(self.game.players) >= MAX_PLAYERS:
            return await interaction.response.send_message("Lobby je plné!", ephemeral=True)

        # Strhnout sázku
        if self.game.sazka > 0:
            if not econ_deduct(uid, self.game.sazka):
                bal = econ_get(uid)
                return await interaction.response.send_message(
                    f"Nemáš dost zlaťáků na sázku! Potřebuješ **{self.game.sazka}**, máš **{bal}** <:goldcoin:1490171741237018795>",
                    ephemeral=True
                )

        self.game.players.append(uid)
        self.game.scores[uid] = 0
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="❌ Opustit", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.game.players:
            return await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
        if uid == self.game.leader_id:
            return await interaction.response.send_message("Leader nemůže opustit lobby.", ephemeral=True)
        self.game.players.remove(uid)
        del self.game.scores[uid]
        # Vrátit sázku při odchodu z lobby
        if self.game.sazka > 0:
            econ_add(uid, self.game.sazka)
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="🐾 Přidat Arion", style=discord.ButtonStyle.danger)
    async def add_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.leader_id:
            return await interaction.response.send_message("Jen leader může přidat Arion.", ephemeral=True)
        if self.game.has_arion:
            return await interaction.response.send_message("Arion už je v lobby!", ephemeral=True)
        self.game.add_arion()
        button.disabled = True
        button.label    = "🐾 Arion přidána"
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="▶️ Spustit hru", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.leader_id:
            return await interaction.response.send_message("Hru může spustit jen leader.", ephemeral=True)
        human_players = [p for p in self.game.players if p != ARION_ID]
        if len(human_players) < 1:
            return await interaction.response.send_message("Potřebuješ alespoň 1 hráče!", ephemeral=True)
        if not self.game.has_arion and len(self.game.players) < 2:
            return await interaction.response.send_message("Potřebuješ alespoň 2 hráče nebo přidej Arion!", ephemeral=True)

        self.game.started = True
        self.stop()

        if self.game.is_arion_turn():
            await interaction.response.defer()
            await arion_take_turn(self.game, interaction.channel, interaction.guild)
        else:
            self.game.start_roll_phase()
            embed = waiting_roll_embed(self.game, interaction.guild)
            view  = RollWaitView(self.game)
            await interaction.response.defer()
            self.game.game_message = await interaction.channel.send(embed=embed, view=view)


class RollWaitView(discord.ui.View):
    def __init__(self, game: GameState):
        super().__init__(timeout=600)
        self.game = game
        self.bank_btn.disabled = game.turn_score < MIN_FIRST_SCORE or game.waiting_for_roll

    @discord.ui.button(label="💰 Uložit body a skončit", style=discord.ButtonStyle.success)
    async def bank_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
        if self.game.waiting_for_roll:
            return await interaction.response.send_message("Nejdřív dohoď všechny kostky!", ephemeral=True)
        await _do_bank(interaction, self.game, self)


class ComboSelectView(discord.ui.View):
    def __init__(self, game: GameState, guild, rolled: list):
        super().__init__(timeout=300)
        self.game   = game
        self.guild  = guild
        self.rolled = rolled
        self._build(rolled)

    def _build(self, rolled: list):
        # 1. Kombinace k výběru (řádek 0 a 1)
        combos = find_all_scoring_combos(rolled)
        for i, (selected, pts) in enumerate(combos[:5]):
            label = f"{dice_to_str(selected)} = {pts}b"
            btn   = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=i // 3)
            btn.callback = self._make_combo_cb(selected, pts)
            self.add_item(btn)

        # 2. Magické kostky z inventáře (řádek 2) — každý typ jen jednou za hru
        uid_used = self.game.used_magic_this_game.get(self.game.current_player, set())
        inv      = get_magic_dice(self.guild.id, self.game.current_player)

        if MagicDie.X2 in inv and MagicDie.X2 not in uid_used:
            x2_btn = discord.ui.Button(label="🟥 X2", style=discord.ButtonStyle.danger, row=2)
            x2_btn.callback = self._use_x2
            self.add_item(x2_btn)

        if MagicDie.HOT_DICE in inv and MagicDie.HOT_DICE not in uid_used:
            hd_btn = discord.ui.Button(label="🟦 +6", style=discord.ButtonStyle.primary, row=2)
            hd_btn.callback = self._use_hd
            self.add_item(hd_btn)

        # 3. Akční tlačítka (řádek 3)
        bank_btn = discord.ui.Button(
            label="💰 Uložit body a skončit",
            style=discord.ButtonStyle.success,
            row=3,
            disabled=self.game.turn_score < MIN_FIRST_SCORE
        )
        bank_btn.callback = self._bank_cb
        self.add_item(bank_btn)

        self._roll_again_btn = discord.ui.Button(
            label=f"🎲 Hodit znovu ({self.game.remaining_dice} kostek)",
            style=discord.ButtonStyle.secondary,
            row=3,
            disabled=True
        )
        self._roll_again_btn.callback = self._roll_again_cb
        self.add_item(self._roll_again_btn)

    def _make_combo_cb(self, selected: list, pts: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.game.current_player:
                return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
            
            self.game.keep(selected)
            
            for item in self.children:
                # Vypnout pouze tlačítka s kombinacemi (obsahují znak "=" a nápis např. "100b")
                if getattr(item, 'label', None) and "=" in item.label:
                    item.disabled = True 
                # Zpřístupnit/znepřístupnit bank podle bodů
                if item.style == discord.ButtonStyle.success:
                    item.disabled = self.game.turn_score < MIN_FIRST_SCORE
                    
            self._roll_again_btn.disabled = False
            self._roll_again_btn.label    = f"🎲 Hodit znovu ({self.game.remaining_dice} kostek)"
            
            emb = combo_embed(self.game, interaction.guild, self.rolled)
            if self.game.remaining_dice == 6:
                emb.set_footer(text="⭐ Aurionis  •  🔥 Hot Dice! Házíš znovu všemi 6!")
            await interaction.response.edit_message(embed=emb, view=self)
        return callback

    async def _use_x2(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)

        remove_magic_die(self.guild.id, self.game.current_player, MagicDie.X2)
        self.game.used_magic_this_game.setdefault(self.game.current_player, set()).add(MagicDie.X2)
        self.game.turn_score *= 2

        for item in self.children:
            if getattr(item, "label", None) == "🟥 X2":
                item.disabled = True

        emb = combo_embed(self.game, self.guild, self.rolled, "🟥 **X2 Kostka použita!** Body v tahu zdvojnásobeny.")
        await interaction.response.edit_message(embed=emb, view=self)

    async def _use_hd(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)

        remove_magic_die(self.guild.id, self.game.current_player, MagicDie.HOT_DICE)
        self.game.used_magic_this_game.setdefault(self.game.current_player, set()).add(MagicDie.HOT_DICE)
        self.game.remaining_dice = 6
        self.game.start_roll_phase()
        self.stop()

        emb = waiting_roll_embed(self.game, self.guild, "🟦 **+6 Kostka použita!** Házíš rovnou znovu všemi 6.")
        new_view = RollWaitView(self.game)
        await interaction.response.edit_message(embed=emb, view=new_view)

    async def _bank_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
        await _do_bank(interaction, self.game, self)

    async def _roll_again_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
        self.game.start_roll_phase()
        embed    = waiting_roll_embed(self.game, interaction.guild)
        new_view = RollWaitView(self.game)
        self.stop()
        await interaction.response.defer()
        self.game.game_message = await interaction.channel.send(embed=embed, view=new_view)


class SafeConfirmView(discord.ui.View):
    """Zobrazí se hráči při Farklu pokud má SAFE kostku."""
    def __init__(self, game: GameState, guild, channel, player_name: str):
        super().__init__(timeout=30)
        self.game        = game
        self.guild       = guild
        self.channel     = channel
        self.player_name = player_name

    @discord.ui.button(label="🟩 Použít SAFE kostku!", style=discord.ButtonStyle.success)
    async def use_safe(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
            
        remove_magic_die(interaction.guild.id, interaction.user.id, MagicDie.SAFE)
        self.game.used_magic_this_game.setdefault(interaction.user.id, set()).add(MagicDie.SAFE)
        self.stop()
        self.game.remaining_dice  = 6
        self.game.collected_rolls = []
        self.game.start_roll_phase() 
        
        embed = waiting_roll_embed(
            self.game, self.guild,
            extra_msg="🟩 **SAFE!** Magická kostka tě zachránila před Farklem! Házíš znovu všemi 6."
        )
        new_view = RollWaitView(self.game)
        await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="❌ Přijmout Farkle", style=discord.ButtonStyle.danger)
    async def decline_safe(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.current_player:
            return await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
        self.stop()
        await self._execute_farkle(interaction)

    async def on_timeout(self):
        """Hráč neodpověděl v čase — automaticky provede Farkle a předá tah."""
        self.game.turn_score = 0
        self.game.next_player()
        self.game.start_roll_phase()

        try:
            emb  = farkle_embed(self.game, self.guild, farkle_player_name=self.player_name)
            view = RollWaitView(self.game)
            if self.game.game_message:
                await self.game.game_message.edit(embed=emb, view=view)
            else:
                self.game.game_message = await self.channel.send(embed=emb, view=view)
        except Exception as e:
            print(f"[kostky] SafeConfirmView timeout chyba: {e}")

    async def _execute_farkle(self, interaction: discord.Interaction):
        self.game.turn_score = 0
        self.game.next_player()

        if self.game.is_arion_turn():
            emb = farkle_embed(self.game, self.guild, farkle_player_name=self.player_name)
            await interaction.response.edit_message(embed=emb, view=None)
            await asyncio.sleep(1)
            await arion_take_turn(self.game, self.channel, self.guild)
            return

        self.game.start_roll_phase()
        emb  = farkle_embed(self.game, self.guild, farkle_player_name=self.player_name)
        view = RollWaitView(self.game)
        await interaction.response.edit_message(embed=emb, view=view)

# ── KOSTKY COG ────────────────────────────────────────────────────────────────

class Kostky(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    kostky_group       = app_commands.Group(name="kostky",       description="Farkle / Kostky minihra")
    admin_kostky_group = app_commands.Group(name="admin-kostky", description="Admin správa magických kostek")

    # ── Listener: zachytí výsledek /roll ─────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not message.author.bot or not message.embeds:
            return

        gid = message.guild.id
        if gid not in active_games:
            return

        game = active_games[gid]
        if not game.started or not game.waiting_for_roll:
            return
        if message.channel.id != game.channel_id:
            return
        if game.is_arion_turn():
            return

        current_member = message.guild.get_member(game.current_player)
        if not current_member:
            return

        desc = message.embeds[0].description or ""
        if current_member.mention not in desc:
            return

        roll_value    = None
        expected_dice = game.remaining_dice
        for field in message.embeds[0].fields:
            if "Rozbor hodu" in (field.name or ""):
                match = re.search(rf'{expected_dice}d6' + r'\(([^)]+)\)', field.value or "")
                if match:
                    rolls = [int(x.strip()) for x in match.group(1).split(',')]
                    if len(rolls) == expected_dice:
                        for r in rolls:
                            game.add_roll_result(r)
                        game.waiting_for_roll = False
                        roll_value = rolls
                break

        if roll_value is None:
            return

        guild  = message.guild
        rolled = game.collected_rolls[:]
        combos = find_all_scoring_combos(rolled)

        if not combos:
            uid          = game.current_player
            farkle_name  = current_member.display_name
            inventory    = get_magic_dice(gid, uid)

            # Nabídni SAFE kostku pokud ji hráč vlastní a ještě ji nepoužil tuto hru
            if MagicDie.SAFE in inventory and MagicDie.SAFE not in game.used_magic_this_game.get(uid, set()):
                emb = discord.Embed(
                    title="💀 FARKLE! — Ale...",
                    description=(
                        f"**{farkle_name}** nemá žádnou bodovanou kombinaci!\n\n"
                        "🟩 Máš **SAFE kostku** — chceš ji použít a zachránit se?"
                    ),
                    color=0xe67e22
                )
                emb.add_field(name="📊 Skóre", value=game.leaderboard(guild), inline=False)
                emb.set_footer(text="⭐ Aurionis  •  Máš 30 sekund na rozhodnutí.")
                safe_view = SafeConfirmView(game, guild, message.channel, player_name=farkle_name)
                game.game_message = await message.channel.send(embed=emb, view=safe_view)
                return

            # Normální Farkle — next_player PŘED embedem
            game.turn_score = 0
            game.next_player()

            if game.is_arion_turn():
                emb = farkle_embed(game, guild, farkle_player_name=farkle_name)
                game.game_message = await message.channel.send(embed=emb)
                await asyncio.sleep(1)
                await arion_take_turn(game, message.channel, guild)
                return

            game.start_roll_phase()
            emb  = farkle_embed(game, guild, farkle_player_name=farkle_name)
            view = RollWaitView(game)
            game.game_message = await message.channel.send(embed=emb, view=view)
            return

        emb  = combo_embed(game, guild, rolled)
        view = ComboSelectView(game, guild, rolled)
        f    = make_dice_file(rolled)

        if f:
            game.game_message = await message.channel.send(embed=emb, view=view, file=f)
        else:
            game.game_message = await message.channel.send(embed=emb, view=view)

    # ── /kostky match ─────────────────────────────────────────────────────────

    @kostky_group.command(name="match", description="Vytvoř nebo se připoj do lobby")
    @app_commands.describe(
        cil="Cílové skóre (výchozí: 5000, min: 500, max: 20000)",
        sazka="Sázka v zlaťácích — vítěz bere vše (výchozí: 0)"
    )
    async def kostky_match(self, interaction: discord.Interaction,
                           cil: int = DEFAULT_WINNING_SCORE,
                           sazka: int = 0):
        gid = interaction.guild_id
        uid = interaction.user.id

        if gid in active_games:
            game = active_games[gid]
            if game.started:
                return await interaction.response.send_message("Na serveru už probíhá hra.", ephemeral=True)
            if uid in game.players:
                return await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            if len(game.players) >= MAX_PLAYERS:
                return await interaction.response.send_message("Lobby je plné!", ephemeral=True)

            # Strhnout sázku pokud hra ji má
            if game.sazka > 0:
                if not econ_deduct(uid, game.sazka):
                    bal = econ_get(uid)
                    return await interaction.response.send_message(
                        f"Nemáš dost zlaťáků na sázku! Potřebuješ **{game.sazka}**, máš **{bal}** <:goldcoin:1490171741237018795>",
                        ephemeral=True
                    )

            game.players.append(uid)
            game.scores[uid] = 0
            if game.game_message:
                try:
                    await game.game_message.edit(embed=lobby_embed(game, interaction.guild))
                except Exception:
                    pass
            sazka_msg = f" Sázka **{game.sazka}** <:goldcoin:1490171741237018795> stržena." if game.sazka > 0 else ""
            return await interaction.response.send_message(
                f"✅ Připojil ses! ({len(game.players)}/{MAX_PLAYERS}){sazka_msg}",
                ephemeral=True
            )

        # Nová hra
        cil   = max(500, min(20000, cil))
        sazka = max(0, sazka)

        # Strhnout sázku leadera
        if sazka > 0:
            if not econ_deduct(uid, sazka):
                bal = econ_get(uid)
                return await interaction.response.send_message(
                    f"Nemáš dost zlaťáků na sázku! Potřebuješ **{sazka}**, máš **{bal}** <:goldcoin:1490171741237018795>",
                    ephemeral=True
                )

        game = GameState(leader_id=uid, channel_id=interaction.channel_id, winning_score=cil, sazka=sazka)
        active_games[gid] = game
        await interaction.response.send_message(embed=lobby_embed(game, interaction.guild), view=LobbyView(game))
        game.game_message = await interaction.original_response()

    # ── /kostky start ─────────────────────────────────────────────────────────

    @kostky_group.command(name="start", description="Leader spustí hru")
    async def kostky_start(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        if gid not in active_games:
            return await interaction.response.send_message("Žádné lobby. Začni přes `/kostky match`.", ephemeral=True)
            
        game = active_games[gid]
        if interaction.user.id != game.leader_id:
            return await interaction.response.send_message("Hru může spustit jen leader.", ephemeral=True)
            
        if game.started:
            return await interaction.response.send_message("Hra už běží!", ephemeral=True)
            
        human_players = [p for p in game.players if p != ARION_ID]
        if len(human_players) < 1 or (not game.has_arion and len(game.players) < 2):
            return await interaction.response.send_message("Potřebuješ alespoň 2 hráče nebo přidej Arion!", ephemeral=True)

        game.started    = True
        game.channel_id = interaction.channel_id

        if game.is_arion_turn():
            await interaction.response.defer()
            await arion_take_turn(game, interaction.channel, interaction.guild)
        else:
            game.start_roll_phase()
            await interaction.response.send_message(
                embed=waiting_roll_embed(game, interaction.guild),
                view=RollWaitView(game)
            )
            game.game_message = await interaction.original_response()

    # ── /kostky cancel ────────────────────────────────────────────────────────

    @kostky_group.command(name="cancel", description="Zruší aktuální hru (jen admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def kostky_cancel(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        if gid not in active_games:
            return await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)

        game = active_games[gid]
        # Vrátit sázky všem hráčům pokud hra ještě nezačala nebo hra běží
        if game.sazka > 0:
            for uid in game.players:
                if uid != ARION_ID:
                    econ_add(uid, game.sazka)

        del active_games[gid]
        await interaction.response.send_message("🗑️ Hra zrušena. Sázky byly vráceny.", ephemeral=True)

    # ── /kostky inv ───────────────────────────────────────────────────────────

    @kostky_group.command(name="inv", description="Zobrazí tvoje magické kostky")
    async def kostky_inv(self, interaction: discord.Interaction):
        inv    = get_magic_dice(interaction.guild_id, interaction.user.id)
        counts = Counter(inv)
        embed  = discord.Embed(title="🎒 Tvoje magické kostky", color=0x9b59b6)

        if not inv:
            embed.description = "Nemáš žádné magické kostky.\n*Vyhraj hru v Kostkách a získej první!*"
        else:
            lines = []
            for die_type, info in MAGIC_DIE_INFO.items():
                if counts[die_type] > 0:
                    lines.append(
                        f"{info['emoji']} **{info['name']}** × {counts[die_type]}\n"
                        f"*{info['desc']}*"
                    )
            embed.description = "\n\n".join(lines)

        embed.set_footer(text="⭐ Aurionis  •  Kostky X2 a +6 (Hot Dice) si volíš při hodu. SAFE tě zachrání při Farklu.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /kostky leaderboard ───────────────────────────────────────────────────

    @kostky_group.command(name="leaderboard", description="Celkové statistiky hráčů — výhry a zisky")
    async def kostky_leaderboard(self, interaction: discord.Interaction):
        gid  = interaction.guild_id
        data = get_all_stats(gid)

        if not data:
            embed = discord.Embed(
                title="🏆 Leaderboard Kostek",
                description="Zatím nikdo nevyhrál žádnou hru na tomto serveru.\n*Buď první!*",
                color=0xFFD700
            )
            embed.set_footer(text="⭐ Aurionis")
            return await interaction.response.send_message(embed=embed)

        # Seřadit primárně podle výher, sekundárně podle profitu
        sorted_players = sorted(
            data.items(),
            key=lambda x: (-x[1].get("wins", 0), -x[1].get("profit", 0))
        )[:10]

        medals = ["🥇", "🥈", "🥉"]
        lines  = []

        for i, (uid_str, stats) in enumerate(sorted_players):
            member = interaction.guild.get_member(int(uid_str))
            name   = member.display_name if member else f"Hráč #{uid_str[-4:]}"
            medal  = medals[i] if i < 3 else f"`{i+1}.`"
            wins   = stats.get("wins",   0)
            profit = stats.get("profit", 0)

            if profit > 0:
                profit_str = f"+{profit} <:goldcoin:1490171741237018795>"
            elif profit < 0:
                profit_str = f"{profit} <:goldcoin:1490171741237018795>"
            else:
                profit_str = "—"

            lines.append(
                f"{medal} **{name}**\n"
                f"┣ 🏆 {wins} {wins_word(wins)}\n"
                f"┗ 📈 Profit: **{profit_str}**"
            )

        embed = discord.Embed(
            title="🏆 Leaderboard Kostek",
            description="\n\n".join(lines),
            color=0xFFD700
        )

        # Ukázat stats volajícího pokud není v top 10
        caller_uid    = str(interaction.user.id)
        caller_in_top = any(uid == caller_uid for uid, _ in sorted_players)
        if not caller_in_top and caller_uid in data:
            cs     = data[caller_uid]
            profit = cs.get("profit", 0)
            profit_fmt = f"+{profit}" if profit > 0 else str(profit) if profit < 0 else "—"
            embed.add_field(
                name="📍 Tvoje stats",
                value=(
                    f"🏆 {cs.get('wins', 0)} {wins_word(cs.get('wins', 0))}  •  "
                    f"📈 Profit: **{profit_fmt}** <:goldcoin:1490171741237018795>"
                ),
                inline=False
            )

        total_wins = sum(s.get("wins", 0) for s in data.values())
        embed.set_footer(text=f"⭐ Aurionis  •  Celkem výher na serveru: {total_wins}")
        await interaction.response.send_message(embed=embed)

    # ── /admin-kostky add ─────────────────────────────────────────────────────

    @admin_kostky_group.command(name="add", description="Přidá hráči magickou kostku")
    @app_commands.describe(uzivatel="Hráč, který kostku dostane", kostka="Typ magické kostky")
    @app_commands.choices(kostka=[
        app_commands.Choice(name="🟥 X2 — zdvojnásobí body z hodu",  value=MagicDie.X2),
        app_commands.Choice(name="🟦 Hot Dice (+6) — hod znovu všemi 6", value=MagicDie.HOT_DICE),
        app_commands.Choice(name="🟩 SAFE — zachrání před Farklem",   value=MagicDie.SAFE),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_add(self, interaction: discord.Interaction, uzivatel: discord.Member, kostka: str):
        add_magic_die(interaction.guild_id, uzivatel.id, kostka)
        info = MAGIC_DIE_INFO[kostka]
        await interaction.response.send_message(
            f"✅ **{uzivatel.display_name}** dostal magickou kostku: {info['emoji']} **{info['name']}**",
            ephemeral=True
        )

    # ── /admin-kostky remove ──────────────────────────────────────────────────

    @admin_kostky_group.command(name="remove", description="Odebere hráči magickou kostku")
    @app_commands.describe(uzivatel="Hráč, kterému se kostka odebere", kostka="Typ magické kostky")
    @app_commands.choices(kostka=[
        app_commands.Choice(name="🟥 X2 — zdvojnásobí body z hodu",  value=MagicDie.X2),
        app_commands.Choice(name="🟦 Hot Dice (+6) — hod znovu všemi 6", value=MagicDie.HOT_DICE),
        app_commands.Choice(name="🟩 SAFE — zachrání před Farklem",   value=MagicDie.SAFE),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def admin_remove(self, interaction: discord.Interaction, uzivatel: discord.Member, kostka: str):
        removed = remove_magic_die(interaction.guild_id, uzivatel.id, kostka)
        info    = MAGIC_DIE_INFO[kostka]
        if removed:
            await interaction.response.send_message(
                f"🗑️ **{uzivatel.display_name}** přišel o magickou kostku: {info['emoji']} **{info['name']}**",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"**{uzivatel.display_name}** žádnou kostku **{info['name']}** nemá.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Kostky(bot))