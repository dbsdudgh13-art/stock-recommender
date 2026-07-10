"""업종 매칭 + 상관계수 기반 규칙 기반 추천 로직 (LLM 미사용)."""
import pandas as pd

from .data_loader import get_price_history
from .database import get_connection

SIMILAR_LIMIT = 3
COMBO_CANDIDATE_POOL = 10
COMBO_RESULT_LIMIT = 2
MOMENTUM_SHORT_DAYS = 20
MOMENTUM_LONG_DAYS = 60
TREND_FLAT_THRESHOLD = 2.0  # % 등락률이 이 범위 안이면 횡보로 판단


def get_stock(code: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM stocks WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_similar(code: str, limit: int = SIMILAR_LIMIT):
    stock = get_stock(code)
    if not stock:
        return None, []
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM stocks
            WHERE industry = ? AND code != ?
            ORDER BY market_cap DESC
            LIMIT ?
            """,
            (stock["industry"], code, limit),
        ).fetchall()
        return stock, [dict(r) for r in rows]
    finally:
        conn.close()


def _daily_returns(code: str) -> pd.Series:
    prices = get_price_history(code)
    if prices.empty:
        return pd.Series(dtype=float)
    return prices.pct_change().dropna()


def find_combo_candidates(code: str):
    """같은 업종 내에서 상관계수가 높아(주가가 함께 오르는 수혜 관계) 종목을 찾는다."""
    stock, peers = find_similar(code, limit=COMBO_CANDIDATE_POOL)
    if not stock:
        return None, []

    target_returns = _daily_returns(code)
    if target_returns.empty:
        return stock, []

    results = []
    for peer in peers:
        peer_returns = _daily_returns(peer["code"])
        if peer_returns.empty:
            continue
        joined = pd.concat([target_returns, peer_returns], axis=1, join="inner")
        joined.columns = ["target", "peer"]
        if len(joined) < 20:
            continue
        corr = joined["target"].corr(joined["peer"])
        if corr is None or pd.isna(corr):
            continue
        results.append({**peer, "correlation": round(float(corr), 3)})

    results = [r for r in results if r["correlation"] > 0]
    results.sort(key=lambda r: r["correlation"], reverse=True)
    return stock, results[:COMBO_RESULT_LIMIT]


def industry_direction(industry: str, sample_codes: list[str]):
    """업종 내 대표 종목들의 최근 등락률로 방향성 텍스트를 규칙 기반 생성."""
    short_changes = []
    long_changes = []
    for code in sample_codes:
        prices = get_price_history(code)
        if len(prices) < MOMENTUM_LONG_DAYS + 1:
            continue
        short_changes.append((prices.iloc[-1] / prices.iloc[-MOMENTUM_SHORT_DAYS] - 1) * 100)
        long_changes.append((prices.iloc[-1] / prices.iloc[-MOMENTUM_LONG_DAYS] - 1) * 100)

    if not short_changes:
        return {
            "industry": industry,
            "summary": f"'{industry}' 업종의 최근 가격 데이터가 부족해 방향성을 산출할 수 없습니다.",
            "short_term_change_pct": None,
            "long_term_change_pct": None,
            "disclaimer": DISCLAIMER,
        }

    avg_short = sum(short_changes) / len(short_changes)
    avg_long = sum(long_changes) / len(long_changes)

    def trend_label(change: float) -> str:
        if change > TREND_FLAT_THRESHOLD:
            return "상승"
        if change < -TREND_FLAT_THRESHOLD:
            return "하락"
        return "횡보"

    short_label = trend_label(avg_short)
    long_label = trend_label(avg_long)

    summary = (
        f"'{industry}' 업종 대표 종목 {len(short_changes)}개 평균 기준, "
        f"최근 {MOMENTUM_SHORT_DAYS}거래일 등락률은 {avg_short:+.1f}%로 {short_label} 흐름, "
        f"최근 {MOMENTUM_LONG_DAYS}거래일 등락률은 {avg_long:+.1f}%로 {long_label} 흐름을 보이고 있습니다."
    )

    return {
        "industry": industry,
        "summary": summary,
        "short_term_change_pct": round(avg_short, 2),
        "long_term_change_pct": round(avg_long, 2),
        "disclaimer": DISCLAIMER,
    }


DISCLAIMER = (
    "본 정보는 과거 가격 데이터에 기반한 규칙 기반 통계 정보 제공이며, 투자 자문이나 매수/매도 추천이 아닙니다. "
    "투자 판단과 책임은 본인에게 있습니다."
)
