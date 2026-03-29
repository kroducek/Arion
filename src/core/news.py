"""
News (Cechovní noviny) cog pro ArionBot
Arion píše vlastní noviny o dění na serveru.

Příkazy:
    /news        — zobrazí aktuální noviny
    /news help   — popis novin
    /admin news add title: content:    — přidá článek (admin)
    /admin news remove title:          — odebere článek (admin)
"""

import discord
import json
import os
from datetime import datetime
from discord.ext import commands
from discord import app_commands

from src.utils.paths import NEWS as NEWS_PATH

# ── DATA ──────────────────────────────────────────────────────────────────────

def load_news() -> list:
    if not os.path.exists(NEWS_PATH):
        return []
    try:
        with open(NEWS_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else []
    except Exception:
        return []

def save_news(data: list):
    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

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

    # ── /admin news ───────────────────────────────────────────────────────────

    admin_news_group = app_commands.Group(
        name="admin_news",
        description="Správa cechovních novin (jen admin)",
        default_permissions=discord.Permissions(administrator=True)
    )

    @admin_news_group.command(name="add", description="Přidá článek do novin")
    @app_commands.describe(
        title="Název článku",
        content="Obsah článku"
    )
    async def admin_news_add(self, interaction: discord.Interaction, title: str, content: str):
        articles = load_news()

        # Zkontroluj duplicitní název
        if any(a["title"].lower() == title.lower() for a in articles):
            await interaction.response.send_message(
                f"Článek s názvem **{title}** už existuje. Zvol jiný název nebo ho nejdřív odeber.",
                ephemeral=True
            )
            return

        now     = datetime.now().strftime("%d. %m. %Y")
        article = {"title": title, "content": content, "date": now}
        articles.append(article)
        save_news(articles)

        await interaction.response.send_message(
            f"✅ Článek **{title}** byl přidán do novin.\n"
            f"*Arion si olízla tlapku a zapsala novou zprávu zlatým inkoustem.*",
            ephemeral=True
        )

    @admin_news_group.command(name="remove", description="Odebere článek z novin")
    @app_commands.describe(title="Název článku k odebrání")
    async def admin_news_remove(self, interaction: discord.Interaction, title: str):
        articles = load_news()
        new_list = [a for a in articles if a["title"].lower() != title.lower()]

        if len(new_list) == len(articles):
            await interaction.response.send_message(
                f"Článek **{title}** nebyl nalezen.", ephemeral=True
            )
            return

        save_news(new_list)
        await interaction.response.send_message(
            f"🗑️ Článek **{title}** byl odebrán z novin.\n"
            f"*Arion přemázala řádky tlapkou a mrkla spokojeně.*",
            ephemeral=True
        )

    @admin_news_group.command(name="list", description="Zobrazí seznam všech článků")
    async def admin_news_list(self, interaction: discord.Interaction):
        articles = load_news()
        if not articles:
            await interaction.response.send_message("Žádné články v novinách.", ephemeral=True)
            return
        lines = [f"**{i+1}.** {a['title']} *(přidáno: {a.get('date', '—')})*" for i, a in enumerate(articles)]
        embed = discord.Embed(
            title="📋 Seznam článků v novinách",
            description="\n".join(lines),
            color=0xFFA500
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))