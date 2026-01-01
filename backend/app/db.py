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


def fetch_all(query: str, params: tuple = ()): 
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_one(query: str, params: tuple = ()): 
    with get_conn() as conn:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None


def execute(query: str, params: tuple = ()):
    with get_conn() as conn:
        cur = conn.execute(query, params)
        return cur.lastrowid


def execute_many(query: str, params_list: list[tuple]):
    with get_conn() as conn:
        conn.executemany(query, params_list)


def insert_job(job_type: str, payload: dict | None = None) -> int:
    payload_json = json.dumps(payload or {})
    return execute(
        """
        INSERT INTO jobs (type, status, payload, created_at, updated_at)
        VALUES (?, 'PENDING', ?, ?, ?)
        """,
        (job_type, payload_json, utc_now(), utc_now()),
    )


def update_job(job_id: int, status: str, result: dict | None = None, error: str | None = None):
    result_json = json.dumps(result or {})
    execute(
        """
        UPDATE jobs
        SET status = ?, result = ?, error = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, result_json, error, utc_now(), job_id),
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
