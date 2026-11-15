"""Samostatná Discord aplikace ArionAI."""
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv


class ArionAI(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("src.core.ai.assistant")
        await self.tree.sync()

    async def on_message(self, message):
        # Pouze slash příkazy. Historie se načítá na vyžádání.
        pass


if __name__ == "__main__":
    load_dotenv()
    intents = discord.Intents.default()
    intents.message_content = True
    bot = ArionAI(command_prefix=commands.when_mentioned, intents=intents,
                  help_command=None, allowed_mentions=discord.AllowedMentions.none())
    bot.run(os.environ["DISCORD_TOKEN_AI"])
