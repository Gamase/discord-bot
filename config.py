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

    CLABE: str = os.getenv('CLABE', '')

    ADMIN_ID: int = int(os.getenv('ADMIN_ID') or 0)
    GUILD_ID: int = int(os.getenv('GUILD_ID') or 0)
    PAGOS_CANAL_ID: int = int(os.getenv('PAGOS_CANAL_ID') or AVISO_CANAL_ID or CANAL_ID)

    _raw = os.getenv('AMIGOS_IDS', '')
    AMIGOS_IDS: list[int] = [int(uid) for uid in _raw.split(',') if uid.strip().isdigit()]
