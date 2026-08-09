# 스톡메이트 (StockMate)

국내(코스피·코스닥)와 미국(S&P500) 종목을 검색하면 같은 업종 유사 종목과
과거 주가가 함께 오른 종목 통계(동조 분석), 업종 추이를 **무료로** 보여주는 사이트.

- 라이브: https://stock-recommender-0swa.onrender.com
- 상세 인수인계 문서: [HANDOFF.md](HANDOFF.md)
- 배포·수익화 초보자 가이드: [GUIDE.md](GUIDE.md)

## 실행

```bash
cd backend
venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 접속.
최초 실행 시 KRX 전 종목 + S&P500 목록을 자동으로 받아 `backend/data/app.db`에 캐싱한다.

## 주요 기능

- **종목 검색** — 이름·코드 검색, 가격 범위·업종 필터 (미국 종목은 가격 미표시)
- **유사 종목** — 같은 업종 내 시가총액 상위 3개
- **동조 통계** — 동반 상승 확률, 상승 민감도, 상관계수를 합성한 동조 점수(0~100) 상위 2종목
- **업종 추이** — 최근 20/60거래일 등락률 기반 상승·횡보·하락 판정
- **오늘의 시황** — 매일 장 마감 후 자동 생성되는 시장 요약 (`/blog`)

모든 정보는 과거 데이터 기반 통계이며 투자 자문이 아니다.

## 자동화

외부 cron(cron-job.org)이 매일 아래를 호출한다. 사용자 컴퓨터와 무관하게 동작.

- `POST /admin/refresh-data` (17:30 KST) — 종목·시세 갱신
- `POST /admin/generate-post` (18:00 KST) — 시황 글 생성 (휴장일 자동 스킵)

둘 다 헤더 `X-Admin-Token: <ADMIN_TOKEN>` 필요.

## 환경변수

| 이름 | 설명 |
|---|---|
| `DATABASE_URL` | Neon Postgres 연결 문자열. 시황 글 영구 저장용 (없으면 SQLite 폴백) |
| `ADMIN_TOKEN` | 관리자 엔드포인트 인증 토큰 |
| `ADSENSE_PUB_ID` | 애드센스 게시자 ID (`pub-...`). 설정 시 `/ads.txt` 활성화 |
| `SITE_URL` | sitemap·canonical에 사용할 사이트 주소 |

## 데이터 소스

`FinanceDataReader`로 KRX·미국 시장 공개 데이터를 수집한다. 실시간이 아닌 일별 종가 기준.
ETF·리츠·선물은 지원하지 않는다.
