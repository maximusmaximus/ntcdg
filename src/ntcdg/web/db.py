"""SQLite persistence for web users, uploads and job history (stdlib sqlite3)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    bio TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    venice_key_enc TEXT NOT NULL DEFAULT '',
    venice_key_last4 TEXT NOT NULL DEFAULT '',
    session_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS uploads_user ON uploads(user_id, created_at);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool TEXT NOT NULL,
    deck TEXT NOT NULL DEFAULT '',
    input_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    events_json TEXT NOT NULL DEFAULT '[]',
    log TEXT NOT NULL DEFAULT '',
    output_json TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs(user_id, created_at);
"""

USER_FIELDS = ("display_name", "bio")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    """Tiny thread-safe wrapper: one short-lived connection per operation."""

    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur
            finally:
                conn.close()

    def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, params).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            try:
                return [dict(r) for r in conn.execute(sql, params).fetchall()]
            finally:
                conn.close()

    # ==================== USERS ====================

    def create_user(self, username: str, password_hash: str, display_name: str = "") -> int:
        cur = self._exec(
            "INSERT INTO users (username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (username, display_name or username, password_hash, now_iso()),
        )
        return int(cur.lastrowid)

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE id = ?", (int(user_id),))

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM users WHERE username = ?", (username,))

    def update_profile(self, user_id: int, display_name: str, bio: str) -> None:
        self._exec(
            "UPDATE users SET display_name = ?, bio = ? WHERE id = ?",
            (display_name, bio, int(user_id)),
        )

    def set_password(self, user_id: int, password_hash: str) -> None:
        """Change the password and invalidate every other session."""
        self._exec(
            "UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
            (password_hash, int(user_id)),
        )

    def set_venice_key(self, user_id: int, encrypted: str, last4: str) -> None:
        self._exec(
            "UPDATE users SET venice_key_enc = ?, venice_key_last4 = ? WHERE id = ?",
            (encrypted, last4, int(user_id)),
        )

    def delete_user(self, user_id: int) -> None:
        self._exec("DELETE FROM users WHERE id = ?", (int(user_id),))

    # ==================== UPLOADS ====================

    def add_upload(self, upload_id: str, user_id: int, kind: str, original_name: str,
                   filename: str, size: int) -> None:
        self._exec(
            "INSERT INTO uploads (id, user_id, kind, original_name, filename, size, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (upload_id, int(user_id), kind, original_name, filename, int(size), now_iso()),
        )

    def get_upload(self, user_id: int, upload_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM uploads WHERE id = ? AND user_id = ?", (upload_id, int(user_id)),
        )

    def list_uploads(self, user_id: int, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self._all(
                "SELECT * FROM uploads WHERE user_id = ? AND kind = ? ORDER BY created_at DESC, id",
                (int(user_id), kind),
            )
        return self._all(
            "SELECT * FROM uploads WHERE user_id = ? ORDER BY created_at DESC, id", (int(user_id),),
        )

    def delete_upload(self, user_id: int, upload_id: str) -> None:
        self._exec("DELETE FROM uploads WHERE id = ? AND user_id = ?", (upload_id, int(user_id)))

    # ==================== JOBS ====================

    def insert_job(self, job_id: str, user_id: int, tool: str, deck: str,
                   input_data: dict[str, Any], status: str, created_at: str) -> None:
        self._exec(
            "INSERT INTO jobs (id, user_id, tool, deck, input_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, int(user_id), tool, deck, json.dumps(input_data), status, created_at),
        )

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "events_json", "log", "output_json", "error", "started_at", "finished_at"}
        keys = [k for k in fields if k in allowed]
        if not keys:
            return
        sql = "UPDATE jobs SET " + ", ".join(f"{k} = ?" for k in keys) + " WHERE id = ?"
        self._exec(sql, (*[fields[k] for k in keys], job_id))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def list_jobs(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return self._all(
            "SELECT id, user_id, tool, deck, status, error, created_at, started_at, finished_at "
            "FROM jobs WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (int(user_id), int(limit)),
        )

    def mark_interrupted(self) -> int:
        """Jobs left queued/running by a previous process can never finish."""
        cur = self._exec(
            "UPDATE jobs SET status = 'interrupted', error = 'Interrupted: the server restarted before "
            "this job finished. Run it again.', "
            "finished_at = ? WHERE status IN ('queued', 'running')",
            (now_iso(),),
        )
        return cur.rowcount
