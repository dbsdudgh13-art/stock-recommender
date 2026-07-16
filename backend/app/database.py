import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT,
    industry TEXT,
    close_price REAL,
    change_rate REAL,
    market_cap REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    code TEXT,
    date TEXT,
    close REAL,
    PRIMARY KEY (code, date)
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
