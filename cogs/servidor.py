import asyncio
import json
import os
import shutil
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
from config import Config
from cogs.errores import reiniciar_loop, reportar_tarea_desde

TIMEOUT_TERMUX = 10
DEFAULTS = {
    'servidor_bateria_min': '20',
    'servidor_bateria_rearme': '25',
    'servidor_temp_max': '45',
    'servidor_temp_rearme': '42',
}


def _a_float(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _fmt_bytes(cantidad: float) -> str:
    unidades = ('B', 'KB', 'MB', 'GB', 'TB')
    valor = float(cantidad)
    for unidad in unidades:
        if valor < 1024 or unidad == unidades[-1]:
            if unidad == 'B':
                return f'{int(valor)} B'
            return f'{valor:.1f} {unidad}'
        valor /= 1024
    return f'{valor:.1f} TB'


def _fmt_uptime(segundos: float | None) -> str | None:
    if segundos is None:
        return None
    total = int(segundos)
    dias, resto = divmod(total, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segs = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f'{dias}d')
    if horas or dias:
        partes.append(f'{horas}h')
    partes.append(f'{minutos}m')
    partes.append(f'{segs}s')
    return ' '.join(partes)


def _leer_uptime_telefono() -> float | None:
    try:
        return float(Path('/proc/uptime').read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _leer_memoria() -> dict | None:
    try:
        lineas = Path('/proc/meminfo').read_text().splitlines()
    except OSError:
        return None
    datos = {}
    for linea in lineas:
        partes = linea.split()
        if len(partes) >= 2 and partes[0].endswith(':'):
            try:
                datos[partes[0][:-1]] = int(partes[1]) * 1024
            except ValueError:
                continue
    total = datos.get('MemTotal')
    disponible = datos.get('MemAvailable')
    if disponible is None:
        disponible = sum(datos.get(clave, 0) for clave in ('MemFree', 'Buffers', 'Cached'))
    if not total:
        return None
    return {'total': total, 'disponible': disponible}


def _leer_disco() -> dict | None:
    rutas = (os.environ.get('HOME'), str(Path.home()), '/')
    for ruta in rutas:
        if not ruta:
            continue
        try:
            uso = shutil.disk_usage(ruta)
            return {'libre': uso.free, 'total': uso.total}
        except OSError:
            continue
    return None


class GestorAlertas:
    def __init__(self):
        self.bateria_en_alerta = False
        self.temperatura_en_alerta = False

    def evaluar(self, bateria: float | None, cargando: bool | None,
                temperatura: float | None, bateria_min: float, bateria_rearme: float,
                temp_max: float, temp_rearme: float) -> list[dict]:
        avisos = []

        if bateria is not None:
            if not self.bateria_en_alerta:
                if not cargando and bateria < bateria_min:
                    self.bateria_en_alerta = True
                    avisos.append({'tipo': 'bateria', 'estado': 'alerta', 'valor': bateria})
            elif cargando or bateria >= bateria_rearme:
                self.bateria_en_alerta = False
                avisos.append({'tipo': 'bateria', 'estado': 'recuperado', 'valor': bateria})

        if temperatura is not None:
            if not self.temperatura_en_alerta:
                if temperatura > temp_max:
                    self.temperatura_en_alerta = True
                    avisos.append({'tipo': 'temperatura', 'estado': 'alerta', 'valor': temperatura})
            elif temperatura < temp_rearme:
                self.temperatura_en_alerta = False
                avisos.append({'tipo': 'temperatura', 'estado': 'recuperado', 'valor': temperatura})

        return avisos


async def _es_admin(interaction: discord.Interaction) -> bool:
    cog = interaction.client.get_cog('Servidor')
    return cog is not None and interaction.user.id == await cog.admin_id()


solo_admin = app_commands.check(_es_admin)


class Servidor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inicio = time.time()
        self.alertas = GestorAlertas()
        self._admin_cache: int | None = None

    async def cog_load(self):
        db.settings_seed(DEFAULTS)
        self.vigilar.start()

    async def cog_unload(self):
        self.vigilar.cancel()

    async def admin_id(self) -> int:
        if Config.ADMIN_ID:
            return Config.ADMIN_ID
        if self._admin_cache is None:
            app = await self.bot.application_info()
            self._admin_cache = app.team.owner_id if app.team else app.owner.id
        return self._admin_cache

    @staticmethod
    def _en_termux() -> bool:
        if shutil.which('termux-battery-status') is None:
            return False
        prefix = os.environ.get('PREFIX', '')
        return prefix.startswith('/data/data/com.termux') or os.path.isdir('/data/data/com.termux')

    async def _leer_bateria(self) -> dict | None:
        if not self._en_termux():
            return None
        try:
            proceso = await asyncio.create_subprocess_exec(
                'termux-battery-status',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as e:
            print(f'⚠️ Servidor: no se pudo ejecutar termux-battery-status: {e}')
            return None

        try:
            salida, _ = await asyncio.wait_for(proceso.communicate(), timeout=TIMEOUT_TERMUX)
        except asyncio.TimeoutError:
            try:
                proceso.kill()
            except ProcessLookupError:
                pass
            await proceso.wait()
            print('⚠️ Servidor: termux-battery-status no respondió en 10 s')
            return None

        if proceso.returncode != 0:
            print(f'⚠️ Servidor: termux-battery-status terminó con código {proceso.returncode}')
            return None

        try:
            datos = json.loads(salida.decode('utf-8', errors='replace'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f'⚠️ Servidor: respuesta inválida de termux-battery-status: {e}')
            return None

        estado = str(datos.get('status') or '').upper()
        enchufe = str(datos.get('plugged') or '').upper()
        cargando = (
            enchufe in ('PLUGGED_AC', 'PLUGGED_USB', 'PLUGGED_WIRELESS')
            or estado in ('CHARGING', 'FULL')
        )
        return {
            'porcentaje': _a_float(datos.get('percentage')),
            'temperatura': _a_float(datos.get('temperature')),
            'cargando': cargando,
        }

    def _umbrales(self) -> dict[str, float]:
        valores = {}
        for clave, defecto in DEFAULTS.items():
            guardado = db.setting_get(clave)
            valores[clave] = _a_float(guardado)
            if valores[clave] is None:
                valores[clave] = float(defecto)
        return valores

    def _datos(self, bateria: dict | None) -> dict:
        en_termux = self._en_termux()
        memoria = _leer_memoria() if en_termux else None
        disco = _leer_disco() if en_termux else None
        uptime_tel = _leer_uptime_telefono() if en_termux else None
        latencia = self.bot.latency
        return {
            'bateria': bateria,
            'memoria': memoria,
            'disco': disco,
            'uptime_tel': uptime_tel,
            'uptime_bot': time.time() - self.inicio,
            'latencia': None if latencia != latencia else round(latencia * 1000),
        }

    def _embed_servidor(self, datos: dict) -> discord.Embed:
        bateria = datos['bateria']
        memoria = datos['memoria']
        disco = datos['disco']
        embed = discord.Embed(
            title='📱 Estado del servidor',
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )

        if bateria is None:
            bateria_pct = cargando = temperatura = 'no disponible'
        else:
            pct = bateria['porcentaje']
            temp = bateria['temperatura']
            bateria_pct = f'{pct:.0f}%' if pct is not None else 'no disponible'
            cargando = 'Sí' if bateria['cargando'] else 'No'
            temperatura = f'{temp:.1f} °C' if temp is not None else 'no disponible'

        embed.add_field(name='🔋 Batería', value=bateria_pct)
        embed.add_field(name='🔌 Cargando', value=cargando)
        embed.add_field(name='🌡️ Temperatura batería', value=temperatura)
        embed.add_field(
            name='📱 Uptime del teléfono',
            value=_fmt_uptime(datos['uptime_tel']) or 'no disponible',
        )
        embed.add_field(
            name='🤖 Uptime del bot',
            value=_fmt_uptime(datos['uptime_bot']) or 'no disponible',
        )
        if disco is None:
            almacenamiento = 'no disponible'
        else:
            almacenamiento = f'{_fmt_bytes(disco["libre"])} libres de {_fmt_bytes(disco["total"])}'
        embed.add_field(name='💾 Almacenamiento', value=almacenamiento)
        if memoria is None:
            ram = 'no disponible'
        else:
            usada = memoria['total'] - memoria['disponible']
            ram = f'{_fmt_bytes(usada)} usados de {_fmt_bytes(memoria["total"])}'
        embed.add_field(name='🧠 RAM', value=ram)
        latencia = datos['latencia']
        embed.add_field(
            name='📡 Latencia Discord',
            value=f'{latencia} ms' if latencia is not None else 'no disponible',
        )
        return embed

    @app_commands.command(name='servidor', description='Muestra el estado del teléfono donde corre el bot')
    @solo_admin
    async def servidor(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bateria = await self._leer_bateria()
        embed = self._embed_servidor(self._datos(bateria))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name='umbrales', description='Cambia los umbrales de alertas del servidor')
    @solo_admin
    @app_commands.describe(
        bateria_min='Porcentaje de batería que dispara la alerta',
        bateria_rearme='Porcentaje para rearmar la alerta de batería',
        temp_max='Temperatura en °C que dispara la alerta',
        temp_rearme='Temperatura en °C para rearmar la alerta',
    )
    async def umbrales(self, interaction: discord.Interaction,
                       bateria_min: float | None = None,
                       bateria_rearme: float | None = None,
                       temp_max: float | None = None,
                       temp_rearme: float | None = None):
        valores = self._umbrales()
        cambios = {
            'servidor_bateria_min': bateria_min,
            'servidor_bateria_rearme': bateria_rearme,
            'servidor_temp_max': temp_max,
            'servidor_temp_rearme': temp_rearme,
        }
        for clave, valor in cambios.items():
            if valor is not None:
                valores[clave] = valor

        if not 0 <= valores['servidor_bateria_min'] <= 100:
            return await interaction.response.send_message(
                '❌ La batería mínima debe estar entre 0 y 100.', ephemeral=True
            )
        if not 0 <= valores['servidor_bateria_rearme'] <= 100:
            return await interaction.response.send_message(
                '❌ El rearme de batería debe estar entre 0 y 100.', ephemeral=True
            )
        if valores['servidor_bateria_rearme'] <= valores['servidor_bateria_min']:
            return await interaction.response.send_message(
                '❌ El rearme de batería debe ser mayor que la alerta mínima.', ephemeral=True
            )
        if valores['servidor_temp_max'] <= valores['servidor_temp_rearme']:
            return await interaction.response.send_message(
                '❌ La temperatura máxima debe ser mayor que la de rearme.', ephemeral=True
            )

        for clave, valor in cambios.items():
            if valor is not None:
                db.setting_set(clave, str(valor))

        embed = discord.Embed(
            title='⚙️ Umbrales del servidor',
            color=discord.Color.blurple(),
        )
        embed.add_field(name='Batería baja', value=f"{valores['servidor_bateria_min']:.0f}%")
        embed.add_field(name='Rearme batería', value=f"{valores['servidor_bateria_rearme']:.0f}%")
        embed.add_field(name='Temperatura máxima', value=f"{valores['servidor_temp_max']:.1f} °C")
        embed.add_field(name='Rearme temperatura', value=f"{valores['servidor_temp_rearme']:.1f} °C")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(minutes=5)
    async def vigilar(self):
        try:
            bateria = await self._leer_bateria()
            if bateria is None:
                return
            if bateria['porcentaje'] is None and bateria['temperatura'] is None:
                return

            umbrales = self._umbrales()
            avisos = self.alertas.evaluar(
                bateria['porcentaje'],
                bateria['cargando'],
                bateria['temperatura'],
                umbrales['servidor_bateria_min'],
                umbrales['servidor_bateria_rearme'],
                umbrales['servidor_temp_max'],
                umbrales['servidor_temp_rearme'],
            )
            for aviso in avisos:
                await self._enviar_alerta(aviso, umbrales)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await reportar_tarea_desde(self.bot, 'servidor.vigilar', e)

    @vigilar.before_loop
    async def _antes_vigilar(self):
        await self.bot.wait_until_ready()

    @vigilar.error
    async def _error_vigilar(self, error: Exception):
        await reportar_tarea_desde(self.bot, 'servidor.vigilar', error)
        reiniciar_loop(self.vigilar)

    async def _enviar_alerta(self, aviso: dict, umbrales: dict):
        tipo = aviso['tipo']
        estado = aviso['estado']
        valor = aviso['valor']

        if tipo == 'bateria':
            if estado == 'alerta':
                embed = discord.Embed(
                    title='🔋 Batería baja',
                    description=(
                        f'El teléfono tiene **{valor:.0f}%** y no está cargando '
                        f'(umbral: {umbrales["servidor_bateria_min"]:.0f}%).'
                    ),
                    color=discord.Color.orange(),
                )
            else:
                embed = discord.Embed(
                    title='🔋 Batería recuperada',
                    description=(
                        f'El teléfono está en **{valor:.0f}%** o ya está cargando '
                        f'(rearme: {umbrales["servidor_bateria_rearme"]:.0f}%).'
                    ),
                    color=discord.Color.green(),
                )
        else:
            if estado == 'alerta':
                embed = discord.Embed(
                    title='🌡️ Teléfono caliente',
                    description=(
                        f'La batería está a **{valor:.1f} °C** '
                        f'(umbral: {umbrales["servidor_temp_max"]:.1f} °C).'
                    ),
                    color=discord.Color.red(),
                )
            else:
                embed = discord.Embed(
                    title='🌡️ Temperatura normalizada',
                    description=(
                        f'La batería está a **{valor:.1f} °C** '
                        f'(rearme: {umbrales["servidor_temp_rearme"]:.1f} °C).'
                    ),
                    color=discord.Color.green(),
                )

        embed.timestamp = discord.utils.utcnow()
        errores = self.bot.get_cog('Errores')
        if errores is not None:
            await errores.enviar_al_admin(embed=embed)
            return

        admin = None
        try:
            admin = await self.admin_id()
            usuario = self.bot.get_user(admin) or await self.bot.fetch_user(admin)
            await usuario.send(embed=embed)
            return
        except Exception as e:
            print(f'⚠️ Servidor: DM de alerta falló ({e}); usando canal de respaldo')

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
            if canal is None:
                continue
            try:
                contenido = f'<@{admin}>' if admin else None
                await canal.send(content=contenido, embed=embed)
                return
            except Exception as e:
                print(f'⚠️ Servidor: no se pudo enviar al canal {canal_id}: {e}')


async def setup(bot: commands.Bot):
    await bot.add_cog(Servidor(bot))
