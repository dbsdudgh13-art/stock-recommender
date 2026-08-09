"""KRX 종목/가격 데이터를 FinanceDataReader에서 가져와 SQLite에 캐싱한다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

from .database import get_connection

PRICE_HISTORY_DAYS = 180
PRICE_CACHE_STALE_HOURS = 20


def load_stock_universe(force: bool = False) -> int:
    """전 종목 목록 + 업종 정보를 적재한다. 이미 있으면 force=True일 때만 갱신."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM stocks").fetchone()
        if row["c"] > 0 and not force:
            return row["c"]

        listing = fdr.StockListing("KRX")[["Code", "Name", "Market", "Close", "ChagesRatio", "Marcap"]]
        desc = fdr.StockListing("KRX-DESC")[["Code", "Industry"]]
        merged = listing.merge(desc, on="Code", how="left")
        merged["Industry"] = merged["Industry"].fillna("기타")

        now = datetime.utcnow().isoformat()
        rows = [
            (
                r["Code"],
                r["Name"],
                r["Market"],
                r["Industry"],
                float(r["Close"]) if pd.notna(r["Close"]) else None,
                float(r["ChagesRatio"]) if pd.notna(r["ChagesRatio"]) else None,
                float(r["Marcap"]) if pd.notna(r["Marcap"]) else None,
                now,
            )
            for _, r in merged.iterrows()
        ]
        conn.executemany(
            """
            INSERT INTO stocks (code, name, market, industry, close_price, change_rate, market_cap, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name, market=excluded.market, industry=excluded.industry,
                close_price=excluded.close_price, change_rate=excluded.change_rate,
                market_cap=excluded.market_cap, updated_at=excluded.updated_at
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def load_us_universe() -> int:
    """미국 S&P500 종목(종목명·업종)을 적재. 시세·시총은 무료 소스에 일괄 데이터가 없어 NULL.
    가격은 종목 조회 시 개별로 받아온다(get_price_history). 매 부팅마다 upsert(503개, 가벼움)."""
    conn = get_connection()
    try:
        df = fdr.StockListing("S&P500")[["Symbol", "Name", "Industry"]]
        df["Industry"] = df["Industry"].fillna("기타")
        now = datetime.utcnow().isoformat()
        rows = [
            (r["Symbol"], r["Name"], "S&P500", r["Industry"], None, None, None, now)
            for _, r in df.iterrows()
        ]
        conn.executemany(
            """
            INSERT INTO stocks (code, name, market, industry, close_price, change_rate, market_cap, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name, market=excluded.market, industry=excluded.industry, updated_at=excluded.updated_at
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def get_price_history(code: str) -> pd.Series:
    """종목의 최근 N일 종가를 반환. 마지막으로 받아온 지 오래됐으면 FDR에서 다시 받아온다."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT fetched_at FROM price_fetch_log WHERE code = ?", (code,)
        ).fetchone()
        fresh = row is not None and (
            datetime.utcnow() - datetime.fromisoformat(row["fetched_at"])
            < timedelta(hours=PRICE_CACHE_STALE_HOURS)
        )

        if fresh:
            cached = conn.execute(
                "SELECT date, close FROM price_history WHERE code = ? ORDER BY date", (code,)
            ).fetchall()
            if cached:
                return pd.Series({r["date"]: r["close"] for r in cached}).rename("Close")

        start = (datetime.utcnow() - timedelta(days=PRICE_HISTORY_DAYS)).strftime("%Y-%m-%d")
        df = fdr.DataReader(code, start)
        now = datetime.utcnow().isoformat()
        # 빈 응답도 기록 — 상장폐지·데이터 없는 종목을 매 요청마다 다시 시도하지 않도록
        conn.execute(
            "INSERT OR REPLACE INTO price_fetch_log (code, fetched_at) VALUES (?, ?)", (code, now)
        )
        if df.empty:
            conn.commit()
            return pd.Series(dtype=float)
        conn.executemany(
            "INSERT OR REPLACE INTO price_history (code, date, close) VALUES (?, ?, ?)",
            [(code, idx.strftime("%Y-%m-%d"), float(v)) for idx, v in df["Close"].items()],
        )
        conn.commit()
        return df["Close"]
    finally:
        conn.close()


def prefetch_price_histories(codes: list[str], workers: int = 8) -> None:
    """여러 종목 가격을 동시에 받아 캐시를 채운다.

    순차로 받으면 종목당 왕복 지연이 그대로 쌓여 조합 분석 한 번에 10초가 걸렸다.
    각 스레드가 자기 커넥션을 열므로(get_connection) 스레드 안전하다.
    """
    if not codes:
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(_safe_price_history, codes):
            pass


def _safe_price_history(code: str) -> None:
    try:
        get_price_history(code)
    except Exception:  # 한 종목 실패가 전체 분석을 막지 않게
        pass
