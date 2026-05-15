import os
from collections import defaultdict

from discord.ext import commands
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

MODEL = "llama-3.3-70b-versatile"
MAX_HISTORY = 10


class IA(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.historial: dict[int, list[dict]] = defaultdict(list)

    @commands.command(name='ia')
    async def ia(self, ctx: commands.Context, *, pregunta: str):
        """Pregunta algo a la IA. Uso: !ia <pregunta>"""
        historial = self.historial[ctx.author.id]
        historial.append({"role": "user", "content": pregunta})
        if len(historial) > MAX_HISTORY:
            del historial[:-MAX_HISTORY]

        async with ctx.typing():
            try:
                response = await self.client.chat.completions.create(
                    model=MODEL,
                    messages=historial,
                )
                respuesta = response.choices[0].message.content
            except Exception as e:
                return await ctx.send(f"❌ Error con la IA: {e}")

        historial.append({"role": "assistant", "content": respuesta})
        await ctx.send(respuesta)


async def setup(bot: commands.Bot):
    await bot.add_cog(IA(bot))
