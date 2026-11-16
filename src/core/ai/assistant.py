import asyncio
import logging
import os
import re
import sqlite3
from contextlib import closing

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from src.database import db
from . import archives, service
from .canon import CanonDraft


def archive_channel(interaction, question, selected):
    """Parametr archiv nebo první explicitní odkaz na kanál v dotazu."""
    if selected is None:
        ref = re.search(r"<#(\d+)>|(?:^|\s)#([\w-]+)", question)
        if not ref:
            matches = []
            registry = archives.registered(interaction.guild_id)
            for row in registry:
                channel = interaction.guild.get_channel(row["channel"])
                if channel and any(archives.alias_match(n, question) for n in row["names"].split(",")):
                    if all(channel.permissions_for(m).read_message_history and channel.permissions_for(m).view_channel
                           for m in (interaction.user, interaction.guild.me)):
                        exact = any(f" {archives.normalize(n.strip())} " in
                                    f" {' '.join(archives.words(question))} " for n in row["names"].split(","))
                        matches.append((exact, channel))
            if any(exact for exact, _ in matches):
                matches = [item for item in matches if item[0]]
            if len(matches) > 1:
                raise service.AskError("Dotaz odpovídá více archivům. Vyber zdroj v parametru archiv.")
            if matches:
                selected = matches[0][1]
            elif any(row["channel"] == interaction.channel_id for row in registry):
                selected = interaction.channel
            else:
                return None
        elif ref[1]:
            selected = interaction.guild.get_channel(int(ref[1]))
        else:
            selected = discord.utils.find(
                lambda c: c.name.casefold() == ref[2].casefold(), interaction.guild.text_channels)
    if not isinstance(selected, discord.TextChannel) or selected.guild.id != interaction.guild_id:
        raise service.AskError("Archiv není dostupný. Vyber textový kanál v parametru archiv.")
    for member in (interaction.user, interaction.guild.me):
        perms = selected.permissions_for(member)
        if not (perms.view_channel and perms.read_message_history):
            raise service.AskError("Pro čtení archivu potřebujete ty i ArionAI přístup k jeho historii.")
    return selected


async def search_archive(channel, question, phrase, interaction):
    # Jednorázový výběr kanálu nepovoluje trvalé ukládání jeho obsahu.
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.row_factory = sqlite3.Row
        archives.setup(conn)
        conn.execute("INSERT INTO ai_archives(guild,channel,names) VALUES(?,?,?)",
                     (channel.guild.id, channel.id, ""))
        rows = [archives.rows_for(msg, interaction.client.user.id)
                async for msg in channel.history(limit=500, before=interaction.created_at, oldest_first=False)]
        conn.executemany("INSERT INTO ai_messages(channel,id,author,body,searchable) VALUES(?,?,?,?,?)", rows)
        return archives.select_scene(channel, question, phrase, [], interaction.id, conn)


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
    all_group = app_commands.Group(name="all", description="Přístup hráčů k ArionAI.", parent=arion)

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
        self.index_tasks = {}
        self.indexed = set()
        self.first_pages = {}

    async def cog_load(self):
        archives.setup()
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))

    async def cog_unload(self):
        tasks = list(self.index_tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.session.close()

    def start_index(self, channel):
        if channel.id in self.index_tasks or channel.id in self.indexed:
            return
        with db.transaction() as conn:
            conn.execute("UPDATE ai_archives SET complete=0 WHERE channel=?", (channel.id,))
            conn.execute("DELETE FROM ai_messages WHERE channel=?", (channel.id,))
        self.first_pages[channel.id] = asyncio.Event()
        self.index_tasks[channel.id] = asyncio.create_task(self.build_index(channel))

    async def build_index(self, channel):
        try:
            perms = channel.permissions_for(channel.guild.me)
            if not (perms.view_channel and perms.read_message_history):
                return
            batch = []
            async for message in channel.history(limit=None, oldest_first=False):
                batch.append(archives.rows_for(message, self.bot.user.id))
                if len(batch) >= 100:
                    archives.insert_batch(batch)
                    self.first_pages[channel.id].set()
                    batch.clear()
            archives.insert_batch(batch)
            db.connect().execute("UPDATE ai_archives SET complete=1 WHERE channel=?", (channel.id,))
            self.indexed.add(channel.id)
        except Exception as exc:
            logging.getLogger("ArionAI").warning("Index %s: %s", channel.id, type(exc).__name__)
        finally:
            self.first_pages.pop(channel.id).set()
            self.index_tasks.pop(channel.id, None)

    @commands.Cog.listener()
    async def on_ready(self):
        # Nová gateway session mohla zmeškat editace a smazání během odstávky.
        self.indexed.clear()
        for guild in self.bot.guilds:
            for row in archives.registered(guild.id):
                channel = guild.get_channel(row["channel"])
                if channel:
                    self.start_index(channel)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id in self.index_tasks or message.channel.id in self.indexed:
            archives.insert_batch([archives.rows_for(message, self.bot.user.id)], replace=True)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if payload.channel_id not in self.index_tasks and payload.channel_id not in self.indexed:
            return
        if "content" in payload.data:
            body = payload.data["content"].strip()
            row = db.connect().execute("SELECT author FROM ai_messages WHERE channel=? AND id=?",
                                       (payload.channel_id, payload.message_id)).fetchone()
            if row is not None and row["author"]:
                db.connect().execute("UPDATE ai_messages SET body=?,searchable=? WHERE channel=? AND id=?",
                                     (body, archives.normalize(body), payload.channel_id, payload.message_id))
            elif row is None or body:
                channel = self.bot.get_channel(payload.channel_id)
                if channel:
                    try:
                        message = await channel.fetch_message(payload.message_id)
                    except discord.NotFound:
                        return
                    if channel.id in self.index_tasks or channel.id in self.indexed:
                        archives.insert_batch([archives.rows_for(message, self.bot.user.id)], replace=True)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.channel_id in self.index_tasks or payload.channel_id in self.indexed:
            archives.erase(payload.channel_id, [payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.channel_id in self.index_tasks or payload.channel_id in self.indexed:
            archives.erase(payload.channel_id, payload.message_ids)

    @arion.command(name="archiv", description="Přiřadí postavě archiv a začne indexovat jeho historii.")
    @app_commands.describe(jmena="Jméno postavy a případné přezdívky oddělené čárkami")
    async def bind_archive(self, interaction: discord.Interaction, kanal: discord.TextChannel,
                           jmena: app_commands.Range[str, 1, 150]):
        try:
            channel = archive_channel(interaction, "", kanal)
        except service.AskError as exc:
            return await self.error_reply(interaction, str(exc))
        names = [name.strip() for name in jmena.split(",") if archives.words(name)]
        if not names:
            return await self.error_reply(interaction, "Zadej jméno postavy.")
        archives.register(interaction.guild_id, channel.id, ",".join(names))
        self.start_index(channel)
        await interaction.response.send_message(f"Archiv {channel.mention} přiřazen k {', '.join(names)}.", ephemeral=True)

    @arion.command(name="odebrat_archiv", description="Zastaví indexování kanálu a odstraní místní kopii jeho zpráv.")
    async def unbind_archive(self, interaction: discord.Interaction, kanal: discord.TextChannel):
        try:
            channel = archive_channel(interaction, "", kanal)
        except service.AskError as exc:
            return await self.error_reply(interaction, str(exc))
        task = self.index_tasks.get(channel.id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.index_tasks.pop(channel.id, None)
            self.first_pages.pop(channel.id, None)
        self.indexed.discard(channel.id)
        db.connect().execute("DELETE FROM ai_archives WHERE guild=? AND channel=?", (interaction.guild_id, channel.id))
        await interaction.response.send_message("Registrace a index zpráv byly odstraněny. Schválené lore zůstává uložené.", ephemeral=True)

    def is_dm(self, member):
        return isinstance(member, discord.Member) and any(
            str(role.id) == self.role_id and not role.is_default() for role in member.roles
        )

    async def interaction_check(self, interaction):
        if self.is_dm(interaction.user):
            return True
        if (interaction.type == discord.InteractionType.application_command
                and isinstance(interaction.user, discord.Member)
                and interaction.command is not None
                and interaction.command.qualified_name in {"arion ask", "arion pomoc", "arion status"}
                and db.load_doc(service.state_key(interaction.guild_id)).get("all_members", False)
        ):
            return True
        await interaction.response.send_message("Potřebuješ autorizovanou roli DM.", ephemeral=True)
        return False

    @all_group.command(name="on", description="Povolí rozhovor s Arion všem členům tohoto serveru.")
    async def all_on(self, interaction: discord.Interaction):
        state = db.update_doc(service.state_key(interaction.guild_id), lambda s: s.update(all_members=True))
        note = "" if state.get("enabled") else " Samotnou AI ještě zapni přes /arion on."
        await interaction.response.send_message("Přístup mají všichni členové serveru." + note, ephemeral=True)

    @all_group.command(name="off", description="Vrátí přístup k ArionAI pouze členům s rolí DM.")
    async def all_off(self, interaction: discord.Interaction):
        db.update_doc(service.state_key(interaction.guild_id), lambda s: s.update(all_members=False))
        await interaction.response.send_message("Přístup má opět jen role DM.", ephemeral=True)

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
        access = "všichni členové" if state.get("all_members") else "jen role DM"
        await interaction.response.send_message(
            f"ArionAI je {enabled}. Přístup: {access}. Model: {self.model or 'nenastaven'}. "
            f"Do půlnoci UTC zbývá {remaining}/{self.daily_limit} dotazů.", ephemeral=True)

    @arion.command(name="ask", description="Zeptej se asistenta pro svět Aurionis.")
    @app_commands.describe(dotaz="Otázka pro ArionAI", zpravy="Kolik textových zpráv přiložit (výchozí 20, 0 vypne historii pro tento dotaz)",
                           soukrome="Ano: jen tobě. Ne: do kanálu příkazu. Bez volby je odpověď z archivu soukromá.",
                           archiv="Zdrojový kanál lore",
                           hledat="Slovo či fráze v archivu; bez filtru použiji poslední texty")
    async def ask(self, interaction: discord.Interaction, dotaz: app_commands.Range[str, 1, 2000],
                  zpravy: app_commands.Range[int, 0, 20] = 20, soukrome: bool | None = None,
                  archiv: discord.TextChannel | None = None,
                  hledat: app_commands.Range[str, 1, 100] = ""):
        await self.answer(interaction, dotaz, zpravy, soukrome, archiv, hledat)

    @arion.command(name="lore", description="Připraví z archivních zpráv soukromý návrh kánonu ke schválení.")
    async def draft_lore(self, interaction: discord.Interaction, dotaz: app_commands.Range[str, 1, 2000],
                         archiv: discord.TextChannel, hledat: app_commands.Range[str, 1, 100] = ""):
        await self.answer(interaction, dotaz, 0, True, archiv, hledat, draft=True)

    async def answer(self, interaction, dotaz, zpravy, soukrome, archiv, hledat, draft=False):
        uid = interaction.user.id
        if uid in self.busy:
            return await interaction.response.send_message("Tvůj předchozí dotaz ještě běží.", ephemeral=True)
        self.busy.add(uid)
        step = "kontrola nastavení"
        try:
            if not db.load_doc(service.state_key(interaction.guild_id)).get("enabled"):
                raise service.AskError("ArionAI je na tomto serveru vypnutý.")
            reply = None if draft else service.direct_reply(dotaz)
            if reply is not None:
                private = archiv is not None if soukrome is None else soukrome
                return await interaction.response.send_message(reply, ephemeral=private)
            if self.config_error:
                raise service.AskError(self.config_error)
            archive = archive_channel(interaction, dotaz, archiv)
            dm = self.is_dm(interaction.user)
            if hledat and archive is None:
                raise service.AskError("Vyber archiv nebo do dotazu vlož #kanál.")
            if soukrome is None:
                soukrome = archive is not None
            if archive and archive.id != interaction.channel_id and not dm and not soukrome:
                raise service.AskError("Výpis z jiného kanálu může hráč zobrazit soukromě. Zvol soukrome: ano.")
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
            if zpravy and archive is None:
                step = "načítání historie kanálu"
                history = await read_history(interaction, zpravy)
            step = "příprava podkladů a rezervace kvóty"
            canon = service.lore_context(interaction.guild_id, include_dm_only=dm and soukrome,
                                        channel_id=(archive or interaction.channel).id, question=dotaz)
            lore = []
            coverage = ""
            if archive is not None:
                step = "hledání v archivu"
                row = next((r for r in archives.registered(interaction.guild_id) if r["channel"] == archive.id), None)
                if row:
                    self.start_index(archive)
                    ready = self.first_pages.get(archive.id)
                    if ready:
                        try:
                            await asyncio.wait_for(ready.wait(), timeout=5)
                        except TimeoutError:
                            pass
                    complete = archive.id in self.indexed
                    coverage = archives.coverage(archive.id, complete)
                    lore = archives.select_scene(archive, dotaz, hledat, row["names"].split(","), interaction.id)
                    if not lore and not canon:
                        raise service.AskError(f"{coverage} Pro tento dotaz jsem nenašel zprávy. "
                                               "Zkus parametr hledat nebo dotaz zopakuj po dokončení indexace.")
                else:
                    coverage = "Výběr z nejnovějších 500 zpráv. Celý archiv lze přidat přes /arion archiv."
                    lore = await search_archive(archive, dotaz, hledat, interaction)
                    if not lore and not canon:
                        raise service.AskError(f"{coverage} Pro tento dotaz jsem nenašel zprávy.")
            if draft and not lore:
                raise service.AskError("Ke schválení potřebuji zdrojové zprávy z archivu.")
            service.reserve(interaction.guild_id, self.daily_limit, require_public_access=not dm)
            step = "volání OpenAI"
            answer = await service.generate(self.session, self.api_key, self.model, dotaz,
                                            history, lore, self.output_limit, canon=canon,
                                            coverage=coverage, draft=draft)
            step = "doručení odpovědi do Discordu"
            citation_urls = service.source_urls(lore, canon)
            answer, sources = service.extract_sources(answer, citation_urls)
            chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)]
            authors = ", ".join(dict.fromkeys(discord.utils.escape_markdown(r["autor"]) for r in history))
            receipt = f"Historie pro tento dotaz: {len(history)} zpráv" + (f" · {authors}" if authors else "")
            if sources:
                receipt = f"{coverage} Podklady z {(archive or interaction.channel).mention}: " + " · ".join(
                    f"[{i}](<{url}>)" for i, url in enumerate(sources, 1))
            if draft:
                view = CanonDraft(self, interaction, archive.id, answer, sources)
                await interaction.edit_original_response(content="**Návrh lore**\n" + answer[:1800], view=view)
                await interaction.followup.send(receipt, ephemeral=True)
                return
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

    @arion.command(name="pomoc", description="Co ArionAI umí a jak hledat v archivu.")
    async def help_ai(self, interaction: discord.Interaction):
        await interaction.response.send_message(service.CAPABILITIES, ephemeral=True)


async def setup(bot):
    cog = ArionAssistant()
    cog.bot = bot
    await bot.add_cog(cog)
