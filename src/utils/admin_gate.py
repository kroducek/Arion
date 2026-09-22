"""Rozdělení příkazů mezi hráčské boty (ArionDND/ArionBOT) a ArionDM.

Cogy zůstávají jedny — admin příkazy se jen označí `@admin_only()` a každý bot
si před syncem ze svého stromu odstraní to, co mu nepatří:

    ArionDND / ArionBOT →  drop_admin_commands(bot)   # zmizí admin příkazy
    ArionDM             →  keep_only_admin(bot)       # zůstanou jen admin příkazy

Skupina (`app_commands.Group`) se ořezává po podpříkazech; když v ní nic
nezbude, zmizí celá. Ořezávají se jen příkazy ze `SHARED_COGS` — cogy, které
patří výhradně jednomu botovi, zůstávají nedotčené.
"""
from typing import Callable, TypeVar

from discord import app_commands
from discord.ext import commands

# Cogy, které načítají ArionDND i ArionDM. ArionDND z nich zahodí admin
# příkazy, ArionDM naopak všechno ostatní.
SHARED_COGS = [
    "src.core.dnd.quests",
    "src.core.dnd.achievements",
    "src.core.dnd.perks",
    "src.core.dnd.ranks",
    "src.core.dnd.blacksmith",
    "src.core.dnd.takedown",
    "src.logic.profile",
    "src.logic.stats",
    "src.logic.inventory",
    "src.logic.onboard",
    "src.logic.memory",
    "src.logic.economy",
    "src.logic.reputation",
    "src.logic.rpmanage",
    "src.logic.spirits",
]

_ADMIN_CALLBACKS: set[Callable] = set()

F = TypeVar("F", bound=Callable)


def mark_admin(func: F) -> F:
    """Označí příkaz jako adminský bez přidání kontroly práv.

    Pro příkazy, které si oprávnění hlídají samy uvnitř (např. `manage_messages`).
    """
    _ADMIN_CALLBACKS.add(func)
    return func


def admin_only() -> Callable[[F], F]:
    """`@admin_only()` = kontrola na administrátora + značka pro ArionDM."""
    def decorator(func: F) -> F:
        mark_admin(func)
        return app_commands.checks.has_permissions(administrator=True)(func)
    return decorator


def is_admin_command(command: app_commands.Command) -> bool:
    return command.callback in _ADMIN_CALLBACKS


def _is_shared(command: app_commands.Command | app_commands.Group) -> bool:
    return command.module in SHARED_COGS


def _prune_group(group: app_commands.Group, keep_admin: bool) -> bool:
    """Ořeže podpříkazy skupiny. Vrací True, když ve skupině něco zbylo."""
    for child in list(group.commands):
        if isinstance(child, app_commands.Group):
            if not _prune_group(child, keep_admin):
                group.remove_command(child.name)
        elif _is_shared(child) and is_admin_command(child) is not keep_admin:
            group.remove_command(child.name)
    return bool(group.commands)


def _prune_tree(bot: commands.Bot, keep_admin: bool) -> list[str]:
    removed: list[str] = []
    for command in list(bot.tree.get_commands()):
        if isinstance(command, app_commands.Group):
            if not _prune_group(command, keep_admin):
                bot.tree.remove_command(command.name)
                removed.append(command.name)
        elif isinstance(command, app_commands.Command):
            if _is_shared(command) and is_admin_command(command) is not keep_admin:
                bot.tree.remove_command(command.name)
                removed.append(command.name)
    return removed


def drop_admin_commands(bot: commands.Bot) -> list[str]:
    """Hráčský bot: zahodí admin příkazy ze sdílených cogů (běží pod ArionDM)."""
    return _prune_tree(bot, keep_admin=False)


def keep_only_admin(bot: commands.Bot) -> list[str]:
    """ArionDM: ze sdílených cogů nechá jen admin příkazy."""
    return _prune_tree(bot, keep_admin=True)


def drop_listeners(bot: commands.Bot) -> None:
    """Vypne listenery sdílených cogů — ArionDM je jen konzole na admin příkazy.

    Bez toho by na událost (např. `on_member_join`) reagovali dva boti naráz.
    """
    for cog in bot.cogs.values():
        if type(cog).__module__ not in SHARED_COGS:
            continue
        for name, listener in cog.get_listeners():
            bot.remove_listener(listener, name)


__all__ = [
    "SHARED_COGS",
    "admin_only",
    "mark_admin",
    "is_admin_command",
    "drop_admin_commands",
    "keep_only_admin",
    "drop_listeners",
]
