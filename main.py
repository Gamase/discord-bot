import asyncio
import sys
import traceback

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import discord
from discord.ext import commands
from config import Config

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

COGS = ['cogs.recordatorio', 'cogs.musica', 'cogs.voz', 'cogs.ia']


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
    print(f'✅ Bot conectado como {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f'🔄 {len(synced)} slash commands sincronizados')
    except Exception as e:
        print(f'❌ Error sincronizando slash commands: {e}')


async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f'✅ Cog cargado: {cog}')
            except Exception as e:
                print(f'❌ Error cargando {cog}: {e}')
        await bot.start(Config.TOKEN)


if __name__ == '__main__':
    asyncio.run(main())
