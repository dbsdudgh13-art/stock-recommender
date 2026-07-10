"""업종 매칭 + 상관계수 기반 규칙 기반 추천 로직 (LLM 미사용)."""
import pandas as pd

from .data_loader import get_price_history
from .database import get_connection

SIMILAR_LIMIT = 3
COMBO_CANDIDATE_POOL = 15
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


def _subject_particle(word: str) -> str:
    """받침 유무에 따라 이/가 조사를 고른다 (한글이 아니면 '이(가)')."""
    if not word:
        return "이(가)"
    last = word[-1]
    if "가" <= last <= "힣":
        return "이" if (ord(last) - ord("가")) % 28 else "가"
    return "이(가)"


def _analyze_pair(target_name: str, joined: pd.DataFrame) -> dict | None:
    """타깃이 오른 날 기준으로 동반 상승 정도를 다각도로 측정한다.

    - correlation: 일별 수익률 피어슨 상관계수 (전체 동조성)
    - hit_rate: 타깃 상승일 중 피어 종목도 함께 오른 날의 비율 (동반 상승 확률)
    - upside_capture: 타깃 상승일의 피어 평균 수익률 / 타깃 평균 수익률 (상승 민감도)
    - score: 위 지표를 합성한 0~100 수혜 점수
    """
    corr = joined["target"].corr(joined["peer"])
    if corr is None or pd.isna(corr) or corr <= 0:
        return None

    up_days = joined[joined["target"] > 0]
    if len(up_days) < 10:
        return None

    hit_rate = float((up_days["peer"] > 0).mean())
    target_up_avg = float(up_days["target"].mean())
    peer_on_up_avg = float(up_days["peer"].mean())
    upside_capture = peer_on_up_avg / target_up_avg if target_up_avg > 0 else 0.0

    # 동반 상승 확률을 가장 무겁게, 동조성과 민감도를 보조 지표로 합성
    score = (
        hit_rate * 55
        + min(max(corr, 0), 1) * 30
        + min(max(upside_capture, 0), 1.5) / 1.5 * 15
    )

    reason = (
        f"{target_name}{_subject_particle(target_name)} 오른 날의 {hit_rate * 100:.0f}%에서 함께 상승했고, "
        f"그런 날 평균적으로 {target_name} 상승분의 {upside_capture * 100:.0f}% 수준으로 올랐습니다."
    )

    return {
        "correlation": round(float(corr), 3),
        "hit_rate": round(hit_rate, 3),
        "upside_capture": round(upside_capture, 2),
        "score": round(score, 1),
        "reason": reason,
    }


def find_combo_candidates(code: str):
    """같은 업종 내에서 타깃 상승일에 함께 오르는 경향(수혜 관계)이 강한 종목을 찾는다."""
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
        metrics = _analyze_pair(stock["name"], joined)
        if metrics is None:
            continue
        results.append({**peer, **metrics})

    results.sort(key=lambda r: r["score"], reverse=True)
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
