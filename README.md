# Discord Bot

Bot de Discord multifuncional con reproducción de música de YouTube, panel de control con botones, TTS, recordatorios e IA.

## Features

- **Music** — Reproducción de YouTube con menú de búsqueda, gestión de cola, modos de loop, autoplay por radio y panel en vivo con botones.
- **Playlists & history** — Guarda/carga playlists desde el panel de botones y mantiene las últimas 50 canciones reproducidas por servidor (SQLite).
- **DJ permissions** — Restringe los controles de reproducción a admins, un rol DJ o miembros en el canal de voz del bot.
- **Voice (TTS)** — Lee texto en voz alta usando Edge TTS (voz es-MX) con fallback a eSpeak.
- **Pagos** — Control de pagos mensuales con SQLite: recordatorio mensual con botón «Ya pagué», confirmación del admin y seguimiento cada 3 días a quienes faltan.
- **Reminders** — Recordatorios flexibles por usuario (`!recordar 10m ...`).
- **AI** — Chat con Groq (modelo configurable) con historial de conversación por usuario y cooldown de 3 usos/60s.
- **Errores** — Manejo centralizado de errores de comandos, slash commands, eventos y tareas; DM al admin con traceback censurado y anti-spam por 10 minutos.
- **Servidor** — Estado del teléfono (batería, temperatura, uptime, almacenamiento, RAM) y alertas con histéresis cuando la batería está baja o el equipo se calienta.
- **Stability** — Reconexión automática de voz, heartbeat + watchdog, alertas de inicio/caída y loops que no mueren ante un error.

## Panel de reproducción

El panel se actualiza cada 5 segundos con barra de progreso y dos filas de botones:

| Fila 1 | Acción |
|--------|--------|
| ⏯️ | Pausa / Reanuda |
| ⏭️ | Salta a la siguiente canción |
| 🔁 | Cicla el modo loop: desactivado → repetir canción → repetir cola |
| 📻 | Activa / desactiva autoplay (canciones relacionadas) |
| ⏹️ | Detiene la música y desconecta el bot |

| Fila 2 | Acción |
|--------|--------|
| 📋 | Muestra la cola actual (efímero) |
| 🔀 | Mezcla la cola aleatoriamente |
| 🧹 | Limpia la cola (mantiene la canción actual) |
| 💾 | Abre modal para guardar la cola como playlist |
| 📂 | Abre el gestor de playlists (cargar / borrar) |

Cada botón muestra un mensaje efímero confirmando la acción realizada.

## Commands

### Music
| Comando | Alias | Descripción |
|---------|-------|-------------|
| `!join` | `!conectar` | Conecta el bot a tu canal de voz |
| `!play <búsqueda/URL>` | `!p`, `!reproducir` | Busca (menú de 5 resultados), reproduce una URL o carga una playlist de YouTube/YT Music (hasta 100 pistas) |
| `!play now <link>` | `!p now` | Reproduce la canción de inmediato, interrumpiendo la actual; la cola se mantiene |
| `!pause` | `!pausar` | Pausa la reproducción |
| `!resume` | `!reanudar` | Reanuda la reproducción |
| `!skip` | `!s`, `!saltar` | Salta a la siguiente canción |
| `!stop` | `!detener` | Detiene, limpia la cola y desconecta |
| `!queue` | `!q`, `!cola` | Muestra la cola de reproducción |
| `!np` | `!nowplaying`, `!sonando` | Muestra la canción actual con progreso |
| `!loop [off\|one\|all]` | `!bucle`, `!repetir` | Cambia el modo de loop |
| `!autoplay [on\|off]` | `!radio`, `!automatico` | Activa/desactiva el autoplay |
| `!remove <n>` | `!quitar`, `!rm` | Quita una pista de la cola |
| `!move <de> <a>` | `!mover`, `!mv` | Mueve una pista en la cola |
| `!clear` | `!limpiar`, `!vaciar` | Limpia la cola (mantiene la actual) |
| `!shuffle` | `!mezclar`, `!aleatorio` | Mezcla la cola aleatoriamente |

### History
| Comando | Alias | Descripción |
|---------|-------|-------------|
| `!historial` | `!recientes`, `!history` | Muestra las últimas canciones reproducidas |
| `!last` | `!ultima`, `!última` | Vuelve a reproducir la última canción |

### Voice (TTS)
| Comando | Descripción |
|---------|-------------|
| `!h <texto>` | Lee el texto en voz alta en el canal de voz |

### Reminders
| Comando | Alias | Descripción |
|---------|-------|-------------|
| `!recordar <tiempo> <texto>` | `!recuerdame` | Crea un recordatorio (ej. `10m`, `2h`, `1d`) |
| `!recordatorios` | `!misrecordatorios` | Lista tus recordatorios pendientes |
| `!olvidar <id>` | `!borrarrecordatorio` | Elimina un recordatorio |
| `!prueba` | — | Verifica que el bot funciona |

### Pagos (slash commands)
| Comando | Quién | Descripción |
|---------|-------|-------------|
| `/estado [mes]` | Todos | Quién pagó, quién está en revisión y quién falta (mes `AAAA-MM`, por defecto el actual) |
| `/historial [usuario]` | Todos | Resumen de los últimos 6 meses, general o de una persona |
| `/precio <monto>` | Admin | Cambia el precio por persona (aplica a solicitudes nuevas) |
| `/agregar <usuario>` | Admin | Agrega a alguien a la lista de pagos |
| `/quitar <usuario>` | Admin | Quita a alguien de la lista (su historial se conserva) |
| `/marcar_pagado <usuario> [mes]` | Admin | Marca un pago como confirmado sin pasar por la solicitud |
| `/recordatorio` | Admin | Envía ya el recordatorio del mes actual a quienes faltan |

**Cómo funciona:**
- El día configurado (`dia_recordatorio`, 9:00 hora de Tijuana) se envía el recordatorio mensual al canal `CANAL_ID`, mencionando solo a quienes no han pagado. Queda registrado en la DB, así que no se repite ese mes aunque el bot se reinicie. Si el bot estaba apagado ese día, lo envía en cuanto vuelve.
- La primera vez que arranca, el bot guarda `mes_inicio` en la DB: si el día de recordatorio de este mes ya pasó, empieza a cobrar el mes siguiente; si no, el actual. Los meses anteriores se ignoran.
- Cada 3 días se vuelve a mencionar solo a quienes siguen sin pagar.
- El botón **Ya pagué** crea una solicitud pendiente y le llega al admin por DM (o al canal `PAGOS_CANAL_ID` si el DM falla) con botones **Confirmar** / **Rechazar**. Solo cuenta como pagado al confirmar; un rechazo queda registrado y la persona puede volver a solicitar.
- Todos los botones siguen funcionando después de reiniciar el bot.
- El admin nunca cuenta como deudor. La lista de miembros se siembra desde `AMIGOS_IDS` solo la primera vez; después se administra con `/agregar` y `/quitar`.

### AI
| Comando | Descripción |
|---------|-------------|
| `!ia <pregunta>` | Pregunta a la IA (mantiene historial por usuario, cooldown 3/60s) |

### General
| Comando | Alias | Descripción |
|---------|-------|-------------|
| `!help [comando]` | `!ayuda`, `!comandos` | Menú de ayuda por categoría o detalle de un comando |
| `!ping` | — | Muestra la latencia |
| `!uptime` | `!encendido` | Muestra el tiempo de actividad |
| `!stats` | `!info` | Servidores, usuarios, latencia y uptime |

### Servidor (slash commands, solo admin)
| Comando | Descripción |
|---------|-------------|
| `/servidor` | Batería, carga, temperatura, uptime del teléfono y del bot, almacenamiento, RAM y latencia |
| `/umbrales` | Cambia los umbrales de alerta (`bateria_min`, `bateria_rearme`, `temp_max`, `temp_rearme`) |

`/servidor` está pensado para el Huawei P30 con Termux y `termux-api`. El uptime, la RAM y el almacenamiento se leen de `/proc` y del disco en cualquier sistema. Solo la batería depende de Termux:API: si falta el paquete `termux-api` o `termux-battery-status` falla, esos campos muestran `no disponible` y la causa se registra una sola vez en `bot.log`. En Termux hay que instalar tanto la app Termux:API como el paquete `termux-api`.

El loop de monitoreo revisa cada 5 minutos. Avisa una sola vez por transición:

- Batería menor a `20%` sin cargar; se rearma al llegar a `25%` o al empezar a cargar.
- Temperatura mayor a `45 °C`; se rearma al bajar de `42 °C`.
- También avisa cuando el valor vuelve a la normalidad después de una alerta.

Los umbrales se guardan en la tabla `settings` (`servidor_bateria_min`, `servidor_bateria_rearme`, `servidor_temp_max`, `servidor_temp_rearme`) y se pueden cambiar con `/umbrales`.

### Errores
El cog de errores maneja comandos de prefijo, slash commands, eventos y tareas. Los errores esperados (comando inexistente, cooldown, permisos, argumentos) solo se le muestran al usuario. Los inesperados se envían al admin por DM con usuario, canal, hora de Tijuana y traceback censurado; si es muy largo, va como archivo `.txt`. Si el DM falla, usa el canal de respaldo.

Los errores repetidos se agrupan con anti-spam: el primero avisa y las repeticiones se cuentan durante 10 minutos. Al cerrar la ventana se envía un resumen con el total, aunque no haya un error nuevo.

`/probar_error` (solo admin) lanza una excepción intencional para verificar el flujo completo de reporte.

## DJ permissions

Los controles de reproducción (`pause`, `resume`, `skip`, `stop`, `loop`, `remove`, `move`, `clear`, `shuffle`, `autoplay` y botones del panel) están disponibles para:

- Miembros con **Manage Server** o el dueño del servidor.
- Miembros con el rol configurado en `DJ_ROLE_ID`.
- Miembros conectados al mismo canal de voz que el bot.

Si `DJ_ROLE_ID` es `0` (por defecto), solo admins/dueño y miembros en el canal de voz pueden controlar la reproducción.

## Requirements

- Python 3.11+
- FFmpeg instalado y disponible en `PATH`
- Token de bot de Discord con el intent `message_content` habilitado
- Groq API key (para el módulo de IA)
- Opcional: Termux + `termux-api` para `/servidor` y las alertas del teléfono

## Installation

### 1. Clonar el repositorio

```bash
git clone <repository-url>
cd discord-bot
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```env
DISCORD_TOKEN=your_discord_token
CANAL_ID=channel_id_for_reminders
AVISO_CANAL_ID=channel_id_for_startup_alerts
DJ_ROLE_ID=0
PRECIO=60
DIA_RECORDATORIO=6
AMIGOS_IDS=id1,id2,id3
CLABE=tu_clabe
ADMIN_ID=tu_discord_id
GUILD_ID=id_del_servidor
PAGOS_CANAL_ID=canal_respaldo_para_solicitudes
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
TTS_VOICE=es-MX-DaliaNeural
WATCHDOG_TIMEOUT=120
```

| Variable | Descripción |
|----------|-------------|
| `DISCORD_TOKEN` | Token del bot ([Discord Developer Portal](https://discord.com/developers/applications)) |
| `CANAL_ID` | Canal para recordatorios automáticos |
| `AVISO_CANAL_ID` | Canal para alertas de inicio/caída (por defecto igual a `CANAL_ID`) |
| `DJ_ROLE_ID` | Rol que puede controlar la reproducción (`0` deshabilitado) |
| `PRECIO` | Precio inicial por persona (después se cambia con `/precio`) |
| `DIA_RECORDATORIO` | Día del mes para el recordatorio (1–31; valor inicial guardado en la DB) |
| `AMIGOS_IDS` | IDs que se usan para sembrar la lista de pagos la primera vez |
| `CLABE` | CLABE interbancaria para el recordatorio de pago |
| `ADMIN_ID` | Quien confirma pagos, usa los comandos de admin y recibe errores/alertas por DM (por defecto, el dueño de la app del bot) |
| `GUILD_ID` | Servidor donde se sincronizan los slash commands (por defecto, el servidor de `CANAL_ID`) |
| `PAGOS_CANAL_ID` | Canal de respaldo para solicitudes si el DM al admin falla (por defecto `AVISO_CANAL_ID`) |
| `GROQ_API_KEY` | API key de Groq ([console.groq.com](https://console.groq.com)) |
| `GROQ_MODEL` | Modelo de Groq (por defecto `openai/gpt-oss-120b`) |
| `TTS_VOICE` | Voz de Edge TTS (por defecto `es-MX-DaliaNeural`) |
| `WATCHDOG_TIMEOUT` | Segundos sin heartbeat antes de reiniciar (por defecto `120`) |

### 4. Instalar FFmpeg

**Windows:** Descarga desde [ffmpeg.org](https://ffmpeg.org/download.html) y agrégalo al `PATH`.

**Linux:**
```bash
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

### 5. Iniciar el bot

```bash
python main.py
```

## Operations

- `main.py` escribe `heartbeat` cada 30 segundos.
- `db.py` almacena playlists, historial, recordatorios, pagos y umbrales en `bot.db` (SQLite, no se sube a git).
- `run.sh` redirige la salida del bot a `bot.log`.
- Los errores y alertas también se registran en `bot.log`; los secretos se censuran antes de enviarlos o imprimirlos.

### Tests

```bash
python -m unittest discover -s tests -t . -v
```

Incluyen pruebas de censurado de secretos, anti-spam con ventana de 10 minutos y alertas del servidor con histéresis.

## Project Structure

```
discord-bot/
├── main.py              # Entry point, cog loader, heartbeat y alertas
├── config.py            # Lector de variables de entorno
├── db.py                # Helpers SQLite (playlists, historial, recordatorios, pagos)
├── requirements.txt     # Dependencias principales
├── .env                 # Variables de entorno (no trackeado por git)
├── tests/
│   ├── test_errores.py  # Censurado de secretos y anti-spam
│   └── test_servidor.py # Alertas de batería y temperatura con histéresis
└── cogs/
    ├── errores.py       # Errores de comandos, eventos, tareas y DM al admin
    ├── general.py       # Help, ping, uptime y stats
    ├── musica.py        # Reproducción YouTube, cola, panel con botones y playlists
    ├── voz.py           # TTS con Edge TTS / eSpeak
    ├── recordatorio.py  # Recordatorios por usuario
    ├── pagos.py         # Control de pagos mensuales, botones persistentes y slash commands
    ├── servidor.py      # Estado del teléfono y alertas con histéresis
    └── ia.py            # Chat IA con Groq
```

## Dependencies

```
discord.py>=2.4.0
yt-dlp>=2024.1.0
pyttsx3>=2.90
python-dotenv>=1.0.0
PyNaCl>=1.5.0
groq>=0.9.0
davey>=0.1.7
edge-tts>=7.3.1
aiohttp>=3.9.0
tzdata>=2024.1
```
