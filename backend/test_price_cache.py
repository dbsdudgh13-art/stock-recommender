"""가격 캐시가 실제로 재다운로드를 막는지 확인.

이전 버그: 거래일(price_history.date)로 신선도를 판단해 주말·새벽에는 항상 stale로 보였고,
조합 분석 한 번에 16개 종목을 매번 다시 받아 10초가 걸렸다.

실행: venv/Scripts/python test_price_cache.py
"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app import database

database.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from app import data_loader  # noqa: E402  (DB 경로를 바꾼 뒤 import)

calls = []


def fake_reader(code, start):
    calls.append(code)
    # 마지막 봉이 금요일인 상황 재현 — 예전 로직이 stale로 오판하던 조건
    days = pd.date_range(end=datetime.utcnow() - timedelta(days=3), periods=30, freq="D")
    return pd.DataFrame({"Close": range(100, 130)}, index=days)


def main():
    database.init_db()
    data_loader.fdr.DataReader = fake_reader

    first = data_loader.get_price_history("005930")
    assert len(first) == 30, f"첫 조회 실패: {len(first)}행"
    assert calls == ["005930"], calls

    second = data_loader.get_price_history("005930")
    assert len(second) == 30, f"캐시 조회 실패: {len(second)}행"
    assert calls == ["005930"], f"캐시가 있는데 다시 받아왔다: {calls}"

    # 받아온 시각을 과거로 돌리면 다시 받아와야 한다
    conn = database.get_connection()
    stale = (datetime.utcnow() - timedelta(hours=data_loader.PRICE_CACHE_STALE_HOURS + 1)).isoformat()
    conn.execute("UPDATE price_fetch_log SET fetched_at = ?", (stale,))
    conn.commit()
    conn.close()

    data_loader.get_price_history("005930")
    assert calls == ["005930", "005930"], f"만료됐는데 다시 받지 않았다: {calls}"

    # 병렬 프리페치 후에는 전부 캐시 히트
    calls.clear()
    data_loader.prefetch_price_histories(["000660", "035420", "051910"])
    assert sorted(calls) == ["000660", "035420", "051910"], calls
    calls.clear()
    for c in ["000660", "035420", "051910"]:
        data_loader.get_price_history(c)
    assert calls == [], f"프리페치 후에도 다시 받아왔다: {calls}"

    print("OK")


if __name__ == "__main__":
    main()
