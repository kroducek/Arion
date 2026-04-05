"""
Guess Who – minihra pro ArionBot
Každý hráč dostane tajné slovo od jiného hráče a pokládá ano/ne otázky,
dokud se nepokusí uhádnout přes /guess tip. První kdo uhodne, bere pot.
"""
import discord
import random
from discord import app_commands
from discord.ext import commands

from src.utils.paths import ECONOMY as ECONOMY_FILE, GUESS_SCORES as SCORES_FILE
from src.utils.json_utils import load_json, save_json

COIN        = "<:goldcoin:1490171741237018795>"
MAX_GUESSES = 3
MIN_PLAYERS = 2
MAX_PLAYERS = 8

# ══════════════════════════════════════════════════════════════════════════════
# DATOVÁ VRSTVA
# ══════════════════════════════════════════════════════════════════════════════

def _load_economy() -> dict:
    return load_json(ECONOMY_FILE) or {}

def _save_economy(data: dict):
    save_json(ECONOMY_FILE, data)

def _load_scores() -> dict:
    return load_json(SCORES_FILE) or {}

def _save_scores(data: dict):
    save_json(SCORES_FILE, data)

# ══════════════════════════════════════════════════════════════════════════════
# MODAL – zadání slova
# ══════════════════════════════════════════════════════════════════════════════

class WordModal(discord.ui.Modal):
    word = discord.ui.TextInput(
        label="Zadej jedno slovo (podstatné jméno)",
        placeholder="např. drak, meč, poklad...",
        max_length=30,
        min_length=1,
    )

    def __init__(self, cog: "GuessCog", channel_id: int, target_name: str):
        super().__init__(title=f"Slovo pro {target_name}")
        self.cog        = cog
        self.channel_id = channel_id
        self.target_name = target_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "words":
            await interaction.followup.send("Fáze slov už skončila.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid not in game["assignments"]:
            await interaction.followup.send("Nejsi hráčem této hry.", ephemeral=True)
            return
        if uid in game["words_submitted"]:
            await interaction.followup.send("✅ Slovo jsi už zadal/a.", ephemeral=True)
            return

        raw = self.word.value.strip()
        if not raw or " " in raw:
            await interaction.followup.send("Zadej jedno slovo bez mezer.", ephemeral=True)
            return

        # Ulož slovo – bude hadáno hráčem, jemuž bylo přiřazeno
        guesser_uid = game["assignments"][uid]
        game["words"][guesser_uid] = raw
        game["words_submitted"].add(uid)

        remaining = len(game["assignments"]) - len(game["words_submitted"])
        await interaction.followup.send(
            f"✅ Slovo pro **{self.target_name}** bylo uloženo. "
            + (f"Čeká se ještě na {remaining} hráče." if remaining else ""),
            ephemeral=True
        )

        # Pokud všichni zadali, spusť hru
        if len(game["words_submitted"]) == len(game["assignments"]):
            channel = interaction.client.get_channel(self.channel_id)
            if channel:
                await self.cog._start_game_phase(channel, game)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – tlačítko pro zadání slova
# ══════════════════════════════════════════════════════════════════════════════

class WordSubmitView(discord.ui.View):
    def __init__(self, cog: "GuessCog", channel_id: int):
        super().__init__(timeout=300)   # 5 minut
        self.cog        = cog
        self.channel_id = channel_id

    @discord.ui.button(label="📝 Zadat slovo", style=discord.ButtonStyle.primary)
    async def submit_word(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "words":
            await interaction.response.send_message("Fáze slov skončila.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid not in game["assignments"]:
            await interaction.response.send_message("Nejsi v této hře.", ephemeral=True)
            return
        if uid in game["words_submitted"]:
            await interaction.response.send_message("✅ Slovo jsi už zadal/a.", ephemeral=True)
            return

        target_uid  = game["assignments"][uid]
        target_name = game["player_names"][target_uid]
        await interaction.response.send_modal(
            WordModal(self.cog, self.channel_id, target_name)
        )

    async def on_timeout(self):
        game = self.cog.active_games.get(self.channel_id)
        if not game or game["phase"] != "words":
            return

        # Doplň fallback slova pro hráče, kteří nestihli zadat
        fallback = ["drak", "hrad", "meč", "poklad", "labyrint", "věštkyně", "hvězda", "přízrak"]
        for uid, guesser_uid in game["assignments"].items():
            if uid not in game["words_submitted"] and guesser_uid not in game["words"]:
                game["words"][guesser_uid] = random.choice(fallback)

        channel = self.cog.bot.get_channel(self.channel_id)
        if channel:
            await channel.send("⏰ Čas na zadávání slov vypršel! Chybějící slova byla doplněna automaticky.")
            await self.cog._start_game_phase(channel, game)


# ══════════════════════════════════════════════════════════════════════════════
# VIEW – lobby
# ══════════════════════════════════════════════════════════════════════════════

class GuessLobby(discord.ui.View):
    def __init__(self, cog: "GuessCog", author: discord.Member, bet: int):
        super().__init__(timeout=None)
        self.cog     = cog
        self.author  = author
        self.bet     = bet
        self.players = [author]

    def _embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🔍 Hádej kdo — Lobby",
            description=(
                "*Každý hráč dostane od jiného tajné slovo. "
                "Pokládej ano/ne otázky a uhádni co jsi! "
                "První kdo uhodne, bere celý pot.*\n\n"
                "**Pravidla:**\n"
                "• Hráči se střídají v kladení otázek (nebo volně, po domluvě)\n"
                "• Každá otázka musí mít odpověď **Ano** nebo **Ne**\n"
                f"• Každý hráč má **{MAX_GUESSES} pokusy** uhadnout přes `/guess tip`\n"
                "• Kdo uhodne první, vyhrává celý pot"
            ),
            color=0x9B59B6
        )
        names = "\n".join(f"• {p.display_name}" for p in self.players)
        embed.add_field(name=f"Hráči ({len(self.players)}/{MAX_PLAYERS})", value=names, inline=False)
        embed.add_field(name="Sázka", value=f"{self.bet} {COIN} každý", inline=True)
        embed.add_field(name="Pot",   value=f"{self.bet * len(self.players)} {COIN}", inline=True)
        embed.set_footer(text=f"Min. {MIN_PLAYERS} hráči | Zakladatel spouští hru")
        return embed

    @discord.ui.button(label="Připojit se", style=discord.ButtonStyle.success, custom_id="guess_join")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [p.id for p in self.players]:
            await interaction.response.send_message("Už jsi v lobby!", ephemeral=True)
            return
        if len(self.players) >= MAX_PLAYERS:
            await interaction.response.send_message(f"Lobby je plné ({MAX_PLAYERS} hráčů).", ephemeral=True)
            return

        uid     = str(interaction.user.id)
        economy = _load_economy()
        balance = economy.get(uid, 0)
        if balance < self.bet:
            await interaction.response.send_message(
                f"❌ Nemáš dost zlaťáků! Potřebuješ **{self.bet}** {COIN}, máš **{balance}**.",
                ephemeral=True
            )
            return

        economy[uid] = balance - self.bet
        _save_economy(economy)
        self.players.append(interaction.user)
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="Odejít", style=discord.ButtonStyle.secondary, custom_id="guess_leave")
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.author.id:
            await interaction.response.send_message(
                "Zakladatel nemůže odejít. Použij tlačítko Zrušit.", ephemeral=True
            )
            return
        if interaction.user.id not in [p.id for p in self.players]:
            await interaction.response.send_message("Nejsi v lobby.", ephemeral=True)
            return

        uid     = str(interaction.user.id)
        economy = _load_economy()
        economy[uid] = economy.get(uid, 0) + self.bet
        _save_economy(economy)
        self.players = [p for p in self.players if p.id != interaction.user.id]
        await interaction.response.edit_message(embed=self._embed())

    @discord.ui.button(label="▶ Start", style=discord.ButtonStyle.primary, custom_id="guess_start_btn")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Pouze zakladatel může spustit hru!", ephemeral=True)
            return
        if len(self.players) < MIN_PLAYERS:
            await interaction.response.send_message(
                f"Potřebuješ alespoň {MIN_PLAYERS} hráče!", ephemeral=True
            )
            return

        self.stop()
        await interaction.response.edit_message(
            content="🔍 **Hádej kdo** — Zadávání slov začíná!",
            embed=None, view=None
        )
        await self.cog._begin_word_phase(interaction.channel, self.players, self.bet)

    @discord.ui.button(label="🚫 Zrušit", style=discord.ButtonStyle.danger, custom_id="guess_cancel_lobby")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.user.guild_permissions.administrator
        if interaction.user.id != self.author.id and not is_admin:
            await interaction.response.send_message("Pouze zakladatel nebo admin může zrušit hru.", ephemeral=True)
            return

        economy = _load_economy()
        for p in self.players:
            uid = str(p.id)
            economy[uid] = economy.get(uid, 0) + self.bet
        _save_economy(economy)

        self.stop()
        await interaction.response.edit_message(
            content="🚫 Hra byla zrušena. Sázky vráceny.", embed=None, view=None
        )


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class GuessCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot          = bot
        self.active_games: dict[int, dict] = {}   # channel_id → game state

    # ── Fáze: přiřazení slov ─────────────────────────────────────────────────

    async def _begin_word_phase(self, channel: discord.TextChannel,
                                players: list[discord.Member], bet: int):
        shuffled = players[:]
        random.shuffle(shuffled)

        # Cirkulární přiřazení: player[i] píše slovo pro player[(i+1)%n]
        assignments: dict[str, str] = {}   # uid_pisatele → uid_hadajiciho
        for i, p in enumerate(shuffled):
            writer_uid  = str(p.id)
            guesser_uid = str(shuffled[(i + 1) % len(shuffled)].id)
            assignments[writer_uid] = guesser_uid

        player_names = {str(p.id): p.display_name for p in shuffled}

        self.active_games[channel.id] = {
            "phase":           "words",
            "players":         shuffled,
            "player_names":    player_names,
            "player_ids":      [str(p.id) for p in shuffled],
            "assignments":     assignments,   # writer_uid → guesser_uid
            "words":           {},            # guesser_uid → tajné slovo
            "words_submitted": set(),         # uid_pisatelů, kteří zadali
            "guesses_left":    {str(p.id): MAX_GUESSES for p in shuffled},
            "eliminated":      set(),
            "bet":             bet,
            "pot":             bet * len(shuffled),
        }

        lines = []
        for p in shuffled:
            target_name = player_names[assignments[str(p.id)]]
            lines.append(f"• **{p.display_name}** píše slovo pro **{target_name}**")

        embed = discord.Embed(
            title="📝 Zadávání slov",
            description=(
                "Každý hráč musí kliknout na tlačítko níže a tajně zadat slovo "
                "pro přiřazeného hráče.\n\n"
                + "\n".join(lines)
            ),
            color=0x3498DB
        )
        embed.set_footer(text=f"Čas: 5 minut | Pot: {bet * len(shuffled)} {COIN}")

        view = WordSubmitView(self, channel.id)
        await channel.send(embed=embed, view=view)

    # ── Fáze: hra ────────────────────────────────────────────────────────────

    async def _start_game_phase(self, channel: discord.TextChannel, game: dict):
        game["phase"] = "game"

        status_lines = [
            f"• {p.mention} — {game['guesses_left'][str(p.id)]} pokus(y)"
            for p in game["players"]
        ]

        embed = discord.Embed(
            title="🔍 Hádej kdo — ZAČÍNÁME!",
            description=(
                "Všechna slova byla přiřazena. Hra začíná!\n\n"
                "**Jak hrát:**\n"
                "Pokládejte si navzájem ano/ne otázky v tomto kanálu.\n"
                "Kdo si je jistý, použije `/guess tip <slovo>` pro odhad.\n\n"
                "**Hráči:**\n" + "\n".join(status_lines)
            ),
            color=0x27AE60
        )
        embed.add_field(name="💰 Pot",    value=f"**{game['pot']}** {COIN}", inline=True)
        embed.add_field(name="🎯 Pokusy", value=f"**{MAX_GUESSES}** na hráče",  inline=True)
        embed.set_footer(text="Tip: /guess tip <slovo> • Stav: /guess status")
        await channel.send(embed=embed)

        # ── DM každému hráči: slova všech ostatních (ne jeho vlastní) ───────────
        for p in game["players"]:
            uid = str(p.id)
            others_lines = "\n".join(
                f"• **{q.display_name}** hádá: `{game['words'].get(str(q.id), '???')}`"
                for q in game["players"] if q.id != p.id
            )
            dm_embed = discord.Embed(
                title="🔍 Hádej kdo — Slova ostatních",
                description=(
                    f"Hra začala v {channel.mention}!\n\n"
                    f"**Co hádají ostatní hráči:**\n{others_lines}\n\n"
                    "Odpovídej na jejich otázky — a pokládej vlastní!\n"
                    f"Své slovo hádej přes `/guess tip <slovo>` ({MAX_GUESSES} pokusy)."
                ),
                color=0x9B59B6
            )
            dm_embed.set_footer(text="Tuto zprávu vidíš jen ty.")
            try:
                await p.send(embed=dm_embed)
            except discord.Forbidden:
                pass  # hráč má vypnuté DMs

    # ── Logika hádání ─────────────────────────────────────────────────────────

    async def _process_guess(self, interaction: discord.Interaction, slovo: str):
        game = self.active_games.get(interaction.channel.id)
        if not game or game["phase"] != "game":
            await interaction.response.send_message("Žádná hra neběží v tomto kanálu.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        if uid not in game["player_ids"]:
            await interaction.response.send_message("Nejsi v této hře.", ephemeral=True)
            return
        if uid in game["eliminated"]:
            await interaction.response.send_message(
                "Byl/a jsi vyřazen/a — nemáš žádné pokusy.", ephemeral=True
            )
            return
        if uid not in game["words"]:
            await interaction.response.send_message(
                "Tvoje slovo ještě nebylo přiřazeno (chyba).", ephemeral=True
            )
            return

        correct = game["words"][uid].lower().strip()
        guess   = slovo.lower().strip()

        if guess == correct:
            # ── Výhra ────────────────────────────────────────────────────────
            game["phase"] = "finished"

            economy      = _load_economy()
            economy[uid] = economy.get(uid, 0) + game["pot"]
            _save_economy(economy)

            scores      = _load_scores()
            scores[uid] = scores.get(uid, 0) + 1
            _save_scores(scores)

            reveal_lines = [
                f"• {p.display_name}: **{game['words'].get(str(p.id), '???')}**"
                for p in game["players"]
            ]
            embed = discord.Embed(
                title="🏆 VÍTĚZ!",
                description=(
                    f"🎉 {interaction.user.mention} uhodl/a své slovo!\n\n"
                    f"Tajné slovo bylo: **{game['words'][uid]}**\n"
                    f"Výhra: **{game['pot']}** {COIN}"
                ),
                color=0xF1C40F
            )
            embed.add_field(
                name="Odhalení všech slov",
                value="\n".join(reveal_lines),
                inline=False
            )
            embed.set_footer(text=f"Skóre +1 pro {interaction.user.display_name}")
            await interaction.response.send_message(embed=embed)
            del self.active_games[interaction.channel.id]

        else:
            # ── Špatný odhad ─────────────────────────────────────────────────
            game["guesses_left"][uid] -= 1
            left = game["guesses_left"][uid]

            if left <= 0:
                game["eliminated"].add(uid)
                await interaction.response.send_message(
                    f"❌ Špatně! Vyčerpal/a jsi všechny pokusy — jsi vyřazen/a.\n"
                    f"-# Tvoje slovo bylo: ||{game['words'][uid]}||",
                    ephemeral=True
                )
                # Zkontroluj zbývající hráče
                active = [i for i in game["player_ids"] if i not in game["eliminated"]]
                if len(active) == 1:
                    # Poslední hráč automaticky vyhral
                    winner_uid = active[0]
                    winner     = next(p for p in game["players"] if str(p.id) == winner_uid)
                    game["phase"] = "finished"

                    economy            = _load_economy()
                    economy[winner_uid] = economy.get(winner_uid, 0) + game["pot"]
                    _save_economy(economy)

                    scores             = _load_scores()
                    scores[winner_uid] = scores.get(winner_uid, 0) + 1
                    _save_scores(scores)

                    reveal_lines = [
                        f"• {p.display_name}: **{game['words'].get(str(p.id), '???')}**"
                        for p in game["players"]
                    ]
                    embed = discord.Embed(
                        title="🏆 POSLEDNÍ PŘEŽIVŠÍ — VÍTĚZ!",
                        description=(
                            f"Všichni ostatní vypadli.\n"
                            f"{winner.mention} vyhrává jako poslední přeživší!\n\n"
                            f"Výhra: **{game['pot']}** {COIN}"
                        ),
                        color=0xF1C40F
                    )
                    embed.add_field(
                        name="Odhalení všech slov",
                        value="\n".join(reveal_lines),
                        inline=False
                    )
                    embed.set_footer(text=f"Skóre +1 pro {winner.display_name}")
                    await interaction.channel.send(embed=embed)
                    del self.active_games[interaction.channel.id]
                elif not active:
                    await self._end_no_winner(interaction.channel, game)
                    del self.active_games[interaction.channel.id]
            else:
                await interaction.response.send_message(
                    f"❌ Špatně! Zbývají ti **{left}** pokus(y).",
                    ephemeral=True
                )

    async def _end_no_winner(self, channel: discord.TextChannel, game: dict):
        reveal_lines = [
            f"• {p.display_name}: **{game['words'].get(str(p.id), '???')}**"
            for p in game["players"]
        ]
        embed = discord.Embed(
            title="💀 Konec hry — nikdo nevyhrál",
            description=(
                "Všichni hráči vyčerpali pokusy. Pot propadá.\n\n"
                "**Odhalení slov:**\n" + "\n".join(reveal_lines)
            ),
            color=0x95A5A6
        )
        embed.set_footer(text=f"Pot {game['pot']} {COIN} byl ztracen")
        await channel.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # SLASH COMMANDY
    # ══════════════════════════════════════════════════════════════════════════

    guess = app_commands.Group(name="guess", description="Minihra: Hádej kdo")

    @guess.command(name="start", description="Vytvoří lobby pro hru Hádej kdo")
    @app_commands.describe(sazka="Vstupní sázka každého hráče v zlaťácích (výchozí: 50)")
    async def guess_start(self, interaction: discord.Interaction, sazka: int = 50):
        if interaction.channel.id in self.active_games:
            await interaction.response.send_message("V tomto kanálu už hra běží!", ephemeral=True)
            return
        if sazka < 1:
            await interaction.response.send_message("Sázka musí být alespoň 1 zlaťák.", ephemeral=True)
            return

        uid     = str(interaction.user.id)
        economy = _load_economy()
        balance = economy.get(uid, 0)
        if balance < sazka:
            await interaction.response.send_message(
                f"❌ Nemáš dost zlaťáků! Potřebuješ **{sazka}** {COIN}, máš **{balance}**.",
                ephemeral=True
            )
            return

        economy[uid] = balance - sazka
        _save_economy(economy)

        view = GuessLobby(self, interaction.user, sazka)
        await interaction.response.send_message(embed=view._embed(), view=view)

    @guess.command(name="tip", description="Zkus uhádnout své tajné slovo (3 pokusy)")
    @app_commands.describe(slovo="Tvůj tip — jedno slovo")
    async def guess_tip(self, interaction: discord.Interaction, slovo: str):
        await self._process_guess(interaction, slovo)

    @guess.command(name="status", description="Zobraz stav aktuální hry v tomto kanálu")
    async def guess_status(self, interaction: discord.Interaction):
        game = self.active_games.get(interaction.channel.id)
        if not game:
            await interaction.response.send_message("V tomto kanálu žádná hra neběží.", ephemeral=True)
            return

        phase_label = {
            "words":    "📝 Zadávání slov",
            "game":     "🎮 Probíhá hra",
            "finished": "✅ Dokončeno",
        }.get(game["phase"], game["phase"])

        lines = []
        for p in game["players"]:
            uid  = str(p.id)
            left = game["guesses_left"].get(uid, 0)
            stat = "❌ vyřazen/a" if uid in game["eliminated"] else f"❤️ {left} pokus(y)"
            lines.append(f"• {p.display_name} — {stat}")

        embed = discord.Embed(
            title="🔍 Hádej kdo — Stav hry",
            description="\n".join(lines),
            color=0x3498DB
        )
        embed.add_field(name="Fáze", value=phase_label,           inline=True)
        embed.add_field(name="Pot",  value=f"{game['pot']} {COIN}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @guess.command(name="leaderboard", description="Žebříček nejlepších hráčů Hádej kdo")
    async def guess_leaderboard(self, interaction: discord.Interaction):
        scores = _load_scores()
        if not scores:
            await interaction.response.send_message("Žebříček je zatím prázdný.", ephemeral=True)
            return

        top     = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        medals  = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        lines   = []
        for i, (uid, wins) in enumerate(top):
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"<@{uid}>"
            lines.append(f"{medals[i]} **{name}** — {wins} výher")

        embed = discord.Embed(
            title="🔍 Hádej kdo — Žebříček",
            description="\n".join(lines),
            color=0x9B59B6
        )
        embed.set_footer(text="Top 10 hráčů | počet výher")
        await interaction.response.send_message(embed=embed)

    @guess.command(name="cancel", description="[Admin] Zruší hru a vrátí sázky")
    @app_commands.checks.has_permissions(administrator=True)
    async def guess_cancel(self, interaction: discord.Interaction):
        game = self.active_games.pop(interaction.channel.id, None)
        if not game:
            await interaction.response.send_message("Žádná hra neběží.", ephemeral=True)
            return

        economy = _load_economy()
        for p in game["players"]:
            uid          = str(p.id)
            economy[uid] = economy.get(uid, 0) + game["bet"]
        _save_economy(economy)

        await interaction.response.send_message("🚫 Hra byla zrušena. Sázky vráceny.")

    @guess_cancel.error
    async def cancel_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Jen admin může zrušit hru.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GuessCog(bot))
