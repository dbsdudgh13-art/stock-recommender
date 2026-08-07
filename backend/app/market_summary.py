"""오늘의 시황 글을 서버가 직접 생성한다 (규칙 기반, LLM 미사용).

KRX 스냅샷 + 업종 정보를 받아 시장 전반·업종별 흐름·거래대금까지 요약한다.
Claude 앱/컴퓨터 없이 Render 서버에서 외부 크론 호출만으로 매일 자동 게시 가능.

휴장일(주말·공휴일)에는 생성하지 않는다 — 직전 거래일 데이터를 오늘 시황으로
올리면 같은 내용이 중복 게시되기 때문.
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


class MarketClosed(Exception):
    """오늘 장이 열리지 않아 시황을 생성하지 않음."""


def _kst_today():
    return datetime.utcnow() + timedelta(hours=9)


def _pick(options: list[str], seed_key: str) -> str:
    """날짜별로 안정적이지만 매일 달라지는 문장 선택 (같은 날 재생성 시 동일).

    random.Random(str)은 짧은 문자열에서 분포가 치우쳐, 날짜 숫자 합을 함께 섞는다.
    """
    digits = sum(int(c) for c in seed_key if c.isdigit())
    salt = sum(ord(c) for c in seed_key if not c.isdigit())
    return options[(digits + salt) % len(options)]


def is_trading_day(today: str | None = None) -> bool:
    """오늘 KRX가 열렸는지 확인. 대표 종목의 최신 거래일이 오늘이면 개장일."""
    today = today or _kst_today().strftime("%Y-%m-%d")
    start = (_kst_today() - timedelta(days=10)).strftime("%Y-%m-%d")
    df = fdr.DataReader("005930", start)
    if df.empty:
        return False
    return df.index[-1].strftime("%Y-%m-%d") == today


def _pct(x: float) -> str:
    return f"{x:+.2f}%"


def _eok(amount: float) -> str:
    """원 단위 거래대금을 억/조 단위 문자열로."""
    if amount >= 1_0000_0000_0000:
        return f"{amount / 1_0000_0000_0000:.1f}조원"
    return f"{amount / 1_0000_0000:.0f}억원"


def _market_breadth(df: pd.DataFrame, label: str, seed: str) -> str:
    """상승/하락/보합 종목 수 + 평균 등락률."""
    if df.empty:
        return ""
    up = int((df["ChagesRatio"] > 0).sum())
    down = int((df["ChagesRatio"] < 0).sum())
    flat = int((df["ChagesRatio"] == 0).sum())
    avg = float(df["ChagesRatio"].mean())
    tone = "상승 우위" if up > down else "하락 우위" if down > up else "혼조"
    josa = "은" if (ord(label[-1]) - ord("가")) % 28 else "는"

    templates = [
        f"{label}{josa} 상승 {up}종목, 하락 {down}종목, 보합 {flat}종목으로 {tone} 흐름이었습니다. "
        f"전체 평균 등락률은 {_pct(avg)}입니다.",
        f"{label} 상장 종목 가운데 {up}개가 올랐고 {down}개가 내렸습니다(보합 {flat}개). "
        f"평균 등락률 {_pct(avg)}로 {tone}였습니다.",
        f"{label} 시장은 평균 {_pct(avg)}의 등락률을 기록했습니다. "
        f"상승 {up}종목·하락 {down}종목·보합 {flat}종목으로 {tone}를 보였습니다.",
    ]
    return _pick(templates, seed + label)


def _industry_lines(df: pd.DataFrame, seed: str) -> list[str]:
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

    strong = [
        f"업종별로는 {fmt(top)} 업종이 상대적으로 강했습니다.",
        f"평균 등락률이 높았던 업종은 {fmt(top)} 순입니다.",
        f"업종 단위로 보면 {fmt(top)}이 상위권을 차지했습니다.",
    ]
    weak = [
        f"반면 {fmt(bottom)} 업종은 약세를 보였습니다.",
        f"하위권에는 {fmt(bottom)} 업종이 자리했습니다.",
        f"이와 달리 {fmt(bottom)} 업종은 평균적으로 내렸습니다.",
    ]
    return [_pick(strong, seed + "s"), _pick(weak, seed + "w")]


def _index_drivers(df: pd.DataFrame, label: str) -> list[str]:
    """지수를 움직인 원인 분석.

    단순평균과 시총가중 등락률을 비교하면 '지수는 내렸는데 오른 종목이 더 많은' 식의
    괴리를 잡아낼 수 있고, 종목별 기여도(시총비중 x 등락률)로 주도주를 특정할 수 있다.
    """
    if df.empty or df["Marcap"].sum() == 0:
        return []

    total_cap = df["Marcap"].sum()
    weighted = float((df["ChagesRatio"] * df["Marcap"]).sum() / total_cap)
    simple = float(df["ChagesRatio"].mean())

    d = df.copy()
    d["contrib"] = d["ChagesRatio"] * d["Marcap"] / total_cap
    drivers = d.reindex(d["contrib"].abs().sort_values(ascending=False).index).head(3)
    driver_txt = ", ".join(
        f"{r.Name}({r.contrib:+.2f}%p)" for r in drivers.itertuples()
    )

    lines = [
        f"{label} 지수 기여도를 보면 시가총액 가중 등락률은 {_pct(weighted)}, "
        f"종목 단순평균은 {_pct(simple)}입니다. "
        f"지수에 가장 큰 영향을 준 종목은 {driver_txt} 순입니다."
    ]

    # 괴리 해석: 지수와 체감이 다른 날 설명
    gap = weighted - simple
    if abs(gap) >= 0.4:
        if gap < 0:
            lines.append(
                f"오른 종목 수에 비해 지수가 부진했던 이유는 시가총액 비중이 큰 소수 종목이 하락했기 때문입니다. "
                f"대형주 약세가 지수를 {abs(gap):.2f}%p가량 끌어내린 셈으로, "
                f"이런 날은 지수만 보면 시장 체감과 다르게 느껴질 수 있습니다."
            )
        else:
            lines.append(
                f"반대로 지수는 종목 평균보다 {gap:.2f}%p 높았습니다. "
                f"대형주 몇 종목이 지수를 끌어올린 형태로, 지수 상승폭만큼 개별 종목이 오르지는 않았다는 의미입니다."
            )
    return lines


def _size_and_breadth(df: pd.DataFrame) -> list[str]:
    """대형주 vs 소형주 온도차, 급등락 종목 수, 거래대금 쏠림."""
    lines = []

    big = df.nlargest(100, "Marcap")["ChagesRatio"].mean()
    small = df.nsmallest(1000, "Marcap")["ChagesRatio"].mean()
    if pd.notna(big) and pd.notna(small):
        diff = big - small
        if abs(diff) >= 0.5:
            side = "대형주" if diff > 0 else "중소형주"
            lines.append(
                f"시가총액 규모별로는 상위 100개 종목이 평균 {_pct(big)}, 하위 1,000개 종목이 평균 {_pct(small)}로 "
                f"{side} 쪽에 매수세가 더 몰렸습니다. 규모별 온도차가 {abs(diff):.2f}%p 벌어진 하루였습니다."
            )
        else:
            lines.append(
                f"시가총액 규모별로는 상위 100개 종목 평균 {_pct(big)}, 하위 1,000개 종목 평균 {_pct(small)}로 "
                f"대형주와 중소형주가 비슷한 흐름을 보였습니다."
            )

    surge = int((df["ChagesRatio"] >= 10).sum())
    plunge = int((df["ChagesRatio"] <= -10).sum())
    if surge or plunge:
        if surge > plunge * 2:
            tone = "개별 재료에 따른 급등 종목이 두드러진 장세였습니다"
        elif plunge > surge * 2:
            tone = "급락 종목이 더 많아 투자 심리가 위축된 모습이었습니다"
        else:
            tone = "급등과 급락이 비슷하게 나타나 종목별 편차가 큰 장세였습니다"
        lines.append(f"10% 이상 급등한 종목은 {surge}개, 10% 이상 급락한 종목은 {plunge}개로 {tone}.")

    if "Amount" in df.columns:
        amt = df.dropna(subset=["Amount"])
        total = amt["Amount"].sum()
        if total > 0:
            top10 = amt.nlargest(10, "Amount")["Amount"].sum() / total * 100
            if top10 >= 40:
                lines.append(
                    f"거래대금은 상위 10개 종목이 전체의 {top10:.0f}%를 차지해 특정 종목으로 자금이 크게 쏠렸습니다. "
                    f"소수 주도주 중심의 장세였다는 뜻입니다."
                )
            else:
                lines.append(
                    f"거래대금 상위 10개 종목의 비중은 전체의 {top10:.0f}% 수준으로, "
                    f"자금이 비교적 여러 종목에 분산됐습니다."
                )
    return lines


def _industry_concentration(df: pd.DataFrame) -> list[str]:
    """상승이 특정 업종에 몰렸는지, 전 업종에 퍼졌는지."""
    if "Industry" not in df.columns:
        return []
    grp = df.dropna(subset=["Industry"]).groupby("Industry")["ChagesRatio"].agg(["mean", "count"])
    grp = grp[grp["count"] >= INDUSTRY_MIN]
    if grp.empty:
        return []

    up_ratio = float((grp["mean"] > 0).mean()) * 100
    if up_ratio >= 70:
        msg = (
            f"집계 대상 {len(grp)}개 업종 중 {up_ratio:.0f}%가 평균 상승해 "
            f"특정 업종에 국한되지 않고 시장 전반에 매수세가 유입된 하루였습니다."
        )
    elif up_ratio <= 30:
        msg = (
            f"집계 대상 {len(grp)}개 업종 중 상승 업종 비율이 {up_ratio:.0f}%에 그쳐 "
            f"업종 전반에 걸쳐 매도 우위가 나타났습니다."
        )
    else:
        msg = (
            f"집계 대상 {len(grp)}개 업종 중 {up_ratio:.0f}%만 평균 상승해 "
            f"업종별로 방향이 엇갈린 차별화 장세였습니다."
        )
    return [msg]


def generate() -> tuple[str, str]:
    """(제목, 본문) 반환. 휴장일이면 MarketClosed 예외."""
    d = _kst_today()
    date_str = d.strftime("%Y-%m-%d")
    if not is_trading_day(date_str):
        raise MarketClosed(f"{date_str}은 휴장일입니다.")

    seed = date_str  # 같은 날은 같은 문장, 날마다 다른 문장
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

    intros = [
        f"{d.year}년 {d.month}월 {d.day}일 국내 증시의 종목별 등락을 과거 데이터 기준으로 정리한 요약입니다. "
        f"집계 대상은 코스피·코스닥 상장 종목 {len(listing):,}개입니다.",
        f"{d.month}월 {d.day}일 장 마감 기준으로 코스피·코스닥 {len(listing):,}개 종목의 등락을 집계했습니다.",
        f"오늘({d.month}월 {d.day}일) 국내 증시 마감 데이터를 종목·업종 단위로 정리했습니다. "
        f"집계 대상은 상장 종목 {len(listing):,}개입니다.",
    ]
    parts = [_pick(intros, seed + "i")]

    # 1) 시장 전반
    breadth = [_market_breadth(kospi, "코스피", seed), _market_breadth(kosdaq, "코스닥", seed)]
    parts.extend([b for b in breadth if b])

    # 1-1) 지수를 움직인 원인 (기여도 분석)
    parts.extend(_index_drivers(kospi, "코스피"))

    # 2) 대형주 강세/약세
    ups = top[top["ChagesRatio"] > 0].sort_values("ChagesRatio", ascending=False).head(SHOW)
    downs = top[top["ChagesRatio"] < 0].sort_values("ChagesRatio").head(SHOW)

    def fmt_stocks(rows):
        return ", ".join(f"{r.Name}({_pct(r.ChagesRatio)})" for r in rows.itertuples())

    if not ups.empty:
        opts = [
            f"시가총액 상위 {TOP_N}개 종목 중 상승 종목은 {fmt_stocks(ups)} 등입니다.",
            f"대형주 가운데 오른 종목으로는 {fmt_stocks(ups)}이 있습니다.",
            f"시총 상위권에서는 {fmt_stocks(ups)} 등이 상승 마감했습니다.",
        ]
        parts.append(_pick(opts, seed + "u"))
    if not downs.empty:
        opts = [
            f"같은 그룹에서 하락 마감한 종목은 {fmt_stocks(downs)} 등입니다.",
            f"반대로 {fmt_stocks(downs)} 등은 내렸습니다.",
            f"시총 상위권 중 약세를 보인 종목은 {fmt_stocks(downs)} 등입니다.",
        ]
        parts.append(_pick(opts, seed + "d"))
    if ups.empty and downs.empty:
        parts.append(f"시가총액 상위 {TOP_N}개 종목은 등락이 크지 않은 보합권 흐름이었습니다.")

    # 3) 업종별 흐름 + 상승 확산 정도
    parts.extend(_industry_lines(listing, seed))
    parts.extend(_industry_concentration(listing))

    # 4) 거래대금 상위
    if "Amount" in listing.columns:
        amt = listing.dropna(subset=["Amount"]).sort_values("Amount", ascending=False).head(AMOUNT_SHOW)
        if not amt.empty:
            joined = ", ".join(
                f"{r.Name}({_eok(r.Amount)}, {_pct(r.ChagesRatio)})" for r in amt.itertuples()
            )
            opts = [
                f"거래대금 상위 종목은 {joined} 순이었습니다.",
                f"자금이 가장 많이 몰린 종목은 {joined} 순입니다.",
                f"거래대금 기준으로는 {joined}이 상위를 기록했습니다.",
            ]
            parts.append(_pick(opts, seed + "a"))

    # 5) 변동성 큰 종목 (시총 하위 잡주 제외 위해 상위 300개 내에서)
    mid = listing.sort_values("Marcap", ascending=False).head(300)
    if not mid.empty:
        vol = mid.reindex(mid["ChagesRatio"].abs().sort_values(ascending=False).index).head(3)
        joined = ", ".join(f"{r.Name}({_pct(r.ChagesRatio)})" for r in vol.itertuples())
        opts = [
            f"시가총액 상위 300개 종목 중 등락폭이 컸던 종목은 {joined}입니다.",
            f"주요 종목 가운데 변동폭이 두드러진 곳은 {joined}입니다.",
            f"시총 상위 300개 안에서 가장 크게 움직인 종목은 {joined}입니다.",
        ]
        parts.append(_pick(opts, seed + "v"))

    # 6) 시장 성격 분석 (규모별 온도차·급등락·자금 쏠림)
    parts.extend(_size_and_breadth(listing))

    parts.append(
        "위 수치는 해당 일자의 종가 기준 집계이며, 종목 간 동조 통계는 스톡메이트 검색 기능에서 확인할 수 있습니다."
    )
    parts.append(DISCLAIMER)

    return title, "\n\n".join(parts)
