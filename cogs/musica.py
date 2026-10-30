import asyncio
import random
import re
import time
from collections import deque
from urllib.parse import quote

import aiohttp
import discord
import yt_dlp
from discord import ui
from discord.ext import commands, tasks

import db
from config import Config

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
        self.artist: str = data.get('artist') or data.get('uploader') or ''
        self.query: str = data.get('query', self.webpage_url)

    @classmethod
    async def from_url(cls, url: str, *, loop: asyncio.AbstractEventLoop | None = None,
                       seek: float | None = None) -> 'YTDLSource':
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if data is None:
            raise ValueError("No se pudo obtener información del video.")
        if 'entries' in data:
            data = data['entries'][0]

        data['query'] = url

        stream_url = data.get('url')
        if not stream_url:
            raise ValueError("No se encontró URL de streaming.")

        opciones = dict(FFMPEG_OPTIONS)
        if seek and seek > 1:
            opciones['before_options'] = f"-ss {int(seek)} " + opciones['before_options']

        return cls(discord.FFmpegPCMAudio(stream_url, **opciones), data=data)


class PendingTrack:
    def __init__(self, query: str, title: str = 'Desconocido', user_id: int | None = None):
        self.query = query
        self.title = title
        self.user_id = user_id


class GuildState:
    def __init__(self):
        self.queue: deque[YTDLSource | PendingTrack] = deque()
        self.current: YTDLSource | None = None
        self.loop: str = 'off'
        self.skip_next: bool = False
        self.started_at: float | None = None
        self.paused_total: float = 0.0
        self.paused_at: float | None = None
        self.channel: discord.abc.Messageable | None = None
        self.panel_msg: discord.Message | None = None
        self.panel_channel_id: int | None = None
        self.panel_task: asyncio.Task | None = None
        self.voice_channel_id: int | None = None
        self.last_reconnect: float = 0.0
        self.autoplay: bool = False
        self.auto_seen: set[str] = set()


class PanelView(ui.View):
    def __init__(self, cog: 'Musica', guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    def _state(self) -> GuildState:
        return self.cog._state(self.guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return True
        if self.cog._es_dj_member(interaction.user, interaction.guild):
            return True
        await interaction.response.send_message(
            "❌ Solo el DJ (rol o canal de voz) puede usar los controles.", ephemeral=True
        )
        return False

    @ui.button(emoji='⏯️', style=discord.ButtonStyle.primary)
    async def toggle(self, interaction: discord.Interaction, button: ui.Button):
        state = self._state()
        vc = interaction.guild.voice_client
        if not vc or not state.current:
            return await interaction.response.send_message(
                "❌ No hay música reproduciéndose.", ephemeral=True
            )
        if vc.is_playing():
            if state.paused_at is None:
                state.paused_at = time.monotonic()
            vc.pause()
        elif vc.is_paused():
            if state.paused_at is not None:
                state.paused_total += time.monotonic() - state.paused_at
                state.paused_at = None
            vc.resume()
        await interaction.response.edit_message(
            embed=self.cog._panel_embed(state), view=self
        )

    @ui.button(emoji='⏭️', style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: ui.Button):
        state = self._state()
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message(
                "❌ No hay música reproduciéndose.", ephemeral=True
            )
        state.skip_next = True
        await interaction.response.defer()
        vc.stop()

    @ui.button(emoji='🔁', style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: ui.Button):
        state = self._state()
        orden = ['off', 'one', 'all']
        state.loop = orden[(orden.index(state.loop) + 1) % len(orden)]
        await interaction.response.edit_message(
            embed=self.cog._panel_embed(state), view=self
        )

    @ui.button(emoji='⏹️', style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: ui.Button):
        state = self._state()
        vc = interaction.guild.voice_client
        self.cog._stop_panel(state)
        state.queue.clear()
        state.current = None
        state.loop = 'off'
        state.skip_next = False
        state.started_at = None
        state.paused_total = 0.0
        state.paused_at = None
        if vc:
            await vc.disconnect()
        embed = discord.Embed(
            title="⏹️ Reproducción detenida", color=discord.Color.dark_gray()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class SearchView(ui.View):
    def __init__(self, cog: 'Musica', ctx: commands.Context, resultados: list[dict]):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.resultados = resultados
        self.message: discord.Message | None = None
        for i in range(len(resultados)):
            boton = ui.Button(label=str(i + 1), style=discord.ButtonStyle.secondary)
            boton.callback = self._elegir(i)
            self.add_item(boton)

    def _elegir(self, indice: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.ctx.author.id:
                return await interaction.response.send_message(
                    "❌ Solo quien pidió la búsqueda puede elegir.", ephemeral=True
                )
            res = self.resultados[indice]
            await interaction.response.defer()
            try:
                await interaction.message.edit(
                    content=f"▶️ Elegiste: **{res.get('title', '?')}**",
                    embed=None,
                    view=None,
                )
            except Exception:
                pass
            await self.cog._reproducir_resultado(self.ctx, res)
        return callback

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class Musica(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildState] = {}
        self._vigilar_voz.start()

    def cog_unload(self):
        self._vigilar_voz.cancel()

    def _state(self, guild_id: int) -> GuildState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildState()
        return self._states[guild_id]

    @staticmethod
    def _es_url(texto: str) -> bool:
        t = texto.strip().lower()
        return t.startswith(('http://', 'https://', 'www.'))

    @staticmethod
    def _parse_tiempo(texto: str) -> int:
        texto = texto.strip()
        if ':' in texto:
            total = 0
            for parte in texto.split(':'):
                total = total * 60 + int(parte)
            return total
        return int(texto)

    def _es_dj_member(self, member: discord.Member, guild: discord.Guild) -> bool:
        if member.guild_permissions.manage_guild or member.id == guild.owner_id:
            return True
        rol_id = Config.DJ_ROLE_ID
        if rol_id and any(rol.id == rol_id for rol in member.roles):
            return True
        vc = guild.voice_client
        if vc and vc.channel and member.voice and member.voice.channel:
            return member.voice.channel.id == vc.channel.id
        return False

    def _puede_controlar(self, ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member):
            return False
        return self._es_dj_member(ctx.author, ctx.guild)

    async def _autoencolar(self, guild_id: int) -> bool:
        state = self._state(guild_id)
        actual = state.current
        if actual is None:
            return False
        if actual.query:
            state.auto_seen.add(actual.query)

        resultados = await self._buscar(actual.title, 8)
        agregadas = 0
        for resultado in resultados:
            url = resultado.get('url') or resultado.get('webpage_url') or resultado.get('id')
            if not url or url in state.auto_seen:
                continue
            state.auto_seen.add(url)
            state.queue.append(
                PendingTrack(
                    url,
                    resultado.get('title') or 'Desconocido',
                    getattr(actual, 'user_id', None),
                )
            )
            agregadas += 1
            if agregadas >= 3:
                break

        if agregadas:
            print(f'📻 Autoplay: {agregadas} canción(es) agregadas')
        return agregadas > 0

    async def _buscar(self, query: str, n: int = 5) -> list[dict]:
        opciones = dict(YTDL_OPTIONS)
        opciones.update({
            'extract_flat': True,
            'skip_download': True,
            'noplaylist': True,
            'default_search': f'ytsearch{n}',
        })

        def _run():
            with yt_dlp.YoutubeDL(opciones) as y:
                datos = y.extract_info(f'ytsearch{n}:{query}', download=False)
            return [e for e in (datos.get('entries') or []) if e]

        try:
            return await self.bot.loop.run_in_executor(None, _run)
        except Exception as e:
            print(f'❌ Error buscando "{query}": {e}')
            return []

    def _embed_busqueda(self, query: str, resultados: list[dict]) -> discord.Embed:
        embed = discord.Embed(
            title="🔎 Resultados de búsqueda",
            description=f"Búsqueda: **{query}**\n\n",
            color=discord.Color.blurple(),
        )
        lineas = []
        for i, r in enumerate(resultados, 1):
            dur = r.get('duration') or 0
            dur_txt = self._fmt(dur) if dur else '--:--'
            autor = r.get('uploader') or 'Desconocido'
            lineas.append(f"`{i}.` **{r.get('title', '?')}** — `{dur_txt}`\n     _{autor}_")
        embed.description += "\n".join(lineas)
        embed.set_footer(text="Elegí una opción con los botones (60 s)")
        return embed

    def _record_history(self, guild_id: int, source: YTDLSource):
        try:
            db.history_add(
                guild_id,
                getattr(source, 'user_id', None),
                source.title,
                source.query,
            )
        except Exception as e:
            print(f'⚠️ No se pudo guardar historial: {e}')

    async def _encolar_o_reproducir(self, ctx: commands.Context, source: YTDLSource):
        vc = ctx.guild.voice_client
        state = self._state(ctx.guild.id)
        state.channel = ctx.channel
        if vc and vc.channel:
            state.voice_channel_id = vc.channel.id

        source.user_id = ctx.author.id

        if vc and (vc.is_playing() or vc.is_paused()):
            state.queue.append(source)
            await ctx.send(f"✅ Añadido a la cola (posición **{len(state.queue)}**): **{source.title}**")
        else:
            state.current = source
            self._play(vc, source, ctx.guild.id)
            self._record_history(ctx.guild.id, source)
            await self._start_panel(ctx.guild.id)

    async def _reproducir_resultado(self, ctx: commands.Context, res: dict):
        url = res.get('url') or res.get('webpage_url') or res.get('id')
        try:
            source = await YTDLSource.from_url(url, loop=self.bot.loop)
        except Exception as e:
            return await ctx.send(f"❌ Error al obtener el audio: {e}")
        await self._encolar_o_reproducir(ctx, source)

    @tasks.loop(seconds=15)
    async def _vigilar_voz(self):
        ahora = time.monotonic()
        for guild_id, state in list(self._states.items()):
            if not state.current and not state.queue:
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            vc = guild.voice_client
            if vc and vc.is_connected():
                continue
            if not state.voice_channel_id:
                continue
            if ahora - state.last_reconnect < 30:
                continue

            canal = guild.get_channel(state.voice_channel_id)
            if canal is None:
                continue

            state.last_reconnect = ahora
            print(f'🔄 Reconectando voz en {guild.name}...')
            try:
                if vc:
                    await vc.disconnect(force=True)
                nuevo_vc = await canal.connect()

                if state.current:
                    pos = self._position(state)
                    if state.current.duration:
                        pos = min(pos, max(0, state.current.duration - 2))
                    source = await self._reextract(state.current, seek=pos)
                    if source:
                        state.current = source
                        self._play(nuevo_vc, source, guild_id, offset=pos)
                        await self._start_panel(guild_id)
                        print(f'✅ Voz reconectada y reproducción reanudada en {guild.name}')
                        continue
                await self._play_next(guild_id)
            except Exception as e:
                print(f'❌ Error reconectando voz en {guild.name}: {e}')

    @_vigilar_voz.before_loop
    async def _before_vigilar_voz(self):
        await self.bot.wait_until_ready()

    @_vigilar_voz.error
    async def _error_vigilar_voz(self, error: Exception):
        print(f'❌ Error en _vigilar_voz: {error}')

    @staticmethod
    def _fmt(seg: float) -> str:
        seg = int(max(0, seg))
        h, resto = divmod(seg, 3600)
        m, s = divmod(resto, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    @staticmethod
    def _barra(pos: float, dur: float, ancho: int = 18) -> str:
        if not dur or dur <= 0:
            return "🔘" + "▬" * (ancho - 1)
        pos = max(0.0, min(float(pos), float(dur)))
        lleno = min(int(ancho * pos / dur), ancho - 1)
        return "▬" * lleno + "🔘" + "▬" * (ancho - lleno - 1)

    def _start_timer(self, state: GuildState):
        state.started_at = time.monotonic()
        state.paused_total = 0.0
        state.paused_at = None

    def _position(self, state: GuildState) -> float:
        if state.started_at is None:
            return 0.0
        ahora = state.paused_at if state.paused_at is not None else time.monotonic()
        return max(0.0, ahora - state.started_at - state.paused_total)

    def _panel_embed(self, state: GuildState) -> discord.Embed:
        src = state.current
        if src is None:
            return discord.Embed(title="🎵 Sin reproducción", color=discord.Color.dark_gray())

        dur = src.duration or 0
        pos = self._position(state)
        if dur:
            progreso = f"{self._barra(pos, dur)}\n`{self._fmt(pos)} / {self._fmt(dur)}`"
        else:
            progreso = f"`{self._fmt(pos)} / --:--`"

        icono = {'off': '➡️', 'one': '🔂', 'all': '🔁'}.get(state.loop, '➡️')
        estado = '⏸️ Pausado' if state.paused_at is not None else '▶️ Reproduciendo'

        embed = discord.Embed(
            title=estado,
            description=f"**{src.title}**",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Progreso", value=progreso, inline=False)
        auto = '📻' if state.autoplay else '—'
        embed.set_footer(text=f"Loop {icono}  •  Vol {int(src.volume * 100)}%  •  Autoplay {auto}")
        if src.thumbnail:
            embed.set_thumbnail(url=src.thumbnail)
        return embed

    async def _panel_loop(self, guild_id: int):
        state = self._state(guild_id)
        try:
            while True:
                await asyncio.sleep(5)
                guild = self.bot.get_guild(guild_id)
                vc = guild.voice_client if guild else None
                if not vc or not state.current or not state.panel_msg:
                    return
                if not vc.is_playing() and not vc.is_paused():
                    return
                try:
                    await state.panel_msg.edit(embed=self._panel_embed(state))
                except discord.NotFound:
                    state.panel_msg = None
                    return
                except discord.HTTPException as e:
                    print(f'⚠️ Panel: {e}')
        except asyncio.CancelledError:
            raise
        finally:
            if state.panel_task is asyncio.current_task():
                state.panel_task = None

    async def _refresh_panel(self, guild_id: int):
        state = self._state(guild_id)
        if not state.panel_msg:
            return
        try:
            await state.panel_msg.edit(embed=self._panel_embed(state))
        except Exception:
            pass

    async def _start_panel(self, guild_id: int):
        state = self._state(guild_id)
        if state.panel_task and not state.panel_task.done():
            state.panel_task.cancel()

        canal_id = getattr(state.channel, 'id', None)
        if state.panel_msg and state.panel_channel_id != canal_id:
            state.panel_msg = None

        embed = self._panel_embed(state)
        view = PanelView(self, guild_id)
        if state.panel_msg:
            try:
                await state.panel_msg.edit(embed=embed, view=view)
            except Exception:
                state.panel_msg = None

        if state.panel_msg is None:
            if state.channel is None:
                return
            try:
                state.panel_msg = await state.channel.send(embed=embed, view=view)
                state.panel_channel_id = canal_id
            except Exception as e:
                print(f'⚠️ No se pudo crear el panel de reproducción: {e}')
                return

        state.panel_task = self.bot.loop.create_task(self._panel_loop(guild_id))

    def _stop_panel(self, state: GuildState):
        if state.panel_task and not state.panel_task.done():
            state.panel_task.cancel()
        state.panel_task = None

    def _play(self, vc: discord.VoiceClient, source: YTDLSource, guild_id: int,
              offset: float = 0.0):
        state = self._state(guild_id)
        self._start_timer(state)
        if offset > 0:
            state.started_at = time.monotonic() - offset
        vc.play(
            source,
            after=lambda _: asyncio.run_coroutine_threadsafe(
                self._play_next(guild_id), self.bot.loop
            ),
        )

    async def _reextract(self, source: YTDLSource, seek: float | None = None) -> YTDLSource | None:
        try:
            return await YTDLSource.from_url(source.query, loop=self.bot.loop, seek=seek)
        except Exception as e:
            print(f'❌ Error re-extrayendo audio: {e}')
            return None

    async def _play_next(self, guild_id: int):
        state = self._state(guild_id)
        guild = self.bot.get_guild(guild_id)
        vc = guild.voice_client if guild else None

        if not vc:
            state.current = None
            self._stop_panel(state)
            return

        saltar = state.skip_next
        state.skip_next = False

        if state.current:
            if state.loop == 'one' and not saltar:
                source = await self._reextract(state.current)
                if source:
                    state.current = source
                    self._play(vc, source, guild_id)
                    await self._start_panel(guild_id)
                    return
            elif state.loop == 'all':
                nueva = await self._reextract(state.current)
                if nueva:
                    state.queue.append(nueva)

        if not state.queue and state.autoplay and state.current:
            await self._autoencolar(guild_id)

        if not state.queue:
            state.current = None
            self._stop_panel(state)
            await self._refresh_panel(guild_id)
            return

        item = state.queue.popleft()
        if isinstance(item, PendingTrack):
            source = await self._reextract(item)
            if source is None:
                state.current = None
                self._stop_panel(state)
                return await self._play_next(guild_id)
            source.user_id = item.user_id
            state.current = source
        else:
            state.current = item

        try:
            self._play(vc, state.current, guild_id)
            self._record_history(guild_id, state.current)
            await self._start_panel(guild_id)
        except Exception as e:
            print(f'❌ Error en _play_next: {e}')
            state.current = None
            self._stop_panel(state)

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

        self._state(ctx.guild.id).voice_channel_id = channel.id
        await ctx.send(f"✅ Conectado a **{channel.name}**")

    @commands.command(name='play', aliases=['p', 'reproducir'])
    async def play(self, ctx: commands.Context, *, query: str):
        """Reproduce música. Acepta URL o búsqueda por nombre."""
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")

        vc = ctx.guild.voice_client
        if not vc:
            vc = await ctx.author.voice.channel.connect()

        state = self._state(ctx.guild.id)
        state.channel = ctx.channel
        if vc.channel:
            state.voice_channel_id = vc.channel.id

        if self._es_url(query):
            async with ctx.typing():
                try:
                    source = await YTDLSource.from_url(query, loop=self.bot.loop)
                except Exception as e:
                    return await ctx.send(f"❌ Error al obtener el audio: {e}")
            return await self._encolar_o_reproducir(ctx, source)

        async with ctx.typing():
            resultados = await self._buscar(query, 5)

        if not resultados:
            return await ctx.send("❌ No encontré resultados para esa búsqueda.")

        view = SearchView(self, ctx, resultados)
        msg = await ctx.send(embed=self._embed_busqueda(query, resultados), view=view)
        view.message = msg

    @commands.command(name='pause', aliases=['pausar'])
    async def pause(self, ctx: commands.Context):
        """Pausa la reproducción actual."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            state = self._state(ctx.guild.id)
            if state.paused_at is None:
                state.paused_at = time.monotonic()
            vc.pause()
            await self._refresh_panel(ctx.guild.id)
            await ctx.send("⏸️ Pausado.")
        else:
            await ctx.send("❌ No hay música reproduciéndose.")

    @commands.command(name='resume', aliases=['reanudar'])
    async def resume(self, ctx: commands.Context):
        """Reanuda la reproducción pausada."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            state = self._state(ctx.guild.id)
            if state.paused_at is not None:
                state.paused_total += time.monotonic() - state.paused_at
                state.paused_at = None
            vc.resume()
            await self._refresh_panel(ctx.guild.id)
            await ctx.send("▶️ Reanudado.")
        else:
            await ctx.send("❌ La reproducción no está pausada.")

    @commands.command(name='skip', aliases=['s', 'saltar'])
    async def skip(self, ctx: commands.Context):
        """Salta a la siguiente canción en la cola."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        vc = ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self._state(ctx.guild.id).skip_next = True
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

    @commands.command(name='np', aliases=['nowplaying', 'sonando'])
    async def np(self, ctx: commands.Context):
        """Muestra la canción actual con su progreso."""
        state = self._state(ctx.guild.id)
        if not state.current:
            return await ctx.send("📭 No hay música reproduciéndose.")
        await ctx.send(embed=self._panel_embed(state))

    @commands.command(name='historial', aliases=['recientes', 'history'])
    async def historial(self, ctx: commands.Context):
        """Muestra las últimas canciones reproducidas."""
        filas = db.history_recent(ctx.guild.id, 10)
        if not filas:
            return await ctx.send("📭 Todavía no hay historial.")

        lineas = []
        for i, fila in enumerate(filas, 1):
            lineas.append(f"`{i}.` **{fila['title']}**")
        embed = discord.Embed(
            title="🕘 Últimas canciones",
            description="\n".join(lineas),
            color=discord.Color.dark_teal(),
        )
        await ctx.send(embed=embed)

    @commands.command(name='last', aliases=['ultima', 'última'])
    async def last(self, ctx: commands.Context):
        """Vuelve a reproducir la última canción."""
        fila = db.history_last(ctx.guild.id)
        if not fila:
            return await ctx.send("📭 Todavía no hay historial.")
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")

        vc = ctx.guild.voice_client
        if not vc:
            vc = await ctx.author.voice.channel.connect()

        state = self._state(ctx.guild.id)
        state.channel = ctx.channel
        if vc.channel:
            state.voice_channel_id = vc.channel.id

        async with ctx.typing():
            try:
                source = await YTDLSource.from_url(fila['query'], loop=self.bot.loop)
            except Exception as e:
                return await ctx.send(f"❌ Error al obtener el audio: {e}")

        await self._encolar_o_reproducir(ctx, source)

    @commands.group(name='playlist', aliases=['pl'], invoke_without_command=True)
    async def playlist(self, ctx: commands.Context):
        """Guarda y carga playlists. Uso: !playlist save|load|list|show|delete <nombre>"""
        await ctx.send("Uso: `!playlist save|load|list|show|delete <nombre>`")

    @playlist.command(name='save', aliases=['guardar'])
    async def playlist_save(self, ctx: commands.Context, *, nombre: str):
        """Guarda la canción actual y la cola como playlist."""
        state = self._state(ctx.guild.id)
        pistas = []
        if state.current:
            pistas.append((state.current.query, state.current.title))
        for pista in state.queue:
            pistas.append((pista.query, pista.title))

        if not pistas:
            return await ctx.send("📭 No hay nada para guardar (cola vacía).")

        nombre = nombre.strip()[:50]
        existente = len(db.playlist_tracks(ctx.guild.id, nombre))
        db.playlist_delete(ctx.guild.id, nombre)
        for query, title in pistas:
            db.playlist_add(ctx.guild.id, nombre, query, title)

        accion = "sobrescrita" if existente else "guardada"
        await ctx.send(f"💾 Playlist **{nombre}** {accion} con **{len(pistas)}** canción(es).")

    @playlist.command(name='load', aliases=['cargar'])
    async def playlist_load(self, ctx: commands.Context, *, nombre: str):
        """Carga y reproduce una playlist guardada."""
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")

        nombre = nombre.strip()[:50]
        filas = db.playlist_tracks(ctx.guild.id, nombre)
        if not filas:
            return await ctx.send(f"❌ No existe la playlist **{nombre}**.")

        vc = ctx.guild.voice_client
        if not vc:
            vc = await ctx.author.voice.channel.connect()

        state = self._state(ctx.guild.id)
        state.channel = ctx.channel
        if vc.channel:
            state.voice_channel_id = vc.channel.id

        pendientes = [PendingTrack(f['query'], f['title'], ctx.author.id) for f in filas]

        if vc.is_playing() or vc.is_paused():
            state.queue.extend(pendientes)
            return await ctx.send(
                f"✅ Playlist **{nombre}** agregada: **{len(pendientes)}** canción(es)."
            )

        primero = pendientes.pop(0)
        async with ctx.typing():
            source = await self._reextract(primero)
        if source is None:
            return await ctx.send("❌ No se pudo reproducir la playlist.")

        source.user_id = ctx.author.id
        state.queue.extend(pendientes)
        state.current = source
        self._play(vc, source, ctx.guild.id)
        self._record_history(ctx.guild.id, source)
        await self._start_panel(ctx.guild.id)
        await ctx.send(
            f"▶️ Playlist **{nombre}**: **{source.title}** (+{len(pendientes)} en cola)"
        )

    @playlist.command(name='list', aliases=['lista'])
    async def playlist_list(self, ctx: commands.Context):
        """Lista las playlists guardadas."""
        filas = db.playlist_names(ctx.guild.id)
        if not filas:
            return await ctx.send("📭 No hay playlists guardadas.")

        lineas = [f"• **{fila['name']}** — {fila['total']} canción(es)" for fila in filas]
        embed = discord.Embed(
            title="🎧 Playlists guardadas",
            description="\n".join(lineas)[:4000],
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

    @playlist.command(name='show', aliases=['ver'])
    async def playlist_show(self, ctx: commands.Context, *, nombre: str):
        """Muestra las canciones de una playlist."""
        nombre = nombre.strip()[:50]
        filas = db.playlist_tracks(ctx.guild.id, nombre)
        if not filas:
            return await ctx.send(f"❌ No existe la playlist **{nombre}**.")

        lineas = [f"`{i}.` {fila['title']}" for i, fila in enumerate(filas, 1)]
        embed = discord.Embed(
            title=f"🎧 {nombre}",
            description="\n".join(lineas)[:4000],
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed)

    @playlist.command(name='delete', aliases=['borrar', 'eliminar'])
    async def playlist_delete(self, ctx: commands.Context, *, nombre: str):
        """Elimina una playlist guardada."""
        nombre = nombre.strip()[:50]
        cantidad = db.playlist_delete(ctx.guild.id, nombre)
        if not cantidad:
            return await ctx.send(f"❌ No existe la playlist **{nombre}**.")
        await ctx.send(f"🗑️ Playlist **{nombre}** eliminada (**{cantidad}** canción(es)).")

    @playlist.command(name='add', aliases=['agregar', 'añadir'])
    async def playlist_add(self, ctx: commands.Context, nombre: str, *, consulta: str | None = None):
        """Agrega la cola actual (o una búsqueda) a una playlist. Uso: !playlist add <nombre> [canción]"""
        nombre = nombre.strip()[:50]
        state = self._state(ctx.guild.id)
        pistas = []

        if consulta:
            async with ctx.typing():
                resultados = await self._buscar(consulta, 1)
            if not resultados:
                return await ctx.send("❌ No se encontró la canción.")
            r = resultados[0]
            url = r.get('webpage_url') or r.get('url') or f"https://www.youtube.com/watch?v={r.get('id')}"
            pistas.append((url, r.get('title', 'Canción')))
        else:
            if state.current:
                pistas.append((state.current.query, state.current.title))
            for pista in state.queue:
                pistas.append((pista.query, pista.title))
            if not pistas:
                return await ctx.send("📭 No hay nada para agregar (cola vacía).")

        for query, title in pistas:
            db.playlist_add(ctx.guild.id, nombre, query, title)

        total = len(db.playlist_tracks(ctx.guild.id, nombre))
        await ctx.send(f"➕ Agregadas **{len(pistas)}** canción(es) a **{nombre}** (total: **{total}**).")

    @playlist.command(name='remove', aliases=['quitar', 'rm'])
    async def playlist_remove(self, ctx: commands.Context, nombre: str, posicion: int):
        """Quita una canción de una playlist. Uso: !playlist remove <nombre> <n>"""
        nombre = nombre.strip()[:50]
        filas = db.playlist_tracks(ctx.guild.id, nombre)
        if not filas:
            return await ctx.send(f"❌ No existe la playlist **{nombre}**.")
        if not (1 <= posicion <= len(filas)):
            return await ctx.send(f"❌ Posición inválida. La playlist tiene **{len(filas)}** canción(es).")

        quitada = filas[posicion - 1]
        db.playlist_remove_at(ctx.guild.id, nombre, posicion)
        await ctx.send(f"🗑️ Quitada de **{nombre}**: **{quitada['title']}**")

    @commands.command(name='remove', aliases=['quitar', 'rm'])
    async def remove(self, ctx: commands.Context, posicion: int):
        """Quita una canción de la cola por su posición. Uso: !remove <n>"""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        lista = list(state.queue)

        if not lista:
            return await ctx.send("📭 La cola está vacía.")
        if not (1 <= posicion <= len(lista)):
            return await ctx.send(f"❌ Posición inválida. La cola tiene **{len(lista)}** canción(es).")

        quitada = lista.pop(posicion - 1)
        state.queue = deque(lista)
        await ctx.send(f"🗑️ Quitada de la cola: **{quitada.title}**")

    @commands.command(name='move', aliases=['mover', 'mv'])
    async def move(self, ctx: commands.Context, desde: int, hacia: int):
        """Mueve una canción de posición en la cola. Uso: !move <de> <a>"""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        lista = list(state.queue)

        if not lista:
            return await ctx.send("📭 La cola está vacía.")
        total = len(lista)
        if not (1 <= desde <= total and 1 <= hacia <= total):
            return await ctx.send(f"❌ Posiciones inválidas. La cola tiene **{total}** canción(es).")

        if desde == hacia:
            return await ctx.send("🤷 Esa canción ya está en esa posición.")

        item = lista.pop(desde - 1)
        lista.insert(hacia - 1, item)
        state.queue = deque(lista)
        await ctx.send(f"🔀 Movida **{item.title}** de la posición **{desde}** a la **{hacia}**.")

    @commands.command(name='clear', aliases=['limpiar', 'vaciar'])
    async def clear(self, ctx: commands.Context):
        """Limpia la cola sin detener la canción actual."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        cantidad = len(state.queue)
        if not cantidad:
            return await ctx.send("📭 La cola ya está vacía.")

        state.queue.clear()
        await ctx.send(f"🧹 Cola limpiada (**{cantidad}** canción(es) eliminadas). Sigue sonando la actual.")

    @commands.command(name='shuffle', aliases=['mezclar', 'aleatorio'])
    async def shuffle(self, ctx: commands.Context):
        """Mezcla aleatoriamente la cola."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        lista = list(state.queue)
        if len(lista) < 2:
            return await ctx.send("📭 Necesitás al menos 2 canciones en la cola para mezclar.")

        random.shuffle(lista)
        state.queue = deque(lista)
        await ctx.send(f"🔀 Cola mezclada (**{len(lista)}** canciones).")

    @commands.command(name='seek', aliases=['adelantar'])
    async def seek(self, ctx: commands.Context, tiempo: str):
        """Adelanta la canción. Uso: !seek 90 | 1:30 | 1:02:03"""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        vc = ctx.guild.voice_client
        if not vc or not state.current:
            return await ctx.send("❌ No hay música reproduciéndose.")

        try:
            segundos = self._parse_tiempo(tiempo)
        except ValueError:
            return await ctx.send("❌ Tiempo inválido. Ejemplos: `90`, `1:30`, `1:02:03`.")
        if segundos < 0:
            return await ctx.send("❌ El tiempo no puede ser negativo.")

        duracion = state.current.duration or 0
        if duracion and segundos >= duracion:
            return await ctx.send(f"❌ La canción dura **{self._fmt(duracion)}**.")

        async with ctx.typing():
            source = await self._reextract(state.current, seek=segundos)
        if source is None:
            return await ctx.send("❌ No se pudo hacer seek.")

        source.user_id = getattr(state.current, 'user_id', None)
        state.current = source
        self._play(vc, source, ctx.guild.id, offset=segundos)
        await self._start_panel(ctx.guild.id)
        await ctx.send(f"⏩ Saltando a **{self._fmt(segundos)}** de **{source.title}**")

    @commands.command(name='autoplay', aliases=['radio', 'automatico', 'automático'])
    async def autoplay(self, ctx: commands.Context, modo: str | None = None):
        """Activa/desactiva el autoplay de canciones relacionadas."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)

        if modo is None:
            state.autoplay = not state.autoplay
        else:
            m = modo.lower()
            if m in ('on', 'si', 'sí', '1', 'activar', 'true'):
                state.autoplay = True
            elif m in ('off', 'no', '0', 'desactivar', 'false'):
                state.autoplay = False
            else:
                return await ctx.send("❌ Usa `!autoplay on` o `!autoplay off`.")

        await self._refresh_panel(ctx.guild.id)
        await ctx.send(f"📻 Autoplay: **{'activado' if state.autoplay else 'desactivado'}**")

    @commands.command(name='lyrics', aliases=['letra'])
    async def lyrics(self, ctx: commands.Context, *, consulta: str | None = None):
        """Muestra la letra de la canción actual o de una búsqueda. Uso: !lyrics [artista - canción]"""
        state = self._state(ctx.guild.id)

        if consulta:
            if ' - ' in consulta:
                artista, titulo = consulta.split(' - ', 1)
            else:
                artista, titulo = '', consulta
        elif state.current:
            artista = getattr(state.current, 'artist', '') or ''
            titulo = self._limpiar_titulo(state.current.title)
        else:
            return await ctx.send("❌ No hay canción sonando. Usá `!lyrics <artista - canción>`.")

        artista = artista.strip()
        titulo = titulo.strip()
        if not titulo:
            return await ctx.send("❌ No pude identificar la canción.")

        async with ctx.typing():
            letra = await self._fetch_lyrics(artista, titulo)

        if not letra:
            return await ctx.send(f"❌ No encontré la letra de **{titulo}**.")

        letra = letra.replace('\r\n', '\n').strip()
        embed = discord.Embed(
            title=f"🎤 {artista + ' - ' if artista else ''}{titulo}",
            description=letra[:4000],
            color=discord.Color.purple(),
        )
        if len(letra) > 4000:
            embed.set_footer(text="Letra truncada (muy larga).")
        await ctx.send(embed=embed)

    @staticmethod
    def _limpiar_titulo(titulo: str) -> str:
        t = re.sub(r'[\(\[].*?[\)\]]', ' ', titulo)
        t = re.sub(r'(?i)\b(official|video|audio|lyrics?|letra|hd|hq|remaster(ed)?|en vivo|live|visualizer)\b', ' ', t)
        t = re.sub(r'\s+', ' ', t)
        return t.strip(' -|/')

    @staticmethod
    async def _fetch_lyrics(artista: str, titulo: str) -> str | None:
        if not artista:
            artista = 'Various Artists'
        url = f"https://api.lyrics.ovh/v1/{quote(artista)}/{quote(titulo)}"
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as sesion:
                async with sesion.get(url) as resp:
                    if resp.status != 200:
                        return None
                    datos = await resp.json(content_type=None)
                    return datos.get('lyrics')
        except Exception as e:
            print(f'⚠️ Error buscando letra: {e}')
            return None

    @commands.command(name='stop', aliases=['detener'])
    async def stop(self, ctx: commands.Context):
        """Detiene la música, limpia la cola y desconecta el bot."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        vc = ctx.guild.voice_client
        if not vc:
            return await ctx.send("❌ El bot no está conectado a un canal de voz.")

        state = self._state(ctx.guild.id)
        self._stop_panel(state)
        state.queue.clear()
        state.current = None
        state.loop = 'off'
        state.skip_next = False
        state.started_at = None
        state.paused_total = 0.0
        state.paused_at = None
        await vc.disconnect()
        await ctx.send("⏹️ Música detenida. Bot desconectado.")

    @commands.command(name='loop', aliases=['bucle', 'repetir'])
    async def loop(self, ctx: commands.Context, modo: str | None = None):
        """Cambia el modo de repetición: off, one (canción) o all (cola)."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        orden = ['off', 'one', 'all']
        alias = {
            'off': 'off', 'no': 'off', 'nada': 'off', 'desactivar': 'off',
            'one': 'one', 'una': 'one', 'cancion': 'one', 'canción': 'one', 'single': 'one',
            'all': 'all', 'todo': 'all', 'cola': 'all', 'queue': 'all',
        }

        if modo is None:
            state.loop = orden[(orden.index(state.loop) + 1) % len(orden)]
        else:
            clave = alias.get(modo.lower())
            if not clave:
                return await ctx.send("❌ Modo inválido. Usa: `off`, `one` o `all`.")
            state.loop = clave

        iconos = {
            'off': '➡️ Desactivado',
            'one': '🔂 Repetir canción',
            'all': '🔁 Repetir cola',
        }
        await self._refresh_panel(ctx.guild.id)
        await ctx.send(f"🔁 Loop: **{iconos[state.loop]}**")

    @commands.command(name='volumen', aliases=['vol'])
    async def volumen(self, ctx: commands.Context, vol: int):
        """Ajusta el volumen de 0 a 100."""
        if not self._puede_controlar(ctx):
            return await ctx.send("❌ Solo el DJ (rol o canal de voz) puede usar este comando.")
        state = self._state(ctx.guild.id)
        if not state.current:
            return await ctx.send("❌ No hay música reproduciéndose.")

        vol = max(0, min(100, vol))
        state.current.volume = vol / 100
        await self._refresh_panel(ctx.guild.id)
        await ctx.send(f"🔊 Volumen: **{vol}%**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Musica(bot))
