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


def mark_job_running(job_id: int):
    execute(
        "UPDATE jobs SET status = 'RUNNING', updated_at = ? WHERE id = ?",
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
