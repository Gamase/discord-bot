# Discord Bot

Bot de Discord multifuncional con reproducción de música de YouTube, panel de control con botones, TTS, recordatorios e IA.

## Features

- **Music** — Reproducción de YouTube con menú de búsqueda, gestión de cola, modos de loop, autoplay por radio y panel en vivo con botones.
- **Playlists & history** — Guarda/carga playlists desde el panel de botones y mantiene las últimas 50 canciones reproducidas por servidor (SQLite).
- **DJ permissions** — Restringe los controles de reproducción a admins, un rol DJ o miembros en el canal de voz del bot.
- **Voice (TTS)** — Lee texto en voz alta usando Edge TTS (voz es-MX) con fallback a eSpeak.
- **Reminders** — Recordatorio mensual de pago automático y recordatorios flexibles por usuario (`!recordar 10m ...`).
- **AI** — Chat con Groq (modelo configurable) con historial de conversación por usuario y cooldown de 3 usos/60s.
- **Stability** — Reconexión automática de voz, heartbeat + watchdog, alertas de inicio/caída.

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
| `!forzar_recordatorio` | — | Envía el recordatorio mensual manualmente (solo dueño del bot) |
| `!estado_recordatorio` | — | Muestra el estado del recordatorio automático |
| `!prueba` | — | Verifica que el bot funciona |

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
| `PRECIO` | Precio por persona para YouTube Premium |
| `DIA_RECORDATORIO` | Día del mes para el recordatorio (1–31) |
| `AMIGOS_IDS` | IDs de usuario separados por coma para mencionar |
| `CLABE` | CLABE interbancaria para el recordatorio de pago |
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

**Windows** (doble clic):
- `start_bot.vbs` — Inicia el bot en segundo plano
- `restart_bot.vbs` — Detiene y reinicia el bot
- `stop_bot.vbs` — Detiene el bot

**Línea de comandos:**
```bash
python main.py
```

## Operations

- `main.py` escribe `heartbeat` cada 30 segundos.
- `db.py` almacena playlists, historial y recordatorios en `bot.db` (SQLite).

## Project Structure

```
discord-bot/
├── main.py              # Entry point, cog loader, heartbeat y alertas
├── config.py            # Lector de variables de entorno
├── db.py                # Helpers SQLite (playlists, historial, recordatorios)
├── requirements.txt     # Dependencias principales
├── start_bot.vbs        # Inicia el bot en segundo plano (Windows)
├── restart_bot.vbs      # Reinicia el bot (Windows)
├── stop_bot.vbs         # Detiene el bot (Windows)
├── .env                 # Variables de entorno (no trackeado por git)
└── cogs/
    ├── general.py       # Help, ping, uptime y stats
    ├── musica.py        # Reproducción YouTube, cola, panel con botones y playlists
    ├── voz.py           # TTS con Edge TTS / eSpeak
    ├── recordatorio.py  # Recordatorios mensuales y por usuario
    └── ia.py            # Chat IA con Groq
```

## Dependencies

```
discord.py>=2.3.0
yt-dlp>=2024.1.0
pyttsx3>=2.90
python-dotenv>=1.0.0
PyNaCl>=1.5.0
groq>=0.9.0
edge-tts>=7.3.1
aiohttp>=3.9.0
```
