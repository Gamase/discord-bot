import asyncio
import io
import os
import time
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import Config

TZ = ZoneInfo('America/Tijuana')
VENTANA_ANTISPAM = 600
LIMITE_TRACEBACK = 3900
CLAVES_SECRETAS = ('DISCORD_TOKEN', 'GROQ_API_KEY', 'CLABE')


def censurar_secretos(texto: str | None, env=None) -> str:
    if not texto:
        return texto or ''
    entorno = os.environ if env is None else env
    for clave in CLAVES_SECRETAS:
        valor = str(entorno.get(clave) or '').strip()
        if len(valor) >= 4:
            texto = texto.replace(valor, '[censurado]')
    return texto


class AntiSpam:
    def __init__(self, ventana: float = VENTANA_ANTISPAM):
        self.ventana = ventana
        self._estados: dict[str, dict] = {}

    def registrar(self, clave: str, ahora: float | None = None):
        ahora = time.time() if ahora is None else ahora
        estado = self._estados.get(clave)
        if estado is None:
            self._estados[clave] = {'inicio': ahora, 'conteo': 1}
            return 'primero', 1
        if ahora - estado['inicio'] >= self.ventana:
            previo = estado['conteo']
            self._estados[clave] = {'inicio': ahora, 'conteo': 1}
            return 'resumen', previo
        estado['conteo'] += 1
        return None

    def flush(self, ahora: float | None = None) -> list[tuple[str, int]]:
        ahora = time.time() if ahora is None else ahora
        cerrados = []
        for clave, estado in list(self._estados.items()):
            if ahora - estado['inicio'] >= self.ventana:
                cerrados.append((clave, estado['conteo']))
                del self._estados[clave]
        return cerrados


def _ubicacion(error: Exception | None) -> str:
    if error is None or error.__traceback__ is None:
        return ''
    ultimo = traceback.extract_tb(error.__traceback__)[-1]
    return f'{ultimo.filename}:{ultimo.lineno}'


def _texto_traceback(error: Exception | None, tb: str | None) -> str:
    if tb:
        return tb
    if error is not None:
        return ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    return 'Sin traceback.'


def _contexto_args(args) -> tuple[object | None, object | None]:
    usuario = None
    canal = None
    for obj in args:
        if usuario is None:
            autor = getattr(obj, 'author', None)
            if autor is not None:
                usuario = autor
            elif isinstance(obj, (discord.User, discord.Member)):
                usuario = obj
        if canal is None:
            posible = getattr(obj, 'channel', None)
            if posible is not None:
                canal = posible
            elif isinstance(obj, (discord.abc.GuildChannel, discord.Thread, discord.DMChannel)):
                canal = obj
    return usuario, canal


def _nombre_objeto(obj) -> str:
    if obj is None:
        return 'no disponible'
    nombre = getattr(obj, 'name', None)
    if nombre:
        return f'{nombre} ({getattr(obj, "id", "?")})'
    return str(obj)


def reiniciar_loop(loop: tasks.Loop):
    async def _reiniciar():
        await asyncio.sleep(1)
        try:
            if not loop.is_running():
                loop.start()
        except RuntimeError:
            await asyncio.sleep(2)
            if not loop.is_running():
                loop.start()
        except Exception:
            traceback.print_exc()

    try:
        asyncio.create_task(_reiniciar())
    except RuntimeError:
        pass


async def reportar_tarea_desde(bot: commands.Bot, nombre: str, error: Exception):
    cog = bot.get_cog('Errores')
    if cog is None:
        tb = censurar_secretos(_texto_traceback(error, None))
        print(f'[ERROR] Tarea {nombre}: {type(error).__name__}')
        print(tb)
        return
    try:
        await cog.reportar_tarea(nombre, error)
    except Exception:
        traceback.print_exc()


class Errores(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.anti_spam = AntiSpam()
        self._detalles: dict[str, dict] = {}
        self._admin_cache: int | None = None
        self._on_error_original = None
        self._tree_on_error_original = None

    async def cog_load(self):
        self._on_error_original = self.bot.on_error
        self._tree_on_error_original = self.bot.tree.on_error
        self.bot.on_error = self._on_error_evento
        self.bot.tree.on_error = self._on_error_slash
        self._flush_antispam.start()

    async def cog_unload(self):
        self._flush_antispam.cancel()
        if self._on_error_original is not None:
            self.bot.on_error = self._on_error_original
        if self._tree_on_error_original is not None:
            self.bot.tree.on_error = self._tree_on_error_original

    async def admin_id(self) -> int:
        if Config.ADMIN_ID:
            return Config.ADMIN_ID
        if self._admin_cache is None:
            app = await self.bot.application_info()
            self._admin_cache = app.team.owner_id if app.team else app.owner.id
        return self._admin_cache

    @staticmethod
    def _marcar_manejado(error: Exception):
        try:
            setattr(error, '_errores_manejado', True)
        except Exception:
            pass

    @staticmethod
    def _ya_manejado(error: Exception) -> bool:
        return bool(getattr(error, '_errores_manejado', False))

    async def responder_slash(self, interaction: discord.Interaction, texto: str):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(texto, ephemeral=True)
        except Exception as e:
            print(f'⚠️ Errores: no se pudo responder al usuario: {e}')

    async def responder_y_marcar(self, interaction: discord.Interaction,
                                 error: Exception, texto: str):
        self._marcar_manejado(error)
        await self.responder_slash(interaction, texto)

    @staticmethod
    def _texto_esperado(error: Exception) -> str | None:
        if isinstance(error, commands.CommandNotFound):
            return "❌ Comando no encontrado. Usá `!help` para ver la lista."
        if isinstance(error, (commands.CommandOnCooldown, app_commands.CommandOnCooldown)):
            return f"⏳ Espera {error.retry_after:.0f}s antes de volver a usarlo."
        if isinstance(error, (commands.MissingRequiredArgument, app_commands.TransformerError)):
            argumento = getattr(getattr(error, 'param', None), 'name', None)
            if argumento:
                return f"❌ Falta el argumento `{argumento}`."
            return "❌ Faltan argumentos o alguno no es válido."
        if isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            return "❌ Argumento inválido. Revisá el uso con `!help`."
        if isinstance(error, (commands.MissingPermissions, commands.BotMissingPermissions,
                              app_commands.MissingPermissions, app_commands.BotMissingPermissions)):
            return "❌ No tenés los permisos necesarios para usar esto."
        if isinstance(error, (commands.MissingRole, commands.BotMissingRole,
                              commands.MissingAnyRole, commands.BotMissingAnyRole)):
            return "❌ Falta un rol necesario para usar esto."
        if isinstance(error, (commands.NotOwner, commands.CheckFailure,
                              app_commands.CheckFailure)):
            return "❌ No tenés permiso para usar este comando."
        if isinstance(error, (commands.NoPrivateMessage, app_commands.NoPrivateMessage)):
            return "❌ Este comando solo funciona dentro de un servidor."
        if isinstance(error, commands.NSFWChannelRequired):
            return "❌ Este comando solo funciona en canales NSFW."
        return None

    async def _on_error_evento(self, event_method: str, /, *args, **kwargs):
        try:
            tb = traceback.format_exc()
            usuario, canal = _contexto_args(args)
            await self.reportar(
                tipo='evento', nombre=event_method, error=None, tb=tb,
                usuario=usuario, canal=canal,
            )
        except Exception:
            traceback.print_exc()

    async def _on_error_slash(self, interaction: discord.Interaction,
                              error: app_commands.AppCommandError, /):
        try:
            await self.procesar_slash(interaction, error)
        except Exception:
            traceback.print_exc()

    async def procesar_slash(self, interaction: discord.Interaction,
                             error: Exception, *, desde_handler: bool = False):
        if self._ya_manejado(error):
            return

        comando = getattr(interaction, 'command', None)
        if not desde_handler and comando is not None and comando._has_any_error_handlers():
            return

        self._marcar_manejado(error)
        original = getattr(error, 'original', error)
        texto = self._texto_esperado(original)
        if texto is not None:
            await self.responder_slash(interaction, texto)
            return

        nombre = getattr(comando, 'qualified_name', None) or 'slash'
        await self.reportar(
            tipo='slash', nombre=nombre, error=original, tb=None,
            usuario=getattr(interaction, 'user', None),
            canal=getattr(interaction, 'channel', None),
        )
        await self.responder_slash(
            interaction, "❌ Ocurrió un error inesperado. Ya avisé al admin."
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        try:
            if ctx.command is not None:
                if ctx.command.has_error_handler():
                    return
                if ctx.cog is not None and ctx.cog.has_error_handler():
                    return

            original = getattr(error, 'original', error)
            texto = self._texto_esperado(original)
            if texto is not None:
                try:
                    await ctx.send(texto)
                except discord.HTTPException:
                    pass
                return

            nombre = ctx.command.qualified_name if ctx.command else 'desconocido'
            await self.reportar(
                tipo='comando', nombre=nombre, error=original, tb=None,
                usuario=ctx.author, canal=ctx.channel,
            )
            try:
                await ctx.send("❌ Ocurrió un error inesperado. Ya avisé al admin.")
            except discord.HTTPException:
                pass
        except Exception:
            traceback.print_exc()

    async def reportar_tarea(self, nombre: str, error: Exception):
        tb = _texto_traceback(error, None)
        await self.reportar(tipo='tarea', nombre=nombre, error=error, tb=tb)

    async def reportar(self, *, tipo: str, nombre: str, error: Exception | None,
                       tb: str | None, usuario=None, canal=None):
        texto_tb = censurar_secretos(_texto_traceback(error, tb))
        nombre = str(nombre or 'desconocido')
        if error is not None:
            firma = f'{type(error).__name__}:{_ubicacion(error)}'
        else:
            lineas = [linea for linea in texto_tb.strip().splitlines() if linea]
            firma = lineas[-1][:200] if lineas else 'sin_error'
        clave = f'{tipo}:{nombre}:{firma}'
        aviso = self.anti_spam.registrar(clave)

        detalle = {
            'tipo': tipo,
            'nombre': nombre,
            'usuario': usuario,
            'canal': canal,
            'tb': texto_tb,
            'hora': datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S %Z'),
        }
        self._detalles[clave] = detalle

        print(
            f'[ERROR] {tipo} | {nombre} | usuario={_nombre_objeto(usuario)} '
            f'| canal={_nombre_objeto(canal)} | {type(error).__name__ if error else "sin excepción"}'
        )
        print(texto_tb)

        if aviso is None:
            return

        motivo, conteo = aviso
        repeticiones = max(0, conteo - 1) if motivo == 'resumen' else 0
        try:
            await self._enviar_reporte(detalle, repeticiones=repeticiones)
        except Exception:
            traceback.print_exc()

    @tasks.loop(seconds=30)
    async def _flush_antispam(self):
        try:
            for clave, conteo in self.anti_spam.flush():
                detalle = self._detalles.pop(clave, None)
                if detalle is not None and conteo > 1:
                    await self._enviar_reporte(detalle, repeticiones=conteo - 1)
        except Exception:
            traceback.print_exc()

    @_flush_antispam.before_loop
    async def _antes_flush(self):
        await self.bot.wait_until_ready()

    @_flush_antispam.error
    async def _error_flush(self, error: Exception):
        tb = censurar_secretos(_texto_traceback(error, None))
        print(f'[ERROR] Tarea errores._flush_antispam: {type(error).__name__}')
        print(tb)
        reiniciar_loop(self._flush_antispam)

    @staticmethod
    def _archivo(tb: str, hora: str | None = None) -> discord.File:
        marca = hora or datetime.now(TZ).strftime('%Y-%m-%d_%H-%M-%S')
        marca = marca.replace(' ', '_').replace(':', '-')
        datos = io.BytesIO(tb.encode('utf-8', errors='replace'))
        return discord.File(datos, filename=f'error_{marca}.txt')

    def _embed_reporte(self, detalle: dict, repeticiones: int) -> tuple[discord.Embed, bool]:
        tb = detalle['tb']
        adjuntar = len(tb) > LIMITE_TRACEBACK
        embed = discord.Embed(
            title='🚨 Error inesperado',
            color=discord.Color.red(),
            timestamp=datetime.now(TZ),
        )
        if adjuntar:
            embed.description = 'El traceback completo va adjunto como archivo `.txt`.'
        else:
            embed.description = f'```py\n{tb[-LIMITE_TRACEBACK:]}\n```'
        embed.add_field(name='Tipo', value=detalle['tipo'].capitalize())
        embed.add_field(name='Comando o tarea', value=f'`{detalle["nombre"]}`'[:1024])
        embed.add_field(name='Usuario', value=_nombre_objeto(detalle['usuario'])[:1024])
        embed.add_field(name='Canal', value=_nombre_objeto(detalle['canal'])[:1024])
        embed.add_field(name='Hora (Tijuana)', value=detalle['hora'])
        if repeticiones > 0:
            veces = 'vez' if repeticiones == 1 else 'veces'
            embed.add_field(
                name='Anti-spam',
                value=f'Se repitió **{repeticiones}** {veces} en los últimos 10 minutos.',
                inline=False,
            )
        return embed, adjuntar

    async def _canal_respaldo(self):
        vistos = set()
        for canal_id in (Config.PAGOS_CANAL_ID, Config.AVISO_CANAL_ID, Config.CANAL_ID):
            if not canal_id or canal_id in vistos:
                continue
            vistos.add(canal_id)
            canal = self.bot.get_channel(canal_id)
            if canal is None:
                try:
                    canal = await self.bot.fetch_channel(canal_id)
                except discord.HTTPException:
                    canal = None
            if canal is not None:
                return canal
        return None

    async def enviar_al_admin(self, *, embed=None, contenido: str | None = None,
                              archivo_tb: str | None = None) -> bool:
        admin = None
        try:
            admin = await self.admin_id()
        except Exception as e:
            print(f'⚠️ Errores: no se pudo resolver el admin: {e}')

        if admin:
            try:
                usuario = self.bot.get_user(admin) or await self.bot.fetch_user(admin)
                kwargs = {}
                if contenido:
                    kwargs['content'] = contenido
                if embed is not None:
                    kwargs['embed'] = embed
                if archivo_tb is not None:
                    kwargs['file'] = self._archivo(archivo_tb)
                await usuario.send(**kwargs)
                return True
            except Exception as e:
                print(f'⚠️ Errores: DM al admin falló ({e}); usando canal de respaldo')

        canal = await self._canal_respaldo()
        if canal is None:
            print('❌ Errores: no hay DM ni canal de respaldo disponible')
            return False
        try:
            kwargs = {}
            mencion = contenido if contenido is not None else (f'<@{admin}>' if admin else None)
            if mencion:
                kwargs['content'] = mencion
            if embed is not None:
                kwargs['embed'] = embed
            if archivo_tb is not None:
                kwargs['file'] = self._archivo(archivo_tb)
            await canal.send(**kwargs)
            return True
        except Exception as e:
            print(f'❌ Errores: tampoco se pudo enviar al canal de respaldo: {e}')
            return False

    async def _enviar_reporte(self, detalle: dict, repeticiones: int = 0):
        embed, adjuntar = self._embed_reporte(detalle, repeticiones)
        await self.enviar_al_admin(
            embed=embed,
            archivo_tb=detalle['tb'] if adjuntar else None,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Errores(bot))
