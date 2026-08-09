"""동조 분석 랭킹·캐시·조사 처리 검증.

실행: venv/Scripts/python test_recommender.py
"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app import database

database.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from app import recommender  # noqa: E402  (DB 경로를 바꾼 뒤 import)


def test_particles():
    assert recommender.subject_particle("삼성전자") == "가"  # 받침 없음
    assert recommender.subject_particle("잇츠한불") == "이"  # 받침 있음
    assert recommender.with_particle("삼성전자") == "와"
    assert recommender.with_particle("잇츠한불") == "과"
    assert recommender.subject_particle("AAPL") == "이(가)"


def test_ranking():
    """타깃과 똑같이 움직이는 종목이 무관한 종목보다 위로 와야 한다."""
    rng = np.random.default_rng(42)
    days = pd.date_range("2026-01-01", periods=120, freq="D")
    target = pd.Series(rng.normal(0.001, 0.02, 120), index=days)
    returns = {
        "T": target,
        "TWIN": target * 0.9 + rng.normal(0, 0.002, 120),  # 거의 같이 움직임
        "NOISE": pd.Series(rng.normal(0, 0.02, 120), index=days),  # 무관
    }
    stock = {"code": "T", "name": "테스트전자"}
    peers = [{"code": "NOISE", "name": "무관종목"}, {"code": "TWIN", "name": "동조종목"}]

    ranked = recommender._rank_peers(stock, peers, returns)
    assert ranked, "결과가 비었다"
    assert ranked[0]["code"] == "TWIN", [r["code"] for r in ranked]
    top = ranked[0]
    assert top["hit_rate"] > 0.8, top["hit_rate"]
    assert "테스트전자가 오른 날" in top["reason"], top["reason"]


def test_cache_roundtrip():
    database.init_db()
    payload = [{"code": "TWIN", "name": "동조종목", "score": 77.7, "hit_rate": 0.8}]
    recommender._save_ranking("T", payload)
    assert recommender.get_cached_ranking("T") == payload

    conn = database.get_connection()
    stale = (datetime.utcnow() - timedelta(hours=recommender.COMBO_CACHE_STALE_HOURS + 1)).isoformat()
    conn.execute("UPDATE combo_cache SET computed_at = ?", (stale,))
    conn.commit()
    conn.close()
    assert recommender.get_cached_ranking("T") is None, "만료된 캐시를 그대로 썼다"
    assert recommender.get_cached_ranking("없는코드") is None


if __name__ == "__main__":
    database.init_db()
    test_particles()
    test_ranking()
    test_cache_roundtrip()
    print("OK")
