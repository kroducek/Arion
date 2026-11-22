import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.database import db, deaths
from src.logic.attack_ui import is_dm

logger = logging.getLogger(__name__)
OUTCOMES = {
    "revived": "DM zrušil smrt. Postava má **1 HP**.",
    "deleted": "Hráč smazal postavu.",
    "expired": "Lhůta vypršela. Postava byla automaticky smazána.",
    "missing": "Postava už neexistuje.",
}


class DeathChannelTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        deaths.death_channel.set(interaction.channel_id)
        return await super().interaction_check(interaction)


class DeathView(discord.ui.View):
    def __init__(self, cog, key, death):
        super().__init__(timeout=None)
        self.cog, self.key, self.death = cog, key, death
        for label, emoji, style, action, callback in (
            ("Smazat postavu", None, discord.ButtonStyle.danger, "delete", self.delete),
            ("DM", "🔒", discord.ButtonStyle.secondary, "dm", self.open_panel),
        ):
            button = discord.ui.Button(
                label=label, emoji=emoji, style=style,
                custom_id=f"death:{death['id']}:{action}",
            )
            button.callback = callback
            self.add_item(button)

    async def delete(self, interaction):
        if interaction.user.id != self.death["uid"]:
            return await interaction.response.send_message(
                "Postavu může smazat její hráč.", ephemeral=True,
            )
        await self.cog.decide(interaction, self.key, self.death, "delete", interaction.message)

    async def open_panel(self, interaction):
        if not is_dm(interaction):
            return await interaction.response.send_message("Panel je jen pro DM.", ephemeral=True)
        current = deaths.pending_deaths().get(self.key)
        if not current or current["id"] != self.death["id"] or time.time() >= current["deadline"]:
            return await interaction.response.send_message("Rozhodnutí už je uzavřené.", ephemeral=True)

        screen = interaction.message
        panel = discord.ui.View(timeout=max(1, current["deadline"] - time.time()))
        button = discord.ui.Button(label="Zrušit smrt · nastavit 1 HP", style=discord.ButtonStyle.success)

        async def revive(decision):
            if not is_dm(decision):
                return await decision.response.send_message("Volba je jen pro DM.", ephemeral=True)
            await self.cog.decide(decision, self.key, self.death, "revive", screen)

        button.callback = revive
        panel.add_item(button)
        await interaction.response.send_message("Panel DM", view=panel, ephemeral=True)


class DeathScreen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.views = {}

    async def cog_load(self):
        for key, death in deaths.pending_deaths().items():
            if death.get("message_id"):
                view = DeathView(self, key, death)
                self.bot.add_view(view, message_id=death["message_id"])
                self.views[death["id"]] = view
        self.check_deaths.start()

    async def cog_unload(self):
        self.check_deaths.cancel()
        for view in self.views.values():
            view.stop()

    def embed(self, death, outcome=None):
        name = discord.utils.escape_markdown(
            death["name"] or f"Postava {death['slot']}",
        )
        if outcome:
            description = f"**{name}**\n\n{OUTCOMES[outcome]}"
        else:
            deadline = int(death["deadline"])
            description = (
                f"<@{death['uid']}> · **{name}**\n\n"
                f"Pokud nepadne rozhodnutí, postava se smaže <t:{deadline}:R>."
            )
        return discord.Embed(title="Zemřel jsi. 💀", description=description, color=0x922B21)

    async def send_screen(self, key, death):
        channel_id = death["channel_id"]
        if not channel_id:
            for cid, combat in db.load_doc(deaths.COMBAT).items():
                if any(s.get("profile_key") == key for s in combat.get("stats", {}).values()):
                    channel_id = int(cid)
                    break
        view = DeathView(self, key, death)
        mentions = discord.AllowedMentions(users=[discord.Object(id=death["uid"])])
        embed = self.embed(death)
        message = None
        if channel_id:
            try:
                channel = self.bot.get_partial_messageable(channel_id)
                message = await channel.send(embed=embed, view=view, allowed_mentions=mentions)
            except (discord.Forbidden, discord.NotFound):
                logger.warning("Death screen channel unavailable: %s", channel_id)
        if message is None:
            user = self.bot.get_user(death["uid"]) or await self.bot.fetch_user(death["uid"])
            message = await user.send(embed=embed, view=view, allowed_mentions=mentions)
        if deaths.attach_message(key, death["id"], message):
            death.update(message_id=message.id, message_channel_id=message.channel.id)
            self.views[death["id"]] = view
        else:
            view.stop()

    async def close_screen(self, death, outcome, message=None):
        view = self.views.pop(death["id"], None)
        if view:
            view.stop()
        if message is None and death.get("message_id"):
            channel = self.bot.get_partial_messageable(death["message_channel_id"])
            message = channel.get_partial_message(death["message_id"])
        if message is not None:
            try:
                await message.edit(embed=self.embed(death, outcome), view=None)
            except discord.HTTPException:
                logger.warning("Could not update death screen %s", message.id, exc_info=True)

    async def decide(self, interaction, key, death, action, message):
        await interaction.response.defer(ephemeral=True, thinking=True)
        outcome = deaths.resolve(key, death["id"], action)
        if outcome is not None:
            await self.close_screen(death, outcome, message)
        await interaction.followup.send(OUTCOMES.get(outcome, "Rozhodnutí už je uzavřené."), ephemeral=True)

    @tasks.loop(seconds=2)
    async def check_deaths(self):
        try:
            pending = deaths.pending_deaths()
            for view in list(self.views.values()):
                current = pending.get(view.key)
                if not current or current["id"] != view.death["id"]:
                    await self.close_screen(view.death, "missing")
            for key, death in pending.items():
                try:
                    if time.time() >= death["deadline"]:
                        outcome = deaths.resolve(key, death["id"], "expire")
                        if outcome is not None:
                            await self.close_screen(death, outcome)
                    elif not death.get("message_id"):
                        await self.send_screen(key, death)
                except Exception:
                    logger.exception("Could not process death %s", death["id"])
        except Exception:
            logger.exception("Could not read pending deaths")

    @check_deaths.before_loop
    async def before_check_deaths(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(DeathScreen(bot))
