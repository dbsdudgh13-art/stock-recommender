"""KRX 적재가 실패해도 서버가 뜨는지 검증.

이전 사고: startup에서 fdr.StockListing이 예외를 던지자 앱이 기동을 포기했고
("Application startup failed. Exiting.") Render 배포가 통째로 실패했다.
외부 사이트 장애가 우리 배포 실패로 번지면 안 된다.

실행: venv/Scripts/python test_startup.py
"""
import tempfile
import time
from pathlib import Path

from app import database

database.DB_PATH = Path(tempfile.mkdtemp()) / "test.db"

from app import main  # noqa: E402


def test_startup_survives_krx_failure():
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("Failed to load data from http://data.krx.co.kr/...")

    main.load_stock_universe = boom
    main.load_us_universe = boom
    main.STARTUP_RETRY_DELAY = 0  # 재시도 대기 없이

    main._startup()  # 예외가 새어 나오면 앱이 기동하지 못한다

    for _ in range(50):  # 백그라운드 스레드가 3회 재시도할 때까지
        if len(calls) >= 3:
            break
        time.sleep(0.02)
    assert len(calls) == 3, f"재시도 3회가 아님: {len(calls)}"


def test_startup_normal_path():
    loaded = []
    main.load_stock_universe = lambda: loaded.append('kr')
    main.load_us_universe = lambda: loaded.append('us')

    main._startup()
    for _ in range(50):
        if len(loaded) == 2:
            break
        time.sleep(0.02)
    assert loaded == ['kr', 'us'], loaded


if __name__ == "__main__":
    test_startup_survives_krx_failure()
    test_startup_normal_path()
    print("OK")
