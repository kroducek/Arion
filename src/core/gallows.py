"""
Šibenice – Hangman minihra pro ArionBot
=========================================
Příkazy:
  /sibenice        – spustí hru
  /sibenice_cancel – [Admin] zruší probíhající hru
"""

import random
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
    # 6 — plná šibenice (oběšen)
    ("  ╔═══╗\n"
     "  ║   ║\n"
     "  ║   ●\n"
     "  ║  /│\\\n"
     "  ║  / \\\n"
     "══╩════"),
]


# ── Herní helpers ─────────────────────────────────────────────────────────────

def _display_sentence(sentence: str, guessed: set[str]) -> str:
    """Zobrazí větu s _ pro neuhádnutá písmena."""
    parts = []
    for ch in sentence:
        if ch == " ":
            parts.append("   ")          # oddělovač slov
        elif not ch.isalpha():
            parts.append(ch)             # interpunkce rovnou
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
            "Ostatní hádají písmena — každá chyba staví šibenici.\n"
            "6 chyb = oběšení. Pokud nikdo větu neuhodne, vyhrává šibeničář.\n\n"
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
            await interaction.response.send_message(
                "Zakladatel nemůže odejít. Použij Zrušit.", ephemeral=True
            )
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
            await interaction.response.send_message(
                f"Potřeba alespoň {MIN_PLAYERS} hráče.", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content="🪢 **Šibenice** se spouští…", embed=None, view=None
        )
        await self.cog._start_game(interaction.channel, self.players)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger, custom_id="gal_cancel_lobby")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (interaction.user.id != self.author.id
                and not interaction.user.guild_permissions.administrator):
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
            await interaction.response.send_message(
                "Věta musí obsahovat aspoň jedno písmeno.", ephemeral=True
            )
            return

        game["sentence"] = raw
        game["phase"]    = "playing"
        await interaction.response.send_message("✅ Věta uložena! Hra začíná.", ephemeral=True)

        channel = self.cog.bot.get_channel(self.channel_id)
        if channel:
            await self.cog._begin_playing(channel, game)


class SentenceInputView(discord.ui.View):
    """Ephemeral view v DM šibeničáře."""
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
# HÁDÁNÍ
# ══════════════════════════════════════════════════════════════════════════════

class GuessModal(discord.ui.Modal, title="Hádat"):
    guess = discord.ui.TextInput(
        label="Písmeno — nebo celá věta (= -2 chyby při špatné)",
        placeholder="1 písmeno, nebo celá věta najednou",
        max_length=80,
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

        text = self.guess.value.strip()
        if len(text) == 1 and text.isalpha():
            await self.cog._process_letter(interaction, game, uid, text.lower())
        elif len(text) > 1:
            await self.cog._process_sentence(interaction, game, uid, text)
        else:
            await interaction.response.send_message(
                "Zadej jedno písmeno nebo celou větu.", ephemeral=True
            )


class GallowsGameView(discord.ui.View):
    def __init__(self, cog: "GallowsCog", channel_id: int):
        super().__init__(timeout=None)
        self.cog        = cog
        self.channel_id = channel_id

    @discord.ui.button(label="🔤 Hádat", style=discord.ButtonStyle.primary, custom_id="gal_guess")
    async def guess_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "playing":
            await interaction.response.send_message(
                "Šibeničář ještě nezadal větu. Počkejte!", ephemeral=True
            )
            return
        uid = str(interaction.user.id)
        if uid == game["hangman_uid"]:
            await interaction.response.send_message("Jsi šibeničář — nehádáš!", ephemeral=True)
            return
        pdata = game["players"].get(uid)
        if not pdata:
            await interaction.response.send_message("Nejsi v této hře.", ephemeral=True)
            return
        if not pdata["alive"]:
            await interaction.response.send_message("☠️ Jsi oběšen — nemůžeš hádat.", ephemeral=True)
            return
        await interaction.response.send_modal(GuessModal(self.cog, self.channel_id))


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
        if game.get("game_view"):
            game["game_view"].stop()
        await interaction.response.send_message("🛑 Hra zrušena.")

    # ── Spuštění ──────────────────────────────────────────────────────────────

    async def _start_game(self, channel: discord.TextChannel, players: list[discord.Member]):
        hangman  = random.choice(players)
        guessers = [p for p in players if p.id != hangman.id]

        game: dict = {
            "channel_id":   channel.id,
            "phase":        "waiting",
            "hangman_uid":  str(hangman.id),
            "hangman_name": hangman.display_name,
            "sentence":     "",
            "guessed":      set(),
            "players": {
                str(p.id): {"name": p.display_name, "alive": True, "wrong": 0}
                for p in guessers
            },
            "board_msg": None,
            "game_view":  None,
        }
        self.active_games[channel.id] = game

        # Nastav board zprávu (bez view — přidáme po zadání věty)
        wait_e = discord.Embed(
            title="🪢 Šibenice",
            description=f"✏️ **{hangman.display_name}** (šibeničář) píše větu… čekejte.",
            color=0x2C3E50,
        )
        board_msg = await channel.send(embed=wait_e)
        game["board_msg"] = board_msg

        # Pošli šibeničáři DM s tlačítkem
        hangman_member = channel.guild.get_member(hangman.id)
        input_view = SentenceInputView(self, channel.id)
        if hangman_member:
            dm_e = discord.Embed(
                title="🪢 Šibenice — Jsi šibeničář!",
                description=(
                    "Napiš větu, kterou budou ostatní hádat.\n"
                    "Ostatní uvidí jen `_ _ _` za každé písmeno.\n\n"
                    "Máš 2 minuty."
                ),
                color=0x2C3E50,
            )
            try:
                await hangman_member.send(embed=dm_e, view=input_view)
            except discord.Forbidden:
                # DM zakázány — zkusíme ephemeral v kanálu
                await channel.send(
                    f"{hangman_member.mention} — máš DM zakázány! "
                    f"Hra nemůže pokračovat.",
                )
                self.active_games.pop(channel.id, None)

    # ── Začátek hry ───────────────────────────────────────────────────────────

    async def _begin_playing(self, channel: discord.TextChannel, game: dict):
        e    = self._build_embed(game)
        view = GallowsGameView(self, channel.id)
        game["game_view"] = view

        if game.get("board_msg"):
            try:
                await game["board_msg"].edit(embed=e, view=view)
                return
            except Exception:
                pass
        msg = await channel.send(embed=e, view=view)
        game["board_msg"] = msg

    # ── Hádání písmene ────────────────────────────────────────────────────────

    async def _process_letter(
        self, interaction: discord.Interaction, game: dict, uid: str, letter: str
    ):
        channel = interaction.client.get_channel(game["channel_id"])
        pdata   = game["players"][uid]

        if letter in game["guessed"]:
            await interaction.response.send_message(
                f"Písmeno **{letter.upper()}** už bylo hádáno.", ephemeral=True
            )
            return

        game["guessed"].add(letter)
        sentence = game["sentence"]

        if letter in sentence.lower():
            count = sentence.lower().count(letter)
            await interaction.response.send_message(
                f"✅ **{pdata['name']}** uhádl/a **{letter.upper()}** — {count}× ve větě!",
                ephemeral=False,
            )
            if _is_complete(sentence, game["guessed"]):
                await self._end_game(channel, game, winner_uid=uid)
                return
        else:
            pdata["wrong"] += 1
            await interaction.response.send_message(
                f"❌ **{pdata['name']}** zkusil/a **{letter.upper()}** "
                f"— není ve větě! ({pdata['wrong']}/{MAX_WRONG})",
                ephemeral=False,
            )
            if pdata["wrong"] >= MAX_WRONG:
                pdata["alive"] = False
                await channel.send(f"☠️ **{pdata['name']}** byl/a oběšen/a!")
                if self._all_dead(game):
                    await self._end_game(channel, game, winner_uid=None)
                    return

        try:
            await game["board_msg"].edit(embed=self._build_embed(game))
        except Exception:
            pass

    # ── Hádání celé věty ──────────────────────────────────────────────────────

    async def _process_sentence(
        self, interaction: discord.Interaction, game: dict, uid: str, text: str
    ):
        channel = interaction.client.get_channel(game["channel_id"])
        pdata   = game["players"][uid]

        if _sentence_matches(game["sentence"], text):
            await interaction.response.send_message(
                f"🎉 **{pdata['name']}** uhádl/a celou větu!", ephemeral=False
            )
            await self._end_game(channel, game, winner_uid=uid)
        else:
            pdata["wrong"] = min(pdata["wrong"] + 2, MAX_WRONG)
            await interaction.response.send_message(
                f"❌ **{pdata['name']}** zkusil/a celou větu — špatně! "
                f"+2 chyby → {pdata['wrong']}/{MAX_WRONG}",
                ephemeral=False,
            )
            if pdata["wrong"] >= MAX_WRONG:
                pdata["alive"] = False
                await channel.send(f"☠️ **{pdata['name']}** byl/a oběšen/a za špatný tip!")
                if self._all_dead(game):
                    await self._end_game(channel, game, winner_uid=None)
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

        # Šibenice dle nejhoršího živého hráče
        alive_wrongs = [p["wrong"] for p in game["players"].values() if p["alive"]]
        worst  = max(alive_wrongs, default=0)
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
        e.set_footer(text="🔤 Hádat = 1 písmeno nebo celá věta najednou (špatná věta = +2 chyby)")
        return e

    # ── Konec hry ─────────────────────────────────────────────────────────────

    async def _end_game(
        self, channel: discord.TextChannel, game: dict, winner_uid: str | None
    ):
        self.active_games.pop(channel.id, None)
        if game.get("game_view"):
            game["game_view"].stop()

        sentence = game["sentence"]
        e = discord.Embed(title="🪢 Šibenice — Konec!", color=0x2C3E50)

        if winner_uid:
            wname = game["players"][winner_uid]["name"]
            e.description = f"🎉 **{wname}** uhádl/a větu a vyhrál/a!\n\nVěta byla: **{sentence}**"
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
