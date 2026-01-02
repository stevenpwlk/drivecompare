import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

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


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                retailer TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT,
                result_json TEXT
            );

            CREATE TABLE IF NOT EXISTS unblock_state (
                job_id INTEGER PRIMARY KEY,
                url TEXT,
                reason TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                done INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )


def fetch_one(query: str, params: tuple = ()) -> dict[str, Any] | None:
    with get_conn() as conn:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def execute(query: str, params: tuple = ()) -> int:
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.lastrowid


def fetch_next_job() -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT id, retailer, query, status, created_at, updated_at
        FROM jobs
        WHERE status = 'QUEUED'
        ORDER BY created_at ASC
        LIMIT 1
        """
    )


def mark_job_running(job_id: int) -> None:
    execute(
        "UPDATE jobs SET status = 'RUNNING', updated_at = ? WHERE id = ?",
        (utc_now(), job_id),
    )


def mark_job_blocked(
    job_id: int,
    reason: str | None,
    *,
    result: dict[str, Any] | None = None,
) -> None:
    execute(
        """
        UPDATE jobs
        SET status = 'BLOCKED', result_json = ?, error = ?, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(result or {}), reason, utc_now(), job_id),
    )


def mark_job_failed(job_id: int, error: str, result: dict[str, Any] | None = None) -> None:
    execute(
        """
        UPDATE jobs
        SET status = 'FAILED', result_json = ?, error = ?, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(result or {}), error, utc_now(), job_id),
    )


def mark_job_succeeded(job_id: int, result: dict[str, Any]) -> None:
    execute(
        """
        UPDATE jobs
        SET status = 'SUCCESS', result_json = ?, error = NULL, updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(result or {}), utc_now(), job_id),
    )


def clear_unblock_state(job_id: int) -> None:
    execute(
        "UPDATE unblock_state SET active = 0, done = 0, updated_at = ? WHERE job_id = ?",
        (utc_now(), job_id),
    )


def get_unblock_state(job_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT job_id, url, reason, active, done, updated_at
        FROM unblock_state
        WHERE job_id = ?
        """,
        (job_id,),
    )


init_db()
