"""
SQLite database — accounts, config, state, broadcast logs.
"""
import sqlite3
from typing import Optional
from config import Config


class Database:
    def __init__(self):
        self.path = Config.DB_PATH
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    phone         TEXT PRIMARY KEY,
                    label         TEXT,
                    ad_message    TEXT,
                    send_interval INTEGER DEFAULT 5,
                    cycle_pause   INTEGER DEFAULT 300,
                    log_channel   TEXT,
                    active        INTEGER DEFAULT 1,
                    group_count   INTEGER DEFAULT 0,
                    added_at      TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS user_state (
                    user_id INTEGER PRIMARY KEY,
                    state   TEXT
                );

                CREATE TABLE IF NOT EXISTS broadcast_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone        TEXT,
                    group_id     TEXT,
                    group_title  TEXT,
                    status       TEXT,
                    message_link TEXT,
                    error        TEXT,
                    created_at   TEXT DEFAULT (datetime('now'))
                );
            """)

    # ── User state ────────────────────────────────────────────────────────────
    def set_user_state(self, user_id: int, state: Optional[str]):
        with self._conn() as c:
            if state is None:
                c.execute("DELETE FROM user_state WHERE user_id=?", (user_id,))
            else:
                c.execute("INSERT OR REPLACE INTO user_state(user_id,state) VALUES(?,?)",
                          (user_id, state))

    def get_user_state(self, user_id: int) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("SELECT state FROM user_state WHERE user_id=?",
                            (user_id,)).fetchone()
            return row["state"] if row else None

    # ── Accounts ──────────────────────────────────────────────────────────────
    def add_account(self, phone: str, label: str, ad_message: Optional[str] = None):
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO accounts(phone, label, ad_message) VALUES(?,?,?)",
                (phone, label, ad_message)
            )

    def get_account(self, phone: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM accounts WHERE phone=?", (phone,)).fetchone()
            return dict(row) if row else None

    def list_accounts(self) -> list:
        with self._conn() as c:
            return [dict(r) for r in
                    c.execute("SELECT * FROM accounts ORDER BY added_at").fetchall()]

    def remove_account(self, phone: str):
        with self._conn() as c:
            c.execute("DELETE FROM accounts WHERE phone=?", (phone,))

    def update_account_label(self, phone: str, label: str):
        with self._conn() as c:
            c.execute("UPDATE accounts SET label=? WHERE phone=?", (label, phone))

    def update_account_ad(self, phone: str, ad_message: Optional[str]):
        with self._conn() as c:
            c.execute("UPDATE accounts SET ad_message=? WHERE phone=?", (ad_message, phone))

    def update_account_setting(self, phone: str, key: str, value):
        allowed = {"send_interval", "cycle_pause", "log_channel"}
        if key not in allowed:
            raise ValueError(f"Unknown setting: {key}")
        with self._conn() as c:
            c.execute(f"UPDATE accounts SET {key}=? WHERE phone=?", (value, phone))

    def update_group_count(self, phone: str, count: int):
        with self._conn() as c:
            c.execute("UPDATE accounts SET group_count=? WHERE phone=?", (count, phone))

    # ── Broadcast log ─────────────────────────────────────────────────────────
    def log_broadcast(self, phone: str, group_id: str, group_title: str,
                      status: str, message_link: str = None, error: str = None):
        with self._conn() as c:
            c.execute(
                "INSERT INTO broadcast_log"
                "(phone, group_id, group_title, status, message_link, error)"
                " VALUES(?,?,?,?,?,?)",
                (phone, group_id, group_title, status, message_link, error)
            )
