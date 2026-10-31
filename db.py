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
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS members (
                discord_id INTEGER PRIMARY KEY,
                added_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'rejected')),
                requested_at INTEGER NOT NULL,
                resolved_at INTEGER,
                resolved_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS reminder_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('monthly', 'followup')),
                sent_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_playlists ON playlists(guild_id, name, position);
            CREATE INDEX IF NOT EXISTS idx_history ON history(guild_id, played_at);
            CREATE INDEX IF NOT EXISTS idx_reminders ON reminders(remind_at);
            CREATE INDEX IF NOT EXISTS idx_payments_month ON payments(month, discord_id);
            -- Un solo pago activo (pendiente o confirmado) por persona y mes.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_activo
                ON payments(discord_id, month) WHERE status IN ('pending', 'confirmed');
            -- Un solo recordatorio mensual por mes, aunque el bot se reinicie.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reminder_mensual
                ON reminder_log(month) WHERE kind = 'monthly';
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


def playlist_remove_at(guild_id: int, name: str, index: int) -> int | None:
    with _con() as con:
        fila = con.execute(
            "SELECT id FROM playlists WHERE guild_id = ? AND name = ? "
            "ORDER BY position LIMIT 1 OFFSET ?",
            (guild_id, name, index - 1),
        ).fetchone()
        if fila is None:
            return None
        con.execute("DELETE FROM playlists WHERE id = ?", (fila["id"],))
    return fila["id"]


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


def playlist_clear_all(guild_id: int) -> int:
    with _con() as con:
        cur = con.execute("DELETE FROM playlists WHERE guild_id = ?", (guild_id,))
        return cur.rowcount


def settings_seed(defaults: dict[str, str]):
    with _con() as con:
        con.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", defaults.items()
        )


def setting_get(key: str) -> str | None:
    with _con() as con:
        fila = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return fila["value"] if fila else None


def setting_set(key: str, value: str):
    with _con() as con:
        con.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def members_count() -> int:
    with _con() as con:
        return con.execute("SELECT COUNT(*) FROM members").fetchone()[0]


def member_ids() -> list[int]:
    with _con() as con:
        return [f["discord_id"] for f in con.execute("SELECT discord_id FROM members ORDER BY added_at")]


def member_exists(discord_id: int) -> bool:
    with _con() as con:
        return con.execute("SELECT 1 FROM members WHERE discord_id = ?", (discord_id,)).fetchone() is not None


def member_add(discord_id: int) -> bool:
    with _con() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO members (discord_id, added_at) VALUES (?, ?)",
            (discord_id, int(time.time())),
        )
        return cur.rowcount > 0


def member_remove(discord_id: int) -> bool:
    with _con() as con:
        return con.execute("DELETE FROM members WHERE discord_id = ?", (discord_id,)).rowcount > 0


def payment_get(payment_id: int):
    with _con() as con:
        return con.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def payment_get_active(discord_id: int, month: str):
    with _con() as con:
        return con.execute(
            "SELECT * FROM payments WHERE discord_id = ? AND month = ? "
            "AND status IN ('pending', 'confirmed')",
            (discord_id, month),
        ).fetchone()


def payment_request(discord_id: int, month: str, amount: int) -> int | None:
    """Crea una solicitud pendiente. Devuelve None si ya hay una activa ese mes."""
    try:
        with _con() as con:
            return con.execute(
                "INSERT INTO payments (discord_id, month, amount, status, requested_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (discord_id, month, amount, int(time.time())),
            ).lastrowid
    except sqlite3.IntegrityError:
        return None


def payment_resolve(payment_id: int, status: str, admin_id: int):
    """Resuelve una solicitud pendiente. Devuelve None si ya estaba resuelta."""
    with _con() as con:
        cur = con.execute(
            "UPDATE payments SET status = ?, resolved_at = ?, resolved_by = ? "
            "WHERE id = ? AND status = 'pending'",
            (status, int(time.time()), admin_id, payment_id),
        )
        if cur.rowcount == 0:
            return None
        return con.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()


def payment_mark_paid(discord_id: int, month: str, amount: int, admin_id: int):
    """Confirma el pago del mes. Devuelve None si ya estaba confirmado."""
    ahora = int(time.time())
    with _con() as con:
        fila = con.execute(
            "SELECT id, status FROM payments WHERE discord_id = ? AND month = ? "
            "AND status IN ('pending', 'confirmed')",
            (discord_id, month),
        ).fetchone()
        if fila and fila["status"] == "confirmed":
            return None
        if fila:
            pid = fila["id"]
            con.execute(
                "UPDATE payments SET status = 'confirmed', resolved_at = ?, resolved_by = ? WHERE id = ?",
                (ahora, admin_id, pid),
            )
        else:
            pid = con.execute(
                "INSERT INTO payments (discord_id, month, amount, status, requested_at, resolved_at, resolved_by) "
                "VALUES (?, ?, ?, 'confirmed', ?, ?, ?)",
                (discord_id, month, amount, ahora, ahora, admin_id),
            ).lastrowid
        return con.execute("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()


def payments_month(month: str):
    with _con() as con:
        return con.execute(
            "SELECT discord_id, status, amount FROM payments WHERE month = ?", (month,)
        ).fetchall()


def payments_user(discord_id: int):
    with _con() as con:
        return con.execute(
            "SELECT month, status, amount FROM payments WHERE discord_id = ? ORDER BY month DESC",
            (discord_id,),
        ).fetchall()


def reminder_claim(month: str, kind: str) -> int | None:
    """Registra un envío. Devuelve None si el mensual de ese mes ya existe."""
    try:
        with _con() as con:
            return con.execute(
                "INSERT INTO reminder_log (month, kind, sent_at) VALUES (?, ?, ?)",
                (month, kind, int(time.time())),
            ).lastrowid
    except sqlite3.IntegrityError:
        return None


def reminder_unclaim(log_id: int):
    with _con() as con:
        con.execute("DELETE FROM reminder_log WHERE id = ?", (log_id,))


def reminder_sent_monthly(month: str) -> bool:
    with _con() as con:
        return con.execute(
            "SELECT 1 FROM reminder_log WHERE month = ? AND kind = 'monthly'", (month,)
        ).fetchone() is not None


def reminder_last(month: str) -> int | None:
    with _con() as con:
        return con.execute(
            "SELECT MAX(sent_at) FROM reminder_log WHERE month = ?", (month,)
        ).fetchone()[0]
