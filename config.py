import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TOKEN: str = os.getenv('DISCORD_TOKEN', '')
    CANAL_ID: int = int(os.getenv('CANAL_ID', '0'))
    AVISO_CANAL_ID: int = int(os.getenv('AVISO_CANAL_ID', os.getenv('CANAL_ID', '0')))
    DJ_ROLE_ID: int = int(os.getenv('DJ_ROLE_ID', '0'))
    PRECIO: int = int(os.getenv('PRECIO', '60'))
    DIA_RECORDATORIO: int = int(os.getenv('DIA_RECORDATORIO', '6'))

    _raw = os.getenv('AMIGOS_IDS', '')
    AMIGOS: list[str] = [f"<@{uid.strip()}>" for uid in _raw.split(',') if uid.strip()]
