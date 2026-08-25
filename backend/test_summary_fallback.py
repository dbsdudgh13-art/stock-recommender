"""KRX 전종목 API가 죽어도 시황이 나오는지 검증.

2026-08-10, 08-18, 08-24 시황이 누락됐다. 셋 다 data.krx.co.kr 전종목 API
실패였다(8/24는 Render 로그로 확인 — 재시도 10회 전부 같은 오류).
전종목 API는 당일 데이터만 주므로 지나간 날은 복구할 수 없다.

실행: venv/Scripts/python test_summary_fallback.py
"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app import database

database.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from app import data_loader, market_summary  # noqa: E402

TODAY = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")


def _seed_db(n_stocks=150):
    database.init_db()
    conn = database.get_connection()
    for t in ("stocks", "price_history", "price_fetch_log"):
        conn.execute(f"DELETE FROM {t}")  # 앞 테스트 데이터가 남으면 표본 수가 오염된다
    now = datetime.utcnow().isoformat()
    stocks, prices, logs = [], [], []
    for i in range(n_stocks):
        code = f"{i:06d}"
        market = "KOSPI" if i % 2 else "KOSDAQ"
        industry = ["반도체 제조업", "기초 화학물질 제조업", "자동차 제조업"][i % 3]
        stocks.append((code, f"종목{i}", market, industry, 1000.0, 0.0, 1e12 - i * 1e9, now))
        # 어제/오늘 종가 — 짝수는 상승, 홀수는 하락
        prev, last = 1000.0, 1000.0 * (1.02 if i % 2 == 0 else 0.98)
        yesterday = (datetime.strptime(TODAY, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        prices += [(code, yesterday, prev), (code, TODAY, last)]
        logs.append((code, now))
    conn.executemany(data_loader.UPSERT_SQL, stocks)
    conn.executemany("INSERT OR REPLACE INTO price_history (code, date, close) VALUES (?,?,?)", prices)
    conn.executemany("INSERT OR REPLACE INTO price_fetch_log (code, fetched_at) VALUES (?,?)", logs)
    conn.commit()
    conn.close()


def test_generates_when_krx_dead():
    _seed_db()

    def dead(*a, **k):
        raise ValueError("Failed to load data from http://data.krx.co.kr/...")

    market_summary.fdr.StockListing = dead
    market_summary.is_trading_day = lambda *a, **k: True

    title, body = market_summary.generate()

    assert "시황 요약" in title, title
    assert len(body) > 500, f"본문이 너무 짧다: {len(body)}자"
    assert "시가총액 상위" in body, "집계 범위 안내가 빠졌다"
    assert "거래대금 항목은 포함되지 않았습니다" in body, "거래대금 제외 고지가 빠졌다"
    # 거래대금 문단 자체는 생성되지 않아야 한다
    assert "거래대금 상위" not in body, "없는 거래대금 데이터로 문단을 만들었다"


def test_refuses_when_too_few_stocks():
    """표본이 부족하면 부실한 글을 내느니 실패시킨다 (재시도 대상)."""
    _seed_db(n_stocks=10)

    def dead(*a, **k):
        raise ValueError("KRX 다운")

    market_summary.fdr.StockListing = dead
    market_summary.is_trading_day = lambda *a, **k: True

    try:
        market_summary.generate()
        raise AssertionError("표본이 부족한데 글을 만들었다")
    except ValueError as e:
        assert "시황을 만들지 않는다" in str(e), e


if __name__ == "__main__":
    test_generates_when_krx_dead()
    test_refuses_when_too_few_stocks()
    print("OK")
