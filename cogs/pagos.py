import asyncio
import calendar
import re
import traceback
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

import db
from config import Config

TZ = ZoneInfo('America/Tijuana')
HORA_RECORDATORIO = dtime(hour=9, minute=0, tzinfo=TZ)
DIAS_SEGUIMIENTO = 3
MESES = (
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)
RE_MES = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')
PRIORIDAD = {'confirmed': 3, 'pending': 2, 'rejected': 1}
ICONOS = {'confirmed': '✅', 'pending': '⏳', 'rejected': '✖️'}


def ahora() -> datetime:
    return datetime.now(TZ)


def mes_actual() -> str:
    return ahora().strftime('%Y-%m')


def nombre_mes(mes: str) -> str:
    anio, num = mes.split('-')
    return f"{MESES[int(num) - 1].capitalize()} {anio}"


def mes_siguiente(mes: str) -> str:
    anio, num = map(int, mes.split('-'))
    return f"{anio + num // 12:04d}-{num % 12 + 1:02d}"


def dia_efectivo(dia: int, fecha: datetime) -> int:
    """El día de recordatorio, ajustado a meses más cortos (ej. 31 → 30 en noviembre)."""
    return min(dia, calendar.monthrange(fecha.year, fecha.month)[1])


def meses_recientes(n: int) -> list[str]:
    hoy = ahora()
    anio, num = hoy.year, hoy.month
    salida = []
    for _ in range(n):
        salida.append(f"{anio:04d}-{num:02d}")
        num -= 1
        if num == 0:
            anio, num = anio - 1, 12
    return salida


def _mejor_estado(filas) -> dict:
    """Agrupa filas de pagos por clave y se queda con el estado más relevante."""
    mejores = {}
    for clave, fila in filas:
        actual = mejores.get(clave)
        if actual is None or PRIORIDAD[fila['status']] > PRIORIDAD[actual['status']]:
            mejores[clave] = fila
    return mejores


def _menciones(ids: list[int]) -> str:
    return '\n'.join(f"<@{uid}>" for uid in ids)[:1024] or '—'


# ── Botones persistentes ──────────────────────────────────────────────────────
# DynamicItem reconstruye el botón a partir de su custom_id, así que siguen
# funcionando en mensajes enviados antes de un reinicio.

class YaPague(ui.DynamicItem[ui.Button], template=r'pagos:pague:(?P<mes>\d{4}-\d{2})'):
    def __init__(self, mes: str):
        super().__init__(
            ui.Button(
                label='Ya pagué',
                emoji='💸',
                style=discord.ButtonStyle.success,
                custom_id=f'pagos:pague:{mes}',
            )
        )
        self.mes = mes

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Button, match: re.Match):
        return cls(match['mes'])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('Pagos')
        if cog is None:
            return await interaction.response.send_message(
                "❌ El sistema de pagos no está disponible.", ephemeral=True
            )
        await cog.solicitar_pago(interaction, self.mes)


class ResolverPago(ui.DynamicItem[ui.Button], template=r'pagos:(?P<accion>ok|no):(?P<pid>\d+)'):
    def __init__(self, accion: str, pid: int):
        confirmar = accion == 'ok'
        super().__init__(
            ui.Button(
                label='Confirmar' if confirmar else 'Rechazar',
                emoji='✅' if confirmar else '✖️',
                style=discord.ButtonStyle.success if confirmar else discord.ButtonStyle.danger,
                custom_id=f'pagos:{accion}:{pid}',
            )
        )
        self.accion = accion
        self.pid = pid

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Button, match: re.Match):
        return cls(match['accion'], int(match['pid']))

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('Pagos')
        if cog is None:
            return await interaction.response.send_message(
                "❌ El sistema de pagos no está disponible.", ephemeral=True
            )
        await cog.resolver_pago(interaction, self.pid, self.accion == 'ok')


async def _es_admin(interaction: discord.Interaction) -> bool:
    cog = interaction.client.get_cog('Pagos')
    return cog is not None and interaction.user.id == await cog.admin_id()


solo_admin = app_commands.check(_es_admin)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Pagos(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()
        self._admin_cache: int | None = None
        self._arranque: asyncio.Task | None = None

    async def cog_load(self):
        self.bot.add_dynamic_items(YaPague, ResolverPago)
        db.settings_seed({
            'precio': str(Config.PRECIO),
            'dia_recordatorio': str(Config.DIA_RECORDATORIO),
        })
        # Primer mes que cobra el bot. Si el día de este mes ya pasó, se empieza
        # el siguiente para no mandar de golpe un recordatorio atrasado.
        hoy = ahora()
        inicio = mes_actual()
        if hoy.day > dia_efectivo(self._dia(), hoy):
            inicio = mes_siguiente(inicio)
        db.settings_seed({'mes_inicio': inicio})
        if db.members_count() == 0:
            sembrados = [uid for uid in Config.AMIGOS_IDS if uid != Config.ADMIN_ID]
            for uid in sembrados:
                db.member_add(uid)
            if sembrados:
                print(f'👥 Pagos: {len(sembrados)} miembro(s) sembrados desde AMIGOS_IDS')
        self.recordatorio.start()
        self._arranque = asyncio.create_task(self._revisar_al_arrancar())

    async def cog_unload(self):
        self.recordatorio.cancel()
        if self._arranque:
            self._arranque.cancel()
        self.bot.remove_dynamic_items(YaPague, ResolverPago)

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def admin_id(self) -> int:
        if Config.ADMIN_ID:
            return Config.ADMIN_ID
        if self._admin_cache is None:
            app = await self.bot.application_info()
            self._admin_cache = app.team.owner_id if app.team else app.owner.id
        return self._admin_cache

    def _precio(self) -> int:
        return int(db.setting_get('precio') or Config.PRECIO)

    def _dia(self) -> int:
        return int(db.setting_get('dia_recordatorio') or Config.DIA_RECORDATORIO)

    async def _canal(self, canal_id: int):
        if not canal_id:
            return None
        canal = self.bot.get_channel(canal_id)
        if canal is None:
            try:
                canal = await self.bot.fetch_channel(canal_id)
            except discord.HTTPException:
                return None
        return canal

    async def _miembros(self) -> list[int]:
        admin = await self.admin_id()
        return [uid for uid in db.member_ids() if uid != admin]

    @staticmethod
    def _estados(mes: str) -> dict[int, str]:
        filas = db.payments_month(mes)
        return {uid: f['status'] for uid, f in _mejor_estado((f['discord_id'], f) for f in filas).items()}

    @staticmethod
    def _vista_pago(mes: str) -> ui.View:
        view = ui.View(timeout=None)
        view.add_item(YaPague(mes))
        return view

    async def _enviar_dm_o_canal(self, user_id: int, canal_id: int, **kwargs) -> bool:
        try:
            usuario = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            await usuario.send(**kwargs)
            return True
        except discord.HTTPException as e:
            print(f'⚠️ Pagos: DM a {user_id} falló ({e}); usando canal de respaldo')

        canal = await self._canal(canal_id)
        if canal is None:
            return False
        contenido = kwargs.pop('content', None)
        try:
            await canal.send(content=f"<@{user_id}> {contenido or ''}".strip(), **kwargs)
            return True
        except discord.HTTPException as e:
            print(f'❌ Pagos: tampoco se pudo enviar al canal {canal_id}: {e}')
            return False

    # ── Recordatorios automáticos ─────────────────────────────────────────────

    @tasks.loop(time=HORA_RECORDATORIO)
    async def recordatorio(self):
        await self._revisar()

    @recordatorio.before_loop
    async def _antes_recordatorio(self):
        await self.bot.wait_until_ready()

    async def _revisar_al_arrancar(self):
        # tasks.loop(time=...) no corre al iniciar; si el bot arranca después de la
        # hora del recordatorio, revisamos una vez para no perder el día.
        await self.bot.wait_until_ready()
        if ahora().hour >= HORA_RECORDATORIO.hour:
            await self._revisar()

    async def _revisar(self):
        async with self._lock:
            try:
                hoy = ahora()
                mes = hoy.strftime('%Y-%m')
                if mes < (db.setting_get('mes_inicio') or mes):
                    return
                if hoy.day < dia_efectivo(self._dia(), hoy):
                    return
                if not db.reminder_sent_monthly(mes):
                    await self._enviar_recordatorio(mes, 'monthly')
                    return
                ultimo = db.reminder_last(mes)
                dias = (hoy.date() - datetime.fromtimestamp(ultimo, TZ).date()).days
                if dias >= DIAS_SEGUIMIENTO:
                    await self._enviar_recordatorio(mes, 'followup')
            except Exception as e:
                print(f'❌ Error en recordatorio de pagos: {e}')
                traceback.print_exc()

    async def _enviar_recordatorio(self, mes: str, tipo: str) -> int | None:
        """Devuelve a cuántos se mencionó (0 si nadie debe), o None si no se envió."""
        miembros = await self._miembros()
        estados = self._estados(mes)
        deudores = [uid for uid in miembros if estados.get(uid) in (None, 'rejected')]
        en_revision = [uid for uid in miembros if estados.get(uid) == 'pending']

        if tipo == 'followup' and not deudores:
            return 0

        log_id = db.reminder_claim(mes, tipo)
        if log_id is None:
            return None
        if not deudores:
            print(f'🎉 Pagos {mes}: nadie pendiente, no se envía recordatorio mensual')
            return 0

        canal = await self._canal(Config.CANAL_ID)
        try:
            if canal is None:
                raise RuntimeError(f'canal {Config.CANAL_ID} no encontrado')
            await canal.send(
                content=' '.join(f"<@{uid}>" for uid in deudores),
                embed=self._embed_recordatorio(mes, tipo, deudores, en_revision),
                view=self._vista_pago(mes),
            )
            print(f'📢 Recordatorio de pagos enviado ({tipo}, {mes}, {len(deudores)} pendiente/s)')
            return len(deudores)
        except Exception as e:
            db.reminder_unclaim(log_id)
            print(f'❌ No se pudo enviar el recordatorio de pagos ({tipo}, {mes}): {e}')
            return None

    def _embed_recordatorio(self, mes: str, tipo: str, deudores: list[int],
                            en_revision: list[int]) -> discord.Embed:
        if tipo == 'monthly':
            embed = discord.Embed(
                title=f"🎬 Pago de YouTube Premium — {nombre_mes(mes)}",
                description="¡Paguen el YOUTUBE PREMIUM PERRAAAAS!",
                color=discord.Color.red(),
            )
        else:
            embed = discord.Embed(
                title=f"⏰ Recordatorio de pago — {nombre_mes(mes)}",
                description="Todavía no tenemos registrado su pago de este mes.",
                color=discord.Color.orange(),
            )
        embed.add_field(name="💰 Precio por persona", value=f"${self._precio()}")
        embed.add_field(name="❌ Pendientes", value=str(len(deudores)))
        if en_revision:
            embed.add_field(name="⏳ En revisión", value=str(len(en_revision)))
        if Config.CLABE:
            embed.add_field(name="💳 CLABE interbancaria", value=f"`{Config.CLABE}`", inline=False)
        embed.set_footer(text="Cuando pagues presiona «Ya pagué» y el admin lo confirmará.")
        return embed

    # ── Flujo «Ya pagué» → admin ──────────────────────────────────────────────

    async def solicitar_pago(self, interaction: discord.Interaction, mes: str):
        uid = interaction.user.id
        if uid == await self.admin_id():
            return await interaction.response.send_message(
                "😉 Eres el admin, no necesitas registrar pago.", ephemeral=True
            )
        if not db.member_exists(uid):
            return await interaction.response.send_message(
                "❌ No estás en la lista de pagos. Pídele al admin que te agregue.", ephemeral=True
            )

        activo = db.payment_get_active(uid, mes)
        pid = None if activo else db.payment_request(uid, mes, self._precio())
        if pid is None:
            activo = activo or db.payment_get_active(uid, mes)
            if activo and activo['status'] == 'confirmed':
                texto = f"✅ Tu pago de **{nombre_mes(mes)}** ya está confirmado."
            else:
                texto = f"⏳ Ya tienes una solicitud de **{nombre_mes(mes)}** esperando al admin."
            return await interaction.response.send_message(texto, ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        entregado = await self._avisar_admin(pid, interaction.user)
        if entregado:
            texto = f"📨 Listo, le avisé al admin de tu pago de **{nombre_mes(mes)}**. Te aviso cuando lo confirme."
        else:
            texto = (
                f"⚠️ Registré tu pago de **{nombre_mes(mes)}**, pero no pude avisarle al admin. "
                "Avísale directamente."
            )
        await interaction.followup.send(texto, ephemeral=True)

    async def _avisar_admin(self, pid: int, solicitante: discord.abc.User) -> bool:
        pago = db.payment_get(pid)
        embed = discord.Embed(
            title="💸 Solicitud de pago",
            description=(
                f"{solicitante.mention} (`{solicitante.display_name}`) dice que ya pagó "
                f"**{nombre_mes(pago['month'])}**."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Monto", value=f"${pago['amount']}")
        embed.set_footer(text=f"Solicitud #{pid}")

        view = ui.View(timeout=None)
        view.add_item(ResolverPago('ok', pid))
        view.add_item(ResolverPago('no', pid))

        return await self._enviar_dm_o_canal(
            await self.admin_id(), Config.PAGOS_CANAL_ID, embed=embed, view=view
        )

    async def resolver_pago(self, interaction: discord.Interaction, pid: int, confirmar: bool):
        if interaction.user.id != await self.admin_id():
            return await interaction.response.send_message(
                "❌ Solo el admin puede confirmar o rechazar pagos.", ephemeral=True
            )

        pago = db.payment_resolve(pid, 'confirmed' if confirmar else 'rejected', interaction.user.id)
        if pago is None:
            actual = db.payment_get(pid)
            estado = {'confirmed': 'confirmada', 'rejected': 'rechazada'}.get(
                actual['status'] if actual else '', 'inexistente'
            )
            await interaction.response.send_message(
                f"ℹ️ La solicitud #{pid} ya estaba {estado}.", ephemeral=True
            )
            try:
                await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass
            return

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = discord.Color.green() if confirmar else discord.Color.red()
        embed.add_field(
            name="Resultado",
            value=f"{'✅ Confirmado' if confirmar else '✖️ Rechazado'} <t:{pago['resolved_at']}:R>",
            inline=False,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        await self._notificar_usuario(pago, confirmar)

    async def _notificar_usuario(self, pago, confirmado: bool):
        mes = nombre_mes(pago['month'])
        if confirmado:
            texto = f"✅ Tu pago de **{mes}** (${pago['amount']}) fue confirmado. ¡Gracias!"
        else:
            texto = (
                f"✖️ El admin rechazó tu pago de **{mes}**. Si ya pagaste, vuelve a "
                "presionar «Ya pagué» o habla con el admin."
            )
        await self._enviar_dm_o_canal(pago['discord_id'], Config.CANAL_ID, content=texto)

    # ── Slash commands ────────────────────────────────────────────────────────

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            texto = "❌ Solo el admin puede usar este comando."
        else:
            print(f'❌ Error en /{interaction.command.name if interaction.command else "?"}: {error}')
            traceback.print_exception(type(error), error, error.__traceback__)
            texto = "❌ Ocurrió un error ejecutando el comando."
        if interaction.response.is_done():
            await interaction.followup.send(texto, ephemeral=True)
        else:
            await interaction.response.send_message(texto, ephemeral=True)

    @staticmethod
    async def _validar_mes(interaction: discord.Interaction, mes: str | None) -> str | None:
        mes = (mes or mes_actual()).strip()
        if not RE_MES.match(mes):
            await interaction.response.send_message(
                "❌ Mes inválido. Usa el formato `AAAA-MM`, por ejemplo `2026-10`.", ephemeral=True
            )
            return None
        return mes

    @app_commands.command(name='estado', description='Muestra quién pagó y quién falta este mes')
    @app_commands.describe(mes='Mes en formato AAAA-MM (por defecto, el actual)')
    @app_commands.guild_only()
    async def estado(self, interaction: discord.Interaction, mes: str | None = None):
        mes = await self._validar_mes(interaction, mes)
        if mes is None:
            return

        miembros = await self._miembros()
        filas = db.payments_month(mes)
        estados = self._estados(mes)
        pagaron = [u for u in miembros if estados.get(u) == 'confirmed']
        revision = [u for u in miembros if estados.get(u) == 'pending']
        faltan = [u for u in miembros if estados.get(u) in (None, 'rejected')]
        recaudado = sum(f['amount'] for f in filas if f['status'] == 'confirmed')

        embed = discord.Embed(
            title=f"📋 Pagos — {nombre_mes(mes)}",
            description=f"**{len(pagaron)}/{len(miembros)}** pagado(s) · Recaudado: **${recaudado}**",
            color=discord.Color.green() if miembros and not faltan and not revision else discord.Color.blurple(),
        )
        embed.add_field(name=f"✅ Pagaron ({len(pagaron)})", value=_menciones(pagaron))
        embed.add_field(name=f"⏳ En revisión ({len(revision)})", value=_menciones(revision))
        embed.add_field(name=f"❌ Faltan ({len(faltan)})", value=_menciones(faltan))
        embed.set_footer(text=f"Precio actual: ${self._precio()}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='historial', description='Historial de pagos de los últimos 6 meses')
    @app_commands.describe(usuario='Ver solo el historial de esta persona')
    @app_commands.guild_only()
    async def historial(self, interaction: discord.Interaction, usuario: discord.User | None = None):
        meses = meses_recientes(6)

        if usuario:
            por_mes = _mejor_estado((f['month'], f) for f in db.payments_user(usuario.id))
            lineas = []
            for mes in meses:
                fila = por_mes.get(mes)
                if fila is None:
                    lineas.append(f"❌ **{nombre_mes(mes)}** — sin pago")
                else:
                    lineas.append(f"{ICONOS[fila['status']]} **{nombre_mes(mes)}** — ${fila['amount']}")
            embed = discord.Embed(
                title=f"🧾 Historial de {usuario.display_name}",
                description='\n'.join(lineas),
                color=discord.Color.blurple(),
            )
        else:
            lineas = []
            for mes in meses:
                filas = db.payments_month(mes)
                confirmados = [f for f in filas if f['status'] == 'confirmed']
                pendientes = sum(1 for f in filas if f['status'] == 'pending')
                linea = (
                    f"**{nombre_mes(mes)}** — ✅ {len(confirmados)} pago(s) · "
                    f"${sum(f['amount'] for f in confirmados)}"
                )
                if pendientes:
                    linea += f" · ⏳ {pendientes} en revisión"
                lineas.append(linea)
            embed = discord.Embed(
                title="🧾 Historial de pagos",
                description='\n'.join(lineas),
                color=discord.Color.blurple(),
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='precio', description='(Admin) Cambia el precio mensual por persona')
    @app_commands.describe(monto='Nuevo precio por persona')
    @app_commands.guild_only()
    @solo_admin
    async def precio(self, interaction: discord.Interaction, monto: app_commands.Range[int, 1, 100000]):
        anterior = self._precio()
        db.setting_set('precio', str(monto))
        await interaction.response.send_message(
            f"💰 Precio actualizado: **${anterior}** → **${monto}**. Aplica a las solicitudes nuevas."
        )

    @app_commands.command(name='agregar', description='(Admin) Agrega a alguien a la lista de pagos')
    @app_commands.describe(usuario='Persona a agregar')
    @app_commands.guild_only()
    @solo_admin
    async def agregar(self, interaction: discord.Interaction, usuario: discord.Member):
        if usuario.bot:
            return await interaction.response.send_message("❌ No puedes agregar bots.", ephemeral=True)
        if usuario.id == await self.admin_id():
            return await interaction.response.send_message(
                "❌ El admin no cuenta como deudor.", ephemeral=True
            )
        if not db.member_add(usuario.id):
            return await interaction.response.send_message(
                f"ℹ️ {usuario.mention} ya estaba en la lista.", ephemeral=True
            )
        await interaction.response.send_message(f"👥 {usuario.mention} agregado a la lista de pagos.")

    @app_commands.command(name='quitar', description='(Admin) Quita a alguien de la lista de pagos')
    @app_commands.describe(usuario='Persona a quitar')
    @app_commands.guild_only()
    @solo_admin
    async def quitar(self, interaction: discord.Interaction, usuario: discord.User):
        if not db.member_remove(usuario.id):
            return await interaction.response.send_message(
                f"ℹ️ {usuario.mention} no estaba en la lista.", ephemeral=True
            )
        await interaction.response.send_message(
            f"🗑️ {usuario.mention} quitado de la lista de pagos (su historial se conserva)."
        )

    @app_commands.command(name='marcar_pagado', description='(Admin) Marca a alguien como pagado')
    @app_commands.describe(usuario='Persona que pagó', mes='Mes en formato AAAA-MM (por defecto, el actual)')
    @app_commands.guild_only()
    @solo_admin
    async def marcar_pagado(self, interaction: discord.Interaction, usuario: discord.User,
                            mes: str | None = None):
        mes = await self._validar_mes(interaction, mes)
        if mes is None:
            return
        if not db.member_exists(usuario.id):
            return await interaction.response.send_message(
                f"❌ {usuario.mention} no está en la lista. Usa `/agregar` primero.", ephemeral=True
            )
        pago = db.payment_mark_paid(usuario.id, mes, self._precio(), interaction.user.id)
        if pago is None:
            return await interaction.response.send_message(
                f"ℹ️ {usuario.mention} ya tenía confirmado **{nombre_mes(mes)}**.", ephemeral=True
            )
        await interaction.response.send_message(
            f"✅ {usuario.mention} marcado como pagado en **{nombre_mes(mes)}** (${pago['amount']})."
        )
        await self._notificar_usuario(pago, True)

    @app_commands.command(name='recordatorio', description='(Admin) Envía ya el recordatorio de pago del mes actual')
    @app_commands.guild_only()
    @solo_admin
    async def recordatorio_ahora(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        mes = mes_actual()
        async with self._lock:
            # Si el mensual de este mes ya salió, el forzado cuenta como seguimiento
            # (y reinicia la cuenta de 3 días).
            tipo = 'followup' if db.reminder_sent_monthly(mes) else 'monthly'
            enviados = await self._enviar_recordatorio(mes, tipo)
        if enviados is None:
            texto = "❌ No se pudo enviar el recordatorio. Revisa la consola del bot."
        elif enviados == 0:
            texto = f"🎉 Nadie tiene pendiente **{nombre_mes(mes)}**, no se envió nada."
        else:
            texto = f"📢 Recordatorio de **{nombre_mes(mes)}** enviado a {enviados} persona(s)."
        await interaction.followup.send(texto, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Pagos(bot))
