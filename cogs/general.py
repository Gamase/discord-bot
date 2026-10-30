import time

import discord
from discord import ui
from discord.ext import commands

CATEGORIAS = {
    '🎵 Música': ['Musica'],
    '⏰ Recordatorios': ['Recordatorio'],
    '🤖 IA': ['IA'],
    '🔊 Voz': ['Voz'],
    '⚙️ General': ['General'],
}


def _firma(cmd: commands.Command) -> str:
    partes = [f"!{cmd.name}"]
    if cmd.signature:
        partes.append(cmd.signature)
    return ' '.join(partes)


def _comandos_cog(bot: commands.Bot, nombres: list[str]) -> list[commands.Command]:
    encontrados = []
    for nombre in nombres:
        cog = bot.get_cog(nombre)
        if cog is None:
            continue
        for cmd in cog.get_commands():
            if not cmd.hidden:
                encontrados.append(cmd)
    return encontrados


def _embed_categoria(bot: commands.Bot, titulo: str, nombres: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title=f"📚 Ayuda — {titulo}",
        description="Usá `!help <comando>` para ver el detalle de uno.",
        color=discord.Color.blurple(),
    )
    for cmd in _comandos_cog(bot, nombres):
        doc = cmd.short_doc or 'Sin descripción.'
        if isinstance(cmd, commands.Group):
            subs = ', '.join(f"`{c.name}`" for c in cmd.commands if not c.hidden)
            valor = f"{doc}\nSubcomandos: {subs}" if subs else doc
        else:
            valor = doc
        embed.add_field(name=f"`{_firma(cmd)}`", value=valor[:1024], inline=False)
    if not embed.fields:
        embed.description = "No hay comandos en esta categoría."
    return embed


class HelpView(ui.View):
    def __init__(self, bot: commands.Bot, autor: discord.abc.User):
        super().__init__(timeout=180)
        self.bot = bot
        self.autor = autor

        opciones = [discord.SelectOption(label=nombre, value=nombre) for nombre in CATEGORIAS]
        select = ui.Select(placeholder="Elegí una categoría...", options=opciones)
        select.callback = self._cambiar
        self.add_item(select)
        self.select = select

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor.id:
            await interaction.response.send_message(
                "❌ Solo quien pidió la ayuda puede usar este menú.", ephemeral=True
            )
            return False
        return True

    async def _cambiar(self, interaction: discord.Interaction):
        nombre = interaction.data['values'][0]
        await interaction.response.edit_message(
            embed=_embed_categoria(self.bot, nombre, CATEGORIAS[nombre]), view=self
        )


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inicio = time.time()

    @commands.command(name='help', aliases=['ayuda', 'comandos'])
    async def help(self, ctx: commands.Context, *, consulta: str | None = None):
        """Muestra la ayuda o el detalle de un comando."""
        if consulta:
            cmd = self.bot.get_command(consulta.lstrip('!'))
            if cmd is None:
                return await ctx.send(f"❌ No encontré el comando **{consulta}**.")
            embed = discord.Embed(
                title=f"`{_firma(cmd)}`",
                description=cmd.help or cmd.short_doc or 'Sin descripción.',
                color=discord.Color.blurple(),
            )
            if cmd.aliases:
                embed.add_field(
                    name='Alias',
                    value=', '.join(f"`!{a}`" for a in cmd.aliases),
                    inline=False,
                )
            if isinstance(cmd, commands.Group):
                lineas = [
                    f"`!{cmd.name} {c.name}` — {c.short_doc or 'Sin descripción.'}"
                    for c in cmd.commands
                    if not c.hidden
                ]
                embed.add_field(name='Subcomandos', value='\n'.join(lineas)[:1024] or '—', inline=False)
            return await ctx.send(embed=embed)

        view = HelpView(self.bot, ctx.author)
        await ctx.send(
            embed=_embed_categoria(self.bot, '🎵 Música', CATEGORIAS['🎵 Música']),
            view=view,
        )

    @commands.command(name='ping')
    async def ping(self, ctx: commands.Context):
        """Muestra la latencia del bot."""
        ms = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! Latencia: **{ms} ms**")

    @commands.command(name='uptime', aliases=['encendido'])
    async def uptime(self, ctx: commands.Context):
        """Muestra cuánto lleva encendido el bot."""
        await ctx.send(f"⏱️ En línea desde hace **{_fmt(int(time.time() - self.inicio))}**")

    @commands.command(name='stats', aliases=['info'])
    async def stats(self, ctx: commands.Context):
        """Muestra estadísticas del bot."""
        embed = discord.Embed(title="📊 Estadísticas", color=discord.Color.blurple())
        embed.add_field(name='Servidores', value=str(len(self.bot.guilds)))
        embed.add_field(name='Usuarios', value=str(sum(g.member_count or 0 for g in self.bot.guilds)))
        embed.add_field(name='Latencia', value=f"{round(self.bot.latency * 1000)} ms")
        embed.add_field(name='Uptime', value=_fmt(int(time.time() - self.inicio)))
        await ctx.send(embed=embed)


def _fmt(seg: int) -> str:
    dias, resto = divmod(seg, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segundos = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f"{dias}d")
    if horas or dias:
        partes.append(f"{horas}h")
    partes.append(f"{minutos}m")
    partes.append(f"{segundos}s")
    return ' '.join(partes)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
