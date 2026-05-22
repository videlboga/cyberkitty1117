"""
Модуль работы с базой данных Sammory бота.
Переписан с JSON на SQLite (синхронный sqlite3, WAL mode).
Сохраняет API: load_database() — синхронно, save_database() — async (в to_thread).

Кэш в памяти (_database_cache) — код мутирует dict напрямую, save_database() сбрасывает в SQLite.
"""
import asyncio
import sqlite3
from pathlib import Path
from datetime import datetime as dt

DB_DIR = Path("database")
DB_PATH = DB_DIR / "sammory.db"

# Кэш в памяти — тот же самый объект, который мутируют вызывающие
_database_cache = None

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS superadmins (
    user_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    first_seen TEXT
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY,
    title TEXT,
    admins_updated_at REAL DEFAULT 0,
    last_summary_date TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chat_admins (
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (chat_id, key)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    date TEXT NOT NULL,
    user_id TEXT NOT NULL,
    link_to_message TEXT DEFAULT '',
    text_in_msg TEXT DEFAULT '',
    timestamp TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON messages(chat_id, date);

CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    date TEXT NOT NULL,
    reactor_user_id TEXT NOT NULL,
    message_id INTEGER,
    delta INTEGER DEFAULT 0,
    timestamp TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_reactions_chat_date ON reactions(chat_id, date);

CREATE TABLE IF NOT EXISTS membership_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    user_id TEXT,
    action TEXT,
    event_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_membership_chat ON membership_events(chat_id);
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn):
    conn.executescript(SCHEMA_SQL)


def _build_dict(conn):
    """Читает всё из SQLite и собирает dict в старом формате."""
    db: dict = {}

    # -- superadmins --
    rows = conn.execute("SELECT user_id FROM superadmins").fetchall()
    db['superadmins'] = [r['user_id'] for r in rows] or ['648981358']

    # -- users --
    db['users'] = {}
    for r in conn.execute("SELECT * FROM users"):
        db['users'][r['user_id']] = {
            'username': r['username'] or '',
            'first_seen': r['first_seen'] or '',
        }

    # -- chats --
    db['chats'] = {}
    for r in conn.execute("SELECT * FROM chats"):
        cid = r['chat_id']
        chat = {
            'title': r['title'] or cid,
            'admins': [],
            'admins_updated_at': r['admins_updated_at'] or 0,
            'last_summary_date': r['last_summary_date'] or '',
            'settings': {},
            'history': {},
            'reactions': {},
            'membership_events': [],
        }

        # admins
        for ar in conn.execute(
            "SELECT user_id FROM chat_admins WHERE chat_id=?", (cid,)
        ):
            chat['admins'].append(ar['user_id'])

        # settings
        for sr in conn.execute(
            "SELECT key, value FROM chat_settings WHERE chat_id=?", (cid,)
        ):
            chat['settings'][sr['key']] = sr['value']

        # messages → history (сгруппированы по date)
        for mr in conn.execute(
            "SELECT date, user_id, link_to_message, text_in_msg, timestamp "
            "FROM messages WHERE chat_id=? ORDER BY id", (cid,)
        ):
            date = mr['date']
            if date not in chat['history']:
                chat['history'][date] = []
            chat['history'][date].append({
                'user_id': mr['user_id'],
                'link_to_message': mr['link_to_message'] or '',
                'text_in_msg': mr['text_in_msg'] or '',
                'timestamp': mr['timestamp'] or '',
            })

        # reactions
        for rr in conn.execute(
            "SELECT date, reactor_user_id, message_id, delta, timestamp "
            "FROM reactions WHERE chat_id=? ORDER BY id", (cid,)
        ):
            date = rr['date']
            if date not in chat['reactions']:
                chat['reactions'][date] = []
            chat['reactions'][date].append({
                'reactor_user_id': rr['reactor_user_id'],
                'message_id': rr['message_id'],
                'delta': rr['delta'],
                'timestamp': rr['timestamp'] or '',
            })

        # membership_events
        for er in conn.execute(
            "SELECT user_id, action, event_date "
            "FROM membership_events WHERE chat_id=? ORDER BY id", (cid,)
        ):
            chat['membership_events'].append({
                'user_id': er['user_id'],
                'action': er['action'],
                'date': er['event_date'] or '',
            })

        db['chats'][cid] = chat

    return db


def _flush_dict(db: dict, conn):
    """Полностью переписывает SQLite из dict-кэша (одна транзакция)."""
    conn.execute("BEGIN")

    try:
        # очищаем всё
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM reactions")
        conn.execute("DELETE FROM membership_events")
        conn.execute("DELETE FROM chat_admins")
        conn.execute("DELETE FROM chat_settings")
        conn.execute("DELETE FROM chats")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM superadmins")

        # superadmins
        for uid in db.get('superadmins', ['648981358']):
            conn.execute(
                "INSERT INTO superadmins (user_id) VALUES (?)", (uid,)
            )

        # users
        for uid, udata in db.get('users', {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, username, first_seen) "
                "VALUES (?, ?, ?)",
                (uid, udata.get('username', ''), udata.get('first_seen', '')),
            )

        # chats
        for cid, cdata in db.get('chats', {}).items():
            conn.execute(
                "INSERT INTO chats (chat_id, title, admins_updated_at, last_summary_date) "
                "VALUES (?, ?, ?, ?)",
                (
                    cid,
                    cdata.get('title', cid),
                    cdata.get('admins_updated_at', 0),
                    cdata.get('last_summary_date', ''),
                ),
            )

            # admins
            for uid in cdata.get('admins', []):
                conn.execute(
                    "INSERT OR REPLACE INTO chat_admins (chat_id, user_id) VALUES (?, ?)",
                    (cid, str(uid) if uid is not None else ''),
                )

            # settings
            for key, val in cdata.get('settings', {}).items():
                if val is None:
                    val = ''
                elif not isinstance(val, str):
                    val = str(val)
                conn.execute(
                    "INSERT OR REPLACE INTO chat_settings (chat_id, key, value) VALUES (?, ?, ?)",
                    (cid, key, val),
                )

            # history → messages
            for date_key, msgs in cdata.get('history', {}).items():
                for msg in msgs:
                    conn.execute(
                        "INSERT INTO messages (chat_id, date, user_id, "
                        "link_to_message, text_in_msg, timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            cid,
                            date_key,
                            msg.get('user_id', ''),
                            msg.get('link_to_message', ''),
                            msg.get('text_in_msg', ''),
                            msg.get('timestamp', ''),
                        ),
                    )

            # reactions
            for date_key, rxns in cdata.get('reactions', {}).items():
                for rxn in rxns:
                    conn.execute(
                        "INSERT INTO reactions (chat_id, date, reactor_user_id, "
                        "message_id, delta, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            cid,
                            date_key,
                            str(rxn.get('reactor_user_id', '')),
                            rxn.get('message_id'),
                            rxn.get('delta', 0),
                            rxn.get('timestamp', ''),
                        ),
                    )

            # membership_events
            for ev in cdata.get('membership_events', []):
                conn.execute(
                    "INSERT INTO membership_events (chat_id, user_id, action, event_date) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, str(ev.get('user_id', '')), ev.get('action'), ev.get('date')),
                )

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Public API (совместимость со старым кодом)
# ---------------------------------------------------------------------------
def load_database():
    """Загружает базу данных из SQLite в dict-кэш."""
    global _database_cache

    if _database_cache is not None:
        return _database_cache

    if not DB_PATH.exists():
        _database_cache = {}
        return _database_cache

    conn = _get_conn()
    try:
        _ensure_schema(conn)
        _database_cache = _build_dict(conn)
    except Exception as e:
        print(f"Ошибка при загрузке БД: {e}")
        _database_cache = {}
    finally:
        conn.close()

    return _database_cache


async def save_database(data=None):
    """Сохраняет кэш в SQLite атомарно (одна транзакция)."""
    global _database_cache

    if data is not None:
        _database_cache = data

    if _database_cache is None:
        return

    def _sync_save():
        conn = _get_conn()
        try:
            _ensure_schema(conn)
            _flush_dict(_database_cache, conn)
        except Exception as e:
            print(f"Ошибка при сохранении БД: {e}")
            raise
        finally:
            conn.close()

    await asyncio.to_thread(_sync_save)
