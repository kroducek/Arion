"""
Minigames Hub — centrální rozcestník miniher přes /minigames
"""
import discord
from discord import app_commands
from discord.ext import commands

COIN = "<:goldcoin:1490171741237018795>"

GAME_INFO = [
    {
        "id":      "guess",
        "label":   "🔍 Hádej kdo",
        "desc":    "Hádej tajné slovo pomocí ano/ne otázek",
        "players": "2–8",
        "bet":     True,
        "cog":     "GuessCog",
        "handler": "guess_start",
    },
    {
        "id":      "liar_dice",
        "label":   "🎲 Kostka lháře",
        "desc":    "Bluffuj s kostkami — poslední přeživší bere pot",
        "players": "2–6",
        "bet":     True,
        "cog":     "LiarDiceCog",
        "handler": "cmd_start",
    },
    {
        "id":      "liar_slots",
        "label":   "🎰 Liar Slots",
        "desc":    "Toč sloty a bluffuj o výsledku",
        "players": "2–8",
        "bet":     True,
        "cog":     "SlotsCog",
        "handler": "liar_slots_cmd",
    },
    {
        "id":      "sibenice",
        "label":   "🪢 Šibenice",
        "desc":    "Hádejte tajnou větu písmeno po písmenu",
        "players": "2–8",
        "bet":     False,
        "cog":     "GallowsCog",
        "handler": "sibenice_cmd",
    },
    {
        "id":      "kostky",
        "label":   "🎯 Kostky",
        "desc":    "Farkle s magickými kostkami a sázkami",
        "players": "2–6",
        "bet":     True,
        "cog":     "Kostky",
        "handler": "kostky_match",
    },
    {
        "id":      "labyrinth",
        "label":   "🚪 Door Labyrinth",
        "desc":    "Sociálně-dedukční — unikni nebo odhal vraha",
        "players": "4–10",
        "bet":     False,
        "cog":     "LabyrinthCog",
        "handler": "labyrinth_start",
    },
]


def _hub_embed() -> discord.Embed:
    lines = []
    for g in GAME_INFO:
        bet_tag = f" | {COIN} sázky" if g["bet"] else ""
        lines.append(f"{g['label']} — **{g['players']} hráčů**{bet_tag}")
        lines.append(f"  ↳ {g['desc']}\n")
    embed = discord.Embed(
        title="🎮 Minihry — Arion",
        description="\n".join(lines).strip(),
        color=0x5865F2,
    )
    embed.set_footer(text="Klikni na tlačítko pro otevření lobby")
    return embed


class BetModal(discord.ui.Modal):
    sazka_input: discord.ui.TextInput = discord.ui.TextInput(
        label="Sázka v zlaťácích (0 = bez sázky)",
        placeholder="0",
        required=False,
        max_length=8,
    )

    def __init__(self, game: dict):
        super().__init__(title=f"{game['label']} — Nastavení sázky")
        self.game = game

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.sazka_input.value.strip()
        try:
            sazka = int(raw) if raw else 0
        except ValueError:
            await interaction.response.send_message("❌ Zadej platné číslo.", ephemeral=True)
            return
        if sazka < 0:
            await interaction.response.send_message("❌ Sázka nesmí být záporná.", ephemeral=True)
            return

        cog = interaction.client.cogs.get(self.game["cog"])
        if not cog:
            await interaction.response.send_message("❌ Minihra není dostupná.", ephemeral=True)
            return
        handler = getattr(cog, self.game["handler"])
        await handler(interaction, sazka=sazka)


class MinigamesHubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        for i, game in enumerate(GAME_INFO):
            btn = discord.ui.Button(
                label=game["label"],
                style=discord.ButtonStyle.primary,
                custom_id=f"hub_{game['id']}",
                row=i // 3,
            )
            btn.callback = _make_callback(game)
            self.add_item(btn)


def _make_callback(game: dict):
    async def callback(interaction: discord.Interaction):
        if game["bet"]:
            await interaction.response.send_modal(BetModal(game))
        else:
            cog = interaction.client.cogs.get(game["cog"])
            if not cog:
                await interaction.response.send_message("❌ Minihra není dostupná.", ephemeral=True)
                return
            handler = getattr(cog, game["handler"])
            await handler(interaction)
    return callback


class MinigamesHubCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="minigames", description="Zobraz všechny minihry a otevři lobby jedním klikem")
    async def minigames_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_hub_embed(), view=MinigamesHubView())


async def setup(bot: commands.Bot):
    await bot.add_cog(MinigamesHubCog(bot))
