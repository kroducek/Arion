import discord
from discord.ext import commands
from discord import app_commands
import json
import os

DATA_FILE = "profiles.json"
ECONOMY_FILE = "economy.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_economy():
    if os.path.exists(ECONOMY_FILE):
        try:
            with open(ECONOMY_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except:
            pass
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Zobrazí tvůj dobrodružný průkaz")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        data = load_data()
        user_id = str(target.id)

        if user_id not in data:
            await interaction.response.send_message(
                f"**{target.display_name}** zatím nemá průkaz dobrodruha. Musí projít tutoriálem!",
                ephemeral=True
            )
            return

        user_profile = data[user_id]
        economy = load_economy()
        balance = economy.get(user_id, 0)

        embed = discord.Embed(
            title=f"📜 Průkaz dobrodruha: {user_profile.get('name', target.display_name)}",
            color=0x3498db
        )
        
        embed.add_field(name="🎖️ Rank", value=user_profile.get("rank", "F3"), inline=True)
        embed.add_field(name="👤 Jméno", value=user_profile.get("name", "—"), inline=True)
        embed.add_field(name="<:goldcoin:1477303464781680772> Zlaťáky", value=str(balance), inline=True)

        if "motivation" in user_profile:
            embed.add_field(name="✨ Motivace", value=user_profile.get("motivation"), inline=False)

        if user_profile.get("portrait_url"):
            embed.set_image(url=user_profile.get("portrait_url"))
        
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text=f"ID: {user_id} | Aurionis: Act II")

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Profile(bot))