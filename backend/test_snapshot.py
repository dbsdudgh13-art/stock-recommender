"""KRX가 막혔을 때 스냅샷 폴백이 사이트를 살리는지 검증.

실제 사고: Render에서 data.krx.co.kr 접근이 실패해 종목 DB가 빈 채로 떴고,
종목 페이지 3,377개가 전부 404, sitemap이 3,394 URL에서 27개로 줄었다.

실행: venv/Scripts/python test_snapshot.py
"""
import tempfile
from pathlib import Path

from app import database

database.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from app import data_loader, main  # noqa: E402


def test_snapshot_file_is_sane():
    n = data_loader.load_snapshot()
    assert n > 3000, f"스냅샷 종목 수가 너무 적다: {n}"

    conn = database.get_connection()
    try:
        row = conn.execute("SELECT * FROM stocks WHERE code = '005930'").fetchone()
        assert row and row["name"] == "삼성전자", "삼성전자가 없다"
        assert row["industry"], "업종이 비었다"
        kr = conn.execute("SELECT COUNT(*) c FROM stocks WHERE market != 'S&P500'").fetchone()["c"]
        us = conn.execute("SELECT COUNT(*) c FROM stocks WHERE market = 'S&P500'").fetchone()["c"]
        assert kr > 2500 and us > 400, f"국내 {kr}, 미국 {us}"
    finally:
        conn.close()


def test_startup_falls_back_to_snapshot():
    def boom():
        raise ValueError("Failed to load data from http://data.krx.co.kr/...")

    conn = database.get_connection()
    conn.execute("DELETE FROM stocks")
    conn.commit()
    conn.close()

    main.load_stock_universe = boom
    main.load_us_universe = boom
    main.STARTUP_RETRY_DELAY = 0
    # 폴백 후 자동 사전 계산이 실제로 500종목 시세를 받으러 가지 않게 막는다
    main.recommender.precompute_combos = lambda *a, **k: 0

    main._load_universe_safely()  # 동기 호출

    conn = database.get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) c FROM stocks").fetchone()["c"]
    finally:
        conn.close()
    assert n > 3000, f"폴백 후에도 DB가 비었다: {n}"


def test_stock_list_pagination():
    """목록 페이지가 전 종목을 빠짐없이 덮는지."""
    from fastapi import HTTPException

    data_loader.load_snapshot()
    conn = database.get_connection()
    total = conn.execute("SELECT COUNT(*) c FROM stocks").fetchone()["c"]
    conn.close()

    expected_pages = -(-total // main.STOCKS_PER_PAGE)  # 올림 나눗셈

    first = main.stocks_page(1).body.decode()
    assert f"전체 {expected_pages}페이지" in first, "페이지 수 표기가 틀렸다"
    assert first.count('href="/stock/') >= main.STOCKS_PER_PAGE, "종목 링크가 부족하다"
    assert 'href="/stocks?page=2"' in first, "다음 페이지 링크가 없다"

    last = main.stocks_page(expected_pages).body.decode()
    assert 'href="/stock/' in last, "마지막 페이지가 비었다"

    try:
        main.stocks_page(expected_pages + 1)
        raise AssertionError("범위를 넘은 페이지가 404를 내지 않았다")
    except HTTPException as e:
        assert e.status_code == 404


if __name__ == "__main__":
    database.init_db()
    test_snapshot_file_is_sane()
    test_startup_falls_back_to_snapshot()
    test_stock_list_pagination()
    print("OK")
