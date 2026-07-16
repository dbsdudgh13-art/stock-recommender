"""오늘의 시황 글을 서버가 직접 생성한다 (규칙 기반, LLM 미사용).

KRX 스냅샷을 한 번 받아 시총 상위 종목의 등락을 요약. Claude 앱/컴퓨터 없이
Render 서버에서 외부 크론 호출만으로 매일 자동 게시 가능.
"""
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

TOP_N = 20   # 시총 상위 몇 개를 대상으로
SHOW = 4     # 강세/약세 각각 몇 개 보여줄지
DISCLAIMER = "본 정보는 투자자문이 아니며 과거 데이터를 요약한 참고 정보입니다."


def _kst_today():
    return datetime.utcnow() + timedelta(hours=9)


def generate() -> tuple[str, str]:
    """(제목, 본문) 반환."""
    d = _kst_today()
    title = f"{d.year}년 {d.month}월 {d.day}일 시황 요약"

    df = fdr.StockListing("KRX")[["Name", "ChagesRatio", "Marcap"]].dropna()
    top = df.sort_values("Marcap", ascending=False).head(TOP_N)

    ups = top[top["ChagesRatio"] > 0].sort_values("ChagesRatio", ascending=False).head(SHOW)
    downs = top[top["ChagesRatio"] < 0].sort_values("ChagesRatio").head(SHOW)

    def fmt(rows):
        return ", ".join(f"{r.Name}({r.ChagesRatio:+.1f}%)" for r in rows.itertuples())

    parts = [f"오늘 국내 증시 시가총액 상위 {TOP_N}개 종목 흐름입니다."]
    if not ups.empty:
        parts.append(f"강세: {fmt(ups)}.")
    if not downs.empty:
        parts.append(f"약세: {fmt(downs)}.")
    if ups.empty and downs.empty:
        parts.append("대형주 등락이 크지 않은 보합권 흐름이었습니다.")
    parts.append(DISCLAIMER)

    return title, "\n\n".join(parts)
