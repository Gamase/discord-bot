import asyncio
import time
from collections import deque

import discord
import yt_dlp
from discord import ui
from discord.ext import commands, tasks

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


class GuildState:
    def __init__(self):
        self.queue: deque[YTDLSource] = deque()
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


class PanelView(ui.View):
    def __init__(self, cog: 'Musica', guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    def _state(self) -> GuildState:
        return self.cog._state(self.guild_id)

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

    async def _encolar_o_reproducir(self, ctx: commands.Context, source: YTDLSource):
        vc = ctx.guild.voice_client
        state = self._state(ctx.guild.id)
        state.channel = ctx.channel
        if vc and vc.channel:
            state.voice_channel_id = vc.channel.id

        if vc and (vc.is_playing() or vc.is_paused()):
            state.queue.append(source)
            await ctx.send(f"✅ Añadido a la cola (posición **{len(state.queue)}**): **{source.title}**")
        else:
            state.current = source
            self._play(vc, source, ctx.guild.id)
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
        embed.set_footer(text=f"Loop {icono}  •  Volumen {int(src.volume * 100)}%")
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

        if not state.queue:
            state.current = None
            self._stop_panel(state)
            await self._refresh_panel(guild_id)
            return

        state.current = state.queue.popleft()
        try:
            self._play(vc, state.current, guild_id)
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

    @commands.command(name='stop', aliases=['detener'])
    async def stop(self, ctx: commands.Context):
        """Detiene la música, limpia la cola y desconecta el bot."""
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
        state = self._state(ctx.guild.id)
        if not state.current:
            return await ctx.send("❌ No hay música reproduciéndose.")

        vol = max(0, min(100, vol))
        state.current.volume = vol / 100
        await self._refresh_panel(ctx.guild.id)
        await ctx.send(f"🔊 Volumen: **{vol}%**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Musica(bot))
