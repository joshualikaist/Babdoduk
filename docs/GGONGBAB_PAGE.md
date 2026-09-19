# 꽁밥 (KAIST 무료 식사 행사) 자동 수집 시스템

`lab-ggongbab.html` 은 더 이상 손으로 쓰는 안내 페이지가 아니다. Dooray 메일함 · KAIST 공개 공지 · 수동 입력을
30분마다 모아 OpenAI로 구조화하고, 규칙 검증 · 중복 제거를 거쳐 Supabase에 쌓은 뒤, 공개 조건을 만족하는
행사만 `data/ggongbab/latest.json` 으로 내보내 세로 피드로 보여 준다.

이 문서 하나로 운영 · 디버깅 · 확장이 가능해야 한다.

---

## 1. Architecture

```
Dooray Mail ──(Dooray 자동 분류)──▶ Dooray Project Task  ─┐
KAIST 공개 공지 (학사공지 · 문화행사)                     ├─▶ Collectors ─▶ RawItem
data/ggongbab/manual.json                                 │
KAIST Portal (stub, disabled)                            ─┘
                                                              │
                             raw_items / attachments (Supabase, private)
                                                              │
                                   PII sanitizer ─▶ Rule pre-processor
                                                              │
                          OpenAI Structured Outputs (Luna ─▶ 필요 시 Terra)
                                                              │
                                   Deterministic validator ─▶ needs_review
                                                              │
                                        Dedup / merge (events + event_sources)
                                                              │
                                Public exporter ─▶ data/ggongbab/latest.json
                                                              │
                                           validate_content.py ─▶ publish_generated.py
                                                              │
                                     lab-ggongbab.html + js/ggongbab.js (fetch only)
```

* **Supabase PostgreSQL 이 canonical DB** 다. Git 에 있는 JSON 은 공개 캐시(정적 export)일 뿐이다.
* 브라우저는 DB 에 접속하지 않는다. `latest.json` 만 읽는다.
* 코드 위치

| 경로 | 역할 |
|------|------|
| `scripts/refresh_ggongbab.py` | CLI 진입점 (`--dry-run`, `--export-only`, `--review-report`, `--check`, `--only`) |
| `scripts/ggongbab/config.py` | env 로딩 (`.env` 자동 로드, 값은 절대 하드코딩 안 함) |
| `scripts/ggongbab/models.py` | `RawItem`, `EventExtraction`(AI 스키마), `RuleFacts`, `EventCandidate` |
| `scripts/ggongbab/collectors/` | `dooray.py`, `kaist_public.py`, `manual.py`, `portal.py`(stub) |
| `scripts/ggongbab/parsers/` | `dooray_mail.py`, `html_text.py`, `sanitizer.py`, `rule_parser.py`, `ai_parser.py`, `validator.py` |
| `scripts/ggongbab/db/` | `supabase_client.py`(PostgREST, stdlib), `repository.py`(Supabase + in-memory) |
| `scripts/ggongbab/dedup.py` | 소스 간 동일 행사 판정과 병합 |
| `scripts/ggongbab/exporter.py` | 공개 JSON 생성 |
| `scripts/ggongbab/pipeline.py` | 전체 흐름 · 멱등성 · 통계 |
| `supabase/migrations/001_ggongbab_schema.sql` | 스키마 · RLS · seed |
| `css/ggongbab.css`, `js/ggongbab.js` | 피드 UI |
| `tests/ggongbab/` | pytest (118개) |

---

## 2. Dooray setup

Dooray Mail API 는 쓰지 않는다. Dooray **자동 분류 규칙**이 꽁밥 후보 메일을 아래 프로젝트의 업무(Task)로 만든다.

| 항목 | 값 |
|------|-----|
| 프로젝트 | 밥도둑-꽁밥-행사-수집함 |
| `DOORAY_PROJECT_ID` | `4424523215847914253` |
| Base | `https://api.gov-dooray.com` |
| 인증 | `Authorization: dooray-api ${DOORAY_API_TOKEN}` |

사용하는 endpoint (검증됨):

```
GET /common/v1/members/me
GET /project/v1/projects?member=me&state=active&size=100
GET /project/v1/projects/{PROJECT_ID}/posts?page=N&size=100
GET /project/v1/projects/{PROJECT_ID}/posts/{POST_ID}
```

* Task 의 `users.from` 은 분류 봇이지 원 발신자가 아니다. 원 발신자 · 수신자 · 보낸 시각 · 제목은
  `body.content` 안의 `-----Original Message-----` 블록에서 `parsers/dooray_mail.py` 가 파싱한다.
* `body.mimeType` 이 HTML 이면 `parsers/html_text.py` 로 줄 구조를 살려 텍스트화한다.
* 첨부: `files[]` 와 본문의 `<img src="/files/{id}">` 둘 다 수집한다. `GET …/posts/{id}/files` 는 inline 첨부에서 비어 있을 수 있다.
* **첨부 다운로드 경로 (2026-09-19 실제 토큰으로 검증):**

| 경로 | 결과 |
|------|------|
| `…/posts/{post}/files/{file}?media=raw` | **307 → `file-api.gov-dooray.com` → 200 `image/png`** ✅ |
| `…/posts/{post}/files/{file}` (media 없음) | 404 `{"resultMessage":"null"}` |
| `/files/{file}` (본문 `<img>` 경로) | 404 |

  따라서 `?media=raw` **하나만** 사용한다. 본문의 `/files/{id}` 는 **file id 를 찾는 용도**일 뿐 다운로드 endpoint 가 아니다.
* 307 리다이렉트는 수동으로 따라간다. 토큰을 다시 보내는 기준은 `DOORAY_API_BASE` 에서 유도한 등록 도메인이다.
  `api.gov-dooray.com` → `gov-dooray.com` 이므로 `file-api.gov-dooray.com` 은 신뢰하고, `evil-dooray.com.attacker.net` 같은 유사 호스트나 외부 서명 호스트에는 보내지 않는다.
* 실패해도 첨부는 optional enrichment 이므로 `parse_status=failed` 로만 남고 파이프라인은 계속된다.
  경고에는 서명 URL 이나 토큰 없이 `stage=` / `http=` / `redirected=` 만 찍는다. 예: `stage=request http=404 redirected=no`.
* 첨부가 이미지(8KB 이상, `GGONGBAB_AI_MAX_IMAGE_BYTES` 이하)면 최대 `GGONGBAB_AI_MAX_IMAGES`(기본 2)장을 포스터로 AI 에 함께 보낸다.

---

## 3. Supabase setup

1. 프로젝트를 만들고 `supabase/migrations/001_ggongbab_schema.sql` 을 SQL Editor 또는 `supabase db push` 로 적용한다.
2. Settings → API Keys 에서 **Project URL** 과 **secret key**(`sb_secret_…`) 를 복사해 GitHub Secrets 에 `SUPABASE_URL`, `SUPABASE_SECRET_KEY` 로 넣는다.
3. 모든 테이블은 RLS 가 켜져 있고 정책이 없다. 즉 `anon`/`authenticated` 는 아무것도 읽지 못하고 secret(service role) 키만 접근한다.
4. secret key 는 GitHub Actions / 로컬 `.env` 에만 존재한다. HTML/JS 에 넣지 않는다.
5. **키 이름:** `SUPABASE_SECRET_KEY` 가 우선이고, 비어 있을 때만 예전 이름 `SUPABASE_SERVICE_ROLE_KEY` 를 읽는다(`config.SUPABASE_KEY_ENV`).
   legacy 이름으로 동작하면 실행 로그에 `using legacy SUPABASE_SERVICE_ROLE_KEY` 경고가 한 줄 찍힌다. 새 이름으로 옮긴 뒤 옛 secret 은 지운다.

DB 접근은 `db/supabase_client.py` 가 PostgREST(`/rest/v1`) 로 직접 한다. 별도 SDK 없음.

---

## 4. OpenAI setup

* 공식 Python SDK, **Responses API + Structured Outputs** (`client.responses.parse(..., text_format=EventExtraction)`).
  JSON mode 는 쓰지 않는다. Pydantic 모델의 모든 필드가 required 이고 `None` 을 명시적으로 허용해 strict schema 로 변환된다.
* 모델

| 역할 | env | 기본값 |
|------|-----|--------|
| Primary | `GGONGBAB_AI_MODEL` | `gpt-5.6-luna` |
| Fallback | `GGONGBAB_AI_FALLBACK_MODEL` | `gpt-5.6-terra` |

* Fallback(Terra) 은 **모든 메일에 호출하지 않는다.** `validator.fallback_reasons()` 가 다음 중 하나를 감지할 때만 한 번 더 호출한다.
  `low_confidence`(threshold `GGONGBAB_AI_CONFIDENCE_THRESHOLD`, 기본 0.75) · `date_conflict` · `food_ambiguous` · `rule_conflict` ·
  `missing_essential` · `ai_flagged` · `poster_conflict`. 두 결과 중 검증 문제가 적은 쪽을 택한다(`pick_better`).
* Prompt version: `ggongbab-extract-v2` (`config.PROMPT_VERSION`). `ai_parse_runs.prompt_version` 에 저장되고 **캐시 키의 일부**다.
  프롬프트 의미를 바꾸면 이 값을 올린다. 그러면 저장된 항목이 옛 추출 결과에 고정되지 않고 다음 실행에서 다시 파싱된다.
* System prompt 핵심: 본문/포스터에 **쓰여 있지 않은** 날짜 · 장소 · 음식 · 마감 · URL 을 만들지 말 것, `null`/`unknown` 을 적극 사용할 것,
  `food_provided="true"` 면 `evidence.food` 에 제공 문장을 그대로 인용할 것, `registration_required` 와 `eligibility` 도 명시 근거가 있을 때만 채울 것(8절).

---

## 5. Secrets · 환경 변수

| 이름 | 종류 | 용도 |
|------|------|------|
| `DOORAY_API_TOKEN` | Secret | Dooray API |
| `SUPABASE_URL` | Secret | Supabase project URL |
| `SUPABASE_SECRET_KEY` | Secret | backend 전용. 옛 이름 `SUPABASE_SERVICE_ROLE_KEY` 는 이 값이 비었을 때만 fallback 으로 읽는다 |
| `OPENAI_API_KEY` | Secret | OpenAI |
| `DOORAY_PROJECT_ID` | Variable | 기본 `4424523215847914253` |
| `GGONGBAB_AI_MODEL` / `GGONGBAB_AI_FALLBACK_MODEL` | Variable | 모델 override |

로컬은 `.env.example` 을 `.env` 로 복사해 채운다. `.env` 는 gitignore 되어 있다.
의존성: `pip install -r requirements-ggongbab.txt` (openai, pydantic, pytest).

---

## 6. Database schema

| 테이블 | 공개 여부 | 내용 |
|--------|-----------|------|
| `sources` | private | dooray / kaist_public / manual / portal, priority |
| `raw_items` | private | 수집 원본. `UNIQUE(source_id, external_id)`, `content_hash` index. 발신자 · 원문 · HTML 포함 |
| `attachments` | private | 첨부 메타(`sha256`, `parse_status`). 파일 본체는 저장하지 않음 |
| `ai_parse_runs` | private | 호출마다 model · prompt_version · role(primary/fallback) · parsed_json · 토큰 사용량 · status |
| `events` | export 대상 | 병합된 행사. `status`(draft/published/review/rejected/archived), `needs_review`, `review_reason` |
| `event_sources` | private | `UNIQUE(event_id, raw_item_id)`. 한 행사에 여러 원본 연결 |
| `ingest_runs` | private | 실행마다 seen/new/created/updated/review/ai 카운트 |

`events.food_provided` / `registration_required` 는 `'true' | 'false' | 'unknown'` 텍스트 enum 이다(unknown 을 살리기 위해).

---

## 7. Refresh flow (`pipeline.py`)

1. **collect** — enabled 된 collector 마다 `ingest_runs` 행을 열고 `RawItem` 목록을 받는다. 소스 장애(`CollectorError`)는 기록만 하고 다음 소스로 넘어간다.
2. **idempotency** — `raw_items(source_id, external_id)` 를 찾아 `content_hash` 가 같고 이미 event 에 연결돼 있으면 **AI 를 호출하지 않는다**(`ai_skipped`).
   같은 hash 의 성공한 `ai_parse_runs` 가 있으면 `parsed_json` 을 재사용한다. AI 가 실패한 항목은 raw 만 남아 다음 실행에 다시 시도된다.
3. **sanitize** — `sanitizer.sanitize_for_ai()` 가 이메일 · 전화 · 내선 · 학번 · Dooray member/mention · To/Cc 헤더 · 서명 · 인용 체인을 제거한다.
4. **rules** — `rule_parser.analyze()` 가 날짜(연도 추론 포함) · 시각 · 건물 코드 · **명시적 음식 제공 문구** · URL · 마감 · 행사 여부를 결정적으로 뽑는다.
5. **AI** — Luna 호출 → `validator.fallback_reasons()` → 필요 시 Terra.
6. **validate** — `validator.validate()` 가 AI 결과를 규칙과 대조한다(아래 8절).
7. **dedup / merge** — `dedup.find_match()` 로 기존 event 와 대조. 매치되면 `merge_into()` 로 빈 값만 채우고 충돌은 `needs_review`. `event_sources` 에 연결.
8. **export** — `exporter.build_payload()` → staging 파일 → `validate_content.validate_ggongbab()` 통과 시에만 `latest.json` 교체.

로그에는 카운트만 찍는다. 메일 본문 · 주소 · 토큰은 출력하지 않는다.

```
items: 12 (new/changed 2) | AI parsed: 2 | AI skipped cached: 10 | fallback calls: 1 | AI errors: 0 | events created: 1 | updated: 1 | review: 1 | not events: 0
```

---

## 8. 꽁밥 판정 규칙 (AI + validator 양쪽)

| 문장 | 판정 |
|------|------|
| “참석자에게 점심을 제공합니다” | `food_provided=true` |
| “12시 점심시간에 설명회를 합니다” | 시간 표현일 뿐. `unknown` |

명시적 근거 예: 점심/식사/중식/도시락/간식/다과/커피/피자/샌드위치 **제공**, 식권 **지급**, 케이터링 제공, refreshments/lunch/meal **provided**, 무료 점심.
시간 표현(점심시간, 12시, lunch session)만으로는 근거가 아니다.

validator 가 하는 일:

* AI 가 `true` 인데 `evidence.food` 가 비었거나 제공 문구가 아니면 → `unknown` + `needs_review`.
* 규칙은 제공 문구를 찾았는데 AI 가 `true` 가 아니면 → `needs_review` (+ fallback).
* AI `event_start` 날짜가 본문에서 뽑은 날짜와 다르면 → 시작 시각 폐기 + `needs_review`.
* 건물이 본문 건물 목록과 다르면 폐기. 본문에 건물이 하나뿐이면 규칙 값으로 채움.
* `registration_url` 은 본문에 그대로 있어야 한다. 없으면 폐기 + review.
* 마감일도 본문 날짜와 맞아야 한다.
* 문제가 하나라도 있으면 confidence 를 0.6 이하로 깎는다.

### 신청 여부 (`registration_required`)

“본문에 없음”은 “신청 불필요”가 아니다. 세 값을 모두 유지한다.

| 값 | 필요한 근거 |
|----|-------------|
| `true` | 사전 신청 · 신청 필수/필요 · 등록 필요 · 접수 기간 · 선착순 · RSVP · 신청 링크/폼 · 마감일 |
| `false` | 신청 없이 · 별도 신청 불필요 · 현장 참여 가능 · no registration required · walk-ins welcome |
| `unknown` | 위 어느 쪽도 본문에 없을 때 (기본값) |

AI 가 `false` 라고 해도 명시 근거가 없으면 validator 가 `unknown` 으로 되돌리고 review 사유를 남긴다.

### 참가 자격 (`eligibility`)

**실제 대상 제한**만 기록한다. 예: `KAIST 학부생 대상`, `기계공학과 학생`, `석·박사 과정 학생`, `신입생만`, `외국인 학생 대상`, `선착순 50명`.

`참석자에게`, `참가자`, `방문자`, `attendees`, `everyone` 처럼 **오는 사람을 가리키는 말**은 자격 제한이 아니다 → `null`.
(첫 실제 실행에서 “참석자에게 점심 도시락을 제공합니다”가 `eligibility="참석자"` 로 저장된 회귀. `rule_parser.is_real_eligibility()` 가 막는다.)
본문에 없는 자격 문구도 버린다.

회귀 fixture (`tests/ggongbab/conftest.py`):
“9월 25일 12시 N1에서 기업 설명회를 진행합니다. 참석자에게 점심 도시락을 제공합니다.” → 9/25 12:00, N1, `true`, `lunchbox`.
“9월 25일 12시 점심시간에 기업 설명회를 진행합니다.” → `food_provided != true`.

---

## 9. Dedup

`dedup.score_pair()`:

| 요소 | 점수 |
|------|------|
| 정규화 제목 유사도 (SequenceMatcher ∨ 토큰 Jaccard) | × 0.55 |
| 같은 날짜 / 다른 날짜 | +0.30 / −0.35 |
| 주최 유사 | +0.10 |
| 같은 건물 / 다른 건물 | +0.10 / −0.10 |

임계값 `GGONGBAB_DEDUP_THRESHOLD`(기본 0.72). 후보는 시작 시각 ±3일 안의 event 만 본다.
병합 시 비어 있던 필드만 채우고, `event_start` · `building` · `food_provided` · `registration_url` · `registration_deadline` 이 서로 다르면
기존 값을 유지한 채 `needs_review` 로 올린다. confidence 는 둘 중 큰 값.

---

## 10. Review flow

```
python scripts/refresh_ggongbab.py --review-report
```

```
2 event(s) need review

- [review] 2026-09-26T15:00:00+09:00 · ○○ 채용설명회
    id=… conf=0.6 food=unknown sources=dooray
    reason: 식사 제공 근거 없음 (시간 표현만 있을 수 있음); fallback 사유: food_ambiguous
```

처리는 Supabase 대시보드에서 `events` 행을 고치고 `needs_review=false`, `status='published'` 로 바꾸면 다음 export 에 반영된다.
잘못 잡힌 행사는 `status='rejected'`. 관리자 UI 는 아직 없고 스키마만 준비돼 있다.
GitHub Actions 에서 `workflow_dispatch` → mode `review-report` 로도 볼 수 있다.

---

## 11. Public export (`data/ggongbab/latest.json`)

공개 조건: `status='published'` **and** `needs_review=false` **and** `confidence ≥ GGONGBAB_PUBLISH_CONFIDENCE`(0.7) **and** 만료 아님
(`event_end`(없으면 `event_start`) + `GGONGBAB_EXPIRED_GRACE_HOURS`) **and** 시작이 60일 이내.

```json
{
  "generatedAt": "2026-09-19T12:00:00+09:00",
  "timezone": "Asia/Seoul",
  "count": 1,
  "events": [{
    "id": "uuid", "title": "…", "summary": "…",
    "startAt": "2026-09-25T12:00:00+09:00", "endAt": null,
    "dateText": "9월 25일(목)", "timeText": "12:00",
    "location": {"name": "…", "building": "N1", "room": "101호"},
    "food": {"provided": "true", "type": "lunchbox", "description": "점심 도시락 제공"},
    "organizer": "…", "eligibility": "…",
    "registration": {"required": "unknown", "deadline": null, "url": ""},
    "confidence": 0.97,
    "sources": [{"type": "dooray", "name": "Dooray"}]
  }]
}
```

**tri-state:** `food.provided` 와 `registration.required` 는 **`"true"` / `"false"` / `"unknown"` 문자열**이다. boolean 이 아니다.
“본문에 없음”(`unknown`)을 `false` 로 접으면 “신청 불필요”라는 없는 사실을 만들어 내기 때문이다. `food.type` 은 `provided="true"` 일 때만 채워진다.

**시각:** `startAt` · `endAt` · `registration.deadline` · `generatedAt` 은 모두 **Asia/Seoul(`+09:00`)** 로 내보낸다.
DB 의 `timestamptz` 는 UTC 로 조회되지만(`2026-09-25T03:00:00+00:00`), 공개 피드는 캠퍼스 현지 시각이므로 export 직전에 `exporter.kst_iso()` 가 변환한다(`2026-09-25T12:00:00+09:00`). DB 표현은 그대로 둔다.

절대 포함하지 않는 것: 발신/수신 이메일, raw HTML/text, Dooray ID · task 링크, `/files/…` 첨부 링크, prompt, review_reason, API key.
`validate_content.validate_ggongbab()` 가 이를 정규식 · 키 이름으로 검사하고 실패하면 publish 를 막는다. 검증 항목: JSON · generatedAt · 고유 ID ·
ISO 날짜(**offset 이 반드시 `+09:00`**) · confidence 0~1 · 만료 없음 · URL 형식 · **tri-state 문자열**(boolean 이면 실패) ·
`food.type` 과 `food.provided` 정합성 · private 필드 없음 · 이메일/전화/토큰 패턴 없음 · 같은 날 유사 제목 중복.
`sources[].url` 은 `kaist_public` / `manual` 의 공개 웹 링크만 내보낸다.

---

## 12. Deployment · branches

* 기능 코드(`lab-ggongbab.html`, `css/ggongbab.css`, `js/ggongbab.js`, `scripts/**`)는 **lab 에서만** 개발하고, 공개 반영은 사람이 `main` 에 merge 한다.
* `.github/workflows/ggongbab-refresh.yml` 이 `*/30 * * * *` 로 돈다(정각 보장 없음). cron 은 default branch(main) 의 파일만 읽으므로 **workflow 파일은 main 에 있어야 한다.**
  `content-refresh` 와 같은 concurrency group(`babdoduk-content-refresh`)을 써서 동시에 push 하지 않는다.
* `scripts/publish_generated.py` 의 ALLOWED 에 `data/ggongbab` 이 추가됐다. `latest.json` 만 lab · main 양쪽에 복사되고, 손으로 쓰는 `manual.json` 과 `.staging/` 은 건드리지 않는다.
* 종료 코드 2 = “안전하게 내보낼 것이 없음”(Supabase 불통, 모든 collector 실패, export 검증 실패). 이때 이전 `latest.json` 을 유지하고 publish 단계를 건너뛴다.
* `ggongbab.html`(본편)은 아직 옛 3열 UI 다. lab 검증 뒤 `lab-ggongbab.html` 내용을 옮길 때 `<meta name="robots">`, 상단 lab 리본, `nav.lab` 링크만 빼면 된다.

---

## 13. Frontend (`lab-ggongbab.html`)

* nav · footer · `STR` i18n · `babdoduk-lang` localStorage 정책은 다른 페이지와 동일하다. 페이지 전용 문자열은 `gg.*` 키.
* `js/ggongbab.js` 가 `fetch('data/ggongbab/latest.json', {cache: 'no-store'})` 로 읽고 loading(skeleton) / error(재시도 버튼) / empty 상태를 각각 그린다.
* 세로 피드: 날짜 헤더(오늘/내일 배지) → 카드(시각 · 제목 · 건물/호실 · 지도 링크 · 음식 태그 · 사전 신청 · 마감 · 요약 · 신청/원문 버튼).
* **tri-state 표시:** `true` 만 「식사 제공」/「사전 신청」으로, `false` 는 「식사 없음」/「신청 없이 참여」로, `unknown` 은 점선 테두리의 「식사 여부 미확인」으로 그린다.
  `unknown` 을 `false` 처럼 보여 주지 않는다. 옛 boolean payload 도 `tri()` 가 받아 준다.
* 필터: 기간(오늘/내일/이번 주/전체 예정) × 음식(전체/식사/간식/다과). 선택은 `babdoduk-ggongbab-filter` 에 저장.
* 모든 시각은 KST 로 계산한다(뷰어 시간대 무관). 지도는 카드 안 Google Maps 검색 링크로만 제공(보조 기능).
* 가로 캐러셀 없음. 페이지 전체가 세로 스크롤.

---

## 14. Privacy

* 원문 메일은 `raw_items` 에만 있고 service role 로만 읽을 수 있다.
* AI 에는 sanitize 된 제목 · 본문 · 메일 날짜 · 포스터 이미지만 간다. 수신자 목록 · 발신 주소 · Dooray ID 는 가지 않는다.
* 공개 JSON 은 11절의 검증을 통과해야만 나간다.
* GitHub Actions 로그에는 카운트와 에러 클래스명만 찍힌다.

---

## 15. Debugging

| 증상 | 확인 |
|------|------|
| 서비스 연결 확인 | `python scripts/refresh_ggongbab.py --check` |
| 수집만 확인(외부 서비스 없이) | `python scripts/refresh_ggongbab.py --dry-run --only kaist` |
| 특정 소스만 | `--only dooray` / `--only manual` |
| DB 만 내보내기 | `--export-only` |
| 리뷰 대기 | `--review-report` |
| AI 비용 | Supabase `ai_parse_runs` 의 `usage_input_tokens`, `usage_output_tokens`, `model`, `role` |
| 같은 메일이 계속 AI 를 태움 | `raw_items.content_hash` 가 매번 바뀌는지, `event_sources` 연결이 있는지 |
| 행사가 안 보임 | `events.status`, `needs_review`, `confidence`, 만료 여부 → 11절 조건 |
| 한글이 깨져 보임 | **파일이 아니라 콘솔 문제다.** 아래 UTF-8 항목 참고 |
| 두 번째 실행인데 AI 가 다시 돌았다 | `PROMPT_VERSION` 을 올렸거나 `content_hash` 가 바뀐 것이다. `ai_parse_runs.prompt_version` 비교 |
| 첨부가 계속 실패 | 경고의 `stage=` / `http=` / `redirected=` 확인. 2절의 검증된 경로표와 대조 |
| 테스트 | `python -m pytest tests/ggongbab -q` |
| 공개 JSON 검증만 | `python scripts/validate_content.py` |

### UTF-8: 파일은 멀쩡하고 콘솔이 문제다

`type data\ggongbab\latest.json` 으로 보면 한글이 `湲곗뾽 ?ㅻ챸??` 처럼 보일 수 있다.
이는 Windows 콘솔 코드 페이지(기본 949)가 UTF-8 바이트를 cp949 로 읽어서 생기는 **표시** 문제다. 파일은 정상이다.

확인 (2026-09-19 실측):

```python
from pathlib import Path
import json
raw = Path("data/ggongbab/latest.json").read_bytes()
data = json.loads(raw.decode("utf-8"))            # UTF-8 로 디코드됨, BOM 없음
t = data["events"][0]["title"]
print(t.encode("unicode_escape"))                  # b'\uae30\uc5c5 \uc124\uba85\ud68c' = 기업 설명회
```

코드 쪽은 이미 `json.dumps(..., ensure_ascii=False)` + `write_text(..., encoding="utf-8")` 이므로
**인코딩 변환을 추가하지 마라.** 이중 인코딩만 생긴다. 콘솔에서 제대로 보려면:

```cmd
chcp 65001
type data\ggongbab\latest.json
```

PowerShell 은 `Get-Content data\ggongbab\latest.json -Encoding utf8`, 파이썬 출력은 `set PYTHONIOENCODING=utf-8`.
회귀 테스트: `tests/ggongbab/test_export_contract.py::test_utf8_json_roundtrip_is_real_korean`.

KAIST 공개 collector 가 읽는 게시판(2026-09-19 마크업 기준): 학사공지 `kr/html/footer/0802.html`, 문화행사 `kr/html/campus/053501.html`.
마크업이 바뀌면 `collectors/kaist_public.py` 의 정규식과 `tests/ggongbab/test_pipeline_export.py::test_kaist_public_parsers_and_filter` 를 같이 고친다.
