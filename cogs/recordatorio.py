import re
import time
from datetime import datetime

import discord
from discord.ext import commands, tasks

import db
from config import Config


def _parse_duracion(texto: str) -> int:
    total = 0
    for numero, unidad in re.findall(r'(\d+)\s*([smhd])', texto.lower()):
        total += int(numero) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[unidad]
    return total


def _fmt_duracion(segundos: int) -> str:
    partes = []
    for nombre, valor in (('d', 86400), ('h', 3600), ('m', 60), ('s', 1)):
        if segundos >= valor:
            cantidad, segundos = divmod(segundos, valor)
            partes.append(f"{cantidad}{nombre}")
    return ' '.join(partes) or '0s'


class Recordatorio(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.recordatorio_loop.start()
        self.revisar_recordatorios.start()

    def cog_unload(self):
        self.recordatorio_loop.cancel()
        self.revisar_recordatorios.cancel()

    def _build_mensaje(self, manual: bool = False) -> str:
        hoy = datetime.now()
        menciones = " ".join(Config.AMIGOS)
        icono = "🔔" if manual else "🎬"
        titulo = "RECORDATORIO MANUAL" if manual else "RECORDATORIO MENSUAL"
        return (
            f"{icono} **{titulo} - YOUTUBE PREMIUM** {icono}\n\n"
            f"{menciones}\n\n"
            f"¡Paguen el YOUTUBE PREMIUM PERRAAAAS!\n\n"
            f"💰 **Precio por persona:** ${Config.PRECIO}\n"
            f"📅 **Para el mes:** {hoy.strftime('%B %Y')}\n"
            f"💳 **Método de pago:** CLABE INTERBANCARIA: 012180015553970603\n"
        )

    @tasks.loop(hours=24)
    async def recordatorio_loop(self):
        try:
            hoy = datetime.now()
            if hoy.day == Config.DIA_RECORDATORIO:
                canal = self.bot.get_channel(Config.CANAL_ID)
                if canal:
                    await canal.send(self._build_mensaje())
                    print(f'📢 Recordatorio automático enviado el día {hoy.day}')
                else:
                    print(f'❌ Canal {Config.CANAL_ID} no encontrado')
        except Exception as e:
            print(f'❌ Error en recordatorio_loop: {e}')

    @recordatorio_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    @recordatorio_loop.error
    async def loop_error(self, error: Exception):
        print(f'❌ Error fatal en recordatorio_loop: {error}')
        # Reiniciar el loop tras un error
        self.recordatorio_loop.restart()

    @commands.hybrid_command(
        name='forzar_recordatorio',
        description='Envía un recordatorio de pago de YouTube Premium manualmente'
    )
    async def forzar_recordatorio(self, ctx: commands.Context):
        await ctx.send(self._build_mensaje(manual=True))

    @commands.hybrid_command(
        name='prueba',
        description='Verifica que el bot está funcionando correctamente'
    )
    async def prueba(self, ctx: commands.Context):
        await ctx.send("🤖 ¡Bot funcionando correctamente!")

    @commands.hybrid_command(
        name='estado_recordatorio',
        description='Muestra el estado del recordatorio automático'
    )
    async def estado_recordatorio(self, ctx: commands.Context):
        corriendo = self.recordatorio_loop.is_running()
        next_iter = self.recordatorio_loop.next_iteration

        embed = discord.Embed(title="📋 Estado del Recordatorio", color=discord.Color.blue())
        embed.add_field(name="Estado", value="✅ Activo" if corriendo else "❌ Inactivo", inline=True)
        embed.add_field(name="Día configurado", value=str(Config.DIA_RECORDATORIO), inline=True)
        embed.add_field(name="Precio", value=f"${Config.PRECIO}", inline=True)
        if next_iter:
            embed.add_field(
                name="Próxima revisión",
                value=f"<t:{int(next_iter.timestamp())}:R>",
                inline=False
            )
        await ctx.send(embed=embed)

    @tasks.loop(seconds=30)
    async def revisar_recordatorios(self):
        try:
            for fila in db.reminder_due(int(time.time())):
                rid = fila['id']
                canal = self.bot.get_channel(fila['channel_id'])
                if canal:
                    try:
                        await canal.send(
                            f"⏰ <@{fila['user_id']}> recordatorio: **{fila['message']}**"
                        )
                    except Exception as e:
                        print(f'⚠️ No se pudo enviar recordatorio #{rid}: {e}')
                db.reminder_delete_by_id(rid)
        except Exception as e:
            print(f'❌ Error en revisar_recordatorios: {e}')

    @revisar_recordatorios.before_loop
    async def before_revisar(self):
        await self.bot.wait_until_ready()

    @commands.command(name='recordar', aliases=['recuerdame', 'recuérdame'])
    async def recordar(self, ctx: commands.Context, tiempo: str, *, mensaje: str):
        """Crea un recordatorio. Uso: !recordar 10m <texto>"""
        segundos = _parse_duracion(tiempo)
        if segundos <= 0:
            return await ctx.send(
                "❌ Tiempo inválido. Ejemplos: `10m`, `2h`, `1d`, `1h30m`."
            )
        if segundos > 365 * 86400:
            return await ctx.send("❌ Máximo 1 año.")

        remind_at = int(time.time()) + segundos
        rid = db.reminder_add(ctx.author.id, ctx.channel.id, mensaje, remind_at)
        await ctx.send(
            f"⏰ Recordatorio **#{rid}** en **{_fmt_duracion(segundos)}**: {mensaje}"
        )

    @commands.command(name='recordatorios', aliases=['misrecordatorios'])
    async def recordatorios(self, ctx: commands.Context):
        """Lista tus recordatorios pendientes."""
        filas = db.reminder_list(ctx.author.id)
        if not filas:
            return await ctx.send("📭 No tenés recordatorios pendientes.")

        lineas = [f"`#{f['id']}` <t:{f['remind_at']}:R> — {f['message']}" for f in filas]
        embed = discord.Embed(
            title="⏰ Tus recordatorios",
            description="\n".join(lineas)[:4000],
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed)

    @commands.command(name='olvidar', aliases=['borrarrecordatorio'])
    async def olvidar(self, ctx: commands.Context, recordatorio_id: int):
        """Elimina un recordatorio. Uso: !olvidar <id>"""
        cantidad = db.reminder_delete(recordatorio_id, ctx.author.id)
        if not cantidad:
            return await ctx.send("❌ No existe ese recordatorio (o no es tuyo).")
        await ctx.send(f"🗑️ Recordatorio **#{recordatorio_id}** eliminado.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Recordatorio(bot))
