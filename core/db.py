import sqlite3
from pathlib import Path
from typing import Optional, Any, Dict

class DB:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 10000")
        return con

    def _init_db(self):
        with self._connect() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
            cur = con.cursor()
            # users
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                user_hash TEXT UNIQUE,
                usage_count INTEGER DEFAULT 0,
                region TEXT DEFAULT 'us',
                created_at INTEGER,
                last_active INTEGER,
                last_reminder INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0
            );
            """)

            # favorites
            cur.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                app_id INTEGER,
                app_name TEXT,
                added_at INTEGER,
                UNIQUE(user_id, app_id)
            );
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            
            cur.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_added ON favorites(user_id, added_at DESC)")

            con.commit()

    # ——— users ———
    def get_all_users(self) -> list:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM users")
            return cur.fetchall()
        
    def count_users(self) -> int:
        with self._connect() as con:
            cur = con.cursor()
            return cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get_users_page(self, limit: int, offset: int):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "SELECT * FROM users ORDER BY created_at ASC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            return cur.fetchall()
        
    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            return cur.fetchone()

    def upsert_user(self, user_id: int, username: Optional[str], full_name: str,
                    user_hash: str, now_ts: int) -> sqlite3.Row:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("""
                INSERT INTO users (user_id, username, full_name, user_hash, created_at, last_active)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    full_name=excluded.full_name,
                    last_active=excluded.last_active
            """, (user_id, username, full_name, user_hash, now_ts, now_ts))
            con.commit()
            return cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    
    def add_user_usage(self, user_id: int) -> sqlite3.Row:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET usage_count = usage_count + 1 WHERE user_id=?", (user_id,))
            con.commit()
            return cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

    def set_ban(self, user_id: int, banned: bool):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
            con.commit()
        
    def set_region(self, user_id: int, region: str):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET region=? WHERE user_id=?", (region, user_id))
            con.commit()

    def update_last_reminder(self, user_id: int, ts: int):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("UPDATE users SET last_reminder=? WHERE user_id=?", (ts, user_id))
            con.commit()

    def find_user_by_any(self, key: str) -> Optional[sqlite3.Row]:
        with self._connect() as con:
            cur = con.cursor()
            if key.isdigit():
                cur.execute("SELECT * FROM users WHERE user_id=?", (int(key),))
            elif key.startswith('@'):
                cur.execute("SELECT * FROM users WHERE username=?", (key[1:],))
            else:
                cur.execute("SELECT * FROM users WHERE user_hash=?", (key,))
            return cur.fetchone()

    def stats_for_user(self, user_id: int) -> Dict[str, Any]:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT created_at, last_active, user_hash, username, full_name, region FROM users WHERE user_id=?", (user_id,))
            row = cur.fetchone()
            return {
                "created_at": row["created_at"] if row else None,
                "last_active": row["last_active"] if row else None,
                "user_hash": row["user_hash"] if row else None,
                "username": row["username"] if row else None,
                "full_name": row["full_name"] if row else None,
                "region": row["region"] if row else None
            }
        
    # ——— favorites ———
    def add_favorite(self, user_id: int, app_id: int, app_name: str, added_at: int) -> bool:
        with self._connect() as con:
            cur = con.cursor()
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO favorites (user_id, app_id, app_name, added_at) VALUES (?, ?, ?, ?)",
                    (user_id, app_id, app_name, added_at),
                )
                con.commit()
                return cur.rowcount > 0
            except Exception:
                return False
            
    def remove_favorite(self, user_id: int, app_id: int) -> bool:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM favorites WHERE user_id=? AND app_id=?", (user_id, app_id))
            con.commit()
            return cur.rowcount > 0

    def get_favorites(self, user_id: int) -> list:
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("SELECT app_id, app_name, added_at FROM favorites WHERE user_id=? ORDER BY added_at DESC", (user_id,))
            return cur.fetchall()
