"""Správa cechovních novin — běží v ArionDM. Čtení novin zůstává v ArionBOT."""
import discord
from datetime import datetime
from discord import app_commands
from discord.ext import commands

from src.core.bot.news import load_news, save_news


class NewsAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
    await bot.add_cog(NewsAdmin(bot))
