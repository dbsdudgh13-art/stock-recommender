import os
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .data_loader import load_stock_universe
from .database import get_connection, init_db
from . import market_summary, posts_store, recommender

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


ADSENSE_PUB_ID = os.environ.get("ADSENSE_PUB_ID", "").strip()  # 예: pub-1234567890123456
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
    pages = ["/static/index.html", "/static/blog.html", "/static/about.html",
             "/static/privacy.html", "/static/terms.html"]
    urls = "".join(f"<url><loc>{SITE_URL}{p}</loc></url>" for p in pages)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return PlainTextResponse(xml, media_type="application/xml")


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


@app.post("/admin/refresh-data", dependencies=[Depends(require_admin)])
def admin_refresh_data(background: BackgroundTasks):
    # 전 종목 재적재는 수십 초 걸릴 수 있어 백그라운드로 → 외부 크론 타임아웃 방지
    background.add_task(load_stock_universe, force=True)
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
    title, body = market_summary.generate()
    return {"id": posts_store.create_post(title, body), "title": title}


app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")
