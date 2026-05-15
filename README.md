# Discord Bot

Multifunctional Discord bot with YouTube music playback, text-to-speech (TTS), automatic payment reminders, and AI chat.

## Features

- **Music** — Play audio from YouTube with a song queue and volume control.
- **Voice (TTS)** — Read text aloud in a voice channel using the Sabina voice (pyttsx3).
- **Reminder** — Send automatic monthly payment reminders for YouTube Premium.
- **AI** — Chat with Llama 3.3 70B via Groq API with per-user conversation history.

## Commands

### Music
| Command | Alias | Description |
|---------|-------|-------------|
| `!join` | `!conectar` | Connect the bot to your voice channel |
| `!play <search/URL>` | `!p`, `!reproducir` | Play music from YouTube |
| `!pause` | `!pausar` | Pause playback |
| `!resume` | `!reanudar` | Resume playback |
| `!skip` | `!s`, `!saltar` | Skip to the next song |
| `!queue` | `!q`, `!cola` | Show the playback queue |
| `!stop` | `!detener` | Stop music and disconnect the bot |
| `!volumen <0-100>` | `!vol` | Adjust the volume |

### Voice (TTS)
| Command | Description |
|---------|-------------|
| `!hablar <text>` | Read text aloud in the voice channel using the Sabina voice |

### Reminder
| Command | Description |
|---------|-------------|
| `!forzar_recordatorio` | Manually send the payment reminder |
| `!estado_recordatorio` | Show the status of the automatic reminder |
| `!prueba` | Verify the bot is working correctly |

### AI
| Command | Description |
|---------|-------------|
| `!ia <question>` | Ask Llama 3.3 70B a question (maintains history per user) |

## Requirements

- Python 3.11+
- FFmpeg installed and available in the system PATH
- Discord bot token with `message_content` intent enabled
- Groq API key (for the AI module)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd Bot
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
pip install groq
```

### 3. Configure environment variables

Create a `.env` file in the project root with the following content:

```env
DISCORD_TOKEN=your_discord_token
CANAL_ID=channel_id_for_reminders
PRECIO=60
DIA_RECORDATORIO=6
AMIGOS_IDS=id1,id2,id3
GROQ_API_KEY=your_groq_api_key
```

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Bot token (obtained from the [Discord Developer Portal](https://discord.com/developers/applications)) |
| `CANAL_ID` | ID of the channel where automatic reminders are sent |
| `PRECIO` | Price per person for YouTube Premium |
| `DIA_RECORDATORIO` | Day of the month to send the reminder (1–31) |
| `AMIGOS_IDS` | Comma-separated Discord user IDs to mention |
| `GROQ_API_KEY` | Groq API key (obtained from [console.groq.com](https://console.groq.com)) |

### 4. Install FFmpeg

**Windows:** Download FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html) and add it to the system PATH.

**Linux:**
```bash
sudo apt install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

### 5. Run the bot

```bash
python main.py
```

## Project Structure

```
Bot/
├── main.py              # Entry point, cog loader
├── config.py            # Environment variable reader
├── requirements.txt     # Main dependencies
├── .env                 # Environment variables (not tracked by git)
└── cogs/
    ├── musica.py        # YouTube music playback via yt-dlp
    ├── voz.py           # TTS with pyttsx3
    ├── recordatorio.py  # Automatic payment reminders
    └── ia.py            # AI chat with Groq API (Llama 3.3 70B)
```

## Dependencies

```
discord.py>=2.3.0
yt-dlp>=2024.1.0
pyttsx3>=2.90
python-dotenv>=1.0.0
PyNaCl>=1.5.0
groq>=1.2.0
```
