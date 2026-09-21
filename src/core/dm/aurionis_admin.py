"""Adminské utility z Kroniky — běží v ArionDM.

Obsahuje správu turnaje (`/admin_tournament`) a mazání zpráv (`/erase`).
Hráčský `/tournament list` zůstává v ArionDND.
"""
import discord
from discord import app_commands
from discord.ext import commands

from src.core.dnd.aurionis import load_tournament, save_tournament


class AurionisAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    admin_tournament_group = app_commands.Group(
        name="admin_tournament",
        description="Admin: správa turnaje Hvězdy",
        default_permissions=discord.Permissions(administrator=True),
    )

    @admin_tournament_group.command(name="add", description="[ADMIN] Přidá hráče nebo jméno do turnaje")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        jmeno="Jméno NPC nebo vlastní text",
        hrac="Discord hráč (volitelné — místo jména)"
    )
    async def tournament_add(
        self,
        interaction: discord.Interaction,
        jmeno: str = None,
        hrac: discord.Member = None,
    ):
        if not jmeno and not hrac:
            await interaction.response.send_message("Zadej jméno nebo vyber hráče.", ephemeral=True)
            return

        players = load_tournament()
        entry   = str(hrac.id) if hrac else jmeno
        label   = hrac.display_name if hrac else jmeno

        if entry in players or (hrac and str(hrac.id) in [str(p) for p in players]):
            await interaction.response.send_message(
                f"🐾 *Mňau?* `{label}` už v kronice zapsaného mám!", ephemeral=True
            )
            return

        players.append(entry)
        save_tournament(players)
        await interaction.response.send_message(
            f"✅ *Arion zapsala nové jméno do kroniky.* `{label}` postoupil/a do druhého kola!"
        )

    @admin_tournament_group.command(name="remove", description="[ADMIN] Odebere hráče nebo jméno z turnaje")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        jmeno="Jméno NPC nebo vlastní text",
        hrac="Discord hráč (volitelné)"
    )
    async def tournament_remove(
        self,
        interaction: discord.Interaction,
        jmeno: str = None,
        hrac: discord.Member = None,
    ):
        if not jmeno and not hrac:
            await interaction.response.send_message("Zadej jméno nebo vyber hráče.", ephemeral=True)
            return

        players = load_tournament()
        entry   = str(hrac.id) if hrac else jmeno
        label   = hrac.display_name if hrac else jmeno

        # Hledej v seznamu jako string nebo int
        match = None
        for p in players:
            if str(p) == str(entry):
                match = p
                break

        if match is None:
            await interaction.response.send_message(
                f"🐾 *Mňau?* `{label}` v mém seznamu není.", ephemeral=True
            )
            return

        players.remove(match)
        save_tournament(players)
        await interaction.response.send_message(
            f"❌ *Arion přemázla jméno tlapkou.* `{label}` byl/a z turnaje vyřazen/a."
        )

    @tournament_add.error
    @tournament_remove.error
    async def tournament_admin_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Nemáš oprávnění spravovat turnaj.", ephemeral=True)

    @app_commands.command(name="erase", description="Smaže všechny zprávy v této místnosti")
    @app_commands.describe(confirmation="Potvrzení smazání všech zpráv (napiš 'all')")
    async def erase(self, interaction: discord.Interaction, confirmation: str):
        if confirmation.lower() != "all":
            await interaction.response.send_message("Pro smazání všech zpráv použij '/erase all'", ephemeral=True)
            return

        # Kontrola oprávnění
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("Nemáš oprávnění mazat zprávy.", ephemeral=True)
            return

        channel = interaction.channel

        # Defer odpověď, protože mazání může trvat
        await interaction.response.defer(ephemeral=True)

        try:
            # Smaž všechny zprávy (loop kvůli limitu Discordu)
            deleted_count = 0
            while True:
                deleted = await channel.purge(limit=100)
                deleted_count += len(deleted)
                if len(deleted) < 100:
                    break
            await interaction.followup.send(f"✅ Smazáno {deleted_count} zpráv v této místnosti.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Nemám oprávnění mazat zprávy v této místnosti.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při mazání: {str(e)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AurionisAdmin(bot))
