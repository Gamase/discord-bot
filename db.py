import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / 'bot.db'


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _con() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                query TEXT NOT NULL,
                title TEXT,
                position INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER,
                title TEXT NOT NULL,
                query TEXT NOT NULL,
                played_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                remind_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_playlists ON playlists(guild_id, name, position);
            CREATE INDEX IF NOT EXISTS idx_history ON history(guild_id, played_at);
            CREATE INDEX IF NOT EXISTS idx_reminders ON reminders(remind_at);
            """
        )


def playlist_add(guild_id: int, name: str, query: str, title: str) -> int:
    with _con() as con:
        fila = con.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS pos FROM playlists WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ).fetchone()
        posicion = fila["pos"]
        con.execute(
            "INSERT INTO playlists (guild_id, name, query, title, position) VALUES (?, ?, ?, ?, ?)",
            (guild_id, name, query, title, posicion),
        )
    return posicion


def playlist_names(guild_id: int):
    with _con() as con:
        return con.execute(
            "SELECT name, COUNT(*) AS total FROM playlists WHERE guild_id = ? GROUP BY name ORDER BY name",
            (guild_id,),
        ).fetchall()


def playlist_tracks(guild_id: int, name: str):
    with _con() as con:
        return con.execute(
            "SELECT query, title FROM playlists WHERE guild_id = ? AND name = ? ORDER BY position",
            (guild_id, name),
        ).fetchall()


def playlist_delete(guild_id: int, name: str) -> int:
    with _con() as con:
        cur = con.execute(
            "DELETE FROM playlists WHERE guild_id = ? AND name = ?", (guild_id, name)
        )
        return cur.rowcount


def history_add(guild_id: int, user_id: int | None, title: str, query: str):
    with _con() as con:
        con.execute(
            "INSERT INTO history (guild_id, user_id, title, query, played_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, title, query, int(time.time())),
        )
        con.execute(
            "DELETE FROM history WHERE guild_id = ? AND id NOT IN "
            "(SELECT id FROM history WHERE guild_id = ? ORDER BY played_at DESC, id DESC LIMIT 50)",
            (guild_id, guild_id),
        )


def history_last(guild_id: int):
    with _con() as con:
        return con.execute(
            "SELECT title, query, user_id, played_at FROM history WHERE guild_id = ? "
            "ORDER BY played_at DESC, id DESC LIMIT 1",
            (guild_id,),
        ).fetchone()


def history_recent(guild_id: int, limit: int = 10):
    with _con() as con:
        return con.execute(
            "SELECT title, query, user_id, played_at FROM history WHERE guild_id = ? "
            "ORDER BY played_at DESC, id DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()


def reminder_add(user_id: int, channel_id: int, message: str, remind_at: int) -> int:
    with _con() as con:
        cur = con.execute(
            "INSERT INTO reminders (user_id, channel_id, message, remind_at) VALUES (?, ?, ?, ?)",
            (user_id, channel_id, message, remind_at),
        )
        return cur.lastrowid


def reminder_due(now: int):
    with _con() as con:
        return con.execute(
            "SELECT id, user_id, channel_id, message, remind_at FROM reminders "
            "WHERE remind_at <= ? ORDER BY remind_at",
            (now,),
        ).fetchall()


def reminder_list(user_id: int):
    with _con() as con:
        return con.execute(
            "SELECT id, channel_id, message, remind_at FROM reminders "
            "WHERE user_id = ? ORDER BY remind_at",
            (user_id,),
        ).fetchall()


def reminder_delete(reminder_id: int, user_id: int) -> int:
    with _con() as con:
        cur = con.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)
        )
        return cur.rowcount


def reminder_delete_by_id(reminder_id: int):
    with _con() as con:
        con.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
