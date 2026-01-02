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


def create_job(retailer: str, query: str) -> int:
    return execute(
        """
        INSERT INTO jobs (retailer, query, status, created_at, updated_at)
        VALUES (?, ?, 'QUEUED', ?, ?)
        """,
        (retailer, query, utc_now(), utc_now()),
    )


def fetch_job(job_id: int) -> dict[str, Any] | None:
    job = fetch_one(
        """
        SELECT id, retailer, query, status, created_at, updated_at, error, result_json
        FROM jobs
        WHERE id = ?
        """,
        (job_id,),
    )
    if not job:
        return None
    try:
        job["result"] = json.loads(job.get("result_json") or "{}")
    except json.JSONDecodeError:
        job["result"] = {}
    job.pop("result_json", None)
    return job


def update_job(
    job_id: int,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    execute(
        """
        UPDATE jobs
        SET status = ?, result_json = ?, error = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, json.dumps(result or {}), error, utc_now(), job_id),
    )


def set_unblock_state(
    job_id: int,
    url: str | None,
    reason: str | None,
    *,
    active: bool,
    done: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE unblock_state SET active = 0 WHERE active = 1 AND job_id != ?",
            (job_id,),
        )
        conn.execute(
            """
            INSERT INTO unblock_state (job_id, url, reason, active, done, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                url = excluded.url,
                reason = excluded.reason,
                active = excluded.active,
                done = excluded.done,
                updated_at = excluded.updated_at
            """,
            (
                job_id,
                url,
                reason,
                1 if active else 0,
                1 if done else 0,
                utc_now(),
            ),
        )


def mark_unblock_done(job_id: int) -> None:
    execute(
        """
        UPDATE unblock_state
        SET done = 1, updated_at = ?
        WHERE job_id = ?
        """,
        (utc_now(), job_id),
    )


def get_active_unblock_state() -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT job_id, url, reason, active, done, updated_at
        FROM unblock_state
        WHERE active = 1
        ORDER BY updated_at DESC
        LIMIT 1
        """
    )


init_db()
