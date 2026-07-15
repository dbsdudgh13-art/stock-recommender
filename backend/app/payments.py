"""카카오페이 온라인 단건결제(open-api.kakaopay.com) 연동.

- 결제 준비(ready) → 사용자를 카카오페이 결제창으로 리다이렉트 → 승인(approve)으로 마무리.
- KAKAOPAY_SECRET_KEY 환경변수가 있어야 결제가 활성화된다. 미설정 시 결제 버튼은
  '준비 중' 안내만 표시한다.
- KAKAOPAY_CID 기본값은 테스트용 CID(TC0ONETIME). 카카오페이 비즈니스 심사 통과 후
  발급받은 실거래 CID로 교체하면 실제 결제가 이뤄진다.
- 테스트 CID로는 실제 출금 없이 결제 흐름 전체를 검증할 수 있다.
"""
import os
import uuid
from datetime import datetime

import requests

from .database import get_connection

KAKAOPAY_API = "https://open-api.kakaopay.com/online/v1/payment"
KAKAOPAY_SECRET_KEY = os.environ.get("KAKAOPAY_SECRET_KEY", "").strip()
KAKAOPAY_CID = os.environ.get("KAKAOPAY_CID", "TC0ONETIME").strip()
COMBO_PRICE_KRW = int(os.environ.get("COMBO_PRICE_KRW", "1000"))
CONFIGURED = bool(KAKAOPAY_SECRET_KEY)

PARTNER_USER_ID = "guest"  # 로그인 없는 서비스라 고정값 사용


def _headers() -> dict:
    return {
        "Authorization": f"SECRET_KEY {KAKAOPAY_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _save_session(order_id: str, code: str, tid: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO checkout_sessions (session_id, code, status, is_mock, tid, created_at) "
            "VALUES (?, ?, 'pending', 0, ?, ?)",
            (order_id, code, tid, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def create_checkout_session(code: str, stock_name: str, base_url: str) -> dict:
    if not CONFIGURED:
        return {"configured": False}

    order_id = f"order_{uuid.uuid4().hex}"
    res = requests.post(
        f"{KAKAOPAY_API}/ready",
        json={
            "cid": KAKAOPAY_CID,
            "partner_order_id": order_id,
            "partner_user_id": PARTNER_USER_ID,
            "item_name": f"{stock_name} 종목 통계 분석 콘텐츠",
            "quantity": 1,
            "total_amount": COMBO_PRICE_KRW,
            "tax_free_amount": 0,
            "approval_url": f"{base_url}/api/pay/kakao/approve?code={code}&order_id={order_id}",
            "cancel_url": f"{base_url}/static/pricing.html?code={code}",
            "fail_url": f"{base_url}/static/pricing.html?code={code}",
        },
        headers=_headers(),
        timeout=10,
    )
    if res.status_code != 200:
        detail = _safe_msg(res)
        return {"configured": True, "error": detail}

    data = res.json()
    _save_session(order_id, code, data["tid"])
    return {"configured": True, "checkout_url": data["next_redirect_pc_url"]}


def approve(order_id: str, pg_token: str) -> bool:
    if not CONFIGURED:
        return False

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ?", (order_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    if row["status"] == "paid":
        return True

    res = requests.post(
        f"{KAKAOPAY_API}/approve",
        json={
            "cid": KAKAOPAY_CID,
            "tid": row["tid"],
            "partner_order_id": order_id,
            "partner_user_id": PARTNER_USER_ID,
            "pg_token": pg_token,
        },
        headers=_headers(),
        timeout=10,
    )
    if res.status_code != 200:
        return False

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE checkout_sessions SET status = 'paid' WHERE session_id = ?", (order_id,)
        )
        conn.commit()
    finally:
        conn.close()
    return True


def is_session_paid(session_id: str, code: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ? AND code = ?", (session_id, code)
        ).fetchone()
        return bool(row and row["status"] == "paid")
    finally:
        conn.close()


def _safe_msg(res) -> str:
    try:
        return res.json().get("message") or res.json().get("msg") or "결제 요청에 실패했습니다."
    except Exception:
        return "결제 요청에 실패했습니다."
