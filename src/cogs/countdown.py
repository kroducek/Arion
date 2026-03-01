import discord
from discord.ext import commands
from discord import app_commands
import asyncio

class Countdown(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Definice Slash Commandu
    @app_commands.command(name="countdown", description="Spustí epický odpočet")
    @app_commands.describe(sekundy="Kolik sekund má odpočet trvat?")
    async def countdown(self, interaction: discord.Interaction, sekundy: int):
        # Slash commandy používají 'interaction' místo 'ctx'
        
        # Odeslání první odpovědi (musí se potvrdit přijetí interakce)
        embed = discord.Embed(
            title="⏳ SEQUENCE INITIATED",
            description="Probíhá synchronizace dat...",
            color=discord.Color.red()
        )
        embed.add_field(name="STATUS", value=f"```00:00:{sekundy:02d}```", inline=False)
        
        # U slash commandů používáme response.send_message
        await interaction.response.send_message(embed=embed)
        # Pro následné úpravy potřebujeme objekt zprávy
        msg = await interaction.original_response()

        while sekundy > 0:
            await asyncio.sleep(5)  # Interval 5 sekund podle tvého přání
            sekundy -= 5
            if sekundy < 0: sekundy = 0

            # Formátování času (HH:MM:SS)
            mins, secs = divmod(sekundy, 60)
            hours, mins = divmod(mins, 60)
            time_format = f"{hours:02d}:{mins:02d}:{secs:02d}"

            new_embed = discord.Embed(
                title="⌛ FINAL COUNTDOWN",
                description="Něco velkého se blíží!",
                color=discord.Color.red()
            )
            new_embed.add_field(name="TIME REMAINING", value=f"```\n{time_format}\n```", inline=False)
            new_embed.set_footer(text="Hype is real!")
            
            await msg.edit(embed=new_embed)

        # Finále po doběhnutí
        final_embed = discord.Embed(
            title="🔥 BOOM! JE TO TADY!",
            description="Akce právě začala! @everyone",
            color=discord.Color.gold()
        )
        final_embed.set_image(url="https://media.discordapp.net/attachments/1130940860113092639/1477324236862394510/togif.gif?ex=69a458e9&is=69a30769&hm=b97f1dd3fab95e9186407910ff2a9d08fcc1f6b5ba71fccfafff1118130d9b60&=&width=548&height=306")
        
        await msg.edit(embed=final_embed)

async def setup(bot):
    await bot.add_cog(Countdown(bot))