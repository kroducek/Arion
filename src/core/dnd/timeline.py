"""Story time is manual, per guild and character; Alice anchors the present."""
import asyncio
import io
import math
import random

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from src.database.characters import get_active_slot, get_char, ckey
from src.utils import paths
from src.utils.admin_gate import admin_only
from src.utils.json_utils import load_json, update_json

PERIODS = ("ráno", "dopoledne", "odpoledne", "večer", "noc")
PERIOD_CHOICES = [app_commands.Choice(name=p, value=p) for p in PERIODS]
PAGE_SIZE = 6


def timeline_path():
    return paths.data("timeline.json")


def guild_state(guild_id):
    return load_json(timeline_path(), default={}).get(str(guild_id), {
        "alice": {"day": 0, "period": "ráno", "note": ""}, "players": {},
    })


def set_entry(guild_id, key, day, period, name, note):
    """Player day is relative to Alice at write time, then stored absolutely."""
    def mutate(data):
        state = data.setdefault(str(guild_id), {
            "alice": {"day": 0, "period": "ráno", "note": ""}, "players": {},
        })
        entry = {"day": day if key is None else state["alice"]["day"] + day,
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


NODE_COLORS = ("#73dfff", "#bd9bff", "#ff91bf", "#89edbd", "#ffb67f", "#aabaff")
NODE_ICONS = ("🔵", "🟣", "🌸", "🟢", "🟠", "💠")
FRAME_COUNT = 30


def render_timeline(alice, players, page=1):
    """Looping energy stream assembled from particles, without raster text."""
    width, height, center = 1100, 300, 150
    values = [position(alice)] + [position(e) for e in players]
    low, high = min(values) - .4, max(values) + .4
    xs = [int(70 + (v-low) / (high-low) * 960) for v in values]
    rng = random.Random(42)
    particles = [(rng.random(), rng.uniform(-1, 1), rng.uniform(0, math.tau),
                  rng.choice((1, 1, 1, 2))) for _ in range(1050)]
    frames = []
    for frame in range(FRAME_COUNT):
        phase = frame / FRAME_COUNT
        base = Image.new("RGB", (width, height), (6, 9, 19))
        energy = Image.new("RGB", base.size)
        sparks = Image.new("RGB", base.size)
        ed, sd = ImageDraw.Draw(energy), ImageDraw.Draw(sparks)
        # Multiple braided filaments breathe together along one horizontal axis.
        for strand in range(5):
            points = []
            for x in range(35, width-34, 4):
                envelope = math.sin(math.pi * (x-35) / (width-70)) ** .6
                y = center + envelope * (math.sin(x*.019 - phase*math.tau + strand*1.2)*7
                                         + math.sin(x*.043 + phase*math.tau + strand)*3)
                points.append((x, y))
            ed.line(points, fill=(24+strand*5, 78+strand*15, 120+strand*20), width=2)
        for start, scatter, offset, radius in particles:
            travel = (start + phase) % 1
            x = 35 + travel * (width-70)
            envelope = max(0, math.sin(math.pi*travel)) ** .5
            # Loose motes converge into the stream, then dissolve at its end.
            spread = 4 + 42 * abs(2*travel-1) ** 3
            y = center + scatter*spread + math.sin(travel*22-phase*math.tau+offset)*5*envelope
            intensity = .25 + .75*envelope
            color = (int(75*intensity), int(190*intensity), int(245*intensity))
            ed.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
            if radius == 1:
                sd.point((int(x), int(y)), fill=color)
        # Character anchors have matching colored markers in the text embed.
        # Draw Alice last so her gold anchor remains visible at shared times.
        for i in list(range(1, len(xs))) + [0]:
            x = xs[i]
            color = "#ffd78a" if i == 0 else NODE_COLORS[(i-1) % len(NODE_COLORS)]
            pulse = 11 + 3*math.sin(phase*math.tau+i)
            ed.ellipse((x-pulse, center-pulse, x+pulse, center+pulse), fill=color)
            sd.ellipse((x-3, center-3, x+3, center+3), fill="#f2faff")
            for mote in range(8):
                angle = mote*math.tau/8 + phase*math.tau
                mx, my = x+math.cos(angle)*20, center+math.sin(angle)*11
                sd.point((int(mx), int(my)), fill=color)
        result = ImageChops.add(base, energy.filter(ImageFilter.GaussianBlur(13)))
        result = ImageChops.add(result, energy.filter(ImageFilter.GaussianBlur(3)))
        result = ImageChops.add(result, sparks)
        frames.append(result)
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                   duration=70, loop=0, optimize=False)
    output.seek(0)
    return output


def timeline_embeds(alice, players, page, pages):
    art = discord.Embed(color=0x73DFFF)
    art.set_image(url="attachment://timeline.gif")
    details = discord.Embed(title="Časové proudy", color=0x73DFFF)
    for i, entry in enumerate([alice] + players):
        icon = "🟡" if i == 0 else NODE_ICONS[(i-1) % len(NODE_ICONS)]
        name = "Alice · přítomnost" if i == 0 else entry["name"]
        value = f"**{entry['period'].capitalize()}** · {relative_text(entry, alice)}"
        if entry.get("note"):
            value += "\n" + discord.utils.escape_markdown(entry["note"])
        details.add_field(name=f"{icon} {name}", value=value, inline=False)
    if not players:
        details.description = "DM zatím nepřidal žádné postavy."
    details.set_footer(text=f"Strana {page}/{pages} · Zleva minulost → budoucnost · Zlatý bod: Alice")
    return [art, details]


class Timeline(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="timeline", description="Animovaná časová osa postav vůči Alicině přítomnosti.")
    @app_commands.guild_only()
    @app_commands.describe(strana="Strana časové osy (6 postav na stránku)")
    async def timeline(self, interaction: discord.Interaction, strana: app_commands.Range[int, 1, 1000] = 1):
        state = guild_state(interaction.guild_id)
        rows = sorted(state["players"].items(), key=lambda item: (position(item[1]), item[0]))
        # Deleted characters must not linger on the timeline.
        rows = [entry for key, entry in rows if get_char(*key.split(":"))]
        pages = max(1, math.ceil(len(rows) / PAGE_SIZE))
        if strana > pages:
            await interaction.response.send_message(f"Časová osa má {pages} stran.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        selected = rows[(strana-1)*PAGE_SIZE:strana*PAGE_SIZE]
        try:
            image = await asyncio.to_thread(render_timeline, state["alice"], selected, strana)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Timeline render failed")
            await interaction.followup.send("Časovou osu se nepodařilo vykreslit. Čas postavy najdeš přes /time.", ephemeral=True)
            return
        await interaction.followup.send(
            embeds=timeline_embeds(state["alice"], selected, strana, pages),
            file=discord.File(image, filename="timeline.gif"), ephemeral=True)

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
        if entry.get("note"):
            embed.add_field(name="V příběhu", value=entry["note"], inline=False)
        embed.set_footer(text=f"Alice: {state['alice']['period']} · Příběhový čas posouvá DM.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="timeline_set", description="DM: nastav čas postavy relativně k Alici.")
    @app_commands.guild_only()
    @admin_only()
    @app_commands.choices(cast_dne=PERIOD_CHOICES)
    @app_commands.describe(dny="Odstup od Alice ve dnech: -2 = dva dny v minulosti, 0 = stejný den",
                           slot="Postava 1 nebo 2; bez volby aktivní postava", poznamka="Krátký popis děje")
    async def timeline_set(self, interaction: discord.Interaction, hrac: discord.Member,
                           dny: app_commands.Range[int, -100000, 100000], cast_dne: str,
                           slot: app_commands.Range[int, 1, 2] = None,
                           poznamka: app_commands.Range[str, 0, 160] = ""):
        selected = str(slot) if slot is not None else get_active_slot(hrac.id)
        character = get_char(hrac.id, selected)
        if not character:
            await interaction.response.send_message("Hráč v tomto slotu nemá postavu.", ephemeral=True)
            return
        key = ckey(hrac.id, selected)
        state = set_entry(interaction.guild_id, key, dny, cast_dne, character["name"], poznamka)
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
                               poznamka: app_commands.Range[str, 0, 160] = ""):
        set_entry(interaction.guild_id, None, den, cast_dne, "Alice", poznamka)
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
