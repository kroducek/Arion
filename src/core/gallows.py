"""
Šibenice – Hangman minihra pro ArionBot
=========================================
Příkazy:
  /sibenice        – spustí hru
  /sibenice_cancel – [Admin] zruší probíhající hru

Průběh:
  Každé kolo mají hráči 30s na hlasování pro písmeno.
  Nejpopulárnější písmeno padá — špatné dá +1 chybu VŠEM.
  Kdokoliv může kdykoli tipnout celou větu (+2 chyby při omylu).
"""

import random
from collections import Counter
import discord
from discord import app_commands
from discord.ext import commands

# ── Konstanty ─────────────────────────────────────────────────────────────────

MIN_PLAYERS = 2
MAX_PLAYERS = 8
MAX_WRONG   = 6

_GALLOWS = [
    # 0 chyb
    ("  ╔═══╗\n"
     "  ║    \n"
     "  ║    \n"
     "  ║    \n"
     "══╩════"),
    # 1 — hlava
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║    \n"
     "══╩════"),
    # 2 — trup
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║   │\n"
     "══╩════"),
    # 3 — levá ruka
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║  /│\n"
     "══╩════"),
    # 4 — pravá ruka
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║  /│\\\n"
     "══╩════"),
    # 5 — levá noha
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║  /│\\\n"
     "  ║  /  \n"
     "══╩════"),
    # 6 — plná šibenice
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║  /│\\\n"
     "  ║  / \\\n"
     "══╩════"),
]


# ── Herní helpers ─────────────────────────────────────────────────────────────

def _display_sentence(sentence: str, guessed: set[str]) -> str:
    parts = []
    for ch in sentence:
        if ch == " ":
            parts.append("   ")
        elif not ch.isalpha():
            parts.append(ch)
        elif ch.lower() in guessed:
            parts.append(ch.upper())
        else:
            parts.append("_")
    return " ".join(parts)


def _is_complete(sentence: str, guessed: set[str]) -> bool:
    return all(not ch.isalpha() or ch.lower() in guessed for ch in sentence)


def _sentence_matches(sentence: str, guess: str) -> bool:
    return sentence.strip().lower() == guess.strip().lower()


def _standing_line(name: str, wrong: int, alive: bool) -> str:
    if not alive:
        return f"☠️ ~~{name}~~"
    bar = "█" * wrong + "░" * (MAX_WRONG - wrong)
    return f"🟢 **{name}** `{bar}` {wrong}/{MAX_WRONG}"


# ══════════════════════════════════════════════════════════════════════════════
# LOBBY
# ══════════════════════════════════════════════════════════════════════════════

class GallowsLobbyView(discord.ui.View):
    def __init__(self, cog: "GallowsCog", author: discord.Member):
        super().__init__(timeout=120)
        self.cog    = cog
        self.author = author
        self.players: list[discord.Member] = [author]

    def _embed(self) -> discord.Embed:
        names = "\n".join(f"• {m.display_name}" for m in self.players)
        e = discord.Embed(title="🪢 Šibenice — Lobby", color=0x2C3E50)
        e.description = (
            "Náhodný hráč se stane **šibeničářem** a napíše větu.\n"
            "Ostatní hádají hlasováním — každé kolo 30s na výběr písmene.\n"
            "Špatné písmeno = +1 chyba **všem**. 6 chyb = oběšení.\n\n"
            f"**Hráči ({len(self.players)}/{MAX_PLAYERS}):**\n{names}"
        )
        return e

    @discord.ui.button(label="🙋 Připojit se", style=discord.ButtonStyle.success, custom_id="gal_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.players:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message("Lobby je plné!", ephemeral=True)
            return
        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="🚪 Odejít", style=discord.ButtonStyle.secondary, custom_id="gal_leave")
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message("Zakladatel nemůže odejít. Použij Zrušit.", ephemeral=True)
            return
        if interaction.user not in self.players:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶️ Spustit", style=discord.ButtonStyle.primary, custom_id="gal_start")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            await interaction.response.send_message("Hru může spustit jen zakladatel.", ephemeral=True)
            return
        if len(self.players) < MIN_PLAYERS:
            await interaction.response.send_message(f"Potřeba alespoň {MIN_PLAYERS} hráče.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="🪢 **Šibenice** se spouští…", embed=None, view=None)
        await self.cog._start_game(interaction.channel, self.players)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger, custom_id="gal_cancel_lobby")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze zakladatel nebo admin.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="🚫 Lobby zrušeno.", embed=None, view=None)


# ══════════════════════════════════════════════════════════════════════════════
# ZADÁNÍ VĚTY  (šibeničář přes DM)
# ══════════════════════════════════════════════════════════════════════════════

class SentenceModal(discord.ui.Modal, title="Napiš svou větu"):
    sentence = discord.ui.TextInput(
        label="Věta (max 80 znaků)",
        placeholder="Např.: Arion je nejlepší bot",
        max_length=80,
        min_length=2,
    )

    def __init__(self, cog: "GallowsCog", channel_id: int):
        super().__init__()
        self.cog        = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "waiting":
            await interaction.response.send_message("Hra již začala nebo skončila.", ephemeral=True)
            return
        raw = self.sentence.value.strip()
        if not any(ch.isalpha() for ch in raw):
            await interaction.response.send_message("Věta musí obsahovat aspoň jedno písmeno.", ephemeral=True)
            return
        game["sentence"] = raw
        game["phase"]    = "playing"
        await interaction.response.send_message("✅ Věta uložena! Hra začíná.", ephemeral=True)
        channel = self.cog.bot.get_channel(self.channel_id)
        if channel:
            await self.cog._begin_playing(channel, game)


class SentenceInputView(discord.ui.View):
    def __init__(self, cog: "GallowsCog", channel_id: int):
        super().__init__(timeout=120)
        self.cog        = cog
        self.channel_id = channel_id
        self._submitted = False

    @discord.ui.button(label="✏️ Zadat větu", style=discord.ButtonStyle.primary, custom_id="gal_sentence")
    async def sentence_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._submitted:
            await interaction.response.send_message("Větu jsi již zadal/a.", ephemeral=True)
            return
        self._submitted = True
        self.stop()
        await interaction.response.send_modal(SentenceModal(self.cog, self.channel_id))

    async def on_timeout(self):
        game    = self.cog.active_games.get(self.channel_id)
        channel = self.cog.bot.get_channel(self.channel_id)
        if game and channel and game["phase"] == "waiting":
            self.cog.active_games.pop(self.channel_id, None)
            await channel.send("⏱️ Šibeničář nestihl zadat větu — hra zrušena.")


# ══════════════════════════════════════════════════════════════════════════════
# HLASOVÁNÍ O PÍSMENU
# ══════════════════════════════════════════════════════════════════════════════

class VoteLetterModal(discord.ui.Modal, title="Hlasovat pro písmeno"):
    letter = discord.ui.TextInput(
        label="Napiš písmeno, pro které hlasujete",
        placeholder="např. A, E, R…",
        max_length=2,
        min_length=1,
    )

    def __init__(self, cog: "GallowsCog", channel_id: int):
        super().__init__()
        self.cog        = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "playing":
            await interaction.response.send_message("Hra neprobíhá.", ephemeral=True)
            return
        uid   = str(interaction.user.id)
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Jsi mimo hru.", ephemeral=True)
            return
        raw = self.letter.value.strip().lower()
        if len(raw) != 1 or not raw.isalpha():
            await interaction.response.send_message("Zadej přesně jedno písmeno.", ephemeral=True)
            return
        if raw in game["guessed"]:
            await interaction.response.send_message(f"Písmeno **{raw.upper()}** už bylo hádáno.", ephemeral=True)
            return

        game["current_votes"][uid] = raw
        await interaction.response.send_message(f"✅ Hlasoval/a jsi pro **{raw.upper()}**", ephemeral=True)

        channel = self.cog.bot.get_channel(self.channel_id)
        if game.get("board_msg"):
            try:
                await game["board_msg"].edit(embed=self.cog._build_embed(game))
            except Exception:
                pass

        # Všichni živí hlasovali → tally okamžitě
        alive_uids = {u for u, p in game["players"].items() if p["alive"]}
        if alive_uids <= set(game["current_votes"]):
            view = game.get("vote_view")
            if view and not view._tallied:
                view._tallied = True
                view.stop()
                if channel:
                    await self.cog._tally_votes(channel, game)


class GuessSentenceModal(discord.ui.Modal, title="Hádat celou větu"):
    sentence = discord.ui.TextInput(
        label="Napiš větu (+2 chyby pokud špatně)",
        placeholder="Např.: Arion je nejlepší bot",
        max_length=80,
        min_length=2,
    )

    def __init__(self, cog: "GallowsCog", channel_id: int):
        super().__init__()
        self.cog        = cog
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "playing":
            await interaction.response.send_message("Hra neprobíhá.", ephemeral=True)
            return
        uid   = str(interaction.user.id)
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Jsi mimo hru.", ephemeral=True)
            return
        await self.cog._process_sentence(interaction, game, uid, self.sentence.value.strip())


class VoteView(discord.ui.View):
    """30s hlasovací kolo — hráči volí písmeno."""

    def __init__(self, cog: "GallowsCog", channel_id: int):
        super().__init__(timeout=30)
        self.cog        = cog
        self.channel_id = channel_id
        self._tallied   = False

    @discord.ui.button(label="🗳️ Hlasovat pro písmeno", style=discord.ButtonStyle.primary, custom_id="gal_vote")
    async def vote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "playing":
            await interaction.response.send_message("Hra neprobíhá.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        if uid == game["hangman_uid"]:
            await interaction.response.send_message("Jsi šibeničář — nehádáš!", ephemeral=True)
            return
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi v hře nebo jsi oběšen.", ephemeral=True)
            return
        if uid in game["current_votes"]:
            await interaction.response.send_message(
                f"Už jsi hlasoval/a pro **{game['current_votes'][uid].upper()}**.", ephemeral=True
            )
            return
        await interaction.response.send_modal(VoteLetterModal(self.cog, self.channel_id))

    @discord.ui.button(label="📝 Tipnout celou větu", style=discord.ButtonStyle.secondary, custom_id="gal_sentence_guess")
    async def sentence_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "playing":
            await interaction.response.send_message("Hra neprobíhá.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        if uid == game["hangman_uid"]:
            await interaction.response.send_message("Jsi šibeničář — nehádáš!", ephemeral=True)
            return
        pdata = game["players"].get(uid)
        if not pdata or not pdata["alive"]:
            await interaction.response.send_message("Nejsi v hře nebo jsi oběšen.", ephemeral=True)
            return
        await interaction.response.send_modal(GuessSentenceModal(self.cog, self.channel_id))

    async def on_timeout(self):
        if self._tallied:
            return
        self._tallied = True
        game    = self.cog.active_games.get(self.channel_id)
        channel = self.cog.bot.get_channel(self.channel_id)
        if game and channel and game["phase"] == "playing":
            await self.cog._tally_votes(channel, game)


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class GallowsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, dict] = {}

    # ── Příkazy ───────────────────────────────────────────────────────────────

    @app_commands.command(name="sibenice", description="Spustí hru Šibenice")
    async def sibenice_cmd(self, interaction: discord.Interaction):
        if interaction.channel_id in self.active_games:
            await interaction.response.send_message("Ve tomto kanálu již běží hra!", ephemeral=True)
            return
        view = GallowsLobbyView(self, interaction.user)
        await interaction.response.send_message(embed=view._embed(), view=view)

    @app_commands.command(name="sibenice_cancel", description="[Admin] Zruší probíhající Šibenici")
    async def sibenice_cancel_cmd(self, interaction: discord.Interaction):
        if interaction.channel_id not in self.active_games:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Pouze admin může zrušit hru.", ephemeral=True)
            return
        game = self.active_games.pop(interaction.channel_id)
        if game.get("vote_view"):
            game["vote_view"].stop()
        await interaction.response.send_message("🛑 Hra zrušena.")

    # ── Spuštění ──────────────────────────────────────────────────────────────

    async def _start_game(self, channel: discord.TextChannel, players: list[discord.Member]):
        hangman  = random.choice(players)
        guessers = [p for p in players if p.id != hangman.id]

        game: dict = {
            "channel_id":    channel.id,
            "phase":         "waiting",
            "hangman_uid":   str(hangman.id),
            "hangman_name":  hangman.display_name,
            "sentence":      "",
            "guessed":       set(),
            "current_votes": {},
            "players": {
                str(p.id): {"name": p.display_name, "alive": True, "wrong": 0}
                for p in guessers
            },
            "board_msg": None,
            "vote_view":  None,
        }
        self.active_games[channel.id] = game

        wait_e = discord.Embed(
            title="🪢 Šibenice",
            description=f"✏️ **{hangman.display_name}** (šibeničář) píše větu… čekejte.",
            color=0x2C3E50,
        )
        game["board_msg"] = await channel.send(embed=wait_e)

        hangman_member = channel.guild.get_member(hangman.id)
        input_view = SentenceInputView(self, channel.id)
        if hangman_member:
            dm_e = discord.Embed(
                title="🪢 Šibenice — Jsi šibeničář!",
                description=(
                    "Napiš větu, kterou budou ostatní hádat.\n"
                    "Ostatní uvidí jen `_ _ _` za každé písmeno.\n\nMáš 2 minuty."
                ),
                color=0x2C3E50,
            )
            try:
                await hangman_member.send(embed=dm_e, view=input_view)
            except discord.Forbidden:
                await channel.send(f"{hangman_member.mention} — máš DM zakázány! Hra nemůže pokračovat.")
                self.active_games.pop(channel.id, None)

    # ── Začátek hry ───────────────────────────────────────────────────────────

    async def _begin_playing(self, channel: discord.TextChannel, game: dict):
        await self._start_vote_round(channel, game)

    # ── Hlasovací kolo ────────────────────────────────────────────────────────

    async def _start_vote_round(self, channel: discord.TextChannel, game: dict):
        game["current_votes"] = {}
        view = VoteView(self, channel.id)
        game["vote_view"] = view

        e = self._build_embed(game)
        if game.get("board_msg"):
            try:
                await game["board_msg"].edit(embed=e, view=view)
                return
            except Exception:
                pass
        game["board_msg"] = await channel.send(embed=e, view=view)

    async def _tally_votes(self, channel: discord.TextChannel, game: dict):
        votes = game.get("current_votes", {})

        if not votes:
            await channel.send("⏱️ Nikdo nezhlasoval — kolo přeskočeno.")
            if game["phase"] == "playing":
                await self._start_vote_round(channel, game)
            return

        counts  = Counter(votes.values())
        max_cnt = max(counts.values())
        winners = [l for l, c in counts.items() if c == max_cnt]
        chosen  = random.choice(winners)

        summary = "  ".join(f"**{l.upper()}** ×{c}" for l, c in counts.most_common())
        suffix  = f"— Remíza! Padlo: **{chosen.upper()}**" if len(winners) > 1 else f"— Padá: **{chosen.upper()}**"
        await channel.send(f"🗳️ {summary}  {suffix}")

        await self._process_letter(channel, game, chosen)

    # ── Zpracování písmene (skupinové) ────────────────────────────────────────

    async def _process_letter(self, channel: discord.TextChannel, game: dict, letter: str):
        game["guessed"].add(letter)
        sentence = game["sentence"]

        if letter in sentence.lower():
            count = sentence.lower().count(letter)
            await channel.send(f"✅ **{letter.upper()}** je ve větě! ({count}×)")
            if _is_complete(sentence, game["guessed"]):
                await self._end_game(channel, game, winner="skupina")
                return
        else:
            await channel.send(f"❌ **{letter.upper()}** není ve větě! Všichni dostávají +1 chybu.")
            for pdata in game["players"].values():
                if pdata["alive"]:
                    pdata["wrong"] += 1
                    if pdata["wrong"] >= MAX_WRONG:
                        pdata["alive"] = False
                        await channel.send(f"☠️ **{pdata['name']}** byl/a oběšen/a!")
            if self._all_dead(game):
                await self._end_game(channel, game, winner=None)
                return

        try:
            await game["board_msg"].edit(embed=self._build_embed(game))
        except Exception:
            pass
        await self._start_vote_round(channel, game)

    # ── Hádání celé věty (individuální) ──────────────────────────────────────

    async def _process_sentence(
        self, interaction: discord.Interaction, game: dict, uid: str, text: str
    ):
        channel = interaction.client.get_channel(game["channel_id"])
        pdata   = game["players"][uid]

        if _sentence_matches(game["sentence"], text):
            await interaction.response.send_message(
                f"🎉 **{pdata['name']}** uhádl/a celou větu!", ephemeral=False
            )
            view = game.get("vote_view")
            if view and not view._tallied:
                view._tallied = True
                view.stop()
            await self._end_game(channel, game, winner=pdata["name"])
        else:
            pdata["wrong"] = min(pdata["wrong"] + 2, MAX_WRONG)
            await interaction.response.send_message(
                f"❌ **{pdata['name']}** zkusil/a celou větu — špatně! +2 chyby → {pdata['wrong']}/{MAX_WRONG}",
                ephemeral=False,
            )
            if pdata["wrong"] >= MAX_WRONG:
                pdata["alive"] = False
                await channel.send(f"☠️ **{pdata['name']}** byl/a oběšen/a za špatný tip!")
                if self._all_dead(game):
                    view = game.get("vote_view")
                    if view and not view._tallied:
                        view._tallied = True
                        view.stop()
                    await self._end_game(channel, game, winner=None)
                    return
            try:
                await game["board_msg"].edit(embed=self._build_embed(game))
            except Exception:
                pass

    # ── Board embed ───────────────────────────────────────────────────────────

    def _build_embed(self, game: dict) -> discord.Embed:
        sentence = game["sentence"]
        guessed  = game["guessed"]
        display  = _display_sentence(sentence, guessed)

        alive_wrongs = [p["wrong"] for p in game["players"].values() if p["alive"]]
        worst       = max(alive_wrongs, default=0)
        gallows_str = _GALLOWS[min(worst, MAX_WRONG)]

        e = discord.Embed(
            title=f"🪢 Šibenice | Šibeničář: {game['hangman_name']}",
            color=0x2C3E50,
        )
        e.description = f"```\n{gallows_str}\n\n{display}\n```"

        guessed_str = " ".join(sorted(g.upper() for g in guessed)) or "—"
        e.add_field(name="Uhádnutá písmena", value=guessed_str, inline=False)

        standings = "\n".join(
            _standing_line(p["name"], p["wrong"], p["alive"])
            for p in game["players"].values()
        )
        e.add_field(name="Hráči", value=standings or "—", inline=False)

        votes       = game.get("current_votes", {})
        total_alive = sum(1 for p in game["players"].values() if p["alive"])
        if votes:
            lines    = [f"• {game['players'][u]['name']}: **{l.upper()}**" for u, l in votes.items() if u in game["players"]]
            vote_str = "\n".join(lines) + f"\n*({len(votes)}/{total_alive} hlasovalo)*"
        else:
            vote_str = f"*Čeká se na hlasy… (0/{total_alive})*"
        e.add_field(name="🗳️ Hlasování", value=vote_str, inline=False)

        e.set_footer(text="🗳️ Hlasuj pro písmeno (30s) | 📝 Celá věta = okamžitý tip (+2 chyby při omylu)")
        return e

    # ── Konec hry ─────────────────────────────────────────────────────────────

    async def _end_game(self, channel: discord.TextChannel, game: dict, winner: str | None):
        self.active_games.pop(channel.id, None)
        if game.get("vote_view"):
            game["vote_view"].stop()

        sentence = game["sentence"]
        e = discord.Embed(title="🪢 Šibenice — Konec!", color=0x2C3E50)
        if winner:
            e.description = f"🎉 **{winner}** uhádl/a větu a vyhrál/a!\n\nVěta byla: **{sentence}**"
            e.color = 0x27AE60
        else:
            e.description = (
                f"🏆 **{game['hangman_name']}** (šibeničář) vyhrál/a — nikdo větu neuhodl!\n\n"
                f"Věta byla: **{sentence}**"
            )
            e.color = 0xFF4500

        try:
            await game["board_msg"].edit(embed=e, view=None)
        except Exception:
            await channel.send(embed=e)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _all_dead(self, game: dict) -> bool:
        return all(not p["alive"] for p in game["players"].values())


async def setup(bot: commands.Bot):
    await bot.add_cog(GallowsCog(bot))
