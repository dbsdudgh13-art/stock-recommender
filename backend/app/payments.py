"""토스페이먼츠 결제 연동.

결제위젯을 쓰면 카드, 토스페이, 카카오페이 등을 사용자가 화면에서 선택할 수 있다.
TOSS_CLIENT_KEY는 토스페이먼츠가 공개 문서에서 제공하는 위젯 미리보기용 데모 키를 기본값으로 사용해
결제위젯 화면은 설정 없이도 바로 보인다. 다만 실제 결제 승인(서버 confirm 호출)은 본인 계정의
테스트 시크릿 키가 있어야 동작하므로, TOSS_SECRET_KEY(그리고 TOSS_CLIENT_KEY)를
토스페이먼츠 개발자센터(https://developers.tosspayments.com)에서 무료로 즉시 발급받아
환경변수로 설정해야 한다. (사업자 등록 없이 이메일 가입만으로 테스트 키 발급 가능)
"""
import base64
import os
import uuid
from datetime import datetime

import requests

from .database import get_connection

# 토스페이먼츠 공식 문서에 공개된 결제위젯 미리보기 전용 데모 클라이언트 키 (렌더링만 가능, 실결제 승인 불가)
_DOCS_DEMO_CLIENT_KEY = "test_gck_docs_Ovk5rk1EwkEbP0W43n07xlzm"

TOSS_CLIENT_KEY = os.environ.get("TOSS_CLIENT_KEY", "").strip() or _DOCS_DEMO_CLIENT_KEY
TOSS_SECRET_KEY = os.environ.get("TOSS_SECRET_KEY", "").strip()
TOSS_CONFIGURED = bool(os.environ.get("TOSS_CLIENT_KEY", "").strip() and TOSS_SECRET_KEY)
COMBO_PRICE_KRW = int(os.environ.get("COMBO_PRICE_KRW", "1000"))

TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


def create_checkout_session(code: str, stock_name: str) -> dict:
    order_id = f"order_{uuid.uuid4().hex}"
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO checkout_sessions (session_id, code, status, is_mock, created_at) VALUES (?, ?, 'pending', 0, ?)",
            (order_id, code, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "order_id": order_id,
        "amount": COMBO_PRICE_KRW,
        "order_name": f"{stock_name} 조합 종목·방향성 분석",
        "client_key": TOSS_CLIENT_KEY,
        "configured": TOSS_CONFIGURED,
    }


def confirm_payment(payment_key: str, order_id: str, amount: int) -> tuple[bool, str]:
    if not TOSS_CONFIGURED:
        return False, (
            "결제 기능이 아직 설정되지 않았습니다. 토스페이먼츠 개발자센터에서 테스트 키를 발급받아 "
            "TOSS_CLIENT_KEY / TOSS_SECRET_KEY 환경변수로 설정한 뒤 서버를 다시 시작해 주세요."
        )

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return False, "존재하지 않는 주문입니다."
        if row["status"] == "paid":
            return True, "이미 결제 완료된 주문입니다."
        if amount != COMBO_PRICE_KRW:
            return False, "결제 금액이 일치하지 않습니다."

        auth = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
        res = requests.post(
            TOSS_CONFIRM_URL,
            json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            timeout=10,
        )
        if res.status_code != 200:
            detail = res.json().get("message", "결제 승인에 실패했습니다.")
            return False, detail

        conn.execute(
            "UPDATE checkout_sessions SET status = 'paid' WHERE session_id = ?", (order_id,)
        )
        conn.commit()
        return True, "결제가 완료되었습니다."
    finally:
        conn.close()


def is_session_paid(session_id: str, code: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM checkout_sessions WHERE session_id = ? AND code = ?", (session_id, code)
        ).fetchone()
        return bool(row and row["status"] == "paid")
    finally:
        conn.close()
