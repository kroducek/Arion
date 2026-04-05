"""
Liar Slots – bluffovací slot-machine hra pro ArionBot
=====================================================
Příkazy:
  /liar_slots        – spustí lobby (volitelná sázka v goldech)
  /slots_leaderboard – žebříček výher
  /slots_cancel      – [Admin] zruší probíhající hru
"""

import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

from src.utils.paths import LIAR_SLOTS_SCORES as SCORES_FILE, ECONOMY as ECONOMY_FILE
from src.utils.json_utils import load_json, save_json

# ── Konstanty ─────────────────────────────────────────────────────────────────

MIN_PLAYERS       = 2
MAX_PLAYERS       = 8
EXECUTE_THRESHOLD = 5
RESPONSE_TIMEOUT  = 30   # sekund na reakci ostatních

HEART      = "❤️"
NON_HEARTS = ["💀", "⭐", "💎", "🌙"]
HEART_CHANCE       = 0.30
DEATH_HEART_CHANCE = 0.40

CLAIM_POINTS: dict = {1: 1, 2: 2, 3: 3, "jackpot": 5}

COIN = "<:goldcoin:1490171741237018795>"

# ── Data helpers ──────────────────────────────────────────────────────────────

def _load_eco() -> dict:   return load_json(ECONOMY_FILE, {})
def _save_eco(data: dict): save_json(ECONOMY_FILE, data)

# ── Herní helpers ─────────────────────────────────────────────────────────────

def _spin(n: int = 4) -> list[str]:
    return [HEART if random.random() < HEART_CHANCE else random.choice(NON_HEARTS) for _ in range(n)]


def _hearts(slots: list[str]) -> int:
    return slots.count(HEART)


def _slots_str(slots: list[str]) -> str:
    return " | ".join(slots)


def _claim_true(claim, slots: list[str]) -> bool:
    actual = _hearts(slots)
    return actual == 4 if claim == "jackpot" else actual >= claim


def _claim_label(claim) -> str:
    return "🎰 JACKPOT (4×❤️)" if claim == "jackpot" else f"❤️ × {claim}"


def _can_execute(game: dict, uid: str) -> bool:
    p = game["players"].get(uid)
    if not p or not p["alive"] or p["points"] < EXECUTE_THRESHOLD:
        return False
    alive_pts = [(u, pd["points"]) for u, pd in game["players"].items() if pd["alive"]]
    max_pts = max(pts for _, pts in alive_pts)
    top = [u for u, pts in alive_pts if pts == max_pts]
    return len(top) == 1 and top[0] == uid


def _standings_str(game: dict) -> str:
    alive = sorted(
        [(u, p) for u, p in game["players"].items() if p["alive"]],
        key=lambda x: -x[1]["points"],
    )
    dead = [(u, p) for u, p in game["players"].items() if not p["alive"]]
    lines = []
    for uid, p in alive:
        ex = " ⚡" if _can_execute(game, uid) else ""
        lines.append(f"🟢 **{p['name']}** — {p['points']} bodů{ex}")
    for _, p in dead:
        lines.append(f"💀 ~~{p['name']}~~")
    return "\n".join(lines) or "—"


def _alive_count(game: dict) -> int:
    return sum(1 for p in game["players"].values() if p["alive"])


def _record_win(uid: str):
    scores = load_json(SCORES_FILE, {})
    scores[uid] = scores.get(uid, 0) + 1
    save_json(SCORES_FILE, scores)


# ══════════════════════════════════════════════════════════════════════════════
# LOBBY
# ══════════════════════════════════════════════════════════════════════════════

class SlotsLobbyView(discord.ui.View):
    def __init__(self, cog: "SlotsCog", author: discord.Member, bet: int = 0):
        super().__init__(timeout=120)
        self.cog    = cog
        self.author = author
        self.bet    = bet
        self.players: list[discord.Member] = [author]
        self.paid: set[str] = set()

        # Autor platí hned při vytvoření lobby
        if bet > 0:
            uid = str(author.id)
            eco = _load_eco()
            eco[uid] = eco.get(uid, 0) - bet
            _save_eco(eco)
            self.paid.add(uid)

    def _embed(self) -> discord.Embed:
        names = "\n".join(f"• {m.display_name}" for m in self.players)
        pot   = self.bet * len(self.paid)
        e = discord.Embed(title="🎰 Liar Slots — Lobby", color=0xFFD700)
        e.description = (
            "Bluffovací slot machine. Každý tah točíš 4 sloty — **1 vidí všichni**.\n"
            "Prohlásíš kolik ❤️ máš, ostatní ti buď věří nebo křičí **LIAR!**\n\n"
            f"**Hráči ({len(self.players)}/{MAX_PLAYERS}):**\n{names}"
        )
        if self.bet > 0:
            e.add_field(name="Sázka", value=f"{self.bet} {COIN} každý", inline=True)
            e.add_field(name="Pot",   value=f"{pot} {COIN}", inline=True)
        return e

    @discord.ui.button(label="🎰 Připojit se", style=discord.ButtonStyle.success, custom_id="ls_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.players:
            await interaction.response.send_message("Už jsi ve hře!", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message("Hra je plná!", ephemeral=True)
            return
        uid = str(interaction.user.id)
        if self.bet > 0:
            eco = _load_eco()
            if eco.get(uid, 0) < self.bet:
                await interaction.response.send_message(
                    f"❌ Nemáš dost zlaťáků! Potřebuješ **{self.bet}** {COIN}.", ephemeral=True
                )
                return
            eco[uid] = eco.get(uid, 0) - self.bet
            _save_eco(eco)
            self.paid.add(uid)
        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="🚪 Odejít", style=discord.ButtonStyle.secondary, custom_id="ls_leave")
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message(
                "Zakladatel nemůže odejít. Použij Zrušit.", ephemeral=True
            )
            return
        if interaction.user not in self.players:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        if self.bet > 0 and uid in self.paid:
            eco = _load_eco()
            eco[uid] = eco.get(uid, 0) + self.bet
            _save_eco(eco)
            self.paid.discard(uid)
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶️ Spustit", style=discord.ButtonStyle.primary, custom_id="ls_start")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Hru může spustit jen zakladatel.", ephemeral=True)
            return
        if len(self.players) < MIN_PLAYERS:
            await interaction.response.send_message(
                f"Potřeba alespoň {MIN_PLAYERS} hráče.", ephemeral=True
            )
            return
        pot = self.bet * len(self.paid)
        self.stop()
        await interaction.response.edit_message(content="🎰 **Liar Slots** se spouští…", embed=None, view=None)
        await self.cog._start_game(interaction.channel, self.players, self.bet, pot)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger, custom_id="ls_cancel_lobby")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (interaction.user.id != self.author.id
                and not interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("Pouze zakladatel nebo admin.", ephemeral=True)
            return
        if self.bet > 0 and self.paid:
            eco = _load_eco()
            for uid in self.paid:
                eco[uid] = eco.get(uid, 0) + self.bet
            _save_eco(eco)
        self.stop()
        await interaction.response.edit_message(
            content="🚫 Lobby zrušeno. Sázky vráceny.", embed=None, view=None
        )


# ══════════════════════════════════════════════════════════════════════════════
# SPIN VIEW  (veřejná, aktivuje jen aktuální hráč)
# ══════════════════════════════════════════════════════════════════════════════

class SpinView(discord.ui.View):
    def __init__(self, cog: "SlotsCog", game: dict, uid: str):
        super().__init__(timeout=120)
        self.cog  = cog
        self.game = game
        self.uid  = uid
        self._used = False  # guard proti double-click

        spin_btn = discord.ui.Button(
            label="🎰 Točit!", style=discord.ButtonStyle.primary, custom_id=f"ls_spin_{uid}"
        )
        spin_btn.callback = self._spin_cb
        self.add_item(spin_btn)

        if not game["players"][uid].get("double_spin_used"):
            ds_btn = discord.ui.Button(
                label="🎰🎰 Double Spin (1×)", style=discord.ButtonStyle.secondary,
                custom_id=f"ls_ds_{uid}"
            )
            ds_btn.callback = self._double_spin_cb
            self.add_item(ds_btn)

        if _can_execute(game, uid):
            ex_btn = discord.ui.Button(
                label="⚡ EXECUTE", style=discord.ButtonStyle.danger, custom_id=f"ls_exec_{uid}"
            )
            ex_btn.callback = self._execute_cb
            self.add_item(ex_btn)


    async def _spin_cb(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._used:
            await interaction.response.send_message("Už jsi točil/a.", ephemeral=True)
            return
        self._used = True
        self.stop()
        slots = _spin(4)
        self.game["players"][self.uid]["current_slots"] = slots
        await self.cog._after_spin(interaction, self.game, self.uid, slots)

    async def _double_spin_cb(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._used:
            await interaction.response.send_message("Už jsi točil/a.", ephemeral=True)
            return
        self._used = True
        self.stop()
        self.game["players"][self.uid]["double_spin_used"] = True
        slots_a = _spin(4)
        slots_b = _spin(4)
        view = DoubleSpinChoiceView(self.cog, self.game, self.uid, slots_a, slots_b)
        await interaction.response.send_message(
            f"🎰🎰 **Double Spin!**\n"
            f"**A:** {_slots_str(slots_a)}  ({_hearts(slots_a)}❤️)\n"
            f"**B:** {_slots_str(slots_b)}  ({_hearts(slots_b)}❤️)\n\n"
            f"Vyber výsledek:",
            view=view,
            ephemeral=True,
        )

    async def _execute_cb(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if not _can_execute(self.game, self.uid):
            await interaction.response.send_message("EXECUTE není dostupný.", ephemeral=True)
            return
        if self._used:
            await interaction.response.send_message("Již provedeno.", ephemeral=True)
            return
        self._used = True
        self.stop()
        await self.cog._handle_execute(interaction, self.game, self.uid)

    async def on_timeout(self):
        if self._used:
            return
        channel = self.cog.bot.get_channel(self.game.get("channel_id", 0))
        if channel and self.game.get("channel_id") in self.cog.active_games:
            pdata = self.game["players"][self.uid]
            await channel.send(f"⏱️ **{pdata['name']}** nestihl/a točit — tah přeskočen.")
            game = self.game
            order = game["turn_order"]
            game["turn_idx"] = (game["turn_idx"] + 1) % len(order)
            await self.cog._start_turn(channel, game)


# ══════════════════════════════════════════════════════════════════════════════
# DOUBLE SPIN CHOICE
# ══════════════════════════════════════════════════════════════════════════════

class DoubleSpinChoiceView(discord.ui.View):
    def __init__(self, cog, game, uid, slots_a, slots_b):
        super().__init__(timeout=60)
        self.cog     = cog
        self.game    = game
        self.uid     = uid
        self.slots_a = slots_a
        self.slots_b = slots_b
        self._picked = False  # bug fix: zabrání double-pick

        btn_a = discord.ui.Button(
            label=f"Výsledek A  ({_hearts(slots_a)}❤️)",
            style=discord.ButtonStyle.primary,
            custom_id=f"ds_a_{uid}",
        )
        btn_a.callback = self._pick_a
        self.add_item(btn_a)

        btn_b = discord.ui.Button(
            label=f"Výsledek B  ({_hearts(slots_b)}❤️)",
            style=discord.ButtonStyle.primary,
            custom_id=f"ds_b_{uid}",
        )
        btn_b.callback = self._pick_b
        self.add_item(btn_b)

    async def _pick_a(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._picked:
            await interaction.response.send_message("Již jsi vybral/a.", ephemeral=True)
            return
        self._picked = True
        self.stop()
        self.game["players"][self.uid]["current_slots"] = self.slots_a
        await self.cog._after_spin(interaction, self.game, self.uid, self.slots_a)

    async def _pick_b(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._picked:
            await interaction.response.send_message("Již jsi vybral/a.", ephemeral=True)
            return
        self._picked = True
        self.stop()
        self.game["players"][self.uid]["current_slots"] = self.slots_b
        await self.cog._after_spin(interaction, self.game, self.uid, self.slots_b)

    async def on_timeout(self):
        """Hráč nevybral → použijeme A jako default a pokračujeme."""
        if self._picked:
            return
        self._picked = True
        channel = self.cog.bot.get_channel(self.game.get("channel_id", 0))
        if channel and self.game.get("channel_id") in self.cog.active_games:
            self.game["players"][self.uid]["current_slots"] = self.slots_a
            pdata = self.game["players"][self.uid]
            await channel.send(
                f"⏱️ **{pdata['name']}** nestihl/a vybrat Double Spin → automaticky Výsledek A."
            )
            # Spustíme declare přímo přes fake interaction není možné — přeskočíme tah
            order = self.game["turn_order"]
            self.game["turn_idx"] = (self.game["turn_idx"] + 1) % len(order)
            await self.cog._start_turn(channel, self.game)


# ══════════════════════════════════════════════════════════════════════════════
# DECLARE VIEW  (ephemeral – jen pro aktivního hráče)
# ══════════════════════════════════════════════════════════════════════════════

class DeclareView(discord.ui.View):
    def __init__(self, cog, game, uid, slots):
        super().__init__(timeout=60)
        self.cog      = cog
        self.game     = game
        self.uid      = uid
        self.slots    = slots
        self._declared = False

        options = [
            discord.SelectOption(label="❤️ × 1", value="1", description="+1 bod"),
            discord.SelectOption(label="❤️ × 2", value="2", description="+2 body"),
            discord.SelectOption(label="❤️ × 3", value="3", description="+3 body"),
            discord.SelectOption(label="🎰 JACKPOT — všechna 4 srdce", value="jackpot", description="+5 bodů"),
        ]
        sel = discord.ui.Select(
            placeholder="📢 Prohlásit…", options=options, custom_id=f"ls_declare_{uid}"
        )
        sel.callback = self._declare_cb
        self.add_item(sel)

    async def _declare_cb(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._declared:
            await interaction.response.send_message("Již jsi prohlásil/a.", ephemeral=True)
            return
        self._declared = True
        self.stop()
        val = interaction.data["values"][0]
        claim = int(val) if val != "jackpot" else "jackpot"
        await self.cog._process_declaration(interaction, self.game, self.uid, claim)

    async def on_timeout(self):
        """Hráč nestihl deklarovat — přeskočíme tah."""
        if self._declared:
            return
        channel = self.cog.bot.get_channel(self.game.get("channel_id", 0))
        if channel and self.game.get("channel_id") in self.cog.active_games:
            pdata = self.game["players"][self.uid]
            await channel.send(f"⏱️ **{pdata['name']}** nestihl/a deklarovat — tah přeskočen.")
            order = self.game["turn_order"]
            self.game["turn_idx"] = (self.game["turn_idx"] + 1) % len(order)
            await self.cog._start_turn(channel, self.game)


# ══════════════════════════════════════════════════════════════════════════════
# BET OR PASS VIEW  (veřejná – malý embed po zatočení)
# ══════════════════════════════════════════════════════════════════════════════

class BetOrPassView(discord.ui.View):
    def __init__(self, cog: "SlotsCog", game: dict, uid: str, slots: list):
        super().__init__(timeout=60)
        self.cog   = cog
        self.game  = game
        self.uid   = uid
        self.slots = slots
        self._done = False

        bet_btn = discord.ui.Button(
            label="📢 Vsadit", style=discord.ButtonStyle.primary, custom_id=f"ls_bet_{uid}"
        )
        bet_btn.callback = self._bet_cb
        self.add_item(bet_btn)

        pass_btn = discord.ui.Button(
            label="⏭️ Pass", style=discord.ButtonStyle.secondary, custom_id=f"ls_bpass_{uid}"
        )
        pass_btn.callback = self._pass_cb
        self.add_item(pass_btn)

    async def _bet_cb(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._done:
            await interaction.response.send_message("Tah byl již použit.", ephemeral=True)
            return
        self._done = True
        self.stop()
        await interaction.response.edit_message(view=None)
        h = _hearts(self.slots)
        label = "🎰 **JACKPOT možný!**" if h == 4 else f"Srdcí: **{h}**"
        declare_view = DeclareView(self.cog, self.game, self.uid, self.slots)
        await interaction.followup.send(
            f"🎰 **Tvoje sloty:** {_slots_str(self.slots)}\n"
            f"{label}\n\nCo prohlásíš ostatním?",
            view=declare_view,
            ephemeral=True,
        )

    async def _pass_cb(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Nejsi na tahu.", ephemeral=True)
            return
        if self._done:
            await interaction.response.send_message("Tah byl již použit.", ephemeral=True)
            return
        self._done = True
        self.stop()
        pdata = self.game["players"][self.uid]
        await interaction.response.edit_message(
            content=f"⏭️ **{pdata['name']}** přeskočil/a tah.", embed=None, view=None
        )
        order = self.game["turn_order"]
        self.game["turn_idx"] = (self.game["turn_idx"] + 1) % len(order)
        channel = self.cog.bot.get_channel(self.game["channel_id"])
        if channel:
            await self.cog._start_turn(channel, self.game)

    async def on_timeout(self):
        if self._done:
            return
        self._done = True
        channel = self.cog.bot.get_channel(self.game.get("channel_id", 0))
        if channel and self.game.get("channel_id") in self.cog.active_games:
            pdata = self.game["players"][self.uid]
            await channel.send(f"⏱️ **{pdata['name']}** nestihl/a vsadit — tah přeskočen.")
            order = self.game["turn_order"]
            self.game["turn_idx"] = (self.game["turn_idx"] + 1) % len(order)
            await self.cog._start_turn(channel, self.game)


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE VIEW  (veřejná – ostatní hráči reagují)
# ══════════════════════════════════════════════════════════════════════════════

class ResponseView(discord.ui.View):
    def __init__(self, cog, game, declaring_uid: str, claim, resolve_event: asyncio.Event):
        super().__init__(timeout=RESPONSE_TIMEOUT)
        self.cog           = cog
        self.game          = game
        self.declaring_uid = declaring_uid
        self.claim         = claim
        self.resolve_event = resolve_event
        self.liar_caller_uid: str | None = None
        self._accepted: set[str] = set()

        liar_btn = discord.ui.Button(
            label="🚨 LIAR!", style=discord.ButtonStyle.danger, custom_id="ls_liar"
        )
        liar_btn.callback = self._liar_cb
        self.add_item(liar_btn)

        accept_btn = discord.ui.Button(
            label="✅ Věřím", style=discord.ButtonStyle.success, custom_id="ls_accept"
        )
        accept_btn.callback = self._accept_cb
        self.add_item(accept_btn)

    async def _liar_cb(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid == self.declaring_uid:
            await interaction.response.send_message("Nemůžeš volat LIAR na sebe.", ephemeral=True)
            return
        if not self.game["players"].get(uid, {}).get("alive"):
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if self.game.get("liar_called"):
            await interaction.response.send_message("LIAR byl již zavolán.", ephemeral=True)
            return
        self.game["liar_called"] = True
        self.liar_caller_uid = uid
        caller_name = self.game["players"][uid]["name"]
        await interaction.response.send_message(
            f"🚨 **{caller_name}** volá LIAR! Odhalujeme…", ephemeral=False
        )
        self.resolve_event.set()

    async def _accept_cb(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if uid == self.declaring_uid:
            await interaction.response.send_message("Čekáš na ostatní.", ephemeral=True)
            return
        if not self.game["players"].get(uid, {}).get("alive"):
            await interaction.response.send_message("Nejsi aktivní hráč.", ephemeral=True)
            return
        if self.game.get("liar_called"):
            await interaction.response.send_message("LIAR byl již zavolán.", ephemeral=True)
            return
        self._accepted.add(uid)
        alive_others = {u for u, p in self.game["players"].items()
                        if p["alive"] and u != self.declaring_uid}
        remaining = alive_others - self._accepted
        if not remaining:
            self.resolve_event.set()
            await interaction.response.send_message(
                "✅ Všichni věří — tah se ukončuje!", ephemeral=False
            )
        else:
            await interaction.response.send_message(
                f"✅ Věříš. ({len(self._accepted)}/{len(alive_others)})", ephemeral=True
            )

    async def on_timeout(self):
        if not self.resolve_event.is_set():
            self.resolve_event.set()


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class SlotsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}

    # ── Slash commandy ────────────────────────────────────────────────────────

    @app_commands.command(name="liar_slots", description="Spustí hru Liar Slots")
    @app_commands.describe(sazka="Vstupní sázka v zlaťácích (0 = bez sázky)")
    async def liar_slots_cmd(self, interaction: discord.Interaction, sazka: int = 0):
        cid = interaction.channel_id
        if cid in self.active_games:
            await interaction.response.send_message("Ve tomto kanálu již běží hra!", ephemeral=True)
            return
        if sazka < 0:
            await interaction.response.send_message("Sázka nesmí být záporná.", ephemeral=True)
            return
        if sazka > 0:
            uid = str(interaction.user.id)
            eco = _load_eco()
            if eco.get(uid, 0) < sazka:
                await interaction.response.send_message(
                    f"❌ Nemáš dost zlaťáků! Potřebuješ **{sazka}** {COIN}.", ephemeral=True
                )
                return
        view = SlotsLobbyView(self, interaction.user, sazka)
        await interaction.response.send_message(embed=view._embed(), view=view)

    @app_commands.command(name="slots_leaderboard", description="Žebříček výher Liar Slots")
    async def slots_lb(self, interaction: discord.Interaction):
        scores = load_json(SCORES_FILE, {})
        if not scores:
            await interaction.response.send_message("Žádné záznamy.", ephemeral=True)
            return
        members = {str(m.id): m.display_name for m in interaction.guild.members}
        lines = [
            f"{i}. **{members.get(uid, uid)}** — {w} výher"
            for i, (uid, w) in enumerate(sorted(scores.items(), key=lambda x: -x[1])[:10], 1)
        ]
        e = discord.Embed(title="🎰 Liar Slots — Žebříček", description="\n".join(lines), color=0xFFD700)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="slots_cancel", description="[Admin] Zruší probíhající Liar Slots")
    async def slots_cancel_cmd(self, interaction: discord.Interaction):
        if interaction.channel_id not in self.active_games:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze admin může zrušit hru.", ephemeral=True)
            return
        del self.active_games[interaction.channel_id]
        await interaction.response.send_message("🛑 Hra zrušena.")

    # ── Spuštění hry ──────────────────────────────────────────────────────────

    async def _start_game(
        self,
        channel: discord.TextChannel,
        players: list[discord.Member],
        bet: int = 0,
        pot: int = 0,
    ):
        random.shuffle(players)
        game: dict = {
            "channel_id": channel.id,
            "players": {
                str(m.id): {
                    "name":             m.display_name,
                    "alive":            True,
                    "points":           0,
                    "double_spin_used": False,
                    "current_slots":    [],
                }
                for m in players
            },
            "turn_order": [str(m.id) for m in players],
            "turn_idx":   0,
            "liar_called":   False,
            "current_claim": None,
            "bet": bet,
            "pot": pot,
        }
        self.active_games[channel.id] = game

        names = " · ".join(p["name"] for p in game["players"].values())
        e = discord.Embed(title="🎰 Liar Slots — Hra začíná!", color=0xFFD700)
        e.description = (
            f"Hráči: **{names}**\n\n"
            "**Jak se hraje:**\n"
            "• Točíš 4 sloty — **1 je viditelný** pro všechny, zbytek znáš jen ty\n"
            "• Prohlásíš kolik ❤️ máš: 1, 2, 3, nebo **JACKPOT** (všechna 4)\n"
            "• Ostatní mají 30 sekund — buď věří, nebo volají **🚨 LIAR!**\n"
            "• Lhář chycen → **Death Spin** (40% přežití, jinak vyřazen)\n"
            "• Přežije → přijde o body posledního claimu\n"
            "• Správné LIAR → volající +1 bod, lhář jde na Death Spin\n"
            "• Špatné LIAR → volající −1 bod, deklarující +1 bod\n"
            f"• **{EXECUTE_THRESHOLD} bodů** + jediný lídr → odemkneš **⚡ EXECUTE**\n"
            "• **🎰🎰 Double Spin** — 1× za hru, točíš dvakrát a vybereš výsledek"
        )
        if pot > 0:
            e.add_field(name="💰 Pot", value=f"**{pot}** {COIN}", inline=True)
        await channel.send(embed=e)
        await self._start_turn(channel, game)

    # ── Tah ───────────────────────────────────────────────────────────────────

    async def _start_turn(self, channel: discord.TextChannel, game: dict):
        if game["channel_id"] not in self.active_games:
            return

        order = game["turn_order"]
        n     = len(order)
        if n == 0:
            return

        # Najít dalšího živého hráče
        found = False
        for _ in range(n):
            uid = order[game["turn_idx"] % n]
            if game["players"][uid]["alive"]:
                found = True
                break
            game["turn_idx"] = (game["turn_idx"] + 1) % n

        if not found:
            return

        game["liar_called"] = False
        pdata  = game["players"][uid]
        member = channel.guild.get_member(int(uid))

        pot_str = f" · Pot: **{game['pot']}** {COIN}" if game.get("pot", 0) > 0 else ""
        e = discord.Embed(title=f"🎰 Tah: {pdata['name']}", color=0xFFD700)
        e.add_field(name="📊 Skóre", value=_standings_str(game), inline=False)
        e.set_footer(text=f"Klikni 🎰 Točit! nebo použij speciální akci.{pot_str}")

        view    = SpinView(self, game, uid)
        mention = member.mention if member else pdata["name"]
        await channel.send(f"{mention} — jsi na tahu!", embed=e, view=view)

    # ── Po točení ─────────────────────────────────────────────────────────────

    async def _after_spin(self, interaction: discord.Interaction, game: dict, uid: str, slots: list[str]):
        pdata = game["players"][uid]
        e = discord.Embed(
            title=f"🎰 {pdata['name']} zatočil/a",
            description=f"**Veřejný slot:** {slots[0]}",
            color=0xFFD700,
        )
        e.set_footer(text="📢 Vsadit = prohlásíš kolik ❤️ máš  ·  ⏭️ Pass = přeskočit tah")
        view = BetOrPassView(self, game, uid, slots)
        await interaction.response.send_message(embed=e, view=view)

    # ── Deklarace ─────────────────────────────────────────────────────────────

    async def _process_declaration(
        self, interaction: discord.Interaction, game: dict, uid: str, claim
    ):
        slots       = game["players"][uid]["current_slots"]
        public_slot = slots[0]
        game["current_claim"] = {"uid": uid, "claim": claim, "slots": slots}

        channel = interaction.client.get_channel(game["channel_id"])
        pdata   = game["players"][uid]

        resolve_event = asyncio.Event()
        response_view = ResponseView(self, game, uid, claim, resolve_event)

        e = discord.Embed(
            title=f"📢 {pdata['name']} tvrdí: {_claim_label(claim)}",
            description=f"**Veřejný slot:** {public_slot}",
            color=0xFFD700,
        )
        e.set_footer(text=f"Máš {RESPONSE_TIMEOUT}s — 🚨 LIAR nebo ✅ Věřím")

        await interaction.response.send_message("✅ Prohlášení odesláno!", ephemeral=True)
        msg = await channel.send(embed=e, view=response_view)

        try:
            await asyncio.wait_for(resolve_event.wait(), timeout=RESPONSE_TIMEOUT + 2)
        except asyncio.TimeoutError:
            pass

        for child in response_view.children:
            child.disabled = True
        try:
            await msg.edit(view=response_view)
        except Exception:
            pass

        if game.get("liar_called") and response_view.liar_caller_uid:
            await self._resolve_liar(
                channel, game, response_view.liar_caller_uid, uid, claim, slots
            )
        else:
            await self._award_claim(channel, game, uid, claim)

    # ── Rozhodnutí o LIAR ─────────────────────────────────────────────────────

    async def _resolve_liar(
        self,
        channel: discord.TextChannel,
        game: dict,
        caller_uid: str,
        declarer_uid: str,
        claim,
        slots: list[str],
    ):
        caller   = game["players"][caller_uid]
        declarer = game["players"][declarer_uid]
        is_lie   = not _claim_true(claim, slots)

        e = discord.Embed(
            title=f"🔍 Odhalení: {declarer['name']}",
            description=(
                f"**Sloty:** {_slots_str(slots)}\n"
                f"**Skutečná srdce:** {_hearts(slots)}\n"
                f"**Claim:** {_claim_label(claim)}"
            ),
            color=0xFF4500 if is_lie else 0x27AE60,
        )

        if is_lie:
            caller["points"] += 1
            e.add_field(
                name="✅ LIAR měl pravdu!",
                value=(
                    f"**{declarer['name']}** lhal/a → **Death Spin!**\n"
                    f"**{caller['name']}** získává +1 bod → **{caller['points']}**"
                ),
                inline=False,
            )
            await channel.send(embed=e)
            await self._death_spin(channel, game, declarer_uid)
        else:
            caller["points"]   = max(0, caller["points"] - 1)
            declarer["points"] += 1
            e.add_field(
                name="❌ Špatné obvinění!",
                value=(
                    f"**{caller['name']}** se mýlil/a → −1 bod (**{caller['points']}**)\n"
                    f"**{declarer['name']}** měl/a pravdu → +1 bod (**{declarer['points']}**)"
                ),
                inline=False,
            )
            await channel.send(embed=e)
            await self._next_turn(channel, game)

    # ── Udělení bodů (nikdo nevolal LIAR) ────────────────────────────────────

    async def _award_claim(self, channel: discord.TextChannel, game: dict, uid: str, claim):
        pdata = game["players"][uid]
        pts   = CLAIM_POINTS.get(claim, 1)
        pdata["points"] += pts
        suffix = "bodů" if pts > 4 else ("body" if pts > 1 else "bod")
        await channel.send(
            f"✅ Nikdo nevolal LIAR. "
            f"**{pdata['name']}** získává +**{pts}** {suffix} → celkem **{pdata['points']}**"
        )
        await self._next_turn(channel, game)

    # ── Death Spin ────────────────────────────────────────────────────────────

    async def _death_spin(self, channel: discord.TextChannel, game: dict, uid: str):
        pdata    = game["players"][uid]
        survived = random.random() < DEATH_HEART_CHANCE
        final    = HEART if survived else random.choice(NON_HEARTS)
        all_sym  = [HEART] + NON_HEARTS

        # ── Animace ──────────────────────────────────────────────────────────
        e = discord.Embed(title=f"💀 Death Spin: {pdata['name']}", color=0x8B0000)
        e.description = "🎰 Točí se…\n\n`[ ❓ ]`"
        msg = await channel.send(embed=e)

        # Rychlé točení
        delays = [0.45, 0.45, 0.5, 0.55, 0.65, 0.85, 1.1]
        for i, delay in enumerate(delays):
            sym = random.choice(all_sym) if i < len(delays) - 1 else final
            phase = "🎰 Točí se…" if i < 4 else ("🎰 Zpomaluje…" if i < 6 else "🎰 **Výsledek!**")
            e.description = f"{phase}\n\n# {sym}"
            await asyncio.sleep(delay)
            try:
                await msg.edit(embed=e)
            except Exception:
                pass

        # ── Výsledek ─────────────────────────────────────────────────────────
        if survived:
            claim_info = game.get("current_claim") or {}
            last_claim = claim_info.get("claim", 1)
            pts_lost   = CLAIM_POINTS.get(last_claim, 1)
            pdata["points"] = max(0, pdata["points"] - pts_lost)
            e.color = 0x27AE60
            e.add_field(
                name="❤️ Přežil/a!",
                value=f"Přišel/la o **{pts_lost}** bod(ů) z posledního claimu → **{pdata['points']}** bodů",
                inline=False,
            )
            try:
                await msg.edit(embed=e)
            except Exception:
                pass
            await self._next_turn(channel, game)
        else:
            pdata["alive"] = False
            e.color = 0xFF0000
            e.add_field(
                name="💀 Vyřazen/a!",
                value=f"**{pdata['name']}** opouští hru.",
                inline=False,
            )
            try:
                await msg.edit(embed=e)
            except Exception:
                pass
            if _alive_count(game) <= 1:
                alive = [u for u, p in game["players"].items() if p["alive"]]
                await self._end_game(channel, game, alive[0] if alive else None)
            else:
                await self._next_turn(channel, game)

    # ── Execute ───────────────────────────────────────────────────────────────

    async def _handle_execute(
        self, interaction: discord.Interaction, game: dict, uid: str
    ):
        alive_others = [(u, p) for u, p in game["players"].items() if p["alive"] and u != uid]
        if not alive_others:
            await interaction.response.send_message("Nikdo k eliminaci.", ephemeral=True)
            return

        min_pts    = min(p["points"] for _, p in alive_others)
        targets    = [(u, p) for u, p in alive_others if p["points"] == min_pts]
        target_uid, target = random.choice(targets)
        target["alive"] = False

        channel  = interaction.client.get_channel(game["channel_id"])
        executor = game["players"][uid]

        e = discord.Embed(title="⚡ EXECUTE!", color=0xFF0000)
        e.description = (
            f"**{executor['name']}** aktivoval EXECUTE!\n"
            f"💀 **{target['name']}** byl/a okamžitě eliminován/a."
        )
        await interaction.response.defer()
        await channel.send(embed=e)

        if _alive_count(game) <= 1:
            alive = [u for u, p in game["players"].items() if p["alive"]]
            await self._end_game(channel, game, alive[0] if alive else None)
        else:
            await self._next_turn(channel, game)

    # ── Přechod na dalšího hráče ──────────────────────────────────────────────

    async def _next_turn(self, channel: discord.TextChannel, game: dict):
        if game["channel_id"] not in self.active_games:
            return
        if _alive_count(game) <= 1:
            alive = [u for u, p in game["players"].items() if p["alive"]]
            await self._end_game(channel, game, alive[0] if alive else None)
            return
        game["turn_idx"] = (game["turn_idx"] + 1) % len(game["turn_order"])
        await self._start_turn(channel, game)

    # ── Konec hry ─────────────────────────────────────────────────────────────

    async def _end_game(self, channel: discord.TextChannel, game: dict, winner_uid: str | None):
        self.active_games.pop(channel.id, None)

        rows = []
        for uid, p in sorted(game["players"].items(), key=lambda x: -x[1]["points"]):
            icon = "🏆" if uid == winner_uid else ("💀" if not p["alive"] else "🟢")
            rows.append(f"{icon} **{p['name']}** — {p['points']} bodů")

        e = discord.Embed(title="🎰 Liar Slots — Konec!", color=0xFFD700)
        if winner_uid:
            w = game["players"][winner_uid]
            e.description = f"🏆 Vítěz: **{w['name']}**!"
            _record_win(winner_uid)
            pot = game.get("pot", 0)
            if pot > 0:
                eco = _load_eco()
                eco[winner_uid] = eco.get(winner_uid, 0) + pot
                _save_eco(eco)
                e.description += f"\n🏆 Výhra: **{pot}** {COIN}"
        else:
            e.description = "Všichni byli eliminováni — remíza!"
        e.add_field(name="Výsledky", value="\n".join(rows), inline=False)
        await channel.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(SlotsCog(bot))
