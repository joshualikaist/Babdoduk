# Babdoduk (밥도둑)

KAIST 중심의 식사 정보·메뉴 선택·음식 콘텐츠 사이트입니다. 방문자가 보는 화면은 정적 HTML·CSS·JS이고,
빌드 단계가 없습니다. 그 위에 **생성 데이터 파이프라인**(파이썬 + GitHub Actions)이 붙어
`data/` 아래 JSON을 주기적으로 갱신합니다. 배포는 Vercel 정적 호스팅입니다.

제품 역할과 작업 경계의 기준은 [`PRD.md`](PRD.md), [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md),
[`ARCHITECTURE.md`](ARCHITECTURE.md), [`AGENTS.md`](AGENTS.md)입니다. 아래 운영 기록 중
날짜가 있는 상태 설명은 현재 상태 보장이 아니며, 실행 전 코드·데이터·배포 브랜치를 확인합니다.

---

## 1. 페이지 구성

| 파일 | 역할 |
|------|------|
| **`index.html`** | 현재 홈 — 프로필과 SNS·외부 링크를 중심에 둔 편집형 카드, 푸터 |
| **`food.html`** | 먹방 가계부 — 일별 지출 입력·월/주 표·달력 (`data/food-log.json`) |
| **`event.html`** | 이벤트 — 탭형 목록(날짜 순)·상세 패널. 필드 규칙은 `docs/EVENT_DETAIL_FIELDS.md` |
| **`mukbang.html`** | 밥도둑 매거진 — `data/magazine/`의 네 세로 카테고리, 학식 요약, 음식 추천기 |
| **`ggongbab.html`** | **오늘 뭐 먹지?** — 꽁밥 피드 + KAIST 학식 (`css/ggongbab.css`, `js/ggongbab.js`, `js/kaist-menu.js`) |
| **`history.html`** | 밥도둑의 역사 — 연도별 타임라인 |
| **`lab-ggongbab.html`** | 같은 꽁밥 렌더러를 쓰는 실험 페이지. fixture·localhost preview 모드가 여기에만 있다. `noindex` |
| **`lab.html`** | 실험실 — 본편과 분리해 시험. `noindex`. 홈에 링크 없음 |

상단 내비: 소개 · SNS · 주요 기능(맛집 지도 · 먹방 가계부 · 오늘 뭐 먹지?) · 이벤트 · 언어(EN/한국어).
언어는 `localStorage` 키 `babdoduk-lang`(`ko`/`en`)으로 모든 페이지가 공유합니다.
환영 팝업은 **홈에서만** 뜨고, 「하루 동안 보지 않기」는 `babdoduk-welcome-snooze-until`로 약 24시간 숨깁니다.

### `ggongbab.html` 와 `lab-ggongbab.html`

두 파일은 같은 렌더러(`js/ggongbab.js`)를 씁니다. 모드를 결정하는 핵심 차이는
`<body data-gg-lab>`이며, HTML에는 `noindex`, 실험 리본, 제목 등의 차이도 있습니다.

- 이 속성이 **있으면**(lab) `?fixture=1`, `?preview=1`, `?debug-layout=1` 를 쓸 수 있습니다.
- 이 속성이 **없으면**(본편) 모드는 항상 `normal` 로 고정됩니다. 쿼리스트링을 붙여도
  fixture 데이터나 `.local/` 파일을 읽지 않고, 진단 패널도 만들어지지 않습니다.

본편을 갱신할 때는 lab 파일을 손으로 베끼지 말고 §8의 승격 절차를 따릅니다.

---

## 2. 데이터 파일

| 경로 | 생성 주체 | 비고 |
|------|-----------|------|
| `data/food-log.json` | 사람이 직접 작성 | 인스타 게시 후 Total 금액을 날짜별로 기입 |
| `data/magazine/` | `scripts/refresh_magazine.py` | GitHub Action |
| `data/kaist-menu/` | `scripts/refresh_kaist_menu.py` | GitHub Action |
| `data/ggongbab/latest.json` | 꽁밥 파이프라인 | 공개 피드. 아래 §3 참고 |

생성 JSON은 Action이 lab·main에 **같은 파일만** 푸시합니다. 기능 브랜치를 매일 merge하지 않습니다.

---

## 3. 오늘 뭐 먹지? 파이프라인

KAIST에서 오늘 먹을 수 있는 것을 한 페이지(`ggongbab.html`)에 모읍니다.

- **꽁밥** — 무료 식사·간식·다과가 명시된 교내 행사
- **KAIST 학식** — 공식 학식 JSON (`data/kaist-menu/latest.json`). AI를 쓰지 않습니다.

```
Dooray mailbox  ─┐
KAIST Portal (로컬 resident Chrome + SSO) ─┼─▶ Dooray 수집 프로젝트 ─▶ Collectors
KAIST 공개 공지 (학사공지 · 문화행사)     ─┤
manual.json                            ─┘
        │
        ▼
PII 제거 → 규칙 전처리 → gpt-5.6-luna → 결정적 검증 → 중복 제거
        │
        ▼
Supabase → data/ggongbab/latest.json → 꽁밥 탭

학식: scripts/refresh_kaist_menu.py → data/kaist-menu/latest.json → 학식 탭
```

단계별 구현은 `scripts/ggongbab/` 안에 있습니다.

| 모듈 | 역할 |
|------|------|
| `collectors/` | Dooray 업무 프로젝트(메일·Portal marker), KAIST 공개 공지, `manual.json`. PortalCollector는 클라우드에서 비활성 |
| `prefilter.py` | 규칙 기반 1차 선별. 여기서 걸러진 메일은 모델에 보내지 않는다 |
| `parsers/ai_parser.py` | OpenAI Responses API + Structured Outputs |
| `parsers/ai_errors.py` | 실패를 **로그에 안전한 범주**로 분류 (§6) |
| `pricing.py` | token 사용량 → 예상 비용. 단가가 모여 있는 유일한 곳 |
| `pipeline.py` | 한 항목의 전체 처리와 통계 |
| `dedup.py` | 같은 행사의 중복 등록 제거 |
| `db/` | Supabase(PostgREST) 저장소와 인메모리 저장소 |
| `exporter.py` | 공개 payload 생성 |
| `web/` | 무인 브라우저 에이전트 (§5) |
| `preview.py` | 로컬 미리보기 (§7) |

### 공개 기준

피드에 나가는 행사는 **음식 제공이 본문에 명시된 것**뿐입니다.

- `food.provided` 가 `"true"` 인 것만 카드가 됩니다. `"false"` 와 `"unknown"` 은 나가지 않습니다.
- `needs_review` 가 붙은 행사도 나가지 않습니다.
- 세 값은 **tri-state** 입니다. `"unknown"` 을 `"false"` 로 접으면 안 됩니다. 모르는 것과
  아니라고 적힌 것은 다르고, 후자만 근거가 있습니다.
- 점심·저녁 같은 **시간대 단어는 음식 제공의 근거가 아닙니다.** "중식 제공", "다과 준비"
  처럼 제공을 말하는 표현이 있어야 합니다.

### AI 모델 정책

```
mail (sanitized)
      ↓
gpt-5.6-luna          ← 유일한 기본 모델
      ↓
deterministic validator   ← 진실을 정하는 곳
      ├─ publishable  → 공개 피드
      └─ needs_review → 비공개
```

**production 기본은 `gpt-5.6-luna` 하나입니다.** 자동 fallback은 꺼져 있습니다.

이 시스템에서 모델이 하는 일은 추론이나 창작이 아니라 **문자 그대로의 구조화 추출**입니다.
날짜·장소·음식 근거·신청 정보를 본문에 적힌 대로 꺼내 오는 것이고, `food`·`date`·`location`·
`registration` 의 최종 판정은 결정적 validator가 합니다. 그래서:

- 애매한 원문은 **더 강한 모델로 추측시키지 않고 `needs_review` 로 남깁니다.** review 항목은
  공개 피드에서 제외되므로 안전성은 그대로입니다. **애매함은 오류가 아닙니다.**
- 호출에 `reasoning={"effort": "none"}` 을 명시합니다. chain-of-thought는 여기서 얻는 것이
  없으면서 output token으로 과금됩니다.

`gpt-5.6-terra` 는 삭제하지 않고 **운영자가 명시적으로 켜는 선택적 fallback**으로 남겨 두었습니다.
필수가 아닙니다. 켜려면 환경변수나 GitHub variable에 모델 이름을 직접 넣어야 하고,
비어 있으면 fallback API 호출은 **0** 입니다.

```powershell
# 비교 실행이 필요할 때만
$env:GGONGBAB_AI_FALLBACK_MODEL = "gpt-5.6-terra"
```

fallback을 켜면 `fallbackAttempted` / `fallbackImproved` / `fallbackSame` / `fallbackWorse`
카운터가 쌓입니다. Terra를 상시 켤지는 이 숫자가 모인 뒤에 정합니다. 지금은 Terra가 실제
공개 정확도를 얼마나 개선하는지에 대한 정량 근거가 없습니다. 재평가 조건은 §6 끝에 있습니다.

### 현재 상태

공개 건수는 수집·승인·만료에 따라 바뀝니다. 이 README에 고정된 현재 건수를 두지 않습니다.
2026-09-23의 운영자 확인 기록은 `docs/GGONGBAB_PUBLIC_FEED.md`에 있으며, 그 수치도
새로운 실시간 검증 결과는 아닙니다. 현재 화면 상태는 발행 산출물과 실제 배포 환경에서 확인합니다.

---

## 4. 로컬 준비

```powershell
cd C:\Users\joshu\Babdoduk
pip install -r requirements-ggongbab.txt
copy .env.example .env      # 값을 채운다. .env 는 gitignore 대상
```

`.env` 에 들어가는 값은 `.env.example` 에 이름만 적혀 있습니다.
**토큰·키를 소스에 적지 않습니다.** Dooray 토큰은 `Authorization` 헤더로만 나가고,
Supabase secret key는 서버 전용이라 브라우저로 가지 않습니다.

Windows 콘솔에서 한글이 깨져 보이면 파일이 아니라 코드 페이지 문제입니다.
`chcp 65001` 로 UTF-8을 켜고 다시 실행하세요. **인코딩 변환 코드를 덧붙이지 마세요.**
이중 인코딩이 됩니다.

---

## 5. 메일 수집 에이전트

### 왜 브라우저인가

현재 Gov-Dooray 환경의 personal API token으로는 **메일함을 읽을 수 있는 공개 Mail REST API가
제공되지 않습니다.** 그래서 이미 로그인된 Dooray 웹앱을 브라우저로 띄우고, 그 화면이 스스로
호출하는 **내부 WAPI 응답을 관찰**합니다. 엔드포인트를 추측해서 만들지 않고, `--discover`
단계에서 실제로 오간 요청을 기록해 `.local/dooray-ui.json` 에 계약으로 저장합니다.
계약과 화면이 어긋나면 에이전트는 추측하지 않고 `UI_CHANGED` 로 멈춥니다.

읽음 상태는 **절대 바꾸지 않습니다.** 목록 API와 상세 API 모두 읽음 처리를 일으키지 않는
경로만 사용하고, 읽음 상태 필드를 못 읽으면 본문을 가져오기 전에 중단합니다(fail closed).

### 절차

```powershell
# 1. 상주 Chrome을 띄우고 사람이 한 번 SSO 로그인 (비밀번호는 저장하지 않는다)
python scripts\dooray_web_agent.py --setup --cdp

# 2. 화면이 어떻게 로드되는지 기록해 계약 파일을 만든다
python scripts\dooray_web_agent.py --discover --cdp

# 3. 읽음/미읽음 판별 필드를 실제 응답으로 확인한다
python scripts\dooray_web_agent.py --calibrate --cdp

# 4. 무인 수집 + 파이프라인
python scripts\dooray_web_agent.py --run --since-last-run --run-pipeline --cdp
```

`--setup` 은 사람이 로그인하는 유일한 단계입니다. 그 뒤로는 Windows 작업 스케줄러가
`scripts\run_ggongbab_agent.cmd` 를 돌립니다. 세션이 끊기면 에이전트는 혼자 뚫으려 하지 않고
`AUTH_REQUIRED` 로 끝나므로, 그때만 `--setup` 을 다시 하면 됩니다.

`--cdp` 는 별도 프로필의 상주 Chrome에 `127.0.0.1:9222` 로 붙습니다. Playwright 번들
Chromium이 아니라 설치된 Chrome을 쓰되, **사용자의 기존 Chrome 프로필은 쓰지 않습니다.**
SSO가 에이전트가 제어하지 않는 창에서 끝나 버리는 문제 때문에 이 방식이 필요합니다.

### KAIST Portal 로컬 에이전트

Portal은 GitHub Action에서 SSO 할 수 없으므로 클라우드 collector는 비활성입니다.
동일 공지를 수동으로 다시 열었을 때 `inqCnt`가 달라지는 것이 사용자 관찰로 확인되었습니다.
현재 `/wz/api/board/recents/{pstNo}`의 자동 상세 replay는 계속 금지하며,
`detail_side_effect_reviewed`/`potential_view_side_effect` gate는 유지합니다.

**현재 별도 LIST 전용 경로:** 사람의 SSO/MFA로 인증된 전용 Chrome에서 세션을 메모리로만
전달받아 정확한 `/wz/api/board/recents` 목록 GET만 조회할 수 있습니다. 이 poller는
로컬 Stage A 후보와 운영 heartbeat만 만들고, 상세 GET·Dooray 업무·AI·공개 행사 발행을 하지
않습니다. 세션 만료 시 자동 로그인하지 않고 중단합니다. 실행·복구·한계는
[`docs/PORTAL_LIST_POLLER.md`](docs/PORTAL_LIST_POLLER.md)에 있습니다.

아래의 상세 관찰·generic calibration 설명은 기존 진단 경로에 대한 기록이며 LIST poller의
실행 절차가 아닙니다. setup 성공은 공지 traffic을 통한 세션 준비 확인이지 replay 계약 검증이
아닙니다.

대체 본문 source를 **수동 클릭의 Network 응답으로만** 관찰하려면:

```powershell
python scripts\portal_web_agent.py --discover-detail-alternatives --cdp
```

이미 로그인한 Portal Chrome에 attach만 합니다. Chrome/탭을 새로 열거나 이동·reload하지 않고,
Portal HTTP 요청·DOM click·endpoint probing도 하지 않습니다. 안내 후 60초 동안 공개 공지 하나를
수동으로 여세요. 기존 known detail의 공개 응답은 클릭 ID 대조 기준으로만 사용하고 후보에서 제외합니다.
같은 탭에서 이 응답 전 15초/후 30초에 관찰된 same-host GET 2xx JSON/HTML만 검토합니다.
JSON의 공지 ID와 본문 필드, HTML의 명시적인 공지 본문 container/JSON script data를 검사합니다.
thumb/image·codes·collegePlan·localization/UI bundle·analytics·조회수/읽음 mutation·POST는 제외합니다.

출력은 카운트, method, path template, resource/response type, body/ID path, ID 일치 여부,
counter field 존재 여부뿐입니다. URL query 값·ID·제목·본문·계정 값은 출력하거나 파일에 저장하지 않습니다.
알 수 없는 path segment/key는 `{segment}`/`{key}`로 가려 값이 이름처럼 섞여 나오는 것을 막습니다.
contract·queue·discovery 파일은 바꾸지 않으며 별도 후보 원문 파일도 만들지 않습니다.
후보가 없으면 `no safe alternative observed`(exit 20)로 끝납니다. counter가 있는 후보만 보인 경우에도
같은 문구를 표시합니다. 후보 관찰은 side-effect-free 증명이나 replay 승인이 아니며,
자동 run/dry-run 상세 조회 차단은 그대로 유지됩니다.

KAIST 운영 경로는 DevTools에서 수동 확인한 schema를 쓰는 `--calibrate-known`입니다.
`--discover`와 generic `--calibrate`는 진단/fallback으로 유지합니다.
`--dry-run`/`--run`은 schema와 부작용 검토를 모두 통과한 contract만 사용합니다.
비밀번호·OTP는 채우지 않고, 엔드포인트를 추측하지 않습니다.

```powershell
python scripts\portal_web_agent.py --setup --cdp
python scripts\portal_web_agent.py --calibrate-known --cdp
```

known calibration은 정확히 `GET /wz/api/board/recents`의 `pageIndex=1,2`만 능동 조회합니다.
`recordCountPerPage=10`과 관찰된 structural query 기본값을 그대로 유지하며 dotted query 이름은
문자 그대로 처리합니다. 계정 식별 query는 전송·저장하지 않습니다. 이를 생략한 상태로 HTTP/JSON/
목록 schema 검증이 실패하면 `LOGIN_ID_RUNTIME_REQUIRED`로 종료하고 값을 추측하거나 요구하지 않습니다.
그 다음 120초 동안 사용자가 검증된 두 목록 페이지에서 서로 다른 공개 공지 두 개를 여는 응답만
수동 관찰합니다. calibration에서 상세 API를 능동 호출하지 않습니다.

목록은 `data`, ID는 `pstNo`, 제목은 `pstTtl`, 날짜는 `regDt`로 고정합니다.
상세는 `GET /wz/api/board/recents/{pstNo}`와 root `pstCn`을 사용합니다.
상세 query의 `boardNo`는 반드시 해당 row의 `boardNo`이고, `boardNos=""`, `menuNo="21"`은 고정입니다.
`publicYn == "Y"`인 목록 항목만 날짜/제목 prefilter 후 상세 후보가 됩니다.
상세에도 공개 여부가 있으면 재검사하며 ID·board 값 불일치는 중단합니다.
원본 row/detail 전체나 작성자·계정 정보는 queue/task payload에 전달하지 않습니다.

`2026.09.20 13:07:30`과 `2026.09.20` 날짜를 KST로 파싱하며 기존 ISO도 지원합니다.
두 페이지의 실제 timestamp가 페이지 내부와 페이지 경계 모두 내림차순일 때만 date cutoff를 활성화합니다.
실행 시 응답의 `page.pageIndex`도 요청과 비교합니다. 기존 최대 20페이지/500건 기본 상한과
`--max-pages`, `--max-items`, `--from`, `--to`는 그대로 유지합니다.

**자동 상세 replay는 차단 상태입니다.** 사용자는 같은 공지를 다시 열었을 때 `inqCnt`가 달라짐을
확인했습니다. 이 구현은 이를 자동 상세 GET으로 재시험하지 않으며, 금지된 endpoint 대신 대체 source만 관찰합니다.
calibration은 counter field 존재 여부만 보고하고, 관찰되지 않더라도 부작용이 없다고 추론하지 않습니다.
현재 known draft는 `potential_view_side_effect=true`, `verified=false`로 저장하고
`CALIBRATION BLOCKED: potential detail view-count side effect requires review`로 종료합니다(exit 20).
`known_schema_verified=true`는 두 상세까지 schema 검증을 통과했다는 뜻일 뿐 replay 승인이 아닙니다.
별도 검토가 끝나기 전에는 run과 dry-run 모두 자동 상세 GET을 막으며, 이번 버전에 우회 CLI는 없습니다.
generic discovery/calibration은 known draft/contract를 덮어쓰거나 대신 승인할 수 없습니다.

프로필·계약·상태는 모두 gitignore된 `.local/portal-*` 에만 있습니다.
기존 body 기반 수집 설계에서는 승인된 후보를 Dooray 수집 프로젝트에
`[BABDODUK_INGEST_V1] source=portal` marker로 등록하고 기존 Dooray collector가
`RawItem(source_type="portal")` 로 읽도록 되어 있습니다. 현재 LIST poller의 Stage A 후보는
이 경로에 자동 연결되지 않습니다.
private Portal URL은 공개 JSON에 나가지 않습니다.

아래는 남겨 둔 generic 진단/fallback의 동작입니다. known schema 운영 경로를 대체하지 않습니다.
관찰된 list/detail이 없으면 `PORTAL CALIBRATION FAILED` 로 끝납니다.
setup은 비밀번호 입력창이 없는 화면만으로 성공하지 않으며, 공지 목록 API의 정상 응답을 기다립니다.
setup 성공은 **list-like 응답을 관찰했다는 뜻이며, replay contract 검증 성공이 아닙니다**.
discovery의 60초 동안 목록 첫 페이지와 다음 페이지, 서로 다른 공지 상세 2건을 열어야 합니다.
calibration은 같은 상세 요청 템플릿/본문 경로와 서로 다른 ID의 해시 2개를 확인합니다.
기존 v1 contract는 재사용하지 않으므로 다시 discovery/calibration해야 합니다.

목록 배열과 nested 본문은 관찰된 정확한 JSON 경로만 읽습니다. 관찰로 입증된
page/offset 증가 또는 응답 cursor와 다음 요청의 연결만 pagination에 사용합니다.
빈 페이지·중복만 있는 페이지·검증된 날짜 내림차순 cutoff·최대 페이지/건수에서 멈춥니다.
기간을 지정하면 날짜가 없거나 파싱되지 않는 공지는 제외하며, 날짜 필드가 검증되지 않았으면 중단합니다.
기본 상한은 20페이지/500건입니다. 첫 관찰이 중간 페이지면 그 지점부터 시작하므로 backfill은 첫 페이지부터 관찰하세요.

dry-run은 Dooray writer를 생성하지 않고 queue 파일을 만들거나 변경하지 않습니다.
실제 run에서 task ID가 반환된 공지만 즉시 queue에 기록합니다. queue에는 해시만 저장하며,
변경 공지는 같은 external key의 새 task로 등록하고, 수집 시 최신 내용으로 upsert합니다.
등록 성공 직후 로컬 저장 전에 프로세스가 종료되면 다음 실행에 task가 중복될 수 있지만,
동일 external key로 DB에서 합쳐집니다.

현재 자동 calibration은 동일 Portal host의 관찰된 GET 또는 검증된 JSON/form POST를 지원합니다.
알 수 없는 query 값, 재현할 수 없는 요청, 여러 모호한 목록은 추측하지 않고 중단합니다.
비어 있지 않은 cursor·인증 정보·본문·제목·raw ID는 contract에 저장하지 않습니다.
read/unread/readCount/viewCount 등이 관찰되면 상세 조회를 승인하지 않고 semantics 검토를 요구합니다.
`no-read-state-observed`는 관찰 응답에 해당 필드가 없다는 뜻이며 서버의 모든 부작용을 입증한 것은 아닙니다.
실제 Portal endpoint/path와 동작은 다음 SSO/discovery 단계에서 확인해야 합니다.

discovery는 `Content-Type`과 관계없이 Portal/KAIST 호스트 응답의 JSON 파싱을 시도합니다.
전체 응답, xhr/fetch·document·other, exact host·KAIST host, JSON 파싱, GET·POST,
목록/상세 schema 후보와 재호출 가능한 후보 수를 별도로 출력합니다. 전체 GET/POST 및 resource
카운트는 외부 호스트도 포함하지만 외부 응답 본문은 파싱하지 않습니다. same-host와 KAIST-host
카운트는 겹칠 수 있습니다. production 실행의 strict JSON 검증은 유지합니다.

`*.kaist.ac.kr` 교차 도메인과 document/other의 JSON은 **진단 관찰만** 합니다.
동일 exact Portal host·xhr/fetch 정책을 유지하며 query whitelist를 임의로 확장하지 않습니다.
POST는 JSON/form request body의 scalar를 메모리에서만 검사합니다. multipart/upload는 제외하고,
인증 헤더는 읽지 않습니다. request body 인코딩을 구분하기 위한 Content-Type만 확인합니다.
`replayable detail candidates`는 요청 형식이 맞는 관찰 수이고, 최종 상세 승인에는 여전히
서로 다른 ID 2건과 동일 템플릿/본문 경로 검증이 필요합니다.

`candidate found`와 `replay contract: rejected`를 구분하고, `NO_LIST_CANDIDATE`,
`LIST_SCHEMA_AMBIGUOUS`, `MULTIPLE_LIST_IDENTITIES`, `UNSAFE_REQUEST_SHAPE`,
`CROSS_ORIGIN_LIST`, `PAGINATION_NOT_VERIFIED`, `NO_DETAIL_CANDIDATE`,
`MULTIPLE_DETAIL_SHAPES`, `NOT_ENOUGH_DISTINCT_DETAILS` 등의 고정 사유를 출력합니다.
상세의 host/ID path/body path 문제도 별도 카운트와 사유로 구분됩니다.
pagination parameter와 progression 관찰 여부는 각각 0/1로 출력하며,
pagination parameter가 아예 없는 목록은 `pagination: none`으로 허용합니다.

`.local/portal-discovery-debug.json`은 카운터·사유와 안전한 key/path 이름만 저장합니다.
제목·본문·raw ID·query 값·POST body·쿠키·토큰은 이 파일이나 터미널에 출력하지 않습니다.
일반 `.local/portal-discovery.json`의 검증용 contract와 진단 파일은 둘 다 gitignored입니다.

POST correlation은 요청 URL 또는 body scalar와 상세 응답의 정확히 한 path,
목록의 유일한 ID column/row가 같은 값을 가진 경우만 인정합니다. 서로 다른 ID 2개에서
endpoint·request ID path·response ID path·list ID column이 일치해야 POST replay가 가능합니다.
목록과 상세의 GET/POST는 각각 관찰된 method를 사용하며, nested JSON ID는 검증된 한 path에만
주입합니다. `correlated via URL`/`correlated via POST body` 카운트와 선택된 method/path를 출력합니다.
ID와 무관한 localization 응답이나 codes 목록은 correlation 근거로 선택하지 않습니다.

ID 이외의 고정 POST body field는 기본적으로 저장·재호출하지 않습니다. 운영자가 진단에서
field 이름을 확인하고 승인하려면 discovery에 `--approve-post-field detail:boardId` 또는
`--approve-post-field list:filter.boardId`처럼 대상과 정확한 path를 지정합니다(여러 번 지정 가능).
이 예시는 문법 예시이며 실제 Portal field를 가정하지 않습니다. 승인된 key라도 같은 endpoint의
여러 실제 요청에서 값과 타입이 불변이고 짧은 structural primitive여야 합니다.
credential 형태·sensitive key·중복 key·지원하지 않는 container는 거부합니다.

POST 목록 body의 page/offset/cursor는 선택된 공지 목록의 두 요청에서 확인된 progression만
사용합니다. `bgngDt`/`endDt` 등 날짜 범위 변화는 filter evidence로 분리하고 pagination으로
해석하지 않습니다. 입증된 pagination 시작 값 이외의 고정 field는 위의 승인이 필요합니다.

POST contract의 검증된 body template/default는 `.local/portal-ui.json`에만 저장합니다.
discovery/debug JSON에는 scalar 값을 복사하지 않습니다. discovery가 만든 초안은
`verified=false`이고 `--calibrate --cdp`에서 검증한 뒤에만 실행할 수 있습니다.
승인되지 않았거나 값 검증에 실패한 고정 field는 `POST_STATIC_FIELDS_REQUIRE_APPROVAL_OR_VALIDATION`으로
표시됩니다. 원본 body와 ID 값은 저장하지 않으며 ID 위치에는 `{id}`만 남깁니다.
dry-run의 Portal POST는 검증된 공지 조회에 한정되며 Dooray writer와 queue mutation은 계속 0입니다.

### KAIST 학식

AI를 쓰지 않습니다. 공식 학식 페이지를 파싱합니다.

```powershell
python scripts\refresh_kaist_menu.py
```

생성 실패 시 기존 `data/kaist-menu/latest.json` 을 보존합니다. 페이지는 payload `date`가
오늘 KST와 다를 때 “오늘의 학식”으로 표시하지 않습니다.

### 종료 코드

작업 스케줄러가 마지막 결과 코드만 보여 주므로, 실패 이유마다 번호가 다릅니다.

| 코드 | 이름 | 뜻 |
|------|------|-----|
| 0 | `SUCCESS` | 정상 |
| 10 | `AUTH_REQUIRED` | SSO 세션 만료. 사람이 `--setup` 실행 |
| 20 | `UI_CHANGED` | 화면 구조가 계약과 다름. 추측하지 않고 중단 |
| 30 | `PROJECT_NOT_FOUND` | 수집 대상 프로젝트를 정확히 확인하지 못함 |
| 40 | `PIPELINE_FAILED` | 등록은 됐으나 후속 파이프라인 실패 |

### 주요 옵션

| 옵션 | 뜻 |
|------|-----|
| `--from` / `--to` / `--days` / `--since-last-run` | 수집 기간 |
| `--max-mails` | 읽는 행 수 상한 (기본 200) |
| `--max-ai-candidates` | 모델에 보내는 후보 상한 (기본 50). 넘기려면 `--force` |
| `--ai-error-retries N` | 실패 재시도 횟수 0–2 (기본 1). §6 |
| `--read-state` | `all` / `read` / `unread` |
| `--dry-run` | 읽기만 하고 등록·상태 변경 없음 |

---

## 6. AI 실패 처리와 비용

`scripts/ggongbab/parsers/ai_errors.py` 는 모델 호출 실패를 정해진 범주로 바꿉니다.
**SDK 원본 메시지는 로그에 남기지 않습니다.** 오류 본문이 요청을 그대로 인용할 수 있고,
요청에는 메일 본문이 들어 있기 때문입니다. 출력되는 것은 범주 이름과 개수뿐입니다.

```
AI error summary:
  quota_exhausted: 39
```

### 재시도 대상

| 재시도함 | 재시도 안 함 |
|---|---|
| `timeout` · `rate_limit`(짧은 창) · `connection` · `server_error` · `no_parsed_output` | `quota_exhausted` · `auth` · `bad_request` · `refusal` · 스키마 위반 |

`needs_review`·확신도 미달·행사 아님은 **실패가 아니라 답**이라 재시도 대상이 아닙니다.
재시도 횟수는 `--ai-error-retries` 로 0–2 이고, 재시도 전에 창이 리셋될 만큼 기다립니다.

### 한도 소진과 일시적 혼잡 구분

OpenAI는 둘 다 `429 rate_limit_exceeded` 로 돌려줍니다. 구분은 응답 헤더의 대기 시간으로 합니다.
분 단위 창은 기다렸다 다시 보내면 되지만(`rate_limit`), 하루·한 달치 할당량이 떨어진 경우는
기다려서 될 일이 아니므로 `quota_exhausted` 로 분류하고 재시도하지 않습니다.
이 구분이 없으면 39건 실패가 78건 호출로 불어납니다.

### 계정 단위 실패는 즉시 중단

`quota_exhausted` 와 `auth` 는 **한 건이 아니라 계정이 실패한 것**입니다. 남은 후보를 계속
보내도 똑같이 거절당하므로 첫 거절에서 run을 멈춥니다.

```
AI processing stopped early:
  reason: quota_exhausted
  processed: 1
  remaining: 38
```

보내지 않은 38건은 **오류가 아니라 미시도**로 셉니다(`aiSkippedDueToQuota`).
한 번의 계정 실패를 39건의 추출 실패로 부풀리지 않습니다.

### 실제 사용량과 예상 비용

run이 끝나면 모델별 실제 token 사용량과 **예상** 비용을 출력합니다.
숫자 metadata만 쓰며, 비용 계산을 위해 메일 내용을 저장하지 않습니다.

```
AI usage:
  gpt-5.6-luna
    calls: 39
    input tokens: 118234
    output tokens: 28741
    estimated cost: $0.0581

Total estimated API cost:
  $0.0581
  (estimate only, prices as of 2026-09-20; see the OpenAI billing dashboard)
```

단가는 `scripts/ggongbab/pricing.py` 한 곳에 모여 있습니다. 가격은 바뀔 수 있으므로 항상
**estimated** 로 표시하고 기준 날짜를 함께 적습니다. 실제 청구액은 OpenAI billing 대시보드가
기준입니다.

### 월 $5 예산으로 운영하기

**코드에는 $5 hard cap이 없습니다.** 실제 과금과 한도는 OpenAI 쪽에서 정해지는 것이라,
코드가 막는 것처럼 보이게 만드는 것은 거짓 안전장치입니다. 대신 비용이 낮게 유지되는 이유는
이렇습니다.

- **선불 credit과 project/rate limit은 별개입니다.** credit을 충전해도 요청·토큰 한도는
  따로 적용되므로, 한도는 OpenAI 대시보드에서 직접 확인해야 합니다.
- Luna는 추출 작업 기준으로 단가가 낮습니다. 위 예시처럼 39건 수집이 약 $0.06 수준입니다.
- **content hash 캐시** 덕분에 내용이 그대로인 항목은 AI를 다시 부르지 않습니다.
  30분마다 도는 cron이 매번 전체를 재추출하지 않습니다.
- **규칙 전처리**가 먼저 걸러서, 메일함 전체가 아니라 후보만 모델로 갑니다.
- Terra 자동 fallback이 꺼져 있습니다. Terra는 token당 약 10배라, 후보의 1/5만 fallback을
  타도 Luna 본 run 전체보다 비싸집니다.

고정 월 비용을 약속할 수는 없습니다. 실제 run 비용은 위 terminal summary로 확인하세요.

### Terra를 다시 켤지 판단하는 기준

지금은 자동으로 쓰지 않습니다. 다음을 **모두** 만족할 때만 재평가합니다.

1. 실제 review case가 10~20건 이상 쌓였고
2. 사람이 ground truth를 확인했고
3. Luna가 반복적으로 잘못 추출하고
4. 같은 case에서 Terra가 validator issue를 의미 있게 줄이며
5. 그 개선이 단순 confidence 변화가 아니라 실제 date/food/location **정확도** 개선일 것

이 데이터가 없으면 Terra 자동 fallback을 켜지 않습니다.

---

## 7. 로컬 미리보기 (preview / fixture)

실제 Dooray와 실제 OpenAI를 쓰되 **아무것도 쓰지 않는** 모드입니다.
Dooray 프로젝트 기록 0건, Supabase 기록 0건, `data/ggongbab/latest.json` 수정 0건,
main 수정 0건. 결과는 `.local/ggongbab-preview.json` 에만 남습니다.

```powershell
python scripts\dooray_web_agent.py --preview-feed --from 2026-09-01 --to 2026-09-19 `
  --max-mails 1000 --max-ai-candidates 50 --read-state read --cdp
```

보기:

```powershell
python scripts\check_ggongbab_ui.py --serve     # 127.0.0.1 로만 연다
```

그 뒤 `http://127.0.0.1:8000/lab-ggongbab.html?preview=1`.

미리보기는 **localhost 에서만** 동작합니다. 공개 호스트에서 `?preview=1` 을 열면 `.local/`
요청 자체를 시도하지 않고 안내 문구만 보여 줍니다. 진단 패널도 허용 목록에 있는 숫자
카운터만 렌더링하므로, 로컬 payload에 예상 밖의 필드가 있어도 화면에 나오지 않습니다.

모델을 부르지 않고 레이아웃만 보려면 `?fixture=1` 을 씁니다. 자세한 내용은
`docs/GGONGBAB_PREVIEW.md`.

> 이 저장소에서 `python -m http.server` 는 쓰지 마세요. 디렉터리 목록과 `.local/` 을 그대로
> 노출합니다. `--serve` 는 둘 다 막고 루프백에만 바인딩합니다.

---

## 8. UI 검증과 본편 승격

```powershell
python scripts\check_ggongbab_ui.py            # fixture + 본편 검사
python scripts\check_ggongbab_ui.py --preview  # preview 데이터까지 포함
python scripts\check_site_ui.py                # 8개 HTML의 scrollbar·overflow·nav 검사
```

390 / 430 / 1440 세 뷰포트에서 좌표·가로 스크롤·말줄임·sticky 필터를 확인하고,
본편 `ggongbab.html` 에 대해서는 추가로 다음을 검사합니다.

- `?fixture=1`, `?preview=1`, `?debug-layout=1` 를 붙여도 `normal` 모드일 것
- `.local/` 요청을 **한 번도** 시도하지 않을 것
- `food.provided` 가 `false`·`unknown` 인 행사와 `needs_review` 행사가 카드로 나오지 않을 것
- 진단 토글·실험 리본·`noindex` 가 없을 것

결과 좌표와 스크린샷은 `.local/ui-shots/` 에 남습니다(커밋하지 않음).

**승격 절차** — `lab-ggongbab.html` 을 손으로 베끼지 않습니다. lab 파일에서
`noindex`, 실험 리본(마크업과 CSS), `data-gg-lab`, 실험실 내비 항목을 제거하고 제목을
`오늘 뭐 먹지? · 밥도둑 Babdoduk` 로 바꾼 것이 `ggongbab.html` 입니다. 바꾼 뒤에는 반드시
위 검사를 다시 돌립니다.

---

## 9. 테스트

```powershell
python -m pytest tests\ggongbab
```

파이프라인·검증기·중복 제거·에이전트 계약·AI 실패 처리까지 포함합니다.
로그 privacy 검사도 테스트에 있습니다. `scripts/ggongbab/` 의 모든 `print` 를 AST로 훑어
메일 식별자가 출력되지 않는지 확인합니다.

---

## 10. 자동화 (GitHub Actions)

| 워크플로 | 주기 | 하는 일 |
|----------|------|---------|
| `.github/workflows/ggongbab-refresh.yml` | 30분 | 수집·파싱·저장 후 `data/ggongbab/` 를 lab·main에 푸시 |
| `.github/workflows/magazine-daily.yml` | 매일 | 매거진·학식 데이터 갱신 |

cron은 기본 브랜치(main)에서만 돌기 때문에 이 파일들은 main에 있어야 합니다.
두 워크플로는 `babdoduk-content-refresh` concurrency group을 공유해서 동시에 푸시하지 않습니다.

`workflow_dispatch` 로 `full` / `export-only` / `review-report` 를 골라 수동 실행할 수 있습니다.
내보낼 것이 없으면(종료 코드 2) 이전 `latest.json` 을 그대로 두고 성공으로 끝냅니다.

필요한 secret: `DOORAY_API_TOKEN`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`.
`SUPABASE_SERVICE_ROLE_KEY` 는 `SUPABASE_SECRET_KEY` 가 비었을 때만 읽는 legacy 이름입니다.

변수(secret 아님): `GGONGBAB_AI_MODEL`(기본 `gpt-5.6-luna`), `GGONGBAB_AI_FALLBACK_MODEL`.
후자는 **기본이 비어 있어** cron은 Luna 단독으로 돕니다. 운영자가 GitHub variable을 직접
설정했을 때만 fallback이 켜집니다 (§3).

---

## 11. 브랜치와 배포

저장소는 하나이고 브랜치로 나눕니다. **폴더를 복사해 프로젝트를 나누지 않습니다.**

| 브랜치 | 용도 | Vercel 프로젝트 |
|--------|------|-----------------|
| `main` | 방문자용 본편 | `babdoduk` → https://babdoduk.vercel.app |
| `lab` | 실험 | `babdoduk-lab` → https://babdoduk-lab.vercel.app |

기능 개발은 `lab` 에서 합니다. 본편 반영은 별도 승인과 diff 검토 후 진행하며,
`lab` 전체에 운영 코드·migration·Realtime 변경이 섞여 있을 수 있으므로 시각 변경만을
위해 전체 브랜치를 자동으로 합치지 않습니다. 아래 명령은 **전체 lab 승격이 승인되고 검토된
경우에만** 적용하는 예시입니다.

```powershell
# 실험
git checkout lab
git push origin lab

# 본편 반영
git checkout main
git merge --no-ff lab
git push origin main
```

`git push --force`, `git reset --hard` 후 main 덮어쓰기, main ref 직접 갱신은 하지 않습니다.
`lab` 브랜치에서 `vercel --prod` 를 공개 프로젝트에 대고 실행하지 않습니다.

Vercel CLI가 처음이면:

```powershell
npm install -g vercel
vercel link --project babdoduk-lab --yes    # 또는 --project babdoduk
vercel --prod
```

`In which directory is your code located?` 에는 경로가 아니라 **`.`** 만 입력합니다.

자세한 내용: `docs/DEPLOYMENT_AND_BRANCHES.md`, merge 전 점검: `docs/BRANCH_MERGE_CHECKLIST.md`.

---

## 12. 보안 원칙

- 토큰·키를 소스에 하드코딩하지 않습니다. `.env` 와 GitHub secrets로만 다룹니다.
- KAIST 비밀번호를 저장하지 않습니다. 세션 쿠키·브라우저 프로필·스크린샷을 커밋하지 않습니다.
- 메일 원문을 그대로 모델에 보내지 않습니다. 보내기 전에 개인정보를 제거합니다.
- 로그에 메일 제목·메일 id·`external_id`·발신자 주소·본문·요청 payload를 출력하지 않습니다.
  실패는 범주와 개수로만 보고합니다.
- `.local/` 는 전부 gitignore 대상입니다. 계약 파일·미리보기·스크린샷이 여기 모입니다.

---

## 13. 스크립트 요약

| 파일 | 설명 |
|------|------|
| `scripts/dooray_web_agent.py` | 메일 수집 에이전트 (§5) |
| `scripts/portal_web_agent.py` | Portal 로컬 에이전트 (SSO · 관찰 · 수집 큐) |
| `scripts/refresh_ggongbab.py` | 파이프라인 실행·내보내기·검토 리포트 |
| `scripts/check_ggongbab_ui.py` | UI 좌표·보안 검사, 로컬 서버 (§8) |
| `scripts/check_site_ui.py` | 전체 공개 HTML의 로컬 scrollbar·overflow·nav 회귀 검사 |
| `scripts/validate_content.py` | 생성 JSON 스키마 검증 |
| `scripts/publish_generated.py` | 생성 데이터만 lab·main에 푸시 |
| `scripts/refresh_magazine.py` · `refresh_kaist_menu.py` | 매거진·학식 데이터 |
| `scripts/run_ggongbab_agent.cmd` | 작업 스케줄러 진입점 |
| `rebuild_index.py` · `patch_site.py` | 홈 재생성·공통 패치 (레거시) |

---

## 14. 문서

| 문서 | 내용 |
|------|------|
| `docs/GGONGBAB_PAGE.md` | 꽁밥 페이지 운영 규칙 |
| `docs/GGONGBAB_PREVIEW.md` | 미리보기·fixture 모드 |
| `docs/GGONGBAB_PUBLIC_FEED.md` | 공개 projection과 발행 계약 |
| `docs/GGONGBAB_REALTIME.md` | 공개 Realtime·snapshot fallback |
| `docs/PORTAL_LIST_POLLER.md` | Portal LIST 전용 로컬 poller |
| `docs/GGONGBAB_RESIDENT_OPS.md` | Windows 상주 worker·복구 |
| `docs/DEPLOYMENT_AND_BRANCHES.md` | 배포·브랜치 |
| `docs/BRANCH_MERGE_CHECKLIST.md` | merge 전 점검 |
| `docs/EVENT_DETAIL_FIELDS.md` | 이벤트 상세 필드 |
