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

-- 동조 분석 결과(상위 후보 JSON). 매일 크론이 미리 채워두고, 없으면 조회 시 계산해 채운다.
CREATE TABLE IF NOT EXISTS combo_cache (
    code TEXT PRIMARY KEY,
    computed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

-- 마지막으로 외부에서 받아온 시각. price_history.date(거래일)로는 신선도를 알 수 없다
-- (금요일 봉은 주말 내내 '오래된' 것으로 보여 매 요청마다 재다운로드됐다).
CREATE TABLE IF NOT EXISTS price_fetch_log (
    code TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout: 여러 종목 가격을 병렬로 받아올 때 쓰기 잠금 대기 (기본 5초는 짧다)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
