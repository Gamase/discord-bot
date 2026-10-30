# Discord Bot

Multifunctional Discord bot with YouTube music playback, playlists, live playback panel, TTS, reminders, and AI chat.

## Features

- **Music** — YouTube playback with search menu, queue management, loop modes, autoplay, seek, live panel and volume control.
- **Playlists & history** — Save/load playlists and keep the last 50 played tracks per server (SQLite).
- **Lyrics** — Fetch lyrics for the current song or any `Artist - Song`.
- **DJ permissions** — Restrict playback controls to admins, a DJ role or members in the bot's voice channel.
- **Voice (TTS)** — Read text aloud using Edge TTS (es-MX voice) with eSpeak fallback.
- **Reminders** — Automatic monthly payment reminder plus flexible per-user reminders (`!recordar 10m ...`).
- **AI** — Chat with Groq (default `openai/gpt-oss-120b`) with per-user conversation history.
- **Stability** — Voice auto-reconnect, heartbeat + watchdog, startup/shutdown alerts and yt-dlp auto-update.

## Commands

### Music
| Command | Aliases | Description |
|---------|---------|-------------|
| `!join` | `!conectar` | Connect the bot to your voice channel |
| `!play <search/URL>` | `!p`, `!reproducir` | Search (5 results menu) or play a URL |
| `!pause` | `!pausar` | Pause playback |
| `!resume` | `!reanudar` | Resume playback |
| `!skip` | `!s`, `!saltar` | Skip to the next song |
| `!seek <time>` | `!adelantar` | Seek to `90`, `1:30` or `1:02:03` |
| `!stop` | `!detener` | Stop, clear the queue and disconnect |
| `!queue` | `!q`, `!cola` | Show the playback queue |
| `!np` | `!nowplaying`, `!sonando` | Show the current song with progress |
| `!loop [off\|one\|all]` | `!bucle`, `!repetir` | Cycle or set the loop mode |
| `!autoplay [on\|off]` | `!radio`, `!automatico` | Toggle related-song autoplay |
| `!volumen <0-100>` | `!vol` | Adjust the volume |
| `!remove <n>` | `!quitar`, `!rm` | Remove a track from the queue |
| `!move <from> <to>` | `!mover`, `!mv` | Move a track in the queue |
| `!clear` | `!limpiar`, `!vaciar` | Clear the queue (keeps current song) |
| `!shuffle` | `!mezclar`, `!aleatorio` | Shuffle the queue |
| `!lyrics [artist - song]` | `!letra` | Show lyrics (current song if omitted) |

The live panel updates every 5 seconds with a progress bar and buttons for pause/resume, skip, loop and stop.

### Playlists
| Command | Aliases | Description |
|---------|---------|-------------|
| `!playlist save <name>` | `!pl guardar` | Save current song + queue |
| `!playlist load <name>` | `!pl cargar` | Load and play a playlist |
| `!playlist list` | `!pl lista` | List saved playlists |
| `!playlist show <name>` | `!pl ver` | Show playlist tracks |
| `!playlist add <name> [song]` | `!pl agregar` | Append current queue or one search result |
| `!playlist remove <name> <n>` | `!pl quitar` | Remove a track from a playlist |
| `!playlist delete <name>` | `!pl borrar` | Delete a playlist |

### History
| Command | Aliases | Description |
|---------|---------|-------------|
| `!historial` | `!recientes`, `!history` | Show the last played tracks |
| `!last` | `!ultima`, `!última` | Replay the last track |

### Voice (TTS)
| Command | Description |
|---------|-------------|
| `!h <text>` | Read text aloud in the voice channel |

### Reminders
| Command | Aliases | Description |
|---------|---------|-------------|
| `!recordar <time> <text>` | `!recuerdame`, `!recuérdame` | Create a reminder (e.g. `10m`, `2h`, `1d`) |
| `!recordatorios` | `!misrecordatorios` | List your pending reminders |
| `!olvidar <id>` | `!borrarrecordatorio` | Delete a reminder |
| `!forzar_recordatorio` | — | Send the monthly payment reminder now |
| `!estado_recordatorio` | — | Show the automatic reminder status |
| `!prueba` | — | Verify the bot is working |

### AI
| Command | Description |
|---------|-------------|
| `!ia <question>` | Ask the AI (keeps history per user) |

### General
| Command | Aliases | Description |
|---------|---------|-------------|
| `!help [command]` | `!ayuda`, `!comandos` | Help menu by category or command detail |
| `!ping` | — | Show latency |
| `!uptime` | `!encendido` | Show bot uptime |
| `!stats` | `!info` | Servers, users, latency and uptime |

## DJ permissions

Playback controls (`pause`, `resume`, `skip`, `stop`, `loop`, `volumen`, `remove`, `move`, `clear`, `shuffle`, `seek`, `autoplay` and panel buttons) are allowed for:

- Members with **Manage Server** or the server owner.
- Members with the role set in `DJ_ROLE_ID`.
- Members connected to the same voice channel as the bot.

If `DJ_ROLE_ID` is `0` (default), only admins/owner and members in the voice channel can control playback.

## Requirements

- Python 3.11+
- FFmpeg installed and available in `PATH`
- Discord bot token with the `message_content` intent enabled
- Groq API key (for the AI module)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd discord-bot
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_discord_token
CANAL_ID=channel_id_for_reminders
AVISO_CANAL_ID=channel_id_for_startup_alerts
DJ_ROLE_ID=0
PRECIO=60
DIA_RECORDATORIO=6
AMIGOS_IDS=id1,id2,id3
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
TTS_VOICE=es-MX-DaliaNeural
WATCHDOG_TIMEOUT=120
```

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Bot token (from the [Discord Developer Portal](https://discord.com/developers/applications)) |
| `CANAL_ID` | Channel for automatic reminders |
| `AVISO_CANAL_ID` | Channel for startup/crash alerts (defaults to `CANAL_ID`) |
| `DJ_ROLE_ID` | Role allowed to control playback (`0` disables it) |
| `PRECIO` | Price per person for YouTube Premium |
| `DIA_RECORDATORIO` | Day of the month for the reminder (1–31) |
| `AMIGOS_IDS` | Comma-separated user IDs to mention |
| `GROQ_API_KEY` | Groq API key ([console.groq.com](https://console.groq.com)) |
| `GROQ_MODEL` | Groq model (default `openai/gpt-oss-120b`) |
| `TTS_VOICE` | Edge TTS voice (default `es-MX-DaliaNeural`) |
| `WATCHDOG_TIMEOUT` | Seconds without heartbeat before restart (default `120`) |

### 4. Install FFmpeg

**Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add it to `PATH`.

**Linux:**
```bash
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Termux:**
```bash
pkg install ffmpeg
```

### 5. Run the bot

```bash
python main.py
```

Or with the watchdog (restarts the bot if the heartbeat goes stale):

```bash
./run.sh
```

## Operations

- `main.py` writes `heartbeat` every 30 seconds.
- `run.sh` checks the heartbeat every 15 seconds and restarts the bot after `WATCHDOG_TIMEOUT`; it also sends a Discord alert on crash/hang (throttled to 5 minutes).
- Logs are written to `bot.log` with rotation.
- `db.py` stores playlists, history and reminders in `bot.db` (SQLite).
- `~/bin/actualizar-ytdlp` (cron) updates yt-dlp weekly and restarts the bot if the version changed.
- `~/.termux/boot/10-discord-bot.sh` starts the bot on boot with a wake-lock.

## Project Structure

```
discord-bot/
├── main.py              # Entry point, cog loader, heartbeat and alerts
├── config.py            # Environment variable reader
├── db.py                # SQLite helpers (playlists, history, reminders)
├── run.sh               # Watchdog wrapper
├── requirements.txt     # Main dependencies
├── .env                 # Environment variables (not tracked by git)
└── cogs/
    ├── general.py       # Help, ping, uptime and stats
    ├── musica.py        # YouTube playback, queue, panel, playlists and lyrics
    ├── voz.py           # TTS with Edge TTS / eSpeak
    ├── recordatorio.py  # Monthly and flexible reminders
    └── ia.py            # AI chat with Groq
```

## Dependencies

```
discord.py>=2.3.0
yt-dlp>=2024.1.0
pyttsx3>=2.90
python-dotenv>=1.0.0
PyNaCl>=1.5.0
groq>=0.9.0
davey>=0.1.7
edge-tts>=7.3.1
aiohttp>=3.9.0
```
