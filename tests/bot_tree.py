"""Pomůcka pro testy: postaví skutečný strom příkazů bota bez připojení k Discordu."""
import asyncio
import os
import re
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="arion-tests-"))

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.admin_gate import SHARED_COGS, drop_admin_commands, keep_only_admin

ENTRYPOINTS = ("main_bot.py", "main_dnd.py", "main_dm.py", "main_cards.py")


def cog_list(entrypoint: str) -> list[str]:
    text = open(entrypoint, encoding="utf-8").read()
    body = re.search(r"COGS = \[(.*?)\n\]", text, re.S).group(1)
    cogs = re.findall(r'"(src\.[\w.]+)"', body)
    if entrypoint == "main_dm.py":
        cogs += SHARED_COGS
    return cogs


async def _load(cogs: list[str]) -> commands.Bot:
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default(),
                       help_command=None)
    bot.color = 0x000000
    bot.wiki_url = "https://example.invalid"
    bot.config = {"prefix": "!", "wiki_url": bot.wiki_url,
                  "embed_color": "000000", "campfire_channel": "campfire"}
    for cog in cogs:
        await bot.load_extension(cog)
    return bot


def build_bot(cogs: list[str]) -> commands.Bot:
    return asyncio.run(_load(cogs))


def build_entrypoint(entrypoint: str) -> commands.Bot:
    """Bot i s ořezem stromu, který dělá jeho `setup_hook`."""
    bot = build_bot(cog_list(entrypoint))
    if entrypoint == "main_dm.py":
        keep_only_admin(bot)
    else:
        drop_admin_commands(bot)
    return bot


def full_names(tree: app_commands.CommandTree) -> set[str]:
    """Plná jména příkazů, např. `quest add`."""
    names: set[str] = set()

    def walk(command, prefix: str = ""):
        name = f"{prefix}{command.name}"
        if isinstance(command, app_commands.Group):
            for child in command.commands:
                walk(child, f"{name} ")
        else:
            names.add(name)

    for command in tree.get_commands():
        walk(command)
    return names


def top_level_names(tree: app_commands.CommandTree) -> set[str]:
    return {command.name for command in tree.get_commands()}
