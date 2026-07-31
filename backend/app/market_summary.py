"""오늘의 시황 글을 서버가 직접 생성한다 (규칙 기반, LLM 미사용).

KRX 스냅샷 + 업종 정보를 받아 시장 전반·업종별 흐름·거래대금까지 요약한다.
Claude 앱/컴퓨터 없이 Render 서버에서 외부 크론 호출만으로 매일 자동 게시 가능.
"""
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

TOP_N = 30          # 시총 상위 몇 개를 대형주로 볼지
SHOW = 5            # 강세/약세 각각 몇 개 나열할지
INDUSTRY_MIN = 5    # 업종 집계에 포함할 최소 종목 수
INDUSTRY_SHOW = 3   # 강세/약세 업종 몇 개씩
AMOUNT_SHOW = 5     # 거래대금 상위 몇 개
DISCLAIMER = "본 정보는 투자자문이 아니며 과거 데이터를 요약한 참고 정보입니다. 특정 종목의 매수·매도를 권유하지 않습니다."


def _kst_today():
    return datetime.utcnow() + timedelta(hours=9)


def _pct(x: float) -> str:
    return f"{x:+.2f}%"


def _eok(amount: float) -> str:
    """원 단위 거래대금을 억/조 단위 문자열로."""
    if amount >= 1_0000_0000_0000:
        return f"{amount / 1_0000_0000_0000:.1f}조원"
    return f"{amount / 1_0000_0000:.0f}억원"


def _market_breadth(df: pd.DataFrame, label: str) -> str:
    """상승/하락/보합 종목 수 + 평균 등락률."""
    if df.empty:
        return ""
    up = int((df["ChagesRatio"] > 0).sum())
    down = int((df["ChagesRatio"] < 0).sum())
    flat = int((df["ChagesRatio"] == 0).sum())
    avg = float(df["ChagesRatio"].mean())
    tone = "상승 우위" if up > down else "하락 우위" if down > up else "혼조"
    # 받침 유무에 따라 은/는 (코스피는 / 코스닥은)
    josa = "은" if (ord(label[-1]) - ord("가")) % 28 else "는"
    return (
        f"{label}{josa} 상승 {up}종목, 하락 {down}종목, 보합 {flat}종목으로 {tone} 흐름이었습니다. "
        f"전체 평균 등락률은 {_pct(avg)}입니다."
    )


def _industry_lines(df: pd.DataFrame) -> list[str]:
    """업종별 평균 등락률 상·하위."""
    if "Industry" not in df.columns:
        return []
    grp = df.dropna(subset=["Industry"]).groupby("Industry")["ChagesRatio"]
    stats = grp.agg(["mean", "count"])
    stats = stats[stats["count"] >= INDUSTRY_MIN].sort_values("mean", ascending=False)
    if stats.empty:
        return []

    top = stats.head(INDUSTRY_SHOW)
    bottom = stats.tail(INDUSTRY_SHOW).sort_values("mean")

    def fmt(rows):
        return ", ".join(
            f"{name}({_pct(r['mean'])}, {int(r['count'])}종목)" for name, r in rows.iterrows()
        )

    lines = [
        f"업종별로는 {fmt(top)} 업종이 상대적으로 강했습니다.",
        f"반면 {fmt(bottom)} 업종은 약세를 보였습니다.",
    ]
    return lines


def generate() -> tuple[str, str]:
    """(제목, 본문) 반환."""
    d = _kst_today()
    title = f"{d.year}년 {d.month}월 {d.day}일 국내 증시 시황 요약"

    listing = fdr.StockListing("KRX")[
        ["Code", "Name", "Market", "ChagesRatio", "Amount", "Marcap"]
    ].dropna(subset=["ChagesRatio", "Marcap"])

    # 업종 정보 조인 (실패해도 나머지 요약은 그대로 생성)
    try:
        desc = fdr.StockListing("KRX-DESC")[["Code", "Industry"]]
        listing = listing.merge(desc, on="Code", how="left")
    except Exception:
        pass

    kospi = listing[listing["Market"] == "KOSPI"]
    kosdaq = listing[listing["Market"] == "KOSDAQ"]
    top = listing.sort_values("Marcap", ascending=False).head(TOP_N)

    parts = [
        f"{d.year}년 {d.month}월 {d.day}일 국내 증시의 종목별 등락을 과거 데이터 기준으로 정리한 요약입니다. "
        f"집계 대상은 코스피·코스닥 상장 종목 {len(listing):,}개입니다."
    ]

    # 1) 시장 전반
    breadth = [_market_breadth(kospi, "코스피"), _market_breadth(kosdaq, "코스닥")]
    parts.extend([b for b in breadth if b])

    # 2) 대형주 강세/약세
    ups = top[top["ChagesRatio"] > 0].sort_values("ChagesRatio", ascending=False).head(SHOW)
    downs = top[top["ChagesRatio"] < 0].sort_values("ChagesRatio").head(SHOW)

    def fmt_stocks(rows):
        return ", ".join(f"{r.Name}({_pct(r.ChagesRatio)})" for r in rows.itertuples())

    if not ups.empty:
        parts.append(f"시가총액 상위 {TOP_N}개 종목 중 상승 종목은 {fmt_stocks(ups)} 등입니다.")
    if not downs.empty:
        parts.append(f"같은 그룹에서 하락 마감한 종목은 {fmt_stocks(downs)} 등입니다.")
    if ups.empty and downs.empty:
        parts.append(f"시가총액 상위 {TOP_N}개 종목은 등락이 크지 않은 보합권 흐름이었습니다.")

    # 3) 업종별 흐름
    parts.extend(_industry_lines(listing))

    # 4) 거래대금 상위
    if "Amount" in listing.columns:
        amt = listing.dropna(subset=["Amount"]).sort_values("Amount", ascending=False).head(AMOUNT_SHOW)
        if not amt.empty:
            parts.append(
                "거래대금 상위 종목은 "
                + ", ".join(
                    f"{r.Name}({_eok(r.Amount)}, {_pct(r.ChagesRatio)})" for r in amt.itertuples()
                )
                + " 순이었습니다."
            )

    # 5) 변동성 큰 종목 (시총 하위 잡주 제외 위해 상위 300개 내에서)
    mid = listing.sort_values("Marcap", ascending=False).head(300)
    if not mid.empty:
        vol = mid.reindex(mid["ChagesRatio"].abs().sort_values(ascending=False).index).head(3)
        parts.append(
            "시가총액 상위 300개 종목 중 등락폭이 컸던 종목은 "
            + ", ".join(f"{r.Name}({_pct(r.ChagesRatio)})" for r in vol.itertuples())
            + "입니다."
        )

    parts.append(
        "위 수치는 해당 일자의 종가 기준 집계이며, 종목 간 동조 통계는 스톡메이트 검색 기능에서 확인할 수 있습니다."
    )
    parts.append(DISCLAIMER)

    return title, "\n\n".join(parts)
