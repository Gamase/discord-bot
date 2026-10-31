import asyncio
import sys
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import discord
from discord.ext import commands
from config import Config
from db import init_db

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
)
bot.remove_command('help')

COGS = [
    'cogs.errores',
    'cogs.general',
    'cogs.recordatorio',
    'cogs.musica',
    'cogs.voz',
    'cogs.ia',
    'cogs.pagos',
    'cogs.servidor',
]

HEARTBEAT = Path(__file__).resolve().parent / 'heartbeat'
_anunciado = False


async def heartbeat_loop():
    while True:
        try:
            HEARTBEAT.write_text(str(int(time.time())))
        except Exception as e:
            print(f'⚠️ No se pudo escribir heartbeat: {e}')
        await asyncio.sleep(30)


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
        await bot.process_commands(message)


async def sincronizar_comandos():
    guild_id = Config.GUILD_ID
    if not guild_id:
        canal = bot.get_channel(Config.CANAL_ID)
        guild_id = canal.guild.id if getattr(canal, 'guild', None) else 0

    if not guild_id:
        synced = await bot.tree.sync()
        print(f'🔄 {len(synced)} slash commands sincronizados (global, pueden tardar en aparecer)')
        return

    # Sync por servidor = aparecen al instante. Luego se vacían los globales
    # para no ver cada comando duplicado.
    guild = discord.Object(id=guild_id)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    print(f'🔄 {len(synced)} slash commands sincronizados al servidor {guild_id}')


@bot.event
async def on_ready():
    global _anunciado
    print(f'✅ Bot conectado como {bot.user}')

    if not _anunciado:
        _anunciado = True
        try:
            await sincronizar_comandos()
        except Exception as e:
            print(f'❌ Error sincronizando slash commands: {e}')
        await avisar_en_linea()


async def main():
    init_db()
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


if __name__ == '__main__':
    asyncio.run(main())
