import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .data_loader import load_stock_universe
from .database import get_connection, init_db
from . import payments, recommender

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
# 배포 환경에서는 프록시 뒤라 request.base_url이 http로 잡힐 수 있어 명시 설정을 우선한다
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")

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
    load_stock_universe()


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


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


@app.post("/api/checkout/{code}")
def create_checkout(code: str, request: Request):
    stock = recommender.get_stock(code)
    if not stock:
        raise HTTPException(status_code=404, detail="존재하지 않는 종목 코드입니다.")
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return payments.create_checkout_session(code, stock["name"], base_url)


@app.get("/api/pay/return")
def pay_return(code: str, order_no: str, payToken: str | None = Query(None)):
    """토스페이 인증 완료 후 돌아오는 지점. 승인을 마무리하고 결과 페이지로 보낸다."""
    payments.confirm_return(order_no, payToken)
    return RedirectResponse(
        url=f"/static/result.html?code={code}&session_id={order_no}"
    )


# 판매 상품 확인용 무료 샘플 종목 (이용권 안내 페이지의 '샘플 미리보기'에서 사용)
SAMPLE_CODE = "005930"


@app.get("/api/combo/{code}")
def combo(code: str, session_id: str = Query(...)):
    is_sample = session_id == "sample" and code == SAMPLE_CODE
    if not is_sample and not payments.is_session_paid(session_id, code):
        raise HTTPException(status_code=402, detail="결제가 완료되지 않았습니다.")

    stock, candidates = recommender.find_combo_candidates(code)
    if not stock:
        raise HTTPException(status_code=404, detail="존재하지 않는 종목 코드입니다.")

    sample_codes = [stock["code"]] + [c["code"] for c in candidates]
    direction = recommender.industry_direction(stock["industry"], sample_codes[:10])

    return {"stock": stock, "combo": candidates, "direction": direction}


@app.get("/api/posts")
def list_posts(limit: int = Query(20, le=100)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, created_at FROM posts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/posts/{post_id}")
def get_post(post_id: int):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="존재하지 않는 글입니다.")
        return dict(row)
    finally:
        conn.close()


# ── 아래는 예약 작업(데이터 갱신/장애감시/SEO 콘텐츠 에이전트)이 호출하는 관리자 전용 엔드포인트 ──


@app.post("/admin/refresh-data", dependencies=[Depends(require_admin)])
def admin_refresh_data():
    count = load_stock_universe(force=True)
    return {"status": "ok", "stocks_loaded": count, "refreshed_at": datetime.utcnow().isoformat()}


@app.get("/admin/health", dependencies=[Depends(require_admin)])
def admin_health():
    conn = get_connection()
    try:
        stock_count = conn.execute("SELECT COUNT(*) AS c FROM stocks").fetchone()["c"]
        last_updated = conn.execute("SELECT MAX(updated_at) AS t FROM stocks").fetchone()["t"]
        post_count = conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"]
        return {
            "status": "ok",
            "stock_count": stock_count,
            "stocks_last_updated": last_updated,
            "post_count": post_count,
            "checked_at": datetime.utcnow().isoformat(),
        }
    finally:
        conn.close()


class AdminPostCreate(BaseModel):
    title: str
    body: str


@app.post("/admin/posts", dependencies=[Depends(require_admin)])
def admin_create_post(body: AdminPostCreate):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO posts (title, body, created_at) VALUES (?, ?, ?)",
            (body.title, body.body, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")
