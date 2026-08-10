"""
🎒 Liar's Briefcase — sociální blafovací minihra pro ArionBot (2.0)

VRSTVA 1 — funkční jádro:
  • Hra běží na kola (max 10). Kolem hlavního embedu („stůl") hráči diskutují.
  • Každý hráč má kufřík; bot tajně vybere JEDEN s odměnou.
  • Model 1: hráč vidí JEN svůj kufřík (mám/nemám odměnu), ne kam putuje.
  • Každé kolo:
      – hodnota potu roste (bankéřka Arion reálně přidává — výplata > sázky)
      – kufříky se posunou v kruhu (odměna tiše putuje, hráč nevidí kam)
      – hráči diskutují, pak HLASUJÍ nebo SKIPNOU do dalšího kola
  • Hlasování: tajně se ukazuje na aktuálního nositele.
      – nositel jednoznačně nejvíc hlasů → skupina dělí pot
      – nositel splyne → bere celý pot
      – rovnost → sázky zpět
  • Když se nedohlasuje do 10. kola → Arion bere VŠE (i sázky). Tvrdý trest.

VRSTVA 2 (později): event roll 6×1d6, posun/zpřeházení eventy.
VRSTVA 3 (později): Šašek + Klon (message-intercept).
"""

import random
import asyncio
import logging
import discord
from discord.ext import commands
from discord import app_commands

from src.utils.json_utils import load_json, save_json
from src.utils.paths import data
from src.logic.economy import minigame_file, minigame_coin

logger = logging.getLogger("Briefcase")

# ── Konstanty ─────────────────────────────────────────────────────────────────
MIN_PLAYERS   = 3
MAX_PLAYERS   = 8
MAX_ROUNDS    = 10
DISCUSS_SECS  = 160         # diskuse u stolu (přeskočí se, když všichni rozhodnou)
VOTE_SECS     = 45          # délka hlasování, když se spustí

# Násobitel potu podle kola (lineární: kolo × 0.2 navíc). Kolo 1 = 1.2×, kolo 10 = 3.0×.
def _pot_multiplier(round_no: int) -> float:
    return 1.0 + round_no * 0.2


# ── Event systém (Vrstva 2+4) ─────────────────────────────────────────────────
# Bot pro atmosféru hodí 6×1d6 (zobrazí se), ale samotný event se vybírá VÁŽENĚ —
# tím jsou i vzácné eventy (šašek/klon/loupež) reálně dosažitelné, ne jen teoreticky.
EVENT_WEIGHTS = {
    "klid":       22,   # posun o 1 (nejčastější)
    "dvojposun":  20,   # posun o 2
    "vymena":     14,   # dva hráči si prohodí kufříky (viditelně)
    "shuffle":    12,   # náhodné zpřeházení
    "prohlidka":  12,   # náhodný hráč nakoukne do cizího kufříku
    "roubik":      8,   # jeden hráč nesmí to kolo psát
    "sasek":       6,   # ŠAŠEK — zprávy oběti se prohází
    "loupez":      4,   # Arion ukousne část potu
    "klon":        2,   # KLON — oběť má 2 hlasy, zprávy se kopírují
}

EVENT_INFO = {
    "klid":      ("🎐", "Klid", "Kufříky se v tichosti posunuly o jedno místo."),
    "dvojposun": ("🌀", "Dvojposun", "Průvan! Kufříky přeskočily o dvě místa."),
    "vymena":    ("🔄", "Výměna na povel", "Arion luskla — dva hráči si museli prohodit kufříky!"),
    "shuffle":   ("🎲", "Zpřeházení", "Arion zamíchala kufříky — kdo ví, kde co skončilo."),
    "prohlidka": ("🔍", "Prohlídka", "Jeden zvědavec tajně nakoukl do cizího kufříku…"),
    "roubik":    ("🔇", "Roubík", "Jeden hráč to kolo neřekne ani slovo — Arion mu sebrala hlas."),
    "sasek":     ("🃏", "Šašek", "Šašek si vyhlédl jednu oběť…"),
    "loupez":    ("💰", "Arion loupí", "Bankéřka si ukousla pořádné sousto z potu!"),
    "klon":      ("👥", "Klon", "Ve stínu se objevil klon jednoho z vás…"),
}


def _roll_event() -> tuple[int, str]:
    """Hodí 6×1d6 (flavour) a vážené vybere event."""
    total = sum(random.randint(1, 6) for _ in range(6))
    events  = list(EVENT_WEIGHTS.keys())
    weights = list(EVENT_WEIGHTS.values())
    ev = random.choices(events, weights=weights)[0]
    return total, ev


def _shuffle_words(text: str) -> str:
    """Prohází pořadí slov ve zprávě (efekt šaška). Zachová interpunkci hrubě."""
    words = text.split()
    if len(words) < 2:
        return text + " …ehm?"
    random.shuffle(words)
    return " ".join(words)


SCORES_FILE = data("briefcase_scores.json")

# Hlášky bankéřky Arion (oranžová kočka líně ležící na stole)
_ARION_QUIPS = [
    "Čím dýl váháte, tím víc mňoukám na peníze.",
    "Někdo z vás lže. Já to poznám podle chvění vousků.",
    "Přede mnou nic neschováš, dvojnožče.",
    "Ten pot pěkně roste… škoda by ho bylo nechat.",
    "Mrr. Blafujte dál, baví mě to.",
    "Deset kol a je můj. Nezapomeňte.",
    "Cítím strach. A tuňáka. Hlavně strach.",
    "Kdo se moc brání, ten obvykle lže. *zívnutí*",
]


# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_scores() -> dict:   return load_json(SCORES_FILE, {})
def _save_scores(d: dict):    save_json(SCORES_FILE, d)
def _load_eco() -> dict:      return load_json(minigame_file(), {})
def _save_eco(d: dict):       save_json(minigame_file(), d)


def _record(uid: str, won: bool, profit: int) -> None:
    """Zapíše výsledek do leaderboardu (bohatý tvar {uid:{profit_*,wins,games}})."""
    from src.logic.economy import get_minigame_currency
    cur = get_minigame_currency()
    scores = _load_scores()
    rec = scores.setdefault(uid, {"profit_gold": 0, "profit_silver": 0, "wins": 0, "games": 0})
    rec["games"] = rec.get("games", 0) + 1
    if won:
        rec["wins"] = rec.get("wins", 0) + 1
    rec[f"profit_{cur}"] = rec.get(f"profit_{cur}", 0) + profit
    _save_scores(scores)


def _payout(uid: str, amount: int) -> None:
    if amount == 0:
        return
    eco = _load_eco()
    eco[uid] = eco.get(uid, 0) + amount
    _save_eco(eco)


# ══════════════════════════════════════════════════════════════════════════════
# LOBBY VIEW
# ══════════════════════════════════════════════════════════════════════════════

class BriefcaseLobby(discord.ui.View):
    def __init__(self, cog, author: discord.Member, bet: int):
        super().__init__(timeout=None)
        self.cog     = cog
        self.author  = author
        self.bet     = bet
        self.players = [author]
        self.paid: set[str] = set()

        if bet > 0:
            uid = str(author.id)
            eco = _load_eco()
            eco[uid] = eco.get(uid, 0) - bet
            _save_eco(eco)
            self.paid.add(uid)

    def _embed(self) -> discord.Embed:
        pot = self.bet * len(self.paid) if self.bet > 0 else 0
        embed = discord.Embed(
            title="🎒 Liar's Briefcase — Lobby",
            description=(
                "*Jeden z vás dostane do kufříku odměnu — ale nikdo neví kdo.*\n\n"
                "**Jak se hraje:**\n"
                "▸ Hra běží na kola. Každý si tajně kouká do svého kufříku.\n"
                "▸ Bankéřka **Arion** 🐱 každé kolo peníze **znásobí** — čím dýl hrajete, tím víc.\n"
                "▸ Kufříky kolují — nevíš, kam tvůj putuje.\n"
                "▸ Kdykoli můžete **hlasovat**, kdo má odměnu, nebo **skipnout** dál.\n\n"
                "**Pozor:** když nedohlasujete do 10. kola, **Arion si vezme všechno!**\n\n"
                "**Výhra:**\n"
                "▸ Odhalíte nositele → skupina dělí pot.\n"
                "▸ Nositel splyne → bere celý pot.\n"
            ),
            color=0x9B59B6,
        )
        names = "\n".join(f"• {p.display_name}" for p in self.players)
        embed.add_field(name=f"Hráči ({len(self.players)}/{MAX_PLAYERS})", value=names, inline=True)
        if self.bet > 0:
            embed.add_field(name="Sázka", value=f"{self.bet} {minigame_coin()} každý", inline=True)
            embed.add_field(name="Pot",   value=f"{pot} {minigame_coin()}", inline=True)
        embed.set_footer(text=f"Min. {MIN_PLAYERS} hráči  ·  blafuj, čti ostatní, věř Arion (nebo ne)")
        return embed

    @discord.ui.button(label="Připojit se", emoji="🎒", style=discord.ButtonStyle.success, custom_id="bc_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [p.id for p in self.players]:
            return await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
        if len(self.players) >= MAX_PLAYERS:
            return await interaction.response.send_message(f"Lobby je plné ({MAX_PLAYERS}).", ephemeral=True)

        uid = str(interaction.user.id)
        if self.bet > 0:
            eco = _load_eco()
            if eco.get(uid, 0) < self.bet:
                return await interaction.response.send_message(
                    f"❌ Nemáš dost! Potřebuješ **{self.bet}** {minigame_coin()}.", ephemeral=True)
            eco[uid] = eco.get(uid, 0) - self.bet
            _save_eco(eco)
            self.paid.add(uid)

        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="Odejít", style=discord.ButtonStyle.secondary, custom_id="bc_leave")
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            return await interaction.response.send_message(
                "Zakladatel nemůže odejít. Použij Zrušit.", ephemeral=True)
        if interaction.user.id not in [p.id for p in self.players]:
            return await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)

        uid = str(interaction.user.id)
        if self.bet > 0 and uid in self.paid:
            _payout(uid, self.bet)
            self.paid.discard(uid)
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶ Start", style=discord.ButtonStyle.primary, custom_id="bc_start")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("Pouze zakladatel může spustit hru!", ephemeral=True)
        if len(self.players) < MIN_PLAYERS:
            return await interaction.response.send_message(
                f"Potřebuješ aspoň {MIN_PLAYERS} hráče!", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(
            content="🎒 **Liar's Briefcase** — Hra začíná!", embed=None, view=None)
        pot = self.bet * len(self.paid)
        await self.cog._start_game(interaction.channel, list(self.players), self.bet, pot)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger, custom_id="bc_cancel")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Pouze zakladatel nebo admin.", ephemeral=True)
        if self.bet > 0:
            for uid in self.paid:
                _payout(uid, self.bet)
        self.stop()
        await interaction.response.edit_message(content="🚫 Lobby zrušeno. Sázky vráceny.", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# KUFŘÍK VIEW — tajné kouknutí do vlastního kufříku (Model 1)
# ══════════════════════════════════════════════════════════════════════════════

class TableView(discord.ui.View):
    """Tlačítka u stolu: kouknout do kufříku, spustit hlasování, skip."""

    def __init__(self, cog, channel_id: int):
        super().__init__(timeout=None)
        self.cog        = cog
        self.channel_id = channel_id

    @discord.ui.button(label="🎒 Můj kufřík", style=discord.ButtonStyle.secondary, custom_id="bc_peek")
    async def peek_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game:
            return await interaction.response.send_message("*Hra už neběží.*", ephemeral=True)
        uid = str(interaction.user.id)
        if uid not in game["players"]:
            return await interaction.response.send_message("*Nejsi v této hře.*", ephemeral=True)
        # aktuální nositel = kdo drží odměnu TEĎ (po posunech)
        if uid == game["holder"]:
            msg = ("🎒 **Ve tvém kufříku je ODMĚNA!**\n"
                   "Splyň — když tě neodhalí, bereš celý pot. Ale pozor, kufříky kolují…")
        else:
            msg = ("🎒 **Tvůj kufřík je prázdný.**\n"
                   "Odměnu má někdo jiný. Sleduj ostatní a odhal ho — nebo počkej na větší balík.")
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="🗳️ Hlasovat", style=discord.ButtonStyle.primary, custom_id="bc_callvote")
    async def vote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game:
            return await interaction.response.send_message("*Hra už neběží.*", ephemeral=True)
        uid = str(interaction.user.id)
        if uid not in game["players"]:
            return await interaction.response.send_message("*Nejsi v této hře.*", ephemeral=True)
        if game["phase"] != "discuss":
            return await interaction.response.send_message("*Zrovna nejde vyvolat hlasování.*", ephemeral=True)
        # volba je výlučná — hlas ruší předchozí skip
        game["call_skip"].discard(uid)
        game["call_vote"].add(uid)
        need    = (len(game["players"]) // 2) + 1
        have    = len(game["call_vote"])
        decided = len(game["call_vote"] | game["call_skip"])
        total   = len(game["players"])
        if have >= need:
            await interaction.response.send_message("🗳️ *Většina chce hlasovat — spouštím!*", ephemeral=True)
            game["phase"] = "voting"
            game["trigger_vote"].set()
        elif decided >= total:
            # všichni rozhodli, ale hlasování nemá většinu → převažuje skip
            await interaction.response.send_message("🗳️ Zapsáno. *Všichni rozhodli — jde se dál.*", ephemeral=True)
            game["trigger_skip"].set()
        else:
            await interaction.response.send_message(
                f"🗳️ Chceš hlasovat ({have}/{need}). *Rozhodnuto {decided}/{total}.*", ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="bc_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game:
            return await interaction.response.send_message("*Hra už neběží.*", ephemeral=True)
        uid = str(interaction.user.id)
        if uid not in game["players"]:
            return await interaction.response.send_message("*Nejsi v této hře.*", ephemeral=True)
        if game["phase"] != "discuss":
            return await interaction.response.send_message("*Zrovna nejde skipnout.*", ephemeral=True)
        # volba je výlučná — skip ruší předchozí hlas
        game["call_vote"].discard(uid)
        game["call_skip"].add(uid)
        need    = (len(game["players"]) // 2) + 1
        have    = len(game["call_skip"])
        decided = len(game["call_vote"] | game["call_skip"])
        total   = len(game["players"])
        if have >= need:
            await interaction.response.send_message("⏭️ *Většina chce dál — další kolo!*", ephemeral=True)
            game["trigger_skip"].set()
        elif decided >= total:
            # všichni rozhodli — když vote nemá většinu, převažuje skip
            if len(game["call_vote"]) > len(game["call_skip"]):
                await interaction.response.send_message("⏭️ Zapsáno. *Všichni rozhodli — hlasuje se!*", ephemeral=True)
                game["phase"] = "voting"
                game["trigger_vote"].set()
            else:
                await interaction.response.send_message("⏭️ Zapsáno. *Všichni rozhodli — jde se dál.*", ephemeral=True)
                game["trigger_skip"].set()
        else:
            await interaction.response.send_message(
                f"⏭️ Chceš skip ({have}/{need}). *Rozhodnuto {decided}/{total}.*", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# VOTE VIEW — tajné hlasování dropdownem
# ══════════════════════════════════════════════════════════════════════════════

class VoteView(discord.ui.View):
    def __init__(self, cog, channel_id: int, players: list[str], guild: discord.Guild):
        super().__init__(timeout=None)
        self.cog        = cog
        self.channel_id = channel_id
        options = []
        for uid in players:
            member = guild.get_member(int(uid))
            name   = member.display_name if member else f"Hráč {uid[-4:]}"
            options.append(discord.SelectOption(label=name[:100], value=uid))
        self.select = discord.ui.Select(
            placeholder="🗳️ Kdo má teď odměnu?", options=options[:25], custom_id="bc_vote")
        self.select.callback = self._vote_cb
        self.add_item(self.select)

    async def _vote_cb(self, interaction: discord.Interaction):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game.get("phase") != "voting":
            return await interaction.response.send_message("*Hlasování neběží.*", ephemeral=True)
        uid = str(interaction.user.id)
        if uid not in game["players"]:
            return await interaction.response.send_message("*Nejsi v této hře.*", ephemeral=True)
        choice = interaction.data["values"][0]
        game["votes"][uid] = choice
        target = interaction.guild.get_member(int(choice))
        tname  = target.display_name if target else choice
        await interaction.response.send_message(
            f"✅ Tvůj hlas: **{tname}**  *(můžeš změnit do konce hlasování)*", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN COG
# ══════════════════════════════════════════════════════════════════════════════

class BriefcaseCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict = {}

    # ── Message listener — Šašek / Klon (Vrstva 3) ────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignoruj boty a zprávy mimo hru
        if message.author.bot or not message.guild:
            return
        game = self.active_games.get(message.channel.id)
        if not game:
            return
        effect = game.get("active_effect")
        if not effect:
            return
        uid = str(message.author.id)
        if uid != effect["victim"] or uid not in game["players"]:
            return

        content = message.content or ""
        # Bez message_content intentu je content prázdný → tiše nic neděláme.
        if not content.strip():
            return

        member = message.author
        try:
            if effect["type"] == "roubik":
                # oběť roubíku nesmí to kolo psát — zpráva se smaže bez náhrady
                await message.delete()
                try:
                    await message.channel.send(
                        f"🔇 *{message.author.display_name} chce něco říct, ale Arion mu/jí zacpala pusu.*",
                        delete_after=4)
                except Exception:
                    pass
            elif effect["type"] == "sasek":
                garbled = _shuffle_words(content)
                await message.delete()
                await message.channel.send(
                    embed=discord.Embed(
                        description=f"🃏 *Šašek mluví za* **{member.display_name}**:\n> {garbled[:1500]}",
                        color=0xE91E63))
            elif effect["type"] == "klon":
                # klon jen ZKOPÍRUJE zprávu (dvojitě), originál nechá být
                await message.channel.send(
                    embed=discord.Embed(
                        description=f"👥 *Klon* **{member.display_name}** *opakuje*:\n> {content[:1500]}",
                        color=0x3498DB))
        except discord.Forbidden:
            logger.warning("[briefcase] chybí práva na mazání/posílání (šašek/klon)")
        except discord.NotFound:
            pass
        except Exception:
            logger.exception("[briefcase] efekt zprávy selhal")

    @app_commands.command(name="briefcase", description="🎒 Liar's Briefcase — sociální blafovací hra")
    @app_commands.describe(bet="Sázka na hráče (0 = jen o zábavu)")
    async def briefcase(self, interaction: discord.Interaction, bet: int = 0):
        if interaction.channel.id in self.active_games:
            return await interaction.response.send_message(
                "V tomto kanálu už hra běží.", ephemeral=True)
        if bet < 0:
            return await interaction.response.send_message("Sázka nemůže být záporná.", ephemeral=True)
        if bet > 0:
            eco = _load_eco()
            if eco.get(str(interaction.user.id), 0) < bet:
                return await interaction.response.send_message(
                    f"❌ Nemáš dost na sázku **{bet}** {minigame_coin()}.", ephemeral=True)
        view = BriefcaseLobby(self, interaction.user, bet)
        await interaction.response.send_message(embed=view._embed(), view=view)

    # ── Start hry ─────────────────────────────────────────────────────────────

    async def _start_game(self, channel: discord.TextChannel,
                          players: list[discord.Member], bet: int, pot: int):
        uids   = [str(p.id) for p in players]
        random.shuffle(uids)                 # náhodné pořadí u stolu (kruh)
        holder_idx = random.randrange(len(uids))

        game = {
            "phase":     "discuss",
            "players":   uids,               # pořadí = kruh u stolu
            "holder_idx": holder_idx,        # index nositele v kruhu
            "holder":    uids[holder_idx],   # uid aktuálního nositele (derivované)
            "bet":       bet,
            "base_pot":  pot,
            "round":     0,
            "votes":     {},
            "call_vote": set(),
            "call_skip": set(),
            "last_event":    None,
            "pending_event": None,
            "active_effect": None,
            "arion_cut":     0,
            "trigger_vote": asyncio.Event(),
            "trigger_skip": asyncio.Event(),
        }
        self.active_games[channel.id] = game
        await self._run_round(channel, game)

    # ── Jedno kolo ────────────────────────────────────────────────────────────

    async def _apply_event(self, channel, game, ev, total) -> str:
        """Zpracuje event: pohne kufříky / nastaví efekt / upraví pot. Vrací popisný řádek."""
        n = len(game["players"])
        emoji, ename, edesc = EVENT_INFO[ev]
        guild = channel.guild

        def _nm(uid):
            m = guild.get_member(int(uid))
            return m.display_name if m else uid[-4:]

        if ev == "klid":
            game["holder_idx"] = (game["holder_idx"] + 1) % n

        elif ev == "dvojposun":
            game["holder_idx"] = (game["holder_idx"] + 2) % n

        elif ev == "shuffle":
            game["holder_idx"] = random.randrange(n)

        elif ev == "vymena":
            # dva náhodní hráči si prohodí kufříky — viditelně. Pokud je mezi nimi
            # nositel, odměna putuje s ním na druhou pozici.
            a, b = random.sample(range(n), 2) if n >= 2 else (0, 0)
            if game["holder_idx"] == a:
                game["holder_idx"] = b
            elif game["holder_idx"] == b:
                game["holder_idx"] = a
            edesc = f"🔄 **{_nm(game['players'][a])}** a **{_nm(game['players'][b])}** si prohodili kufříky!"

        elif ev == "prohlidka":
            # náhodný „zvědavec" (ne nositel) nakoukne do náhodného cizího kufříku
            game["holder_idx"] = (game["holder_idx"] + 1) % n   # kufříky se stejně posunou
            holder_now = game["players"][game["holder_idx"]]
            snoopers = [u for u in game["players"] if u != holder_now]
            if snoopers:
                snooper = random.choice(snoopers)
                targets = [u for u in game["players"] if u != snooper]
                target  = random.choice(targets)
                has = (target == holder_now)
                # pošli nakukujícímu tajně DM
                try:
                    sm = guild.get_member(int(snooper))
                    if sm:
                        info = ("🎒 **ODMĚNA!**" if has else "prázdný")
                        await sm.send(f"🔍 Nakoukl/a jsi do kufříku **{_nm(target)}** — je {info}.")
                except Exception:
                    logger.warning("[briefcase] nelze poslat DM s prohlídkou")
                edesc = f"🔍 Někdo tajně nakoukl do cizího kufříku… *(ví to jen on/ona)*"

        elif ev == "roubik":
            game["holder_idx"] = (game["holder_idx"] + 1) % n
            # oběť (kdokoli) nesmí to kolo psát → active_effect roubik
            victim = random.choice(game["players"])
            game["active_effect"] = {"type": "roubik", "victim": victim}
            edesc = f"🔇 **{_nm(victim)}** to kolo neřekne ani slovo — Arion mu/jí sebrala hlas."

        elif ev == "loupez":
            game["holder_idx"] = (game["holder_idx"] + 1) % n
            # Arion ukousne 15-30 % z base potu (sníží výplatu)
            cut = random.randint(15, 30)
            game["arion_cut"] = game.get("arion_cut", 0) + cut
            edesc = f"💰 Arion si ukousla **{cut} %** z potu! *Chamtivost bolí.*"

        elif ev in ("sasek", "klon"):
            game["holder_idx"] = (game["holder_idx"] + 1) % n
            holder_now = game["players"][game["holder_idx"]]
            candidates = [u for u in game["players"] if u != holder_now]
            victim = random.choice(candidates) if candidates else random.choice(game["players"])
            game["active_effect"] = {"type": ev, "victim": victim}
            if ev == "sasek":
                edesc = f"🃏 **{_nm(victim)}** je do konce kola ovládán/a šaškem — slova se zamotají."
            else:
                edesc = f"👥 Objevil se **klon {_nm(victim)}**! Do konce kola má **dva hlasy**."

        return f"{emoji} **{ename}** *(hod {total})* — {edesc}"

    async def _run_round(self, channel: discord.TextChannel, game: dict):
        while game["round"] < MAX_ROUNDS:
            if self.active_games.get(channel.id) is not game:
                return
            game["round"] += 1
            r = game["round"]
            game["active_effect"] = None   # efekt (šašek/klon) platí jen jedno kolo

            # ── Event roll (6×1d6) — určí, jak se kufříky pohnou ──────────────
            n = len(game["players"])
            event_line = None
            if r > 1:   # 1. kolo bez pohybu (rozdání)
                total, ev = _roll_event()
                game["last_event"] = ev
                event_line = await self._apply_event(channel, game, ev, total)
                game["holder"] = game["players"][game["holder_idx"]]

            # reset kol
            game["call_vote"].clear()
            game["call_skip"].clear()
            game["phase"] = "discuss"
            game["trigger_vote"].clear()
            game["trigger_skip"].clear()

            cur_pot = int(game["base_pot"] * _pot_multiplier(r))
            # Arion loupež: odečti nakousnutá % z potu (kumulativně, max 80 %)
            cut_pct = min(game.get("arion_cut", 0), 80)
            if cut_pct:
                cur_pot = round(cur_pot * (1 - cut_pct / 100))
            await channel.send(embed=self._table_embed(channel.guild, game, cur_pot, event_line),
                               view=TableView(self, channel.id))

            # čekej na diskusi / vote / skip
            action = await self._wait_for_action(channel, game)
            if self.active_games.get(channel.id) is not game:
                return

            if action == "vote":
                await self._do_voting(channel, game, cur_pot)
                return   # hlasování hru ukončí
            # jinak (skip nebo vypršel čas) → další kolo

        # došla kola bez hlasování → Arion bere vše
        await self._arion_takes_all(channel, game)

    async def _wait_for_action(self, channel, game) -> str:
        """Čeká na spuštění hlasování, skip, nebo vypršení diskuse. Vrací akci."""
        vote_task = asyncio.create_task(game["trigger_vote"].wait())
        skip_task = asyncio.create_task(game["trigger_skip"].wait())
        timer     = asyncio.create_task(asyncio.sleep(DISCUSS_SECS))
        done, pending = await asyncio.wait(
            {vote_task, skip_task, timer}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if vote_task in done:
            return "vote"
        if skip_task in done:
            return "skip"
        return "timeout"   # nikdo nerozhodl → další kolo automaticky

    # ── Table embed ───────────────────────────────────────────────────────────

    def _table_embed(self, guild, game, cur_pot, event_line=None) -> discord.Embed:
        r = game["round"]
        mult = _pot_multiplier(r)
        seat_lines = []
        for uid in game["players"]:
            m = guild.get_member(int(uid))
            seat_lines.append(f"🎒 {m.display_name if m else uid[-4:]}")
        embed = discord.Embed(
            title=f"🎒 Stůl — kolo {r}/{MAX_ROUNDS}",
            description=(
                "🐱 *Bankéřka Arion líně leží na stole a počítá peníze.*\n\n"
                "Diskutujte — kdo má odměnu? Pak **Hlasovat**, nebo **Skip** pro větší balík.\n"
                f"-# Kufříky mezi koly kolují. Koukni si do svého tlačítkem **🎒 Můj kufřík**."
            ),
            color=0xE67E22,
        )
        embed.add_field(name="U stolu", value="\n".join(seat_lines), inline=True)
        embed.add_field(name="💰 Hodnota potu",
                        value=f"**{cur_pot}** {minigame_coin()}\n-# ({mult:.1f}× díky Arion)", inline=True)
        if event_line:
            embed.add_field(name="🎲 Událost kola", value=event_line, inline=False)
        if r >= MAX_ROUNDS:
            embed.add_field(name="⚠️ Poslední kolo!",
                            value="Když nedohlasujete, **Arion bere vše!**", inline=False)
        embed.set_footer(text=f"Diskuse ~{DISCUSS_SECS}s  ·  🐱 Arion hlídá pot")
        # Arion občas prohodí komentář (flavour)
        if random.random() < 0.5:
            quip = random.choice(_ARION_QUIPS)
            embed.description += "\n\n🐱 *" + quip + " — Arion*"
        return embed

    # ── Hlasování ─────────────────────────────────────────────────────────────

    async def _do_voting(self, channel, game, cur_pot):
        game["phase"] = "voting"
        game["votes"] = {}
        embed = discord.Embed(
            title="🗳️ Hlasování",
            description=(f"Kdo má **teď** odměnu? Hlasujte tajně níže.\n"
                         f"-# Pot na stole: **{cur_pot}** {minigame_coin()}  ·  {VOTE_SECS}s"),
            color=0x9B59B6,
        )
        await channel.send(embed=embed, view=VoteView(self, channel.id, game["players"], channel.guild))

        waited = 0
        while waited < VOTE_SECS:
            await asyncio.sleep(5)
            waited += 5
            if self.active_games.get(channel.id) is not game:
                return
            if len(game["votes"]) >= len(game["players"]):
                break

        await self._resolve(channel, game, cur_pot)

    async def _resolve(self, channel, game, cur_pot):
        players = game["players"]
        holder  = game["holder"]
        votes   = game["votes"]
        bet     = game.get("bet", 0)

        tally: dict[str, int] = {}
        # Klon: pokud je při hlasování aktivní klon, jeho oběť má DVA hlasy.
        effect = game.get("active_effect")
        clone_victim = effect["victim"] if (effect and effect["type"] == "klon") else None
        for _voter, target in votes.items():
            weight = 2 if _voter == clone_victim else 1
            tally[target] = tally.get(target, 0) + weight
        holder_votes = tally.get(holder, 0)
        max_votes    = max(tally.values()) if tally else 0
        top_count    = sum(1 for v in tally.values() if v == max_votes)

        guild = channel.guild
        def _nm(uid):
            m = guild.get_member(int(uid))
            return m.display_name if m else f"Hráč {uid[-4:]}"

        group_wins = (holder_votes == max_votes and top_count == 1 and holder_votes > 0)
        tie        = (holder_votes == max_votes and top_count > 1)

        lines = []
        if group_wins:
            winners = [u for u in players if u != holder]
            share = cur_pot // len(winners) if winners else 0
            rem   = cur_pot - share * len(winners)
            for i, u in enumerate(winners):
                _payout(u, share + (1 if i < rem else 0))
            for u in players:
                _record(u, u != holder, (share - bet) if u != holder else -bet)
            color, title = 0x2ECC71, "🕵️ Skupina odhalila nositele!"
            lines.append(f"🎒 Odměnu měl/a **{_nm(holder)}** — a byl/a odhalen/a!")
            lines.append(f"💰 Pot **{cur_pot}** {minigame_coin()} si rozdělilo {len(winners)} hráčů (~{share}).")
        elif tie:
            if bet > 0:
                for u in players:
                    _payout(u, bet)
            for u in players:
                _record(u, False, 0)
            color, title = 0xF1C40F, "⚖️ Rovnost hlasů!"
            lines.append(f"🎒 Odměnu měl/a **{_nm(holder)}**. Nikdo nezískal většinu — **sázky zpět**.")
        else:
            _payout(holder, cur_pot)
            for u in players:
                _record(u, u == holder, (cur_pot - bet) if u == holder else -bet)
            color, title = 0xE74C3C, "🎭 Nositel splynul!"
            lines.append(f"🎒 Odměnu měl/a **{_nm(holder)}** — a nikdo ho/ji neodhalil!")
            lines.append(f"💰 **{_nm(holder)}** bere celý pot **{cur_pot}** {minigame_coin()}.")

        if votes:
            vlines = []
            for voter in players:
                vlines.append(f"• {_nm(voter)} → " +
                              (f"**{_nm(votes[voter])}**" if voter in votes else "*nehlasoval/a*"))
            lines.append("\n**Jak se hlasovalo:**\n" + "\n".join(vlines))

        # ── statistiky po hře ──
        stat_lines = []
        # Detektiv — kdo trefil nositele
        detectives = [v for v, t in votes.items() if t == holder and v != holder]
        if detectives:
            stat_lines.append("🕵️ **Detektiv:** " + ", ".join(_nm(u) for u in detectives))
        # Nejobviňovanější nevinný — kdo dostal nejvíc hlasů, ale nebyl nositel
        innocent_tally = {t: c for t, c in tally.items() if t != holder}
        if innocent_tally:
            mv = max(innocent_tally.values())
            scapegoats = [u for u, c in innocent_tally.items() if c == mv]
            if scapegoats:
                stat_lines.append(f"🐐 **Obětní beránek:** " + ", ".join(_nm(u) for u in scapegoats)
                                  + f" *({mv} hlasů, ale nevinný)*")
        if stat_lines:
            lines.append("\n" + "\n".join(stat_lines))

        embed = discord.Embed(title=title, description="\n".join(lines), color=color)
        hm = guild.get_member(int(holder))
        if hm:
            embed.set_thumbnail(url=hm.display_avatar.url)
        embed.set_footer(text="🎒 Liar's Briefcase")
        self.active_games.pop(channel.id, None)

        # dramatické odhalení — napětí než padne výsledek
        try:
            suspense = await channel.send(embed=discord.Embed(
                title="🎒 Kufřík se pomalu otevírá…",
                description="*Arion líně zvedla víčko…*", color=0x95A5A6))
            await asyncio.sleep(2.5)
            await suspense.delete()
        except Exception:
            pass
        await channel.send(embed=embed)

    # ── Arion bere vše (nedohlasováno do 10. kola) ────────────────────────────

    async def _arion_takes_all(self, channel, game):
        embed = discord.Embed(
            title="🐱 Arion bere vše!",
            description=("Deset kol uběhlo a nikdo se neodhodlal hlasovat.\n"
                         "Bankéřka **Arion** líně zívla, shrábla celý stůl i vaše sázky "
                         "a odkráčela. *Chamtivost se nevyplácí.*"),
            color=0x34495E,
        )
        embed.set_footer(text="🎒 Liar's Briefcase")
        for u in game["players"]:
            _record(u, False, -game.get("bet", 0))
        self.active_games.pop(channel.id, None)
        await channel.send(embed=embed)

    # ── Admin zrušení ─────────────────────────────────────────────────────────

    @app_commands.command(name="briefcase_cancel", description="[Admin] Zruší probíhající Liar's Briefcase")
    @app_commands.checks.has_permissions(administrator=True)
    async def briefcase_cancel(self, interaction: discord.Interaction):
        game = self.active_games.get(interaction.channel.id)
        if not game:
            return await interaction.response.send_message("Tady žádná hra neběží.", ephemeral=True)
        if game.get("bet", 0) > 0:
            for u in game["players"]:
                _payout(u, game["bet"])
        self.active_games.pop(interaction.channel.id, None)
        await interaction.response.send_message("🚫 Hra zrušena, sázky vráceny.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BriefcaseCog(bot))