"""Story time is manual, per guild and character; Alice anchors the present."""
import math
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from src.database.characters import get_active_slot, get_char, ckey
from src.utils import paths
from src.utils.admin_gate import admin_only
from src.utils.json_utils import load_json, update_json

PERIODS = ("ráno", "dopoledne", "odpoledne", "večer", "noc")
PERIOD_CHOICES = [app_commands.Choice(name=p, value=p) for p in PERIODS]
PAGE_SIZE = 20
LOCATION_PAGE_SIZE = 20
UNKNOWN_LOCATION = "Bez lokace"


def timeline_path():
    return paths.data("timeline.json")


def guild_state(guild_id):
    return load_json(timeline_path(), default={}).get(str(guild_id), {
        "alice": {"day": 0, "period": "ráno", "note": ""}, "players": {},
    })


def set_entry(guild_id, key, day, period, name, note, location=None):
    """Player day is relative to Alice at write time, then stored absolutely."""
    def mutate(data):
        state = data.setdefault(str(guild_id), {
            "alice": {"day": 0, "period": "ráno", "note": ""}, "players": {},
        })
        previous = state["alice"] if key is None else state["players"].get(key, {})
        entry = {"location": location.strip() if location is not None else previous.get("location", ""),
                 "day": day if key is None else state["alice"]["day"] + day,
                 "period": period, "name": name, "note": note}
        if key is None:
            state["alice"] = entry
        else:
            state["players"][key] = entry
        return data
    return update_json(timeline_path(), mutate)[str(guild_id)]


def relative_text(entry, alice):
    delta = entry["day"] - alice["day"]
    if delta == 0:
        shift = PERIODS.index(entry["period"]) - PERIODS.index(alice["period"])
        return "přítomnost" if shift == 0 else (
            "stejný den, dříve než Alice" if shift < 0 else "stejný den, později než Alice")
    return f"{abs(delta)} d před Alicí" if delta < 0 else f"{delta} d po Alici"


def position(entry):
    return entry["day"] + PERIODS.index(entry["period"]) / len(PERIODS)


def timeline_media():
    directory = Path(paths.ASSETS_DIR) / "timeline"
    # Drop the user's finished animation beside the source PNG to activate it.
    animated = directory / "timeline.gif"
    return animated if animated.is_file() else directory / "timeline.png"


def location_of(entry):
    return " ".join(entry.get("location", "").split()) or UNKNOWN_LOCATION


def clean_text(value):
    return discord.utils.escape_markdown(" ".join(str(value).split()))


def player_line(entry, alice):
    return (f"**{clean_text(entry['name'])}** · {entry['period']} · "
            f"{relative_text(entry, alice)} · {clean_text(location_of(entry))}")


def timeline_embeds(alice, players, page, pages, location=None):
    art = discord.Embed(color=0xA894E8)
    art.set_image(url=f"attachment://{timeline_media().name}")
    lines = [f"**Alice** · {alice['period']} · přítomnost · {clean_text(location_of(alice))}"]
    for entry in players:
        lines.append(player_line(entry, alice))
    if not players:
        lines.append("V této lokaci zatím nejsou žádné postavy." if location else "Zatím nejsou přidané žádné postavy.")
    details = discord.Embed(title=location or "Všechny lokace", description="\n".join(lines), color=0xA894E8)
    details.set_footer(text=f"Strana {page}/{pages} · Alice určuje přítomnost")
    return [art, details]


class TimelineView(discord.ui.View):
    def __init__(self, author_id, alice, players, page=1):
        super().__init__(timeout=600)
        self.author_id, self.alice, self.players = author_id, alice, players
        self.page, self.location_page, self.location = page, 0, None
        # Merge differently capitalized location spellings into one button.
        locations = {}
        for entry in players:
            label = location_of(entry)
            locations.setdefault(label.casefold(), label)
        self.locations = sorted(locations.values(), key=str.casefold)
        self.rebuild()

    def filtered(self):
        return [entry for entry in self.players if self.location is None or
                location_of(entry).casefold() == self.location.casefold()]

    @property
    def pages(self):
        return len(self.chunks())

    def chunks(self):
        pages, current, length = [], [], 0
        for entry in self.filtered():
            size = len(player_line(entry, self.alice)) + 1
            if current and (len(current) >= PAGE_SIZE or length + size > 3500):
                pages.append(current)
                current, length = [], 0
            current.append(entry)
            length += size
        return pages + [current] if current or not pages else pages

    def embeds(self):
        entries = self.chunks()[self.page-1]
        return timeline_embeds(self.alice, entries, self.page, self.pages, self.location)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Otevři si vlastní osu přes /timeline.", ephemeral=True)
            return False
        return True

    def add_control(self, label, callback, row, active=False, disabled=False):
        button = discord.ui.Button(label=label, row=row, disabled=disabled,
                                   style=discord.ButtonStyle.primary if active else discord.ButtonStyle.secondary)
        button.callback = callback
        self.add_item(button)

    async def refresh(self, interaction):
        self.rebuild()
        await interaction.response.edit_message(embeds=self.embeds(), view=self)

    def rebuild(self):
        self.clear_items()
        async def all_locations(interaction):
            self.location, self.page = None, 1
            await self.refresh(interaction)
        self.add_control("Vše", all_locations, 0, active=self.location is None)
        start = self.location_page * LOCATION_PAGE_SIZE
        for index, label in enumerate(self.locations[start:start+LOCATION_PAGE_SIZE]):
            async def select(interaction, selected=label):
                self.location, self.page = selected, 1
                await self.refresh(interaction)
            self.add_control(label, select, (index+1)//5, active=self.location == label)
        # At most 21 location buttons + four controls fits Discord's 25 buttons.
        location_pages = max(1, math.ceil(len(self.locations)/LOCATION_PAGE_SIZE))
        async def previous_locations(interaction):
            self.location_page = max(0, self.location_page-1)
            await self.refresh(interaction)
        async def next_locations(interaction):
            self.location_page = min(location_pages-1, self.location_page+1)
            await self.refresh(interaction)
        async def previous_players(interaction):
            self.page = max(1, self.page-1)
            await self.refresh(interaction)
        async def next_players(interaction):
            self.page = min(self.pages, self.page+1)
            await self.refresh(interaction)
        if location_pages > 1:
            self.add_control("Lokace zpět", previous_locations, 4, disabled=self.location_page == 0)
            self.add_control("Další lokace", next_locations, 4, disabled=self.location_page == location_pages-1)
        self.add_control("Předchozí", previous_players, 4, disabled=self.page == 1)
        self.add_control("Další", next_players, 4, disabled=self.page == self.pages)


class Timeline(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="timeline", description="Časová osa postav podle lokace vůči Alicině přítomnosti.")
    @app_commands.guild_only()
    @app_commands.describe(strana="Strana časové osy (20 postav na stránku)")
    async def timeline(self, interaction: discord.Interaction, strana: app_commands.Range[int, 1, 1000] = 1):
        state = guild_state(interaction.guild_id)
        rows = sorted(state["players"].items(), key=lambda item: (position(item[1]), item[0]))
        # Deleted characters must not linger on the timeline.
        rows = [entry for key, entry in rows if get_char(*key.split(":"))]
        view = TimelineView(interaction.user.id, state["alice"], rows, strana)
        if strana > view.pages:
            await interaction.response.send_message(f"Časová osa má {view.pages} stran.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        await interaction.followup.send(embeds=view.embeds(), view=view,
            file=discord.File(timeline_media()), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="time", description="Část dne a odstup aktivní postavy od Aliciny přítomnosti.")
    @app_commands.guild_only()
    async def time(self, interaction: discord.Interaction, hrac: discord.Member = None):
        member = hrac or interaction.user
        state = guild_state(interaction.guild_id)
        key = ckey(member.id, get_active_slot(member.id))
        entry = state["players"].get(key)
        if not entry or not get_char(member.id, get_active_slot(member.id)):
            await interaction.response.send_message("Tato postava zatím nemá nastavený čas. Nastaví ho DM přes /timeline_set.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Čas · {entry['name']}", color=0x6EDBFF,
                              description=f"**{entry['period'].capitalize()}**\n{relative_text(entry, state['alice'])}")
        embed.add_field(name="Lokace", value=location_of(entry), inline=False)
        if entry.get("note"):
            embed.add_field(name="V příběhu", value=entry["note"], inline=False)
        embed.set_footer(text=f"Alice: {state['alice']['period']} · Příběhový čas posouvá DM.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="timeline_set", description="DM: nastav čas postavy relativně k Alici.")
    @app_commands.guild_only()
    @admin_only()
    @app_commands.choices(cast_dne=PERIOD_CHOICES)
    @app_commands.describe(dny="Odstup od Alice ve dnech: -2 = dva dny v minulosti, 0 = stejný den",
                           slot="Postava 1 nebo 2; bez volby aktivní postava", poznamka="Krátký popis děje", lokace="Lokace postavy; bez zadání se zachová stávající")
    async def timeline_set(self, interaction: discord.Interaction, hrac: discord.Member,
                           dny: app_commands.Range[int, -100000, 100000], cast_dne: str,
                           slot: app_commands.Range[int, 1, 2] = None,
                           poznamka: app_commands.Range[str, 0, 160] = "",
                           lokace: app_commands.Range[str, 1, 60] = None):
        selected = str(slot) if slot is not None else get_active_slot(hrac.id)
        character = get_char(hrac.id, selected)
        if not character:
            await interaction.response.send_message("Hráč v tomto slotu nemá postavu.", ephemeral=True)
            return
        key = ckey(hrac.id, selected)
        state = set_entry(interaction.guild_id, key, dny, cast_dne, character["name"], poznamka, lokace)
        await interaction.response.send_message(
            f"Nastaveno: **{character['name']}** · {cast_dne} · {relative_text(state['players'][key], state['alice'])}.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="timeline_present", description="DM: nastav Alicin den a část dne — přítomnost příběhu.")
    @app_commands.guild_only()
    @admin_only()
    @app_commands.choices(cast_dne=PERIOD_CHOICES)
    @app_commands.describe(den="Absolutní příběhový den; počáteční je 0. Posun 0 → 1 uběhne jeden den.")
    async def timeline_present(self, interaction: discord.Interaction,
                               den: app_commands.Range[int, -100000, 100000], cast_dne: str,
                               poznamka: app_commands.Range[str, 0, 160] = "",
                           lokace: app_commands.Range[str, 1, 60] = None):
        set_entry(interaction.guild_id, None, den, cast_dne, "Alice", poznamka, lokace)
        await interaction.response.send_message(
            f"Alicina přítomnost: den **{den}**, **{cast_dne}**. Čas ostatních postav zůstává na místě.", ephemeral=True)

    @app_commands.command(name="timeline_remove", description="DM: odeber postavu z časové osy.")
    @app_commands.guild_only()
    @admin_only()
    async def timeline_remove(self, interaction: discord.Interaction, hrac: discord.Member,
                              slot: app_commands.Range[int, 1, 2] = None):
        key = ckey(hrac.id, str(slot) if slot is not None else get_active_slot(hrac.id))
        def mutate(data):
            data.get(str(interaction.guild_id), {}).get("players", {}).pop(key, None)
            return data
        update_json(timeline_path(), mutate)
        await interaction.response.send_message("Postava odebrána z časové osy.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Timeline(bot))
