import asyncio
import re
import time

import discord
from discord.ext import commands, tasks

import db
from cogs.errores import reiniciar_loop, reportar_tarea_desde


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
        self.revisar_recordatorios.start()

    def cog_unload(self):
        self.revisar_recordatorios.cancel()

    @commands.hybrid_command(
        name='prueba',
        description='Verifica que el bot está funcionando correctamente'
    )
    async def prueba(self, ctx: commands.Context):
        await ctx.send("🤖 ¡Bot funcionando correctamente!")

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
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await reportar_tarea_desde(self.bot, 'recordatorio.revisar_recordatorios', e)

    @revisar_recordatorios.before_loop
    async def before_revisar(self):
        await self.bot.wait_until_ready()

    @revisar_recordatorios.error
    async def _error_revisar_recordatorios(self, error: Exception):
        await reportar_tarea_desde(self.bot, 'recordatorio.revisar_recordatorios', error)
        reiniciar_loop(self.revisar_recordatorios)

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
