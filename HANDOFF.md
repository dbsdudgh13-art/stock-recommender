# 인수인계 자료 — 종목 유사/조합 추천 MVP

작성일: 2026-07-10

## 1. 프로젝트 개요

국내(코스피/코스닥) 종목을 검색하면
1. 같은 분야(업종) **유사 종목 3개**를 무료로 보여주고
2. 결제(토스페이먼츠) 후에는 **상관계수가 높은 "함께 오르는 종목(수혜주)" 2개**와
3. 해당 업종의 **방향성(등락률 기반 규칙형 요약)** 을 보여주는 웹앱.

투자자문이 아니라는 면책 문구가 모든 결과에 포함됨. LLM은 사용하지 않고 전부 규칙/통계 기반.

## 2. 현재 상태

기능 전체가 동작하는 MVP 프로토타입 상태. 로컬에서 실행해 브라우저로 검색→유사종목→결제→수혜주/방향성까지 전 과정을 실제로 확인 완료.

**미완료/제한된 부분**은 8번 항목 참고.

## 3. 실행 방법

```bash
cd backend
venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 http://127.0.0.1:8000 접속. 최초 실행 시 KRX 전 종목 목록(약 2,872개)을 자동으로 받아 `backend/data/app.db`(SQLite)에 캐싱함 (몇 초~수십 초 소요).

`.claude/launch.json`에 `preview_start`용 설정이 등록되어 있어 Claude Code의 Browser 프리뷰 도구로도 바로 띄울 수 있음.

## 4. 폴더 구조

```
backend/
  app/
    main.py          # FastAPI 라우터
    database.py       # SQLite 스키마/연결
    data_loader.py     # FinanceDataReader로 KRX 종목·가격 적재/캐싱
    recommender.py     # 유사 종목·수혜주·방향성 로직 (규칙 기반)
    payments.py        # 토스페이먼츠 결제위젯 연동
  static/              # 프론트엔드 (순수 HTML/JS, 빌드 없음)
    index.html          # 검색 + 가격/업종 필터
    app.js              # 카드 렌더링, 검색, 유사종목 패널, 결제 시작
    checkout.html        # 토스 결제위젯 페이지
    toss-success.html     # 결제 승인 콜백 → 서버 confirm 호출
    toss-fail.html         # 결제 실패 페이지
    result.html            # 수혜주 + 방향성 결과 페이지
  requirements.txt
  data/app.db          # SQLite 캐시 (gitignore 대상, 삭제해도 재생성됨)
README.md              # 실행법 + 데이터소스/로직 요약 (사용자 대상 짧은 버전)
```

## 5. 데이터 소스

- **가격/시가총액**: `FinanceDataReader.StockListing('KRX')`
- **업종 분류**: `FinanceDataReader.StockListing('KRX-DESC')` (KSIC 업종, Code 기준 join)
- 둘 다 무료·키 불필요. 한국투자증권 OpenAPI 등은 승인 절차가 있어 의도적으로 배제함.
- 가격 히스토리(180일)는 종목별로 최초 조회 시점에 받아 SQLite `price_history`에 캐싱, 20시간 지나면 재조회.

## 6. 핵심 로직 (recommender.py)

- `SIMILAR_LIMIT = 3` — 무료로 보여주는 같은 업종 유사 종목 개수
- `COMBO_CANDIDATE_POOL = 10` — 수혜주 계산 시 내부적으로 살펴보는 같은 업종 후보 풀
- `COMBO_RESULT_LIMIT = 2` — 유료로 보여주는 수혜주 개수
- **수혜주 로직**: 같은 업종 내 종목들과의 최근 180일 일별 수익률 피어슨 상관계수를 계산 → **양의 상관계수만 남기고 내림차순 정렬** → 상위 2개. (⚠️ 초기 버전은 반대로 "낮은 상관계수(분산 효과)" 기준이었으나, 사용자 요청으로 "같이 오르는 종목" 기준으로 완전히 뒤집었음)
- **방향성 로직**: 업종 대표 종목들의 최근 20/60거래일 평균 등락률로 상승/횡보/하락 판정 (임계값 ±2%)

## 7. 결제 (토스페이먼츠)

- `POST /api/checkout/{code}` → 주문 생성, `TOSS_CLIENT_KEY`와 함께 결제위젯 페이지로 이동
- `checkout.html`에서 토스 결제위젯 렌더링 → 신용카드/토스페이/카카오페이/페이코/네이버페이 모두 선택 가능 (토스 연동 하나로 전부 제공됨)
- 결제 승인 후 `toss-success.html` → `POST /api/toss/confirm` → 토스 서버에 금액·주문번호 검증 → 세션 `paid` 처리 → `result.html`로 이동
- **환경변수 미설정 시**: `TOSS_CLIENT_KEY`는 토스 공식 문서의 위젯 미리보기 전용 데모 키(`test_gck_docs_...`)로 자동 대체되어 화면은 뜨지만, **실제 결제 승인은 불가** (배너로 안내됨)
- **실제 결제가 되게 하려면**: https://developers.tosspayments.com 무료 가입(사업자 등록 불필요) → 개발자센터에서 테스트 키 발급 → 환경변수 설정:
  ```bash
  export TOSS_CLIENT_KEY=test_ck_...
  export TOSS_SECRET_KEY=test_sk_...
  ```
- 가격은 `COMBO_PRICE_KRW` 환경변수로 조정 가능 (기본 1,000원)

## 8. 알려진 제한사항 / TODO

- 실시간 시세 아님 (일별 종가 기준)
- git 저장소 아님 (버전관리 미시작 상태) — 필요 시 `git init` 권장
- SQLite 단일 파일 캐시, 다중 서버/동시성 고려 안 됨
- `checkout_sessions` 테이블의 `is_mock` 컬럼은 Stripe/모의결제 시절의 흔적으로 현재는 사용 안 함(항상 0) — 정리해도 무방
- 실제 결제 확인까지 브라우저로 끝까지 완결 테스트는 안 함 (토스 시크릿 키가 없어 위젯 렌더링까지만 확인, 서버 confirm 로직은 코드 리뷰 + 에러 핸들링으로 검증)
- Node.js는 설치돼 있지만 프론트엔드는 계속 순수 HTML/JS 유지 중 (이미 잘 동작해서 굳이 React/Vite로 안 바꿈 — 필요하면 요청하면 전환 가능)

## 9. 진행 히스토리 요약 (의사결정 이유)

1. 그린필드 시작 → 데이터 소스/결제수단 등 사용자에게 질문 후 방향 확정
2. Node.js 없어서 프론트엔드는 Vite/React 대신 Tailwind CDN + 순수 JS로 시작
3. 결제는 처음엔 Stripe 테스트 모드(+모의결제 폴백)로 구현
4. 사용자 피드백: 이미지를 더 풍부하게(아바타/뱃지/등락률 색상 등), 유사종목 3개로 제한 → 반영
5. 사용자 피드백: 결제를 토스페이먼츠+카카오페이로 → Stripe/모의결제 완전히 걷어내고 토스 결제위젯으로 교체 (카카오페이는 토스 위젯 안에 자동 포함됨)
6. 버그: 좁은 화면에서 가격/업종 뱃지 겹침, 조합 페이지에서 종목명 안 보임 → flex 레이아웃을 `ml-[Npx]` 같은 픽셀 오프셋 대신 `flex-1` 컬럼 중첩 구조로 재작성해 해결
7. 사용자 피드백: 유사종목 버튼 클릭 시 자동 스크롤, 조합 기준을 "분산 효과(저상관)"에서 "동반 상승 수혜주(고상관)"로 반전 → 반영
8. 조합 종목 개수 5개 → 2개로 고정
9. 성장 단계 착수 (2026-07-10): 애드센스 수익화, AI 에이전트 자동관리, 홍보, 실결제 전환을 요청받아 다음을 추가:
   - 법적 페이지 3종(`privacy.html`/`terms.html`/`about.html`, 애드센스 심사 필수 요건) + 홈/결과 페이지 하단 푸터 링크
   - `ADMIN_TOKEN` 헤더로 보호되는 관리자 API 3종: `POST /admin/refresh-data`, `GET /admin/health`, `POST /admin/posts` — 예약된 AI 에이전트가 호출
   - "오늘의 시황" 블로그 기능 (`posts` 테이블, `/api/posts`, `blog.html`/`blog-post.html`) — SEO 유입 + 애드센스 콘텐츠 요건 겸용
   - `git init` + `.gitignore` 완료, 단 **git commit은 의도적으로 하지 않음** — git 전역 설정을 건드리지 않기 위해 사용자가 GitHub Desktop으로 최초 커밋/푸시하도록 [GUIDE.md](GUIDE.md)에 안내
   - Claude Code 예약 작업(스케줄) 3종 생성 완료: `stock-data-refresh-agent`(평일 18:50), `stock-site-health-monitor`(매시 정각+7분), `stock-seo-content-agent`(평일 19:15). 현재는 URL/토큰이 플레이스홀더(`YOUR-SITE-DOMAIN.example.com`, `YOUR_ADMIN_TOKEN`) 상태라 실행 시 스스로 건너뛰고 1일 1회 알림만 보냄 — 배포 완료 후 실제 값으로 `update_scheduled_task` 필요 (GUIDE.md 7단계)
   - [GUIDE.md](GUIDE.md) 신규 작성: GitHub Desktop → Render 배포 → 가비아 도메인 연결 → 홈택스 개인사업자등록 → 토스페이먼츠 라이브 키 전환 → 구글 애드센스 신청 → 예약 에이전트 활성화 → 홍보 방법까지 비개발자 기준 클릭 단위로 서술

## 10. 다음에 작업 이어받을 때 참고할 것

- 위 히스토리 때문에 코드에 "낮은 상관계수가 좋다"는 예전 논리/문구가 남아있으면 버그이니 확인할 것 (6번 항목 기준이 최종)
- 프리뷰 브라우저 창 폭이 약 279px로 매우 좁게 렌더링되는 환경이므로, 카드형 UI를 수정할 때는 항상 이 폭에서 테스트할 것 (아바타+텍스트+버튼을 한 줄에 욱여넣으면 텍스트가 짓눌리는 버그가 반복 발생했음)
- 결제 흐름을 실제로 끝까지 확인하려면 토스페이먼츠 테스트 키가 필요함 (7번 항목 참고)
- `backend/static/about.html`의 `contact@example.com`은 실제 운영자 이메일로 교체 필요 (애드센스 심사 전 필수)
- 예약된 3개 AI 에이전트(`stock-data-refresh-agent`, `stock-site-health-monitor`, `stock-seo-content-agent`, `C:\Users\user\.claude\scheduled-tasks\` 아래 SKILL.md로 저장됨)는 아직 플레이스홀더 URL/토큰 상태 — 배포 URL과 ADMIN_TOKEN이 정해지면 반드시 `update_scheduled_task`로 갱신해야 실제로 동작함
- git 저장소는 초기화만 되어 있고 커밋은 없음 (git 전역 설정을 건드리지 않기 위해 의도적으로 커밋하지 않았음) — 사용자가 GitHub Desktop으로 첫 커밋/푸시를 해야 함 (GUIDE.md 1단계)
