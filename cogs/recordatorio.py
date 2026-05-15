import discord
from discord.ext import commands, tasks
from datetime import datetime
from config import Config


class Recordatorio(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.recordatorio_loop.start()

    def cog_unload(self):
        self.recordatorio_loop.cancel()

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


async def setup(bot: commands.Bot):
    await bot.add_cog(Recordatorio(bot))
