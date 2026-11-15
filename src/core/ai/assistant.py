import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from src.database import db
from . import service


async def read_history(interaction, count):
    channel = interaction.channel
    if not callable(getattr(channel, "history", None)):
        raise service.AskError("V tomto kanálu nelze načíst historii.")
    for perms in (interaction.permissions, interaction.app_permissions):
        if not (perms.view_channel and perms.read_message_history):
            raise service.AskError("Ty i ArionAI potřebujete v tomto kanálu oprávnění číst historii.")

    records = []
    async for message in channel.history(limit=100, before=interaction.created_at, oldest_first=False):
        if message.is_system() or (message.author.bot and not message.webhook_id):
            continue
        content = message.clean_content.strip()
        if not content:
            continue
        records.append({"autor": message.author.display_name, "ucet": message.author.name,
                        "text": content[:1000]})
        if len(records) == count:
            break
    records.reverse()
    return records


class ArionAssistant(commands.Cog):
    arion = app_commands.Group(name="arion", description="AI asistent pro vypravěče.",
                               guild_only=True)

    def __init__(self):
        self.role_id = os.getenv("ARION_AI_DM_ROLE_ID", "").strip()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("ARION_AI_MODEL", "").strip()
        missing = [name for name, value in (("OPENAI_API_KEY", self.api_key),
                                           ("ARION_AI_MODEL", self.model)) if not value]
        self.config_error = "V prostředí ArionAI chybí: " + ", ".join(missing) if missing else ""
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
        if self.config_error:
            return await interaction.response.send_message(self.config_error, ephemeral=True)
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
    @app_commands.describe(dotaz="Otázka pro ArionAI", zpravy="Kolik textových zpráv přiložit (výchozí 20, 0 vypne historii pro tento dotaz)",
                           soukrome="Zobrazit odpověď jen tobě (výchozí: veřejně)")
    async def ask(self, interaction: discord.Interaction, dotaz: app_commands.Range[str, 1, 2000],
                  zpravy: app_commands.Range[int, 0, 20] = 20, soukrome: bool = False):
        uid = interaction.user.id
        if uid in self.busy:
            return await interaction.response.send_message("Tvůj předchozí dotaz ještě běží.", ephemeral=True)
        self.busy.add(uid)
        step = "kontrola nastavení"
        try:
            if not db.load_doc(service.state_key(interaction.guild_id)).get("enabled"):
                raise service.AskError("ArionAI je na tomto serveru vypnutý.")
            if self.config_error:
                raise service.AskError(self.config_error)
            if not soukrome:
                perms = interaction.app_permissions
                in_thread = isinstance(interaction.channel, discord.Thread)
                can_send = perms.send_messages_in_threads if in_thread else perms.send_messages
                if not can_send:
                    raise service.AskError("ArionAI sem nemůže posílat zprávy. Povol mu zápis "
                                           "nebo použij soukrome: ano.")
            step = "potvrzení příkazu v Discordu"
            await interaction.response.defer(ephemeral=True, thinking=True)
            history = []
            if zpravy:
                step = "načítání historie kanálu"
                history = await read_history(interaction, zpravy)
                if not history:
                    raise service.AskError(
                        "Mezi posledními 100 zprávami zde není čitelný text hráčů. "
                        "Zkus napsat běžnou textovou zprávu do stejného kanálu. Pro dotaz bez historie zadej zpravy:0.")
            step = "příprava podkladů a rezervace kvóty"
            lore = service.lore_context(interaction.guild_id, include_dm_only=soukrome)
            service.reserve(interaction.guild_id, self.daily_limit)
            step = "volání OpenAI"
            answer = await service.generate(self.session, self.api_key, self.model, dotaz,
                                            history, lore, self.output_limit)
            step = "doručení odpovědi do Discordu"
            chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)]
            authors = ", ".join(dict.fromkeys(discord.utils.escape_markdown(r["autor"]) for r in history))
            receipt = f"Historie pro tento dotaz: {len(history)} zpráv" + (f" · {authors}" if authors else "")
            if soukrome:
                await interaction.edit_original_response(content=chunks.pop(0))
                for chunk in chunks:
                    await interaction.followup.send(chunk, ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
                await interaction.followup.send(receipt, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            else:
                for chunk in chunks:
                    await interaction.channel.send(chunk, allowed_mentions=discord.AllowedMentions.none())
                await interaction.edit_original_response(content="Odpověď je v kanálu. " + receipt)
        except service.AskError as exc:
            await self.error_reply(interaction, str(exc))
        except (aiohttp.ClientError, TimeoutError):
            await self.error_reply(interaction, "OpenAI je dočasně nedostupné nebo vypršel čas na odpověď.")
        except Exception as exc:
            kind = type(exc).__name__
            logging.getLogger("ArionAI").warning("Dotaz %s selhal při kroku '%s' (%s)",
                                                 interaction.id, step, kind)
            await self.error_reply(interaction, f"Dotaz selhal při kroku „{step}“ ({kind}).")
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
