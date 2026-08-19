"""시황 생성 재시도 검증.

2026-08-18 시황이 누락됐다. KRX가 응답하지 않아 generate()가 예외를 던졌고,
한 번 실패하면 그날 글이 통째로 사라졌다. 전종목 API는 당일 데이터만 주므로
지나간 날은 복구할 수 없다 — 그래서 그 자리에서 재시도해야 한다.

실행: venv/Scripts/python test_post_retry.py
"""
import tempfile
from pathlib import Path

from app import database

database.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from app import main  # noqa: E402

main.POST_RETRY_DELAY = 0  # 대기 없이


def _reset(created):
    main.posts_store.title_exists = lambda t: False
    main.posts_store.create_post = lambda t, b: (created.append((t, b)), 1)[1]


def test_retries_until_success():
    """앞 두 번 실패해도 세 번째에 게시되어야 한다."""
    created = []
    _reset(created)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise ValueError("Failed to load data from http://data.krx.co.kr/...")
        return ("2026년 8월 19일 국내 증시 시황 요약", "본문")

    main.market_summary.generate = flaky
    main._generate_post_with_retry()

    assert len(attempts) == 3, f"재시도 횟수: {len(attempts)}"
    assert len(created) == 1, "글이 게시되지 않았다"
    assert created[0][0].startswith("2026년 8월 19일"), created[0][0]


def test_market_closed_does_not_retry():
    """휴장일은 재시도 대상이 아니다 — 몇 번 시도해도 결과가 같다."""
    created = []
    _reset(created)
    attempts = []

    def closed():
        attempts.append(1)
        raise main.market_summary.MarketClosed("2026-08-15은 휴장일입니다.")

    main.market_summary.generate = closed
    main._generate_post_with_retry()

    assert len(attempts) == 1, f"휴장일인데 재시도했다: {len(attempts)}"
    assert not created, "휴장일에 글이 게시됐다"


def test_gives_up_after_max_attempts():
    created = []
    _reset(created)
    attempts = []

    def always_fail():
        attempts.append(1)
        raise ValueError("KRX 다운")

    main.market_summary.generate = always_fail
    main._generate_post_with_retry()

    assert len(attempts) == main.POST_MAX_ATTEMPTS, len(attempts)
    assert not created


def test_duplicate_is_skipped():
    created = []
    _reset(created)
    main.posts_store.title_exists = lambda t: True
    main.market_summary.generate = lambda: ("같은 제목", "본문")

    main._generate_post_with_retry()
    assert not created, "중복인데 다시 게시됐다"


if __name__ == "__main__":
    test_retries_until_success()
    test_market_closed_does_not_retry()
    test_gives_up_after_max_attempts()
    test_duplicate_is_skipped()
    print("OK")
