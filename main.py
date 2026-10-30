import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import discord
from aiohttp import web
from discord.ext import commands
from config import Config
from db import init_db

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

COGS = ['cogs.general', 'cogs.recordatorio', 'cogs.musica', 'cogs.voz', 'cogs.ia']

HEARTBEAT = Path(__file__).resolve().parent / 'heartbeat'
HEALTH_HOST = os.getenv('HEALTH_HOST', '127.0.0.1')
HEALTH_PORT = int(os.getenv('HEALTH_PORT', '8787'))
_anunciado = False


async def heartbeat_loop():
    while True:
        try:
            HEARTBEAT.write_text(str(int(time.time())))
        except Exception as e:
            print(f'⚠️ No se pudo escribir heartbeat: {e}')
        await asyncio.sleep(30)


async def _health(request: web.Request) -> web.Response:
    if not bot.is_ready() or bot.is_closed():
        return web.Response(status=503, text='down')
    try:
        edad = time.time() - HEARTBEAT.stat().st_mtime
    except OSError:
        edad = 99999
    if edad > 90:
        return web.Response(status=503, text='stale')
    return web.Response(text='ok')


async def iniciar_salud() -> web.AppRunner | None:
    app = web.Application()
    app.router.add_get('/health', _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HEALTH_HOST, HEALTH_PORT)
    await site.start()
    print(f'❤️ Health: http://{HEALTH_HOST}:{HEALTH_PORT}/health')
    return runner


async def avisar_en_linea():
    canal_id = Config.AVISO_CANAL_ID
    canal = bot.get_channel(canal_id) if canal_id else None
    if canal is None:
        return
    try:
        await canal.send("✅ Bot en línea.")
    except Exception as e:
        print(f'⚠️ No se pudo enviar aviso de arranque: {e}')


@bot.event
async def on_message(message: discord.Message):
    if not message.author.bot:
        print(f'[DEBUG] {message.author} ({message.guild}/{message.channel}): {message.content}')
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    print(f'[ERROR] Comando: {ctx.message.content!r} | Autor: {ctx.author}')
    traceback.print_exception(type(error), error, error.__traceback__)


@bot.event
async def on_ready():
    global _anunciado
    print(f'✅ Bot conectado como {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'🔄 {len(synced)} slash commands sincronizados')
    except Exception as e:
        print(f'❌ Error sincronizando slash commands: {e}')

    if not _anunciado:
        _anunciado = True
        await avisar_en_linea()


async def main():
    init_db()
    runner = None
    try:
        runner = await iniciar_salud()
    except Exception as e:
        print(f'⚠️ No se pudo iniciar health endpoint: {e}')
    hb = asyncio.create_task(heartbeat_loop())
    try:
        async with bot:
            for cog in COGS:
                try:
                    await bot.load_extension(cog)
                    print(f'✅ Cog cargado: {cog}')
                except Exception as e:
                    print(f'❌ Error cargando {cog}: {e}')
            await bot.start(Config.TOKEN)
    finally:
        hb.cancel()
        if runner is not None:
            await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
