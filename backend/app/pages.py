"""검색엔진이 읽을 수 있도록 블로그를 서버에서 HTML로 렌더한다.

기존 blog.html / blog-post.html은 JS로 내용을 채워서 크롤러에게는 빈 페이지로 보였다.
여기서는 제목·본문·메타태그를 서버가 직접 HTML에 넣어 반환한다.
"""
import html
import os
from datetime import datetime

from .recommender import subject_particle, with_particle

SITE_URL = os.environ.get("SITE_URL", "https://stock-recommender-0swa.onrender.com").rstrip("/")

_HEAD = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="description" content="{desc}" />
<meta property="og:type" content="{og_type}" />
<meta property="og:title" content="{og_title}" />
<meta property="og:description" content="{desc}" />
<meta property="og:url" content="{url}" />
<link rel="canonical" href="{url}" />
<title>{title}</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css" />
<style>body {{ font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif; }}</style>
</head>
<body class="min-h-screen" style="background: radial-gradient(1200px 500px at 50% -10%, #eef2ff, #f8fafc);">
  <div class="max-w-2xl mx-auto px-4 py-10">
"""

_FOOTER = """
    <footer class="mt-12 pt-6 border-t border-slate-200 text-xs text-slate-400">
      <div class="flex flex-wrap gap-x-4 gap-y-2">
        <a href="/blog" class="hover:underline">오늘의 시황</a>
        <a href="/static/guide.html" class="hover:underline">지표 설명</a>
        <a href="/static/about.html" class="hover:underline">소개 · 문의</a>
        <a href="/static/privacy.html" class="hover:underline">개인정보처리방침</a>
        <a href="/static/terms.html" class="hover:underline">이용약관</a>
      </div>
      <p class="mt-3 leading-relaxed">스톡메이트(StockMate) · 문의 opedband@naver.com</p>
    </footer>
  </div>
</body>
</html>
"""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y년 %m월 %d일")
    except Exception:
        return iso[:10]


def render_blog_list(posts: list[dict]) -> str:
    desc = "코스피·코스닥 시장의 일별 등락, 업종 흐름, 거래대금 쏠림을 데이터로 정리한 시황 기록입니다."
    head = _HEAD.format(
        title="오늘의 시황 | 스톡메이트(StockMate)",
        og_title="오늘의 시황 - 스톡메이트",
        desc=_esc(desc),
        url=f"{SITE_URL}/blog",
        og_type="website",
    )

    if posts:
        items = "".join(
            f"""
      <a href="/post/{p['id']}" class="block bg-white rounded-2xl shadow-sm border border-slate-100 p-5 hover:shadow-md hover:border-indigo-100 transition">
        <h2 class="font-semibold text-slate-800">{_esc(p['title'])}</h2>
        <div class="text-xs text-slate-400 mt-1">{_fmt_date(p['created_at'])}</div>
      </a>"""
            for p in posts
        )
    else:
        items = '<div class="text-sm text-slate-400">아직 등록된 글이 없습니다.</div>'

    body = f"""
    <a href="/" class="text-sm text-indigo-600 hover:underline">← 홈으로 돌아가기</a>
    <h1 class="text-2xl font-extrabold text-slate-900 mt-3 mb-1">📰 오늘의 시황</h1>
    <p class="text-sm text-slate-500 mb-6">{_esc(desc)} 투자자문이 아닙니다.</p>
    <div class="space-y-3">{items}</div>
"""
    return head + body + _FOOTER


def _fmt_cap(cap: float | None) -> str:
    """시가총액(원)을 조/억 단위로."""
    if not cap:
        return "-"
    if cap >= 1_0000_0000_0000:
        return f"{cap / 1_0000_0000_0000:.1f}조원"
    return f"{cap / 1_0000_0000:.0f}억원"


def _fmt_change(rate: float | None) -> str:
    if rate is None:
        return '<span class="text-slate-400">-</span>'
    color = "text-rose-600" if rate > 0 else "text-blue-600" if rate < 0 else "text-slate-500"
    return f'<span class="{color} font-semibold">{rate:+.2f}%</span>'


def render_stock(stock: dict, peers: list[dict], stats: dict, combo: list[dict] | None = None) -> str:
    """종목 상세 — 크롤러가 종목명·업종·유사 종목을 HTML에서 바로 읽는다."""
    name, code = stock["name"], stock["code"]
    industry = stock["industry"] or "기타"
    is_kr = stock["market"] != "S&P500"
    combo = combo or []

    ga, wa = subject_particle(name), with_particle(name)
    if combo:
        top = combo[0]
        desc = (
            f"{name}{ga} 오른 날 함께 오른 종목은 {top['name']}"
            f"(동반 상승 확률 {top['hit_rate'] * 100:.0f}%, 동조 점수 {top['score']})입니다. "
            f"{name}({code}){wa} 같은 업종 '{industry}' 종목 {stats['peer_count']}개의 동조 통계를 무료로 확인하세요."
        )
    else:
        desc = (
            f"{name}({code}){wa} 같은 업종 '{industry}' 종목 {stats['peer_count']}개를 시가총액 순으로 정리했습니다. "
            f"과거 주가가 함께 오른 종목 통계(동조 분석)를 무료로 확인하세요."
        )
    head = _HEAD.format(
        title=f"{_esc(name)}({_esc(code)}) 유사 종목 · 동조 분석 | 스톡메이트(StockMate)",
        og_title=f"{_esc(name)} 유사 종목 · 동조 분석",
        desc=_esc(desc),
        url=f"{SITE_URL}/stock/{_esc(code)}",
        og_type="article",
    )

    price_row = ""
    if is_kr:
        price = f"{stock['close_price']:,.0f}원" if stock["close_price"] else "-"
        price_row = f"""
        <div><dt class="text-xs text-slate-400">종가</dt><dd class="font-semibold text-slate-800">{price}</dd></div>
        <div><dt class="text-xs text-slate-400">등락률</dt><dd>{_fmt_change(stock['change_rate'])}</dd></div>
        <div><dt class="text-xs text-slate-400">시가총액</dt><dd class="font-semibold text-slate-800">{_fmt_cap(stock['market_cap'])}</dd></div>"""

    if peers:
        rows = "".join(
            f"""
        <a href="/stock/{_esc(p['code'])}" class="flex items-center gap-3 py-3 border-b border-slate-100 last:border-0 hover:bg-slate-50 -mx-2 px-2 rounded-lg transition">
          <div class="min-w-0 flex-1">
            <div class="font-semibold text-slate-800 truncate">{_esc(p['name'])}</div>
            <div class="text-xs text-slate-400">{_esc(p['code'])} · {_esc(p['market'])}</div>
          </div>
          <div class="text-right text-sm shrink-0">
            <div>{_fmt_change(p['change_rate'])}</div>
            <div class="text-xs text-slate-400">{_fmt_cap(p['market_cap'])}</div>
          </div>
        </a>"""
            for p in peers
        )
        peer_block = f'<div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 mt-4">{rows}</div>'
    else:
        peer_block = '<div class="text-sm text-slate-400 mt-4">같은 업종으로 분류된 다른 종목이 없습니다.</div>'

    if stats["avg_change"] is not None:
        trend = "상승" if stats["avg_change"] > 0 else "하락" if stats["avg_change"] < 0 else "보합"
        industry_line = (
            f"'{industry}' 업종에는 {stats['peer_count']}개 종목이 있으며, "
            f"직전 거래일 평균 등락률은 {stats['avg_change']:+.2f}%로 {trend} 흐름이었습니다. "
            f"이 중 {stats['up_count']}개가 상승, {stats['down_count']}개가 하락했습니다."
        )
    else:
        industry_line = f"'{industry}' 업종에는 {stats['peer_count']}개 종목이 분류되어 있습니다."

    if combo:
        cards = "".join(
            f"""
        <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 mt-3">
          <div class="flex items-baseline gap-2">
            <a href="/stock/{_esc(c['code'])}" class="font-bold text-slate-800 hover:underline">{_esc(c['name'])}</a>
            <span class="text-xs text-slate-400">{_esc(c['code'])}</span>
            <span class="ml-auto text-xs font-bold text-indigo-600">동조 점수 {c['score']}</span>
          </div>
          <p class="text-sm text-slate-600 mt-2 leading-relaxed">{_esc(c['reason'])}</p>
          <div class="flex gap-4 text-xs text-slate-400 mt-3">
            <span>동반 상승 확률 {c['hit_rate'] * 100:.0f}%</span>
            <span>상관계수 {c['correlation']}</span>
            <span>상승 민감도 {c['upside_capture'] * 100:.0f}%</span>
          </div>
        </div>"""
            for c in combo[:3]
        )
        combo_block = f"""
    <h2 class="text-lg font-bold text-slate-900 mt-8">{_esc(name)}{wa} 함께 오른 종목</h2>
    <p class="text-sm text-slate-500 mt-1">최근 180일(약 6개월) 동안 {_esc(name)}{ga} 상승한 날, 같은 업종에서 함께 오르는 경향이 가장 강했던 종목입니다.</p>
    {cards}
"""
    else:
        combo_block = ""

    body = f"""
    <a href="/" class="text-sm text-indigo-600 hover:underline">← 종목 검색</a>
    <h1 class="text-2xl font-extrabold text-slate-900 mt-3">{_esc(name)} <span class="text-slate-400 text-lg font-bold">{_esc(code)}</span></h1>
    <p class="text-sm text-slate-500 mt-1">{_esc(stock['market'])} · {_esc(industry)}</p>

    <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 mt-4">
      <dl class="grid grid-cols-3 gap-4 text-sm">{price_row or '<div class="col-span-3 text-xs text-slate-400">미국 종목은 시세 데이터를 제공하지 않습니다.</div>'}</dl>
      <a href="/static/result.html?code={_esc(code)}"
         class="block text-center mt-5 bg-indigo-600 text-white text-sm font-semibold rounded-xl py-3 hover:bg-indigo-700 transition">
        {_esc(name)} 동조 종목 분석 보기 →
      </a>
      <p class="text-xs text-slate-400 mt-2 text-center">과거 180일 주가로 계산한 동반 상승 확률·상관계수·상승 민감도</p>
    </div>

    {combo_block}
    <h2 class="text-lg font-bold text-slate-900 mt-8">{_esc(name)}{wa} 같은 업종 종목</h2>
    <p class="text-sm text-slate-500 mt-1">{_esc(industry_line)}</p>
    {peer_block}

    <div class="text-xs text-slate-400 bg-slate-100/80 rounded-xl p-3 mt-6 leading-relaxed">
      ⚠️ 본 정보는 과거 가격 데이터에 기반한 규칙 기반 통계 정보 제공이며, 투자 자문이나 매수/매도 추천이 아닙니다.
      <a href="/static/guide.html" class="text-indigo-500 hover:underline">지표 설명 보기</a>
    </div>
"""
    return head + body + _FOOTER


def render_post(post: dict, prev_post: dict | None = None, next_post: dict | None = None) -> str:
    title = post["title"]
    body_text = post["body"]
    # 본문 앞부분을 메타 설명으로 (검색결과 스니펫)
    desc = " ".join(body_text.split())[:150]

    head = _HEAD.format(
        title=f"{_esc(title)} | 스톡메이트(StockMate)",
        og_title=_esc(title),
        desc=_esc(desc),
        url=f"{SITE_URL}/post/{post['id']}",
        og_type="article",
    )

    paragraphs = "".join(
        f'<p class="mb-4">{_esc(para)}</p>'
        for para in body_text.split("\n\n")
        if para.strip()
    )

    nav = []
    if prev_post:
        nav.append(
            f'<a href="/post/{prev_post["id"]}" class="text-indigo-600 hover:underline">← {_esc(prev_post["title"])}</a>'
        )
    if next_post:
        nav.append(
            f'<a href="/post/{next_post["id"]}" class="text-indigo-600 hover:underline">{_esc(next_post["title"])} →</a>'
        )
    nav_html = (
        f'<div class="flex justify-between gap-4 text-xs mt-6">{"".join(f"<span>{n}</span>" for n in nav)}</div>'
        if nav
        else ""
    )

    body = f"""
    <a href="/blog" class="text-sm text-indigo-600 hover:underline">← 오늘의 시황 목록</a>
    <article class="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 mt-4">
      <h1 class="text-xl font-bold text-slate-900">{_esc(title)}</h1>
      <div class="text-xs text-slate-400 mt-1 mb-4">{_fmt_date(post['created_at'])}</div>
      <div class="text-sm text-slate-700 leading-relaxed">{paragraphs}</div>
    </article>
    {nav_html}
    <div class="text-xs text-slate-400 bg-slate-100/80 rounded-xl p-3 mt-4">
      ⚠️ 본 정보는 과거 가격 데이터에 기반한 규칙 기반 통계 정보 제공이며, 투자 자문이나 매수/매도 추천이 아닙니다.
    </div>
"""
    return head + body + _FOOTER
