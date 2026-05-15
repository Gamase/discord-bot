import asyncio
import os
import tempfile

import discord
import pyttsx3
from discord.ext import commands

VOICE_NAME = 'Microsoft Sabina Desktop'


def _tts_sync(texto: str) -> str:
    """Genera WAV temporal con pyttsx3 (bloqueante — llamar en executor)."""
    engine = pyttsx3.init()
    try:
        for voice in engine.getProperty('voices'):
            if VOICE_NAME in voice.name:
                engine.setProperty('voice', voice.id)
                break

        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp.close()

        engine.save_to_file(texto, tmp.name)
        engine.runAndWait()
        return tmp.name
    finally:
        engine.stop()


class Voz(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='hablar')
    async def hablar(self, ctx: commands.Context, *, texto: str):
        """Lee un texto en el canal de voz con la voz Sabina. Uso: !hablar [texto]"""
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz.")

        channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client

        if vc:
            if vc.is_playing():
                return
            await vc.move_to(channel)
        else:
            vc = await channel.connect()

        try:
            loop = asyncio.get_event_loop()
            tmp_path = await loop.run_in_executor(None, _tts_sync, texto)
        except Exception as e:
            return await ctx.send(f"❌ Error generando TTS: {e}")

        def after_tts(error: Exception | None):
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            if error:
                print(f'❌ Error reproduciendo TTS: {error}')

        vc.play(discord.FFmpegPCMAudio(tmp_path), after=after_tts)


async def setup(bot: commands.Bot):
    await bot.add_cog(Voz(bot))
