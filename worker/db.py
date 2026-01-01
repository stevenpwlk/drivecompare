import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "/data/drivecompare.db")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ensure_job_columns() -> None:
    with get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "blocked_url" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN blocked_url TEXT")
        if "blocked_reason" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN blocked_reason TEXT")
        if "blocked_at" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN blocked_at TEXT")
        if "retry_requested" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN retry_requested INTEGER NOT NULL DEFAULT 0")


def ensure_key_value_table() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS key_value (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )


def fetch_one(query: str, params: tuple = ()):
    with get_conn() as conn:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetch_all(query: str, params: tuple = ()):
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def execute(query: str, params: tuple = ()): 
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.lastrowid


def update_job(job_id: int, status: str, result: dict | None = None, error: str | None = None):
    execute(
        """
        UPDATE jobs
        SET status = ?, result = ?, error = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, json.dumps(result or {}), error, utc_now(), job_id),
    )


def update_job_blocked(
    job_id: int,
    reason: str,
    blocked_url: str | None,
    blocked_at: str,
    result: dict | None = None,
    error: str | None = None,
):
    execute(
        """
        UPDATE jobs
        SET status = 'BLOCKED',
            result = ?,
            error = ?,
            blocked_url = ?,
            blocked_reason = ?,
            blocked_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(result or {}),
            error,
            blocked_url,
            reason,
            blocked_at,
            utc_now(),
            job_id,
        ),
    )


def mark_job_running(job_id: int):
    execute(
        "UPDATE jobs SET status = 'RUNNING', updated_at = ? WHERE id = ?",
        (utc_now(), job_id),
    )


def mark_job_retrying(job_id: int):
    execute(
        """
        UPDATE jobs
        SET status = 'RUNNING', retry_requested = 0, updated_at = ?
        WHERE id = ?
        """,
        (utc_now(), job_id),
    )


def enqueue_job(job_type: str, payload: dict | None = None) -> int:
    return execute(
        """
        INSERT INTO jobs (type, status, payload, created_at, updated_at)
        VALUES (?, 'PENDING', ?, ?, ?)
        """,
        (job_type, json.dumps(payload or {}), utc_now(), utc_now()),
    )


def get_key_value(key: str) -> str | None:
    row = fetch_one("SELECT value FROM key_value WHERE key = ?", (key,))
    return row["value"] if row else None


def set_key_value(key: str, value: str) -> None:
    execute(
        """
        INSERT INTO key_value (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def delete_key_value(key: str) -> None:
    execute("DELETE FROM key_value WHERE key = ?", (key,))


ensure_job_columns()
ensure_key_value_table()
