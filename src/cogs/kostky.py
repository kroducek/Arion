"""
Kostky (Farkle) minihra pro ArionBot
- Hráči házejí pomocí /roll XdY (kompatibilní s roll.py)
- Nastavitelný cíl skóre
- Arion NPC boss mode
- Sázky kompatibilní s gold systemem (economy.json)
"""

import discord
import re
import random
import asyncio
import json
import os
from discord.ext import commands
from discord import app_commands
from itertools import combinations
from collections import Counter

try:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from utils.dice_image import build_dice_image
    DICE_IMAGES_ENABLED = True
except Exception:
    DICE_IMAGES_ENABLED = False

# ── KONFIGURACE ───────────────────────────────────────────────────────────────

DEFAULT_WINNING_SCORE = 5000
MIN_FIRST_SCORE       = 350
MAX_PLAYERS           = 6
ARION_ID              = -1
ECONOMY_PATH          = "economy.json"
KOSTKY_LB_PATH        = "kostky_leaderboard.json"
DICE_EMOJI            = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

# ── ARION KOMENTÁŘE ───────────────────────────────────────────────────────────

ARION_ROLL_COMMENTS = [
    "*Arion hodí kostkami s elegancí zkušené hráčky...*",
    "*Arion přimhouří oči a hodí.*",
    "*'Mňau.' — Arion hodí bez jakékoliv námahy.*",
    "*Arion si olízne tlapku a elegantně hodí.*",
    "*'Tohle bude zajímavé...' zamumlá Arion a hodí.*",
    "*Arion si protáhne záda a bez váhání hodí.*",
    "*Arion poklepe tlapkou o stůl a hodí.*",
    "*'Pozorujte mistra.' — Arion hodí s úsměvem.*",
    "*Arion přejede pohledem po kostkách a hodí.*",
    "*Arion hodí s takovým klidem, jako by to ani nebylo důležité.*",
]

ARION_GOOD_ROLL = [
    "*'Přesně jak jsem čekala.' — Arion se usmívá.*",
    "*Arion spokojeně přede.*",
    "*'Ani jsem se nemusela snažit.' — říká Arion klidně.*",
    "*Arion mrká spokojeně na kostky.*",
    "*'Hezký hod.' — Arion přikývne sama sobě.*",
    "*Arion si tiše zapíská a nakloní hlavu.*",
    "*'To by nikoho nepřekvapilo.' — odtuší Arion.*",
    "*Arion jemně odfrkne a spokojeně sleduje výsledek.*",
    "*'Klasika.' — řekne Arion jednoduše.*",
    "*Arion si pohladí fousky. Jde to samo.*",
]

ARION_BAD_ROLL = [
    "*'Hm. Tohle se nestává často.' — Arion vypadá překvapeně.*",
    "*Arion zamračeně zírá na kostky.*",
    "*'Nevadí. Příště.' — Arion si hladí fousky.*",
    "*Arion zvedne obočí. Neočekávané.*",
    "*'Zajímavé...' — mumlá Arion a odloží kostky.*",
    "*Arion chvíli mlčí a dívá se na výsledek.*",
    "*'Každému se to stane.' — říká Arion, ale vypadá podrážděně.*",
    "*Arion si odkašle a tváří se, jako by se nic nestalo.*",
]

ARION_BANK_COMMENTS = [
    "*Arion si zapíše body zlatým perem.*",
    "*'Prozatím stačí.' — Arion odloží kostky.*",
    "*Arion přikývne a spokojeně uloží svůj zisk.*",
    "*'Bezpečně uloženo.' — Arion si sepne tlapky.*",
    "*Arion elegantně posune body na svou stranu stolu.*",
    "*'Na víc nemám náladu.' — Arion se odvalí od stolu.*",
    "*Arion si tiše poznačí číslo a usmívá se.*",
]

ARION_FARKLE_COMMENTS = [
    "*'Tenhle hod se vůbec nepočítá.' — Arion mávne tlapkou.*",
    "*Arion zamračeně odstrčí kostky.*",
    "*'To se stává.' — říká Arion suše.*",
    "*Arion si odkašle. Tohle nečekala.*",
    "*'Jednou za čas.' — Arion pokrčí rameny.*",
    "*Arion zvedne obočí a pomalu odtlačí kostky.*",
]

ARION_CONTINUE_COMMENTS = [
    "*Arion chce více...*",
    "*'Ještě není konec.' — Arion sahá po kostkách.*",
    "*Arion se usmívá. Tohle nestačí.*",
    "*'Pojďme dál.' — Arion přikývne.*",
    "*Arion si protáhne prsty. Pokračuje.*",
    "*'Pár bodů navíc neuškodí.' — říká Arion.*",
]

# ── GOLD SYSTEM ───────────────────────────────────────────────────────────────

def load_economy() -> dict:
    if not os.path.exists(ECONOMY_PATH):
        return {}
    try:
        with open(ECONOMY_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}

def save_economy(data: dict):
    with open(ECONOMY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def get_balance(uid: int) -> int:
    data = load_economy()
    return data.get(str(uid), 0)

def transfer_gold(from_uid: int, to_uid: int, amount: int) -> bool:
    """Převede gold od from_uid k to_uid. Vrátí False pokud nemá dost."""
    data = load_economy()
    fid  = str(from_uid)
    tid  = str(to_uid)
    if data.get(fid, 0) < amount:
        return False
    data[fid] = data.get(fid, 0) - amount
    data[tid] = data.get(tid, 0) + amount
    save_economy(data)
    return True

def add_gold(uid: int, amount: int):
    data = load_economy()
    sid  = str(uid)
    data[sid] = data.get(sid, 0) + amount
    save_economy(data)

def deduct_gold(uid: int, amount: int) -> bool:
    """Odečte gold. Vrátí False pokud nemá dost."""
    data = load_economy()
    sid  = str(uid)
    if data.get(sid, 0) < amount:
        return False
    data[sid] -= amount
    save_economy(data)
    return True

# ── POMOCNÉ FUNKCE ────────────────────────────────────────────────────────────

# ── KOSTKY LEADERBOARD ───────────────────────────────────────────────────────

def load_lb() -> dict:
    if not os.path.exists(KOSTKY_LB_PATH):
        return {}
    try:
        with open(KOSTKY_LB_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception:
        return {}

def save_lb(data: dict):
    with open(KOSTKY_LB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def record_win(uid: int):
    """Zaznamená výhru hráče nebo Arion (uid == ARION_ID)."""
    data = load_lb()
    key  = "arion" if uid == ARION_ID else str(uid)
    data[key] = data.get(key, 0) + 1
    save_lb(data)


def make_dice_file(dice: list):
    if not DICE_IMAGES_ENABLED or not dice:
        return None
    try:
        buf = build_dice_image(dice)
        return discord.File(buf, filename="dice.png")
    except Exception as e:
        print(f"[kostky] dice image chyba: {e}")
        return None

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
            if face == 1:
                total += count * 100
            elif face == 5:
                total += count * 50
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
    if n == 6 and sorted_dice == [1,2,3,4,5,6]:
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

def dice_to_str(dice: list) -> str:
    return "  ".join(DICE_EMOJI[d] for d in dice)

# ── ARION AI ──────────────────────────────────────────────────────────────────

def arion_decide(rolled: list, turn_score: int, remaining_dice: int, winning_score: int, arion_total: int) -> tuple:
    combos = find_all_scoring_combos(rolled)
    if not combos:
        return None, False
    best_combo, best_pts = combos[0]
    new_turn      = turn_score + best_pts
    new_remaining = remaining_dice - len(best_combo)
    if new_remaining == 0:
        new_remaining = 6
    close_to_win = (arion_total + new_turn) >= winning_score * 0.8
    risky_dice   = new_remaining <= 2
    has_enough   = new_turn >= MIN_FIRST_SCORE
    if close_to_win and has_enough:
        return best_combo, True
    if risky_dice and new_turn >= 600:
        return best_combo, True
    if has_enough and random.random() < 0.25:
        return best_combo, True
    return best_combo, False

# ── HERNÍ STAV ────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self, leader_id: int, channel_id: int, winning_score: int = DEFAULT_WINNING_SCORE, bet: int = 0):
        self.leader_id     = leader_id
        self.channel_id    = channel_id
        self.winning_score = winning_score
        self.bet           = bet        # sázka na hráče (0 = žádná)
        self.pot           = 0          # celkový bank sázek
        self.bets_paid     = set()      # kteří hráči už zaplatili sázku
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

    @property
    def current_player(self):
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

    def player_name(self, uid, guild) -> str:
        if uid == ARION_ID:
            return "🐾 Arion"
        m = guild.get_member(uid)
        return m.display_name if m else str(uid)

    def leaderboard(self, guild) -> str:
        lines = []
        for uid, pts in sorted(self.scores.items(), key=lambda x: -x[1]):
            name   = self.player_name(uid, guild)
            marker = " 👑" if pts >= self.winning_score else ""
            lines.append(f"**{name}**: {pts} bodů{marker}")
        return "\n".join(lines) if lines else "—"

    def bet_line(self) -> str:
        if self.bet == 0:
            return ""
        return f"💰 **Sázka:** {self.bet} <:goldcoin:1477303464781680772> na hráče | Bank: **{self.pot}** <:goldcoin:1477303464781680772>"

# ── AKTIVNÍ HRY ───────────────────────────────────────────────────────────────

active_games = {}

# ── POMOCNÉ EMBEDY ────────────────────────────────────────────────────────────

def lobby_embed(game, guild):
    arion_line = "\n• 🐾 **Arion** *(NPC Boss)*" if game.has_arion else ""
    bet_desc   = f"\n💰 **Sázka:** {game.bet} <:goldcoin:1477303464781680772> na hráče" if game.bet > 0 else ""
    embed = discord.Embed(
        title="🎲 Kostky (Farkle) — Lobby",
        description=(
            f"*Arion rozkládá kostky na stůl a přimhouří oči...*\n\n"
            f"**Cíl:** {game.winning_score} bodů{bet_desc}\n"
            f"**Zápis od:** {MIN_FIRST_SCORE} bodů\n"
        ),
        color=0xFFA500
    )
    names = []
    for uid in game.players:
        if uid == ARION_ID:
            continue
        m     = guild.get_member(uid)
        crown = " 👑" if uid == game.leader_id else ""
        paid  = " ✅" if uid in game.bets_paid else (" 💰 *nezaplatil*" if game.bet > 0 else "")
        names.append(f"• {m.display_name if m else uid}{crown}{paid}")
    player_list = "\n".join(names) + arion_line
    embed.add_field(name=f"Hráči ({len(game.players)}/{MAX_PLAYERS})", value=player_list or "—", inline=False)
    embed.set_footer(text="Leader může spustit hru tlačítkem ▶️ | Všichni musí zaplatit sázku před startem")
    return embed


def waiting_roll_embed(game, guild, extra_msg=""):
    name = game.player_name(game.current_player, guild)
    need = game.remaining_dice
    if game.is_arion_turn():
        desc = (f"{extra_msg}\n\n" if extra_msg else "") + f"🐾 **Arion** hází {need} {'kostku' if need == 1 else 'kostek'}..."
    else:
        desc = (f"{extra_msg}\n\n" if extra_msg else "") + (
            f"🎲 **{name}** je na tahu!\n\n"
            f"Hoď `/roll {need}d6`"
        )
    embed = discord.Embed(title="🎲 Kostky", description=desc, color=0xFFA500)
    embed.add_field(name="Body v tahu", value=f"**{game.turn_score}**", inline=True)
    embed.add_field(name="Zbývající kostky", value=f"**{need}**", inline=True)
    embed.add_field(name="Skóre", value=game.leaderboard(guild), inline=False)
    if game.bet > 0:
        embed.add_field(name="💰 Bank", value=f"**{game.pot}** <:goldcoin:1477303464781680772>", inline=True)
    embed.set_footer(text=f"Cíl: {game.winning_score} bodů | Zápis od {MIN_FIRST_SCORE} bodů")
    return embed


def combo_embed(game, guild, rolled, arion_comment=""):
    combos = find_all_scoring_combos(rolled)
    embed  = discord.Embed(title="🎲 Kostky", color=0x3498db)
    if arion_comment:
        embed.description = arion_comment
    if combos:
        combo_text = "\n".join(
            f"• {'  '.join(DICE_EMOJI[d] for d in s)} = **{p}b**"
            for s, p in combos[:5]
        )
        embed.add_field(name="Dostupné kombinace", value=combo_text, inline=False)
    else:
        embed.add_field(name="💀 FARKLE!", value="Žádná bodovaná kombinace!", inline=False)
        embed.color = discord.Color.red()
    embed.add_field(name="Body v tahu", value=f"**{game.turn_score}**", inline=True)
    embed.add_field(name="Zbývající kostky", value=f"**{game.remaining_dice}**", inline=True)
    embed.add_field(name="Skóre", value=game.leaderboard(guild), inline=False)
    if game.bet > 0:
        embed.add_field(name="💰 Bank", value=f"**{game.pot}** <:goldcoin:1477303464781680772>", inline=True)
    embed.set_footer(text=f"Cíl: {game.winning_score} bodů")
    return embed

# ── ARION NPC TAH ─────────────────────────────────────────────────────────────

async def arion_take_turn(game: GameState, channel: discord.TextChannel, guild):
    """Arion odehraje celý svůj tah automaticky."""
    await asyncio.sleep(2.0)

    while True:
        rolled  = [random.randint(1, 6) for _ in range(game.remaining_dice)]
        comment = random.choice(ARION_ROLL_COMMENTS)
        combos  = find_all_scoring_combos(rolled)
        f       = make_dice_file(rolled)

        if not combos:
            farkle_comment = random.choice(ARION_FARKLE_COMMENTS)
            game.turn_score = 0
            game.next_player()
            game.start_roll_phase()

            emb = waiting_roll_embed(
                game, guild,
                extra_msg=(
                    f"{comment}\n"
                    f"🎲 Arion hodila: {dice_to_str(rolled)}\n\n"
                    f"💀 **FARKLE!** {farkle_comment}"
                )
            )
            view = RollWaitView(game)
            if f:
                game.game_message = await channel.send(embed=emb, view=view)
                await channel.send(file=f)
            else:
                game.game_message = await channel.send(embed=emb, view=view)
            return

        selected, should_bank = arion_decide(
            rolled, game.turn_score, game.remaining_dice,
            game.winning_score, game.scores.get(ARION_ID, 0)
        )
        pts          = game.keep(selected)
        good_comment = random.choice(ARION_GOOD_ROLL)

        if should_bank:
            bank_comment = random.choice(ARION_BANK_COMMENTS)
            total        = game.bank()

            if total >= game.winning_score:
                # Arion vyhrála — speciální finální hlášky (nezměněno)
                win_comments = [
                    "🐾 *Arion vítězně zamává ocasem.*\n'Říkala jsem, že budete potřebovat štěstí. Příště přijďte připravenější.'",
                    "🐾 *Arion sklapne knihu.*\n'Porazit mě? Milá myšlenka. Ale ne dnes.'",
                ]
                win_comment = random.choice(win_comments)
                pot_line    = f"\n\n💰 Bank **{game.pot}** <:goldcoin:1477303464781680772> propadá do éteru." if game.bet > 0 else ""
                emb = discord.Embed(
                    title="🏆 Arion vyhrála!",
                    description=(
                        f"{comment}\n"
                        f"🎲 Arion hodila: {dice_to_str(rolled)}\n"
                        f"Vybrala: {dice_to_str(selected)} = **+{pts}b** | {good_comment}\n"
                        f"💰 {bank_comment}\n\n"
                        f"{win_comment}{pot_line}"
                    ),
                    color=discord.Color.gold()
                )
                emb.add_field(name="Konečné skóre", value=game.leaderboard(guild), inline=False)
                record_win(ARION_ID)
                del active_games[guild.id]
                await channel.send(embed=emb)
                if f:
                    await channel.send(file=f)
                return

            game.next_player()
            game.start_roll_phase()
            emb = waiting_roll_embed(
                game, guild,
                extra_msg=(
                    f"{comment}\n"
                    f"🎲 Arion hodila: {dice_to_str(rolled)}\n"
                    f"Vybrala: {dice_to_str(selected)} = **+{pts}b** | {good_comment}\n"
                    f"💰 {bank_comment} Arion uložila celkem **{total}** bodů."
                )
            )
            view = RollWaitView(game)
            game.game_message = await channel.send(embed=emb, view=view)
            if f:
                await channel.send(file=f)
            return

        # Pokračuje
        cont_comment = random.choice(ARION_CONTINUE_COMMENTS)
        emb = discord.Embed(
            title="🎲 Kostky",
            description=(
                f"{comment}\n"
                f"🎲 Arion hodila: {dice_to_str(rolled)}\n"
                f"Vybrala: {dice_to_str(selected)} = **+{pts}b** | {good_comment}\n\n"
                f"{cont_comment}"
            ),
            color=0x9b59b6
        )
        emb.add_field(name="Body v tahu", value=f"**{game.turn_score}**", inline=True)
        emb.add_field(name="Zbývající kostky", value=f"**{game.remaining_dice}**", inline=True)
        emb.add_field(name="Skóre", value=game.leaderboard(guild), inline=False)
        if game.bet > 0:
            emb.add_field(name="💰 Bank", value=f"**{game.pot}** <:goldcoin:1477303464781680772>", inline=True)
        emb.set_footer(text=f"Cíl: {game.winning_score} bodů")
        await channel.send(embed=emb)
        if f:
            await channel.send(file=f)

        await asyncio.sleep(2.5)

# ── VIEWS ─────────────────────────────────────────────────────────────────────

class LobbyView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=300)
        self.game = game

    @discord.ui.button(label="Připojit se ✋", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid in self.game.players:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        if len(self.game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("Lobby je plné!", ephemeral=True)
            return
        self.game.players.append(uid)
        self.game.scores[uid] = 0
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="Opustit ❌", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.game.players:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return
        if uid == self.game.leader_id:
            await interaction.response.send_message("Leader nemůže opustit lobby.", ephemeral=True)
            return
        # Vrať sázku pokud zaplatil
        if self.game.bet > 0 and uid in self.game.bets_paid:
            add_gold(uid, self.game.bet)
            self.game.pot -= self.game.bet
            self.game.bets_paid.discard(uid)
        self.game.players.remove(uid)
        del self.game.scores[uid]
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="💰 Zaplatit sázku", style=discord.ButtonStyle.primary)
    async def pay_bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.game.players:
            await interaction.response.send_message("Nejsi v lobby!", ephemeral=True)
            return
        if self.game.bet == 0:
            await interaction.response.send_message("Tato hra nemá sázku.", ephemeral=True)
            return
        if uid in self.game.bets_paid:
            await interaction.response.send_message("Sázku jsi už zaplatil!", ephemeral=True)
            return
        if not deduct_gold(uid, self.game.bet):
            bal = get_balance(uid)
            await interaction.response.send_message(
                f"Nemáš dost zlaťáků! Potřebuješ **{self.game.bet}**, máš **{bal}** <:goldcoin:1477303464781680772>",
                ephemeral=True
            )
            return
        self.game.bets_paid.add(uid)
        self.game.pot += self.game.bet
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="🐾 Přidat Arion", style=discord.ButtonStyle.danger)
    async def add_arion(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.leader_id:
            await interaction.response.send_message("Jen leader může přidat Arion.", ephemeral=True)
            return
        if self.game.has_arion:
            await interaction.response.send_message("Arion už je v lobby!", ephemeral=True)
            return
        self.game.add_arion()
        button.disabled = True
        button.label    = "🐾 Arion přidána"
        await interaction.response.edit_message(embed=lobby_embed(self.game, interaction.guild), view=self)

    @discord.ui.button(label="▶️ Spustit hru", style=discord.ButtonStyle.primary, row=1)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.leader_id:
            await interaction.response.send_message("Hru může spustit jen leader.", ephemeral=True)
            return
        human_players = [p for p in self.game.players if p != ARION_ID]
        if not self.game.has_arion and len(self.game.players) < 2:
            await interaction.response.send_message("Potřebuješ alespoň 2 hráče nebo přidej Arion!", ephemeral=True)
            return
        # Zkontroluj sázky — všichni musí zaplatit
        if self.game.bet > 0:
            unpaid = [uid for uid in human_players if uid not in self.game.bets_paid]
            if unpaid:
                names = ", ".join(
                    (interaction.guild.get_member(uid).display_name if interaction.guild.get_member(uid) else str(uid))
                    for uid in unpaid
                )
                await interaction.response.send_message(
                    f"Ještě nezaplatili sázku: **{names}**", ephemeral=True
                )
                return

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
    def __init__(self, game):
        super().__init__(timeout=600)
        self.game = game
        self.bank_btn.disabled = game.turn_score < MIN_FIRST_SCORE or game.waiting_for_roll

    @discord.ui.button(label="💰 Uložit body a skončit", style=discord.ButtonStyle.success)
    async def bank_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.current_player:
            await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
            return
        if self.game.waiting_for_roll:
            await interaction.response.send_message("Nejdřív dohoď všechny kostky!", ephemeral=True)
            return
        await _do_bank(interaction, self.game, self)


class ComboSelectView(discord.ui.View):
    def __init__(self, game, guild, rolled):
        super().__init__(timeout=300)
        self.game   = game
        self.guild  = guild
        self.rolled = rolled
        self._build(rolled)

    def _build(self, rolled):
        combos = find_all_scoring_combos(rolled)
        for i, (selected, pts) in enumerate(combos[:5]):
            label = f"{dice_to_str(selected)} = {pts}b"
            btn   = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, row=i // 3)
            btn.callback = self._make_combo_cb(selected, pts)
            self.add_item(btn)
        bank_btn = discord.ui.Button(
            label="💰 Uložit body a skončit",
            style=discord.ButtonStyle.success,
            row=2,
            disabled=self.game.turn_score < MIN_FIRST_SCORE
        )
        bank_btn.callback = self._bank_cb
        self.add_item(bank_btn)
        self._roll_again_btn = discord.ui.Button(
            label=f"🎲 Hodit znovu ({self.game.remaining_dice} kostek)",
            style=discord.ButtonStyle.secondary,
            row=2,
            disabled=True
        )
        self._roll_again_btn.callback = self._roll_again_cb
        self.add_item(self._roll_again_btn)

    def _make_combo_cb(self, selected, pts):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.game.current_player:
                await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
                return
            self.game.keep(selected)
            for item in self.children:
                if item.style == discord.ButtonStyle.primary:
                    item.disabled = True
            self._roll_again_btn.disabled = False
            self._roll_again_btn.label    = f"🎲 Hodit znovu ({self.game.remaining_dice} kostek)"
            for item in self.children:
                if item.style == discord.ButtonStyle.success:
                    item.disabled = self.game.turn_score < MIN_FIRST_SCORE
            hot = self.game.remaining_dice == 6
            emb = combo_embed(self.game, interaction.guild, self.rolled)
            if hot:
                emb.set_footer(text="🔥 Hot Dice! Házíš znovu všemi 6!")
            await interaction.response.edit_message(embed=emb, view=self)
        return callback

    async def _bank_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.current_player:
            await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
            return
        await _do_bank(interaction, self.game, self)

    async def _roll_again_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.game.current_player:
            await interaction.response.send_message("Teď nehraješ ty!", ephemeral=True)
            return
        self.game.start_roll_phase()
        embed    = waiting_roll_embed(self.game, interaction.guild)
        new_view = RollWaitView(self.game)
        self.stop()
        await interaction.response.defer()
        self.game.game_message = await interaction.channel.send(embed=embed, view=new_view)

# ── SDÍLENÁ LOGIKA BANK ───────────────────────────────────────────────────────

async def _do_bank(interaction, game, view):
    total = game.bank()
    guild = interaction.guild

    if total >= game.winning_score:
        winner_uid  = game.current_player
        winner      = guild.get_member(winner_uid)
        win_name    = winner.display_name if winner else "Neznámý"

        # Vyplať pot vítězi (jen lidé, ne Arion)
        pot_line = ""
        if game.bet > 0 and game.pot > 0 and winner_uid != ARION_ID:
            add_gold(winner_uid, game.pot)
            pot_line = f"\n💰 **{win_name}** získal celý bank: **{game.pot}** <:goldcoin:1477303464781680772>!"

        lose_comment = ""
        if game.has_arion:
            lose_comments = [
                "😾 *Arion překvapeně zírá na skóre.*\n'Neuvěřitelné... Zasloužená výhra. Tentokrát.'",
                "😾 *Arion pomalu přikývne.*\n'Dobře hráno. Ale příště budu připravenější.'",
            ]
            lose_comment = "\n\n" + random.choice(lose_comments)

        embed = discord.Embed(
            title="🏆 VÍTĚZ!",
            description=(
                f"**{win_name}** dosáhl **{total}** bodů a vyhrál!"
                f"{pot_line}"
                f"{lose_comment}\n\n"
                f"*Arion tleská tlapkami a zapisuje jméno zlatým inkoustem...*"
            ),
            color=discord.Color.gold()
        )
        embed.add_field(name="Konečné skóre", value=game.leaderboard(guild), inline=False)
        record_win(winner_uid)
        del active_games[guild.id]
        view.stop()
        await interaction.response.defer()
        await interaction.channel.send(embed=embed)
        return

    prev_name = game.player_name(game.current_player, guild)
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
    embed    = waiting_roll_embed(game, guild, extra_msg=f"💰 **{prev_name}** uložil celkem **{total}** bodů.")
    new_view = RollWaitView(game)
    view.stop()
    await interaction.response.defer()
    game.game_message = await interaction.channel.send(embed=embed, view=new_view)

# ── KOSTKY COG ────────────────────────────────────────────────────────────────

class Kostky(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    kostky_group = app_commands.Group(name="kostky", description="Farkle / Kostky minihra")

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
            farkle_name = current_member.display_name
            game.turn_score = 0
            game.next_player()
            if game.is_arion_turn():
                emb = waiting_roll_embed(game, guild, extra_msg=f"💀 **FARKLE!** {farkle_name} ztratil všechny body!")
                game.game_message = await message.channel.send(embed=emb)
                await asyncio.sleep(1)
                await arion_take_turn(game, message.channel, guild)
                return
            game.start_roll_phase()
            emb  = waiting_roll_embed(game, guild, extra_msg=f"💀 **FARKLE!** {farkle_name} ztratil všechny body!")
            view = RollWaitView(game)
            game.game_message = await message.channel.send(embed=emb, view=view)
            return

        emb  = combo_embed(game, guild, rolled)
        view = ComboSelectView(game, guild, rolled)
        f    = make_dice_file(rolled)
        if f:
            game.game_message = await message.channel.send(embed=emb, view=view)
            await message.channel.send(file=f)
        else:
            game.game_message = await message.channel.send(embed=emb, view=view)

    # ── /kostky match ─────────────────────────────────────────────────────────

    @kostky_group.command(name="match", description="Vytvoř nebo se připoj do lobby")
    @app_commands.describe(
        cil="Cílové skóre (výchozí: 5000, min: 500, max: 20000)",
        sazka="Sázka v zlaťácích na hráče — vítěz bere vše (výchozí: 0)"
    )
    async def kostky_match(self, interaction: discord.Interaction, cil: int = DEFAULT_WINNING_SCORE, sazka: int = 0):
        gid = interaction.guild_id
        uid = interaction.user.id

        if gid in active_games:
            game = active_games[gid]
            if game.started:
                await interaction.response.send_message("Na serveru už probíhá hra.", ephemeral=True)
                return
            if uid in game.players:
                await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
                return
            if len(game.players) >= MAX_PLAYERS:
                await interaction.response.send_message("Lobby je plné!", ephemeral=True)
                return
            game.players.append(uid)
            game.scores[uid] = 0
            if game.game_message:
                try:
                    await game.game_message.edit(embed=lobby_embed(game, interaction.guild))
                except Exception:
                    pass
            await interaction.response.send_message(f"✅ Připojil ses! ({len(game.players)}/{MAX_PLAYERS})", ephemeral=True)
            return

        cil   = max(500, min(20000, cil))
        sazka = max(0, sazka)

        # Zakladatel zaplatí sázku hned
        if sazka > 0:
            if not deduct_gold(uid, sazka):
                bal = get_balance(uid)
                await interaction.response.send_message(
                    f"Nemáš dost zlaťáků na sázku! Potřebuješ **{sazka}**, máš **{bal}** <:goldcoin:1477303464781680772>",
                    ephemeral=True
                )
                return

        game = GameState(leader_id=uid, channel_id=interaction.channel_id, winning_score=cil, bet=sazka)
        if sazka > 0:
            game.bets_paid.add(uid)
            game.pot = sazka

        active_games[gid] = game
        await interaction.response.send_message(embed=lobby_embed(game, interaction.guild), view=LobbyView(game))
        game.game_message = await interaction.original_response()

    # ── /kostky start ─────────────────────────────────────────────────────────

    @kostky_group.command(name="start", description="Leader spustí hru")
    async def kostky_start(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        if gid not in active_games:
            await interaction.response.send_message("Žádné lobby. Začni přes `/kostky match`.", ephemeral=True)
            return
        game = active_games[gid]
        if interaction.user.id != game.leader_id:
            await interaction.response.send_message("Hru může spustit jen leader.", ephemeral=True)
            return
        if game.started:
            await interaction.response.send_message("Hra už běží!", ephemeral=True)
            return
        human_players = [p for p in game.players if p != ARION_ID]
        if not game.has_arion and len(game.players) < 2:
            await interaction.response.send_message("Potřebuješ alespoň 2 hráče nebo přidej Arion!", ephemeral=True)
            return
        if game.bet > 0:
            unpaid = [uid for uid in human_players if uid not in game.bets_paid]
            if unpaid:
                names = ", ".join(
                    (interaction.guild.get_member(uid).display_name if interaction.guild.get_member(uid) else str(uid))
                    for uid in unpaid
                )
                await interaction.response.send_message(f"Ještě nezaplatili sázku: **{names}**", ephemeral=True)
                return

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

    @kostky_group.command(name="cancel", description="Zruší aktuální hru a vrátí sázky (jen admin)")
    @app_commands.checks.has_permissions(administrator=True)
    async def kostky_cancel(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        if gid not in active_games:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return
        game = active_games[gid]
        # Vrať sázky všem kdo zaplatili
        if game.bet > 0:
            for uid in game.bets_paid:
                add_gold(uid, game.bet)
        del active_games[gid]
        refund_line = f" Sázky byly vráceny." if game.bet > 0 else ""
        await interaction.response.send_message(f"🗑️ Hra zrušena.{refund_line}", ephemeral=True)

    # ── /kostky score ─────────────────────────────────────────────────────────

    @kostky_group.command(name="score", description="Zobrazí aktuální skóre")
    async def kostky_score(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        if gid not in active_games:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return
        game  = active_games[gid]
        embed = discord.Embed(title="🏆 Aktuální skóre", color=0xFFD700)
        embed.add_field(name="Skóre", value=game.leaderboard(interaction.guild), inline=False)
        if game.bet > 0:
            embed.add_field(name="💰 Bank", value=f"**{game.pot}** <:goldcoin:1477303464781680772>", inline=True)
        embed.set_footer(text=f"Cíl: {game.winning_score} bodů")
        await interaction.response.send_message(embed=embed, ephemeral=True)


    # ── /kostky leaderboard ──────────────────────────────────────────────────

    @kostky_group.command(name="leaderboard", description="Žebříček vítězů Kostek")
    async def kostky_leaderboard(self, interaction: discord.Interaction):
        data = load_lb()
        if not data:
            await interaction.response.send_message("Zatím nikdo nevyhrál ani jednu hru!", ephemeral=True)
            return

        sorted_entries = sorted(data.items(), key=lambda x: -x[1])
        medals = ["🥇", "🥈", "🥉"]
        lines  = []

        for i, (key, wins) in enumerate(sorted_entries):
            prefix = medals[i] if i < 3 else f"**{i+1}.**"
            if key == "arion":
                name = "🐾 Arion *(NPC Boss)*"
            else:
                try:
                    member = interaction.guild.get_member(int(key))
                    name   = member.display_name if member else f"Neznámý ({key})"
                except Exception:
                    name = f"Neznámý ({key})"
            win_word = "výhra" if wins == 1 else ("výhry" if 2 <= wins <= 4 else "výher")
            lines.append(f"{prefix} {name} — **{wins}** {win_word}")

        embed = discord.Embed(
            title="🎲 Kostky — Žebříček vítězů",
            description="\n".join(lines),
            color=0xFFA500
        )

        # Pozice volajícího hráče
        caller_key  = str(interaction.user.id)
        caller_rank = next((i+1 for i, (k, _) in enumerate(sorted_entries) if k == caller_key), None)
        caller_wins = data.get(caller_key, 0)
        if caller_rank:
            win_word = "výhra" if caller_wins == 1 else ("výhry" if 2 <= caller_wins <= 4 else "výher")
            embed.set_footer(text=f"Tvoje pozice: #{caller_rank} ({caller_wins} {win_word})")
        else:
            embed.set_footer(text="Zatím nemáš žádnou výhru. Tak do toho!")

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Kostky(bot))