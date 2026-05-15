import asyncio
from collections import deque

import discord
import yt_dlp
from discord.ext import commands

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)
        self.title: str = data.get('title', 'Desconocido')
        self.webpage_url: str = data.get('webpage_url', '')
        self.duration: int | None = data.get('duration')
        self.thumbnail: str | None = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url: str, *, loop: asyncio.AbstractEventLoop | None = None) -> 'YTDLSource':
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if data is None:
            raise ValueError("No se pudo obtener información del video.")
        if 'entries' in data:
            data = data['entries'][0]

        stream_url = data.get('url')
        if not stream_url:
            raise ValueError("No se encontró URL de streaming.")

        return cls(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS), data=data)


class GuildState:
    def __init__(self):
        self.queue: deque[YTDLSource] = deque()
        self.current: YTDLSource | None = None


class Musica(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildState] = {}

    def _state(self, guild_id: int) -> GuildState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildState()
        return self._states[guild_id]

    async def _play_next(self, guild_id: int):
        state = self._state(guild_id)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None

        if not vc or not state.queue:
            state.current = None
            return

        try:
            state.current = state.queue.popleft()
            vc.play(
                state.current,
                after=lambda _: asyncio.run_coroutine_threadsafe(
                    self._play_next(guild_id), self.bot.loop
                ),
            )
        except Exception as e:
            print(f'❌ Error en _play_next: {e}')
            state.current = None

    @commands.command(name='join', aliases=['conectar'])
    async def join(self, ctx: commands.Context):
        """Conecta el bot a tu canal de voz."""
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")

        channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client

        if vc:
            await vc.move_to(channel)
        else:
            await channel.connect()

        await ctx.send(f"✅ Conectado a **{channel.name}**")

    @commands.command(name='play', aliases=['p', 'reproducir'])
    async def play(self, ctx: commands.Context, *, query: str):
        """Reproduce música desde YouTube. Acepta URL o nombre de canción."""
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")

        vc = ctx.guild.voice_client
        if not vc:
            vc = await ctx.author.voice.channel.connect()

        async with ctx.typing():
            try:
                source = await YTDLSource.from_url(query, loop=self.bot.loop)
            except Exception as e:
                return await ctx.send(f"❌ Error al obtener el audio: {e}")

        state = self._state(ctx.guild.id)

        if vc.is_playing() or vc.is_paused():
            state.queue.append(source)
            await ctx.send(f"✅ Añadido a la cola (posición **{len(state.queue)}**): **{source.title}**")
        else:
            state.current = source
            vc.play(
                source,
                after=lambda _: asyncio.run_coroutine_threadsafe(
                    self._play_next(ctx.guild.id), self.bot.loop
                ),
            )
            await ctx.send(f"▶️ Reproduciendo: **{source.title}**")

    @commands.command(name='pause', aliases=['pausar'])
    async def pause(self, ctx: commands.Context):
        """Pausa la reproducción actual."""
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸️ Pausado.")
        else:
            await ctx.send("❌ No hay música reproduciéndose.")

    @commands.command(name='resume', aliases=['reanudar'])
    async def resume(self, ctx: commands.Context):
        """Reanuda la reproducción pausada."""
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶️ Reanudado.")
        else:
            await ctx.send("❌ La reproducción no está pausada.")

    @commands.command(name='skip', aliases=['s', 'saltar'])
    async def skip(self, ctx: commands.Context):
        """Salta a la siguiente canción en la cola."""
        vc = ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await ctx.send("⏭️ Canción saltada.")
        else:
            await ctx.send("❌ No hay música reproduciéndose.")

    @commands.command(name='queue', aliases=['q', 'cola'])
    async def queue(self, ctx: commands.Context):
        """Muestra la cola de reproducción."""
        state = self._state(ctx.guild.id)

        if not state.current and not state.queue:
            return await ctx.send("📭 La cola está vacía.")

        embed = discord.Embed(title="🎵 Cola de Reproducción", color=discord.Color.green())

        if state.current:
            embed.add_field(
                name="▶️ Reproduciendo ahora",
                value=f"**{state.current.title}**",
                inline=False,
            )

        if state.queue:
            lista = "\n".join(f"`{i + 1}.` {t.title}" for i, t in enumerate(state.queue))
            embed.add_field(name="📋 En cola", value=lista[:1024], inline=False)

        embed.set_footer(text=f"{len(state.queue)} canción(es) en espera")
        await ctx.send(embed=embed)

    @commands.command(name='stop', aliases=['detener'])
    async def stop(self, ctx: commands.Context):
        """Detiene la música, limpia la cola y desconecta el bot."""
        vc = ctx.guild.voice_client
        if not vc:
            return await ctx.send("❌ El bot no está conectado a un canal de voz.")

        state = self._state(ctx.guild.id)
        state.queue.clear()
        state.current = None
        await vc.disconnect()
        await ctx.send("⏹️ Música detenida. Bot desconectado.")

    @commands.command(name='volumen', aliases=['vol'])
    async def volumen(self, ctx: commands.Context, vol: int):
        """Ajusta el volumen de 0 a 100."""
        state = self._state(ctx.guild.id)
        if not state.current:
            return await ctx.send("❌ No hay música reproduciéndose.")

        vol = max(0, min(100, vol))
        state.current.volume = vol / 100
        await ctx.send(f"🔊 Volumen: **{vol}%**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Musica(bot))
