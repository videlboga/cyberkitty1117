"""
Миграция: JSON → SQLite.
Читает users_database.json, пишет sammory.db с полной схемой.
Перед миграцией делает бэкап JSON (копирует в users_database.json.bak).
"""
import json
import sqlite3
import shutil
from datetime import datetime as dt
from pathlib import Path


DB_DIR = Path("database")
JSON_PATH = DB_DIR / "users_database.json"
DB_PATH = DB_DIR / "sammory.db"


def _get_conn():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
    """)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn):
    conn.executescript("""
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
            link_to_message TEXT,
            text_in_msg TEXT DEFAULT '',
            timestamp TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_chat_date ON messages(chat_id, date);

        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            date TEXT NOT NULL,
            reactor_user_id TEXT NOT NULL,
            message_id INTEGER,
            delta INTEGER DEFAULT 0,
            timestamp TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_reactions_chat_date ON reactions(chat_id, date);

        CREATE TABLE IF NOT EXISTS membership_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            user_id INTEGER,
            action TEXT,
            event_date TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_membership_chat ON membership_events(chat_id);
    """)


def migrate():
    print(f"[{dt.now().isoformat()}] Sammory JSON → SQLite migration")

    if not JSON_PATH.exists():
        print(f"JSON database не найден: {JSON_PATH}")
        # Проверяем, может уже есть SQLite
        if DB_PATH.exists():
            print(f"SQLite база уже существует: {DB_PATH} — пропускаю.")
            return True
        print("Нет данных для миграции. Создам пустую SQLite базу.")
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = _get_conn()
        try:
            _init_db(conn)
            conn.commit()
        finally:
            conn.close()
        return True

    # 1. Back up JSON
    bak_path = JSON_PATH.with_suffix(".json.bak")
    if not bak_path.exists():
        shutil.copy2(str(JSON_PATH), str(bak_path))
        json_size = JSON_PATH.stat().st_size
        print(f"✅ Бэкап: {bak_path} ({json_size:,} байт)")
    else:
        print(f"ℹ️  Бэкап уже есть: {bak_path}")

    # 2. Load JSON
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    print(f"📦 Загружено: {len(db.get('chats', {}))} чатов, "
          f"{len(db.get('users', {}))} пользователей")

    # 3. Write to SQLite
    conn = _get_conn()
    try:
        _init_db(conn)
        conn.execute("BEGIN")

        # --- superadmins ---
        conn.execute("DELETE FROM superadmins")
        for uid in db.get("superadmins", ["648981358"]):
            conn.execute("INSERT INTO superadmins (user_id) VALUES (?)", (uid,))

        # --- users ---
        conn.execute("DELETE FROM users")
        for uid, udata in db.get("users", {}).items():
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, username, first_seen) "
                "VALUES (?, ?, ?)",
                (uid, udata.get("username"), udata.get("first_seen")),
            )

        # --- chats ---
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM reactions")
        conn.execute("DELETE FROM membership_events")
        conn.execute("DELETE FROM chat_admins")
        conn.execute("DELETE FROM chat_settings")
        conn.execute("DELETE FROM chats")

        total_msgs = 0
        total_rxns = 0
        total_membership = 0

        for cid, cdata in db.get("chats", {}).items():
            conn.execute(
                "INSERT INTO chats (chat_id, title, admins_updated_at, last_summary_date) "
                "VALUES (?, ?, ?, ?)",
                (
                    cid,
                    cdata.get("title", cid),
                    cdata.get("admins_updated_at", 0),
                    cdata.get("last_summary_date", ""),
                ),
            )

            # admins
            for uid in cdata.get("admins", []):
                conn.execute(
                    "INSERT OR IGNORE INTO chat_admins (chat_id, user_id) VALUES (?, ?)",
                    (cid, str(uid)),
                )

            # settings
            for key, val in cdata.get("settings", {}).items():
                if val is None:
                    val = ""
                elif not isinstance(val, str):
                    val = str(val)
                conn.execute(
                    "INSERT OR REPLACE INTO chat_settings (chat_id, key, value) "
                    "VALUES (?, ?, ?)",
                    (cid, key, val),
                )

            # history → messages
            for date_key, msgs in cdata.get("history", {}).items():
                for msg in msgs:
                    conn.execute(
                        "INSERT INTO messages (chat_id, date, user_id, "
                        "link_to_message, text_in_msg, timestamp) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            cid,
                            date_key,
                            msg.get("user_id", ""),
                            msg.get("link_to_message", ""),
                            msg.get("text_in_msg", ""),
                            msg.get("timestamp", ""),
                        ),
                    )
                    total_msgs += 1

            # reactions
            for date_key, rxns in cdata.get("reactions", {}).items():
                for rxn in rxns:
                    conn.execute(
                        "INSERT INTO reactions (chat_id, date, reactor_user_id, "
                        "message_id, delta, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            cid,
                            date_key,
                            str(rxn.get("reactor_user_id", "")),
                            rxn.get("message_id"),
                            rxn.get("delta", 0),
                            rxn.get("timestamp", ""),
                        ),
                    )
                    total_rxns += 1

            # membership_events
            for ev in cdata.get("membership_events", []):
                conn.execute(
                    "INSERT INTO membership_events (chat_id, user_id, action, event_date) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, ev.get("user_id"), ev.get("action"), ev.get("date")),
                )
                total_membership += 1

        conn.execute("COMMIT")

        # Stats
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM messages")
        msg_count = cursor.fetchone()["cnt"]
        conn.commit()

        print(f"✅ Миграция завершена:")
        print(f"   - Чатов: {len(db.get('chats', {}))}")
        print(f"   - Сообщений: {total_msgs} (в БД: {msg_count})")
        print(f"   - Реакций: {total_rxns}")
        print(f"   - Событий подписки: {total_membership}")

        db_size = DB_PATH.stat().st_size
        print(f"   - Размер БД: {db_size:,} байт")
        print(f"   - Файл: {DB_PATH}")

        return True

    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"❌ Ошибка миграции: {e}")
        return False

    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
