import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "/data/drivecompare.db")

SCHEMA = """
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

INSERT OR IGNORE INTO leclerc_unblock_state
(id, active, blocked, done, updated_at)
VALUES (1, 0, 0, 0, datetime('now'));
"""


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    main()
