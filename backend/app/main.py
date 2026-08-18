import os
import threading
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .data_loader import load_stock_universe, load_us_universe
from .database import get_connection, init_db
from . import market_summary, pages, posts_store, recommender

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()

app = FastAPI(title="종목 유사/조합 추천 MVP")


def require_admin(x_admin_token: str = Header(default="")) -> None:
    """데이터 갱신/장애감시/콘텐츠 작성용 예약 작업(에이전트)이 호출하는 관리자 엔드포인트 보호.

    ADMIN_TOKEN 환경변수를 설정해야 활성화된다 (미설정 시 관리자 엔드포인트 전체 비활성).
    """
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN 환경변수가 설정되지 않아 관리자 기능이 비활성화되어 있습니다.")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="관리자 토큰이 올바르지 않습니다.")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    posts_store.init()
    load_stock_universe()
    load_us_universe()


# 게시자 ID는 페이지 소스에 그대로 노출되는 공개 값이라 기본값으로 둔다 (환경변수로 덮어쓸 수 있음)
ADSENSE_PUB_ID = os.environ.get("ADSENSE_PUB_ID", "pub-4920759454915079").strip()
SITE_URL = os.environ.get("SITE_URL", "https://stock-recommender-0swa.onrender.com").rstrip("/")


@app.get("/")
def root():
    # 리다이렉트 대신 index.html 직접 반환 → 루트 URL에서 google-site-verification/OG 태그 노출
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/ads.txt", response_class=PlainTextResponse)
def ads_txt():
    if not ADSENSE_PUB_ID:
        raise HTTPException(status_code=404, detail="not configured")
    return f"google.com, {ADSENSE_PUB_ID}, DIRECT, f08c47fec0942fa0\n"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt():
    return f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"


@app.get("/sitemap.xml", response_class=PlainTextResponse)
def sitemap_xml():
    static_paths = ["/", "/blog", "/static/guide.html",
                    "/static/about.html", "/static/privacy.html", "/static/terms.html",
                    "/static/article/comovement-score.html",
                    "/static/article/correlation-pitfalls.html",
                    "/static/article/industry-classification.html",
                    "/static/article/faq.html"]
    urls = "".join(f"<url><loc>{SITE_URL}{p}</loc></url>" for p in static_paths)
    # 시황 글 전부 포함 — 크롤러가 개별 글 URL을 알 수 있어야 색인된다
    for p in posts_store.list_posts(1000):
        urls += (
            f"<url><loc>{SITE_URL}/post/{p['id']}</loc>"
            f"<lastmod>{p['created_at'][:10]}</lastmod></url>"
        )
    # 전 종목 페이지 — 색인 대상이 수천 개로 늘어난다 (SEO 핵심)
    conn = get_connection()
    try:
        codes = conn.execute("SELECT code FROM stocks ORDER BY market_cap IS NULL, market_cap DESC").fetchall()
    finally:
        conn.close()
    urls += "".join(f"<url><loc>{SITE_URL}/stock/{r['code']}</loc></url>" for r in codes)

    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return PlainTextResponse(xml, media_type="application/xml")


@app.get("/static/blog.html")
def blog_legacy():
    return RedirectResponse(url="/blog", status_code=301)


@app.get("/static/blog-post.html")
def blog_post_legacy(id: int | None = None):
    return RedirectResponse(url=f"/post/{id}" if id else "/blog", status_code=301)


@app.get("/blog", response_class=HTMLResponse)
def blog_page():
    """서버 렌더 블로그 목록 (크롤러가 제목·링크를 HTML에서 바로 읽음)."""
    return HTMLResponse(pages.render_blog_list(posts_store.list_posts(100)))


@app.get("/post/{post_id}", response_class=HTMLResponse)
def post_page(post_id: int):
    """서버 렌더 글 상세 (본문이 HTML에 포함되어야 검색 색인됨)."""
    post = posts_store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="존재하지 않는 글입니다.")
    all_posts = posts_store.list_posts(1000)
    ids = [p["id"] for p in all_posts]  # 최신순
    prev_post = next_post = None
    if post_id in ids:
        i = ids.index(post_id)
        if i + 1 < len(ids):  # 더 오래된 글
            prev_post = all_posts[i + 1]
        if i > 0:  # 더 최신 글
            next_post = all_posts[i - 1]
    return HTMLResponse(pages.render_post(post, prev_post, next_post))


@app.get("/stock/{code}", response_class=HTMLResponse)
def stock_page(code: str):
    """서버 렌더 종목 페이지 — 종목명·업종·유사 종목이 HTML에 포함되어야 검색 색인된다.

    동조 분석은 종목당 최대 15개 가격 히스토리를 외부에서 받아와야 해서 여기서 하지 않는다.
    (크롤러가 수천 페이지를 훑을 때 타임아웃) 이 페이지는 DB 조회만 한다.
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM stocks WHERE code = ?", (code,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="존재하지 않는 종목 코드입니다.")
        stock = dict(row)
        industry = stock["industry"]

        peers = [
            dict(r)
            for r in conn.execute(
                "SELECT code, name, market, change_rate, market_cap FROM stocks "
                "WHERE industry = ? AND code != ? ORDER BY market_cap IS NULL, market_cap DESC, name LIMIT 12",
                (industry, code),
            ).fetchall()
        ]
        s = conn.execute(
            "SELECT COUNT(*) AS n, AVG(change_rate) AS avg_chg, "
            "SUM(CASE WHEN change_rate > 0 THEN 1 ELSE 0 END) AS up, "
            "SUM(CASE WHEN change_rate < 0 THEN 1 ELSE 0 END) AS down "
            "FROM stocks WHERE industry = ?",
            (industry,),
        ).fetchone()
        stats = {
            "peer_count": s["n"],
            "avg_change": s["avg_chg"],
            "up_count": s["up"] or 0,
            "down_count": s["down"] or 0,
        }
    finally:
        conn.close()
    # 미리 계산된 것만 쓴다 — 여기서 직접 계산하면 크롤러가 수천 페이지 훑을 때 죽는다
    combo = recommender.get_cached_ranking(code)
    return HTMLResponse(pages.render_stock(stock, peers, stats, combo))


@app.get("/api/industries")
def list_industries():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT industry FROM stocks WHERE industry IS NOT NULL ORDER BY industry"
        ).fetchall()
        return [r["industry"] for r in rows]
    finally:
        conn.close()


@app.get("/api/search")
def search_stocks(
    q: str = Query("", description="종목명 또는 코드"),
    min_price: float | None = Query(None),
    max_price: float | None = Query(None),
    industry: str | None = Query(None),
    limit: int = Query(30, le=100),
):
    conn = get_connection()
    try:
        clauses = []
        params: list = []
        if q:
            clauses.append("(name LIKE ? OR code LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if min_price is not None:
            clauses.append("close_price >= ?")
            params.append(min_price)
        if max_price is not None:
            clauses.append("close_price <= ?")
            params.append(max_price)
        if industry:
            clauses.append("industry = ?")
            params.append(industry)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT code, name, market, industry, close_price, change_rate, market_cap FROM stocks {where} "
            f"ORDER BY market_cap DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/similar/{code}")
def similar_stocks(code: str):
    stock, peers = recommender.find_similar(code)
    if not stock:
        raise HTTPException(status_code=404, detail="존재하지 않는 종목 코드입니다.")
    return {"stock": stock, "similar": peers}


@app.get("/api/combo/{code}")
def combo(code: str):
    stock, candidates = recommender.find_combo_candidates(code)
    if not stock:
        raise HTTPException(status_code=404, detail="존재하지 않는 종목 코드입니다.")

    sample_codes = [stock["code"]] + [c["code"] for c in candidates]
    direction = recommender.industry_direction(stock["industry"], sample_codes[:10])

    return {"stock": stock, "combo": candidates, "direction": direction}


@app.get("/api/posts")
def list_posts(limit: int = Query(20, le=100)):
    return posts_store.list_posts(limit)


@app.get("/api/posts/{post_id}")
def get_post(post_id: int):
    post = posts_store.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="존재하지 않는 글입니다.")
    return post


# ── 아래는 예약 작업(데이터 갱신/장애감시/SEO 콘텐츠 에이전트)이 호출하는 관리자 전용 엔드포인트 ──


_refresh_lock = threading.Lock()


def _refresh_all() -> None:
    # 크론이 17:30·17:50 두 번 호출한다 (재시도용). 앞 작업이 아직 돌면 건너뛴다
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        load_stock_universe(force=True)
        # 동조 분석 사전 계산 — 종목 페이지에 실을 문장이 여기서 만들어지고, 조회 응답도 즉시가 된다
        recommender.precompute_combos()
    finally:
        _refresh_lock.release()


@app.post("/admin/refresh-data", dependencies=[Depends(require_admin)])
def admin_refresh_data(background: BackgroundTasks):
    # 전 종목 재적재 + 사전 계산은 수 분 걸려 백그라운드로 → 외부 크론 타임아웃 방지
    background.add_task(_refresh_all)
    return {"status": "started"}


@app.get("/admin/health", dependencies=[Depends(require_admin)])
def admin_health():
    conn = get_connection()
    try:
        stock_count = conn.execute("SELECT COUNT(*) AS c FROM stocks").fetchone()["c"]
        last_updated = conn.execute("SELECT MAX(updated_at) AS t FROM stocks").fetchone()["t"]
        return {
            "status": "ok",
            "stock_count": stock_count,
            "stocks_last_updated": last_updated,
            "post_count": posts_store.count_posts(),
            "checked_at": datetime.utcnow().isoformat(),
        }
    finally:
        conn.close()


class AdminPostCreate(BaseModel):
    title: str
    body: str


@app.post("/admin/posts", dependencies=[Depends(require_admin)])
def admin_create_post(body: AdminPostCreate):
    return {"id": posts_store.create_post(body.title, body.body)}


@app.post("/admin/generate-post", dependencies=[Depends(require_admin)])
def admin_generate_post():
    """서버가 직접 오늘의 시황을 생성·저장. 외부 크론이 매일 호출 → 컴퓨터 없이 자동 게시."""
    try:
        title, body = market_summary.generate()
    except market_summary.MarketClosed as e:
        return {"skipped": "market closed", "detail": str(e)}
    if posts_store.title_exists(title):  # 같은 날 중복 방지 (테스트/재실행 대비)
        return {"skipped": "already exists", "title": title}
    return {"id": posts_store.create_post(title, body), "title": title}


app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")
