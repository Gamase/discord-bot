import os
from collections import defaultdict

from discord.ext import commands
from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_HISTORY = 10
SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Eres un asistente en un servidor de Discord. "
        "Responde siempre en español, de forma clara y concisa."
    ),
}


class IA(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.historial: dict[int, list[dict]] = defaultdict(list)

    @commands.command(name='ia')
    @commands.cooldown(3, 60, commands.BucketType.user)
    async def ia(self, ctx: commands.Context, *, pregunta: str):
        """Pregunta algo a la IA. Uso: !ia <pregunta>"""
        historial = self.historial[ctx.author.id]
        historial.append({"role": "user", "content": pregunta})
        if len(historial) > MAX_HISTORY * 2:
            del historial[:-MAX_HISTORY * 2]

        async with ctx.typing():
            try:
                response = await self.client.chat.completions.create(
                    model=MODEL,
                    messages=[SYSTEM_PROMPT] + historial,
                )
                respuesta = response.choices[0].message.content or "No obtuve respuesta, intenta de nuevo."
            except Exception as e:
                print(f'❌ Error IA: {e}')
                return await ctx.send("❌ La IA falló, intenta de nuevo.")

        historial.append({"role": "assistant", "content": respuesta})

        if len(respuesta) <= 2000:
            await ctx.send(respuesta)
        else:
            for i in range(0, len(respuesta), 2000):
                await ctx.send(respuesta[i:i + 2000])


async def setup(bot: commands.Bot):
    await bot.add_cog(IA(bot))
