from .cog import LabyrinthCog
from discord.ext import commands


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LabyrinthCog(bot))
