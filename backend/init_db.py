import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "/data/drivecompare.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    brand TEXT,
    size TEXT,
    unit TEXT,
    barcode TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS store_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    price REAL NOT NULL,
    loyalty_gain REAL DEFAULT 0,
    updated_at TEXT,
    FOREIGN KEY(store_id) REFERENCES stores(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    price REAL NOT NULL,
    loyalty_gain REAL DEFAULT 0,
    captured_at TEXT NOT NULL,
    FOREIGN KEY(store_id) REFERENCES stores(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS baskets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS basket_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    basket_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(basket_id) REFERENCES baskets(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS equivalences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    equivalent_product_id INTEGER NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES products(id),
    FOREIGN KEY(equivalent_product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    result TEXT,
    error TEXT,
    blocked_url TEXT,
    blocked_reason TEXT,
    blocked_at TEXT,
    retry_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS key_value (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

SEED_STORES = [
    ("LECLERC_SECLIN", "Leclerc Seclin Lorival"),
    ("AUCHAN_FT", "Auchan Faches-Thumesnil"),
]

SEED_PRODUCTS = [
    ("Lait demi-écrémé", "Marque Repère", "1", "L"),
    ("Pâtes spaghetti", "Barilla", "500", "g"),
    ("Beurre doux", "Président", "250", "g"),
    ("Jambon blanc", "Fleury Michon", "4", "tranches"),
]

SEED_STORE_PRODUCTS = [
    ("LECLERC_SECLIN", "Lait demi-écrémé", 1.05, 0.02),
    ("AUCHAN_FT", "Lait demi-écrémé", 1.15, 0.05),
    ("LECLERC_SECLIN", "Pâtes spaghetti", 1.35, 0.00),
    ("AUCHAN_FT", "Pâtes spaghetti", 1.49, 0.00),
    ("LECLERC_SECLIN", "Beurre doux", 2.10, 0.10),
    ("AUCHAN_FT", "Beurre doux", 2.35, 0.15),
    ("LECLERC_SECLIN", "Jambon blanc", 2.95, 0.20),
    ("AUCHAN_FT", "Jambon blanc", 3.05, 0.25),
]


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat()

    for code, name in SEED_STORES:
        conn.execute(
            "INSERT OR IGNORE INTO stores (code, name, created_at) VALUES (?, ?, ?)",
            (code, name, now),
        )

    for name, brand, size, unit in SEED_PRODUCTS:
        conn.execute(
            """
            INSERT INTO products (name, brand, size, unit, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, brand, size, unit, now),
        )

    conn.row_factory = sqlite3.Row
    store_map = {
        row["code"]: row["id"]
        for row in conn.execute("SELECT id, code FROM stores")
    }
    product_map = {
        row["name"]: row["id"]
        for row in conn.execute("SELECT id, name FROM products")
    }

    for store_code, product_name, price, loyalty_gain in SEED_STORE_PRODUCTS:
        conn.execute(
            """
            INSERT INTO store_products (store_id, product_id, price, loyalty_gain, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (store_map[store_code], product_map[product_name], price, loyalty_gain, now),
        )
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    main()
