"""토스페이(토스 간편결제 직접 계약, pay.toss.im) 연동.

가입비·연회비 없는 토스페이 직접 계약용 API(v2) 연동이다. 결제 수단은 '토스 앱 결제' 단일.
TOSSPAY_API_KEY 환경변수에 상점 API 키(가입 승인 후 토스페이 상점 관리에서 발급)를 설정하면
결제가 활성화되고, 미설정 상태에서는 결제 버튼이 '준비 중' 안내만 표시한다.
테스트 키와 실거래 키가 구분되므로 운영 반영 시 실거래 키인지 확인할 것.
"""
import os
import uuid
from datetime import datetime

import requests

from .database import get_connection

TOSSPAY_API_URL = "https://pay.toss.im/api/v2"
TOSSPAY_API_KEY = os.environ.get("TOSSPAY_API_KEY", "").strip()
COMBO_PRICE_KRW = int(os.environ.get("COMBO_PRICE_KRW", "1000"))
CONFIGURED = bool(TOSSPAY_API_KEY)


def _save_session(order_no: str, code: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO checkout_sessions (session_id, code, status, is_mock, created_at) VALUES (?, ?, 'pending', 0, ?)",
            (order_no, code, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def create_checkout_session(code: str, stock_name: str, base_url: str) -> dict:
    if not CONFIGURED:
        return {"configured": False}

    order_no = f"order_{uuid.uuid4().hex}"
    res = requests.post(
        f"{TOSSPAY_API_URL}/payments",
        json={
            "orderNo": order_no,
            "amount": COMBO_PRICE_KRW,
            "amountTaxFree": 0,
            "productDesc": f"{stock_name} 수혜주·방향성 분석",
            "apiKey": TOSSPAY_API_KEY,
            "autoExecute": False,
            "retUrl": f"{base_url}/api/pay/return?code={code}&order_no={order_no}",
            "retCancelUrl": f"{base_url}/static/index.html",
        },
        timeout=10,
    )
    data = res.json()
    if res.status_code != 200 or data.get("code") != 0:
        return {"configured": True, "error": data.get("msg") or "결제 생성에 실패했습니다."}

    _save_session(order_no, code)
    return {"configured": True, "checkout_url": data["checkoutPage"], "order_no": order_no}


def _get_status(order_no: str) -> dict:
    res = requests.post(
        f"{TOSSPAY_API_URL}/status",
        json={"apiKey": TOSSPAY_API_KEY, "orderNo": order_no},
        timeout=10,
    )
    return res.json()


def _execute(pay_token: str) -> dict:
    res = requests.post(
        f"{TOSSPAY_API_URL}/execute",
        json={"apiKey": TOSSPAY_API_KEY, "payToken": pay_token},
        timeout=10,
    )
    return res.json()


def _mark_paid(order_no: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE checkout_sessions SET status = 'paid' WHERE session_id = ?", (order_no,)
        )
        conn.commit()
    finally:
        conn.close()


def confirm_return(order_no: str, pay_token: str | None = None) -> bool:
    """토스페이 인증 완료 후 retUrl로 돌아왔을 때 승인·검증을 마무리한다."""
    if not CONFIGURED:
        return False

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ?", (order_no,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    if row["status"] == "paid":
        return True

    status = _get_status(order_no)
    pay_status = status.get("payStatus")

    if pay_status == "PAY_APPROVED":
        token = pay_token or status.get("payToken")
        if not token:
            return False
        _execute(token)
        status = _get_status(order_no)
        pay_status = status.get("payStatus")

    if pay_status == "PAY_COMPLETE":
        _mark_paid(order_no)
        return True
    return False


def is_session_paid(session_id: str, code: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ? AND code = ?", (session_id, code)
        ).fetchone()
        return bool(row and row["status"] == "paid")
    finally:
        conn.close()
