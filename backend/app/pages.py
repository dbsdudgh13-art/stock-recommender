"""검색엔진이 읽을 수 있도록 블로그를 서버에서 HTML로 렌더한다.

기존 blog.html / blog-post.html은 JS로 내용을 채워서 크롤러에게는 빈 페이지로 보였다.
여기서는 제목·본문·메타태그를 서버가 직접 HTML에 넣어 반환한다.
"""
import html
import os
from datetime import datetime

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
