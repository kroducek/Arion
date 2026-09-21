"""
News (Cechovní noviny) cog pro ArionBot
Arion píše vlastní noviny o dění na serveru.

Příkazy:
    /news        — zobrazí aktuální noviny
    /news help   — popis novin
    (správa článků: /admin_news v ArionDM)
"""

import discord
from discord.ext import commands
from discord import app_commands

from src.utils.paths import NEWS as NEWS_PATH
from src.utils.json_utils import load_json, save_json

# ── DATA ──────────────────────────────────────────────────────────────────────

def load_news() -> list:
    data = load_json(NEWS_PATH, default=[])
    return data if isinstance(data, list) else []

def save_news(data: list):
    save_json(NEWS_PATH, data)

# ── EMBEDY ────────────────────────────────────────────────────────────────────

def news_embed(articles: list) -> discord.Embed:
    embed = discord.Embed(
        title="📰 Cechovní noviny Aurionisu",
        description=(
            "*Arion si sedla za psací stůl, olízla tlapku a začala psát...*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0xFFA500
    )

    if not articles:
        embed.add_field(
            name="🐾 Žádné zprávy",
            value="*Arion ještě nic nezapsala. Brzy se něco stane...*",
            inline=False
        )
    else:
        for article in articles:
            date_str = article.get("date", "—")
            title    = article.get("title", "Bez názvu")
            content  = article.get("content", "—")
            embed.add_field(
                name=f"📌 {title}",
                value=f"{content}\n-# *{date_str}*",
                inline=False
            )

    embed.set_footer(text="Arion osobní kronika | Cechovní noviny Aurionisu")
    return embed

# ── COG ───────────────────────────────────────────────────────────────────────

class News(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /news ─────────────────────────────────────────────────────────────────

    news_group = app_commands.Group(name="news", description="Cechovní noviny Aurionisu")

    @news_group.command(name="show", description="Zobrazí aktuální cechovní noviny")
    async def news_show(self, interaction: discord.Interaction):
        articles = load_news()
        await interaction.response.send_message(embed=news_embed(articles))

    @news_group.command(name="help", description="Co jsou cechovní noviny?")
    async def news_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📰 Co jsou Cechovní noviny?",
            description=(
                "*Arion se rozhodla, že svět si zaslouží vědět co se děje...*\n\n"
                "Cechovní noviny jsou místo kde Arion shrnuje vše důležité — "
                "události, oznámení, výsledky turnajů a další dění ve světě Aurionisu.\n\n"
                "**Příkazy:**\n"
                "`/news show` — zobrazí aktuální noviny\n"
                "`/news help` — zobrazí tuto nápovědu\n\n"
                "*Noviny spravují admini. Pokud chceš vidět něco v novinách, zeptej se jich!*"
            ),
            color=0xFFA500
        )
        embed.set_footer(text="Arion osobní kronika | Cechovní noviny Aurionisu")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))
