"""시황 글(posts) 영구 저장소.

DATABASE_URL 있으면 Postgres(Neon) 사용 → Render 무료 플랜 재시작에도 글 보존.
없으면 SQLite 폴백(로컬 개발용). posts만 여기서 관리하고, 종목/가격 데이터는
기존 SQLite(database.py) 그대로 — 부팅 시 재적재되므로 휘발 상관없음.

드라이버는 pg8000(순수 파이썬) — 컴파일 불필요, 어느 파이썬 버전에서도 설치됨.
"""
import os
from datetime import datetime
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import pg8000.dbapi

    _u = urlparse(DATABASE_URL)

    def _conn():
        return pg8000.dbapi.connect(
            user=_u.username,
            password=_u.password,
            host=_u.hostname,
            port=_u.port or 5432,
            database=_u.path.lstrip("/"),
            ssl_context=True,  # Neon은 SSL 필수
        )

    _PH = "%s"
    _CREATE = (
        "CREATE TABLE IF NOT EXISTS posts ("
        "id SERIAL PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    _INSERT = "INSERT INTO posts (title, body, created_at) VALUES (%s, %s, %s) RETURNING id"
else:
    from .database import get_connection

    def _conn():
        return get_connection()

    _PH = "?"
    _CREATE = (
        "CREATE TABLE IF NOT EXISTS posts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    _INSERT = "INSERT INTO posts (title, body, created_at) VALUES (?, ?, ?)"


def _rows_to_dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def init() -> None:
    conn = _conn()
    try:
        conn.cursor().execute(_CREATE)
        conn.commit()
    finally:
        conn.close()


def list_posts(limit: int):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id, title, created_at FROM posts ORDER BY id DESC LIMIT {_PH}", (limit,))
        return _rows_to_dicts(cur)
    finally:
        conn.close()


def get_post(post_id: int):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT id, title, body, created_at FROM posts WHERE id = {_PH}", (post_id,))
        rows = _rows_to_dicts(cur)
        return rows[0] if rows else None
    finally:
        conn.close()


def title_exists(title: str) -> bool:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM posts WHERE title = {_PH} LIMIT 1", (title,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def count_posts() -> int:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM posts")
        return cur.fetchone()[0]
    finally:
        conn.close()


def create_post(title: str, body: str) -> int:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(_INSERT, (title, body, datetime.utcnow().isoformat()))
        new_id = cur.fetchone()[0] if USE_PG else cur.lastrowid
        conn.commit()
        return new_id
    finally:
        conn.close()
