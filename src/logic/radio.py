"""Radio cog — YouTube přehrávač pro voice kanály."""

import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

from src.utils.paths import DATA_DIR

COOKIES_PATH = os.path.join(DATA_DIR, "youtube_cookies.txt")

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

YDL_FLAT = {
    'format': 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': 'in_playlist',
}

YDL_STREAM = {
    'format': 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
}


def _cookies_opt() -> dict:
    # Preferuj env var, fallback na data dir
    path = os.getenv("YOUTUBE_COOKIES_FILE", "") or COOKIES_PATH
    if path and os.path.isfile(path):
        return {'cookiefile': path}
    return {}


def _sync_extract_flat(url: str) -> dict:
    with yt_dlp.YoutubeDL({**YDL_FLAT, **_cookies_opt()}) as ydl:
        return ydl.extract_info(url, download=False)


def _sync_get_stream(url: str) -> str:
    with yt_dlp.YoutubeDL({**YDL_STREAM, **_cookies_opt()}) as ydl:
        info = ydl.extract_info(url, download=False)
        return info['url']


class RadioCog(commands.Cog):
    radio = app_commands.Group(name="radio", description="🎵 YouTube radio přehrávač")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._queues: dict[int, list[dict]] = {}
        self._current: dict[int, dict | None] = {}

    def _queue(self, gid: int) -> list[dict]:
        return self._queues.setdefault(gid, [])

    def _vc(self, guild_id: int) -> discord.VoiceClient | None:
        return next((vc for vc in self.bot.voice_clients if vc.guild.id == guild_id), None)

    async def _extract_tracks(self, url: str, requester: discord.Member) -> list[dict]:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _sync_extract_flat, url)
        if not data:
            raise ValueError("yt-dlp nepřinesl žádná data — zkus jiný odkaz nebo zkontroluj URL.")

        if 'entries' in data:
            tracks = []
            for e in data['entries']:
                if not e:
                    continue
                webpage = e.get('url') or e.get('webpage_url', '')
                if not webpage.startswith('http'):
                    webpage = f"https://www.youtube.com/watch?v={e['id']}"
                tracks.append({
                    'title': e.get('title', 'Neznámý název'),
                    'webpage_url': webpage,
                    'requester': requester,
                })
            return tracks

        return [{
            'title': data.get('title', 'Neznámý název'),
            'webpage_url': data.get('webpage_url', url),
            'requester': requester,
        }]

    async def _play_next(self, guild_id: int):
        vc = self._vc(guild_id)
        if not vc or not vc.is_connected():
            self._current.pop(guild_id, None)
            return

        queue = self._queue(guild_id)
        if not queue:
            self._current[guild_id] = None
            return

        track = queue.pop(0)
        self._current[guild_id] = track

        loop = asyncio.get_event_loop()
        try:
            stream_url = await loop.run_in_executor(None, _sync_get_stream, track['webpage_url'])
        except Exception as e:
            print(f"[Radio] Nelze získat stream pro {track['title']}: {e}")
            await self._play_next(guild_id)
            return

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS),
            volume=0.4,
        )

        def after(error):
            if error:
                print(f"[Radio] Chyba přehrávání: {error}")
            asyncio.run_coroutine_threadsafe(self._play_next(guild_id), self.bot.loop)

        vc.play(source, after=after)

    @radio.command(name="play", description="Přehraje YouTube URL nebo playlist do voice kanálu")
    @app_commands.describe(url="YouTube odkaz nebo playlist URL")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.user.voice:
            return await interaction.response.send_message(
                "❌ Nejsi v žádném voice kanálu.", ephemeral=True
            )

        await interaction.response.defer()

        guild_id = interaction.guild.id
        voice_channel = interaction.user.voice.channel

        vc = self._vc(guild_id)
        if vc is None:
            vc = await voice_channel.connect()
        elif vc.channel.id != voice_channel.id:
            await vc.move_to(voice_channel)

        try:
            tracks = await self._extract_tracks(url, interaction.user)
        except Exception as e:
            return await interaction.followup.send(f"❌ Chyba při načítání: {e}", ephemeral=True)

        if not tracks:
            return await interaction.followup.send("❌ Nic nenalezeno.", ephemeral=True)

        self._queue(guild_id).extend(tracks)

        if len(tracks) == 1:
            msg = f"🎵 Přidáno do fronty: **{tracks[0]['title']}**"
        else:
            msg = f"🎵 Přidáno **{len(tracks)} tracků** z playlistu"

        await interaction.followup.send(msg)

        if not vc.is_playing() and not vc.is_paused():
            await self._play_next(guild_id)

    @radio.command(name="skip", description="Přeskočí aktuální track")
    async def skip(self, interaction: discord.Interaction):
        vc = self._vc(interaction.guild.id)
        if not vc or not vc.is_playing():
            return await interaction.response.send_message("❌ Nic se nehraje.", ephemeral=True)
        vc.stop()
        await interaction.response.send_message("⏭️ Přeskočeno.")

    @radio.command(name="stop", description="Zastaví přehrávání a odpojí bota")
    async def stop(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        vc = self._vc(guild_id)
        if not vc:
            return await interaction.response.send_message("❌ Bot není ve voice kanálu.", ephemeral=True)

        self._queues.pop(guild_id, None)
        self._current.pop(guild_id, None)
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Zastaveno, fronta vymazána.")

    @radio.command(name="queue", description="Zobrazí aktuální frontu")
    async def queue_cmd(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        queue = self._queue(guild_id)
        current = self._current.get(guild_id)

        if not current and not queue:
            return await interaction.response.send_message("📭 Fronta je prázdná.", ephemeral=True)

        embed = discord.Embed(title="🎵 Radio — Fronta", color=0x1DB954)

        if current:
            embed.add_field(
                name="▶️ Teď hraje",
                value=f"**{current['title']}**\n-# přidal {current['requester'].mention}",
                inline=False,
            )

        if queue:
            lines = []
            for i, t in enumerate(queue[:10], 1):
                lines.append(f"`{i}.` **{t['title']}** · {t['requester'].mention}")
            if len(queue) > 10:
                lines.append(f"-# *...a {len(queue) - 10} dalších*")
            embed.add_field(name="📋 Ve frontě", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RadioCog(bot))
