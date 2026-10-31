import asyncio
import os
import tempfile

import discord
import edge_tts
import pyttsx3
from discord.ext import commands

VOICE = os.getenv('TTS_VOICE', 'es-MX-DaliaNeural')
VOICE_2 = os.getenv('TTS_VOICE_2', 'es-MX-JorgeNeural')

VOICE_NAMES = (
    'Microsoft Sabina Desktop',
    'Spanish (Spain)',
    'Spanish (Latin America)',
)


async def _tts_edge(texto: str, voz: str = VOICE) -> str:
    """Genera un MP3 temporal con Edge TTS (voz neuronal)."""
    tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    tmp.close()
    try:
        await edge_tts.Communicate(texto, voz).save(tmp.name)
        if os.path.getsize(tmp.name) == 0:
            raise RuntimeError('Edge TTS devolvió un archivo vacío')
        return tmp.name
    except Exception:
        os.unlink(tmp.name)
        raise


def _tts_sync(texto: str) -> str:
    """Genera WAV temporal con pyttsx3 (bloqueante — llamar en executor)."""
    engine = pyttsx3.init()
    try:
        voices = engine.getProperty('voices')
        for nombre in VOICE_NAMES:
            voz = next((v for v in voices if nombre in v.name), None)
            if voz is not None:
                engine.setProperty('voice', voz.id)
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

    @commands.command(name='h')
    async def hablar(self, ctx: commands.Context, *, texto: str):
        """Lee un texto en el canal de voz con voz en español. Uso: !h [texto]"""
        await self._decir(ctx, texto, VOICE)

    @commands.command(name='h2')
    async def hablar2(self, ctx: commands.Context, *, texto: str):
        """Lee un texto con la segunda voz configurada. Uso: !h2 [texto]"""
        await self._decir(ctx, texto, VOICE_2)

    async def _decir(self, ctx: commands.Context, texto: str, voz: str):
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
            try:
                tmp_path = await _tts_edge(texto, voz)
            except Exception as e:
                print(f'⚠️ Edge TTS falló ({e}); usando eSpeak de respaldo')
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
