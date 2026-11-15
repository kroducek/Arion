import asyncio
import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from src.database import db
from . import service


class ArionAssistant(commands.Cog):
    arion = app_commands.Group(name="arion", description="AI asistent pro vypravěče.",
                               guild_only=True)

    def __init__(self):
        self.role_id = os.getenv("ARION_AI_DM_ROLE_ID", "").strip()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("ARION_AI_MODEL", "").strip()
        self.daily_limit = max(1, int(os.getenv("ARION_AI_DAILY_LIMIT", "50")))
        self.output_limit = max(1, int(os.getenv("ARION_AI_OUTPUT_TOKENS", "800")))
        self.busy = set()

    async def cog_load(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))

    async def cog_unload(self):
        await self.session.close()

    async def interaction_check(self, interaction):
        if isinstance(interaction.user, discord.Member) and any(
            str(role.id) == self.role_id and not role.is_default() for role in interaction.user.roles
        ):
            return True
        await interaction.response.send_message("Potřebuješ autorizovanou roli DM.", ephemeral=True)
        return False

    @arion.command(name="on", description="Zapne ArionAI pro tento server.")
    async def enable(self, interaction: discord.Interaction):
        if not self.api_key or not self.model:
            return await interaction.response.send_message(
                "Doplň OPENAI_API_KEY a ARION_AI_MODEL v prostředí ArionAI.", ephemeral=True)
        db.update_doc(service.state_key(interaction.guild_id), lambda state: state.update(enabled=True))
        await interaction.response.send_message("ArionAI je zapnutý.", ephemeral=True)

    @arion.command(name="off", description="Vypne nové dotazy na tomto serveru.")
    async def disable(self, interaction: discord.Interaction):
        db.update_doc(service.state_key(interaction.guild_id), lambda state: state.update(enabled=False))
        await interaction.response.send_message("ArionAI je vypnutý.", ephemeral=True)

    @arion.command(name="status", description="Zobrazí nastavení a zbývající denní kvótu.")
    async def status(self, interaction: discord.Interaction):
        state = db.load_doc(service.state_key(interaction.guild_id))
        enabled = "zapnutý" if state.get("enabled") else "vypnutý"
        remaining = max(0, self.daily_limit - service.usage(state))
        await interaction.response.send_message(
            f"ArionAI je {enabled}. Model: {self.model or 'nenastaven'}. "
            f"Do půlnoci UTC zbývá {remaining}/{self.daily_limit} dotazů.", ephemeral=True)

    @arion.command(name="ask", description="Zeptej se asistenta pro svět Aurionis.")
    @app_commands.describe(dotaz="Otázka pro ArionAI", zpravy="Kolik posledních zpráv přiložit (0–20)",
                           soukrome="Zobrazit odpověď jen tobě (výchozí: veřejně)")
    async def ask(self, interaction: discord.Interaction, dotaz: app_commands.Range[str, 1, 2000],
                  zpravy: app_commands.Range[int, 0, 20] = 0, soukrome: bool = False):
        uid = interaction.user.id
        if uid in self.busy:
            return await interaction.response.send_message("Tvůj předchozí dotaz ještě běží.", ephemeral=True)
        self.busy.add(uid)
        try:
            if not db.load_doc(service.state_key(interaction.guild_id)).get("enabled"):
                raise service.AskError("ArionAI je na tomto serveru vypnutý.")
            if not self.api_key or not self.model:
                raise service.AskError("ArionAI nemá nastavený klíč nebo model OpenAI.")
            await interaction.response.defer(ephemeral=True, thinking=True)
            history = []
            if zpravy:
                channel = interaction.channel
                if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
                    raise service.AskError("V tomto kanálu nelze načíst historii.")
                for member in (interaction.user, interaction.guild.me):
                    perms = channel.permissions_for(member)
                    if not (perms.view_channel and perms.read_message_history):
                        raise service.AskError("Pro přiložení historie potřebuješ ty i bot oprávnění číst historii kanálu.")
                async for message in channel.history(limit=zpravy, before=interaction.created_at):
                    if message.content:
                        history.append([message.author.display_name, message.content[:400]])
                history.reverse()
            lore = service.lore_context(interaction.guild_id, include_dm_only=soukrome)
            service.reserve(interaction.guild_id, self.daily_limit)
            answer = await service.generate(self.session, self.api_key, self.model, dotaz,
                                            history, lore, self.output_limit)
            chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)]
            if soukrome:
                await interaction.edit_original_response(content=chunks.pop(0))
                for chunk in chunks:
                    await interaction.followup.send(chunk, ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
            else:
                for chunk in chunks:
                    await interaction.channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
                await interaction.edit_original_response(content="Odpověď je v kanálu.")
        except service.AskError as exc:
            await self.error_reply(interaction, str(exc))
        except (aiohttp.ClientError, TimeoutError):
            await self.error_reply(interaction, "OpenAI je dočasně nedostupné nebo vypršel čas na odpověď.")
        except Exception as exc:
            logging.getLogger("ArionAI").warning("Dotaz selhal (%s)", type(exc).__name__)
            await self.error_reply(interaction, "Dotaz se nepodařilo dokončit.")
        finally:
            self.busy.discard(uid)

    @staticmethod
    async def error_reply(interaction, text):
        if interaction.response.is_done():
            await interaction.edit_original_response(content=text)
        else:
            await interaction.response.send_message(text, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ArionAssistant())
