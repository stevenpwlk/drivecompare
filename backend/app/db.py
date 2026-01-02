import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.getenv("DB_PATH", "/data/drivecompare.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utcnow_iso() -> str:
    return utc_now()


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

            CREATE TABLE IF NOT EXISTS leclerc_unblock_state (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                active INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                done INTEGER DEFAULT 0,
                job_id INTEGER,
                reason TEXT,
                blocked_url TEXT,
                unblock_url TEXT,
                updated_at TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO leclerc_unblock_state
            (id, active, blocked, done, updated_at)
            VALUES (1, 0, 0, 0, datetime('now'))
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


def get_unblock_state() -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT id, active, blocked, done, job_id, reason, blocked_url, unblock_url, updated_at
        FROM leclerc_unblock_state
        WHERE id = 1
        """
    )


def set_blocked(
    job_id: int,
    reason: str | None,
    blocked_url: str | None,
    unblock_url: str | None,
) -> None:
    execute(
        """
        UPDATE leclerc_unblock_state
        SET active = 1,
            blocked = 1,
            done = 0,
            job_id = ?,
            reason = ?,
            blocked_url = ?,
            unblock_url = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (job_id, reason, blocked_url, unblock_url, utc_now()),
    )


def set_done() -> None:
    execute(
        """
        UPDATE leclerc_unblock_state
        SET active = 0,
            blocked = 0,
            done = 1,
            updated_at = ?
        WHERE id = 1
        """,
        (utc_now(),),
    )


def reset_unblock_state() -> None:
    execute(
        """
        UPDATE leclerc_unblock_state
        SET active = 0,
            blocked = 0,
            done = 0,
            job_id = NULL,
            reason = NULL,
            blocked_url = NULL,
            unblock_url = NULL,
            updated_at = ?
        WHERE id = 1
        """,
        (utc_now(),),
    )
