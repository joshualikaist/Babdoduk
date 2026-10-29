# 인스타 레이더 도입 후 점검·효율 감사

점검 시각: 2026-10-29 23시대 KST. 코드 기준 `origin/lab` e6130a1ae2a6db87c17c4aa6680819c68035e41b, `origin/main` 455c041570d5c92d7064b50420ef85dccca4a4c6. 운영 정보는 같은 시각의 스냅숏이며 파일명 날짜는 요청대로 유지했다. 파일·서비스·계정에는 변경을 가하지 않았다. 이 보고서만 별도 작업 트리에 작성한다.

## 한눈에

1. **확인 필요** — 두 브랜치의 정적 피드에 문제 두 건의 검색어가 없지만, 피드가 오확정 전인 10-29 04:24 KST에 생성됐다. **다음 갱신 뒤 다시 확인 필요**; 삭제 후의 실제 공개 여부는 미확인이다.
2. **확인 필요** — 수정된 서비스는 실행 중이며 로그 오류와 현재 상태 이상은 없으나, 재시작 이후 신규 자동 확정 0건이어서 무시각 차단의 실운영 사례가 없다. 사람이 매긴 최신 네 예시는 모두 현재 거절과 일치하나 세 예시가 같은 게시물이다.
3. **문제** — 현 구조는 인스타 원본이 두레이 출처로 보이고 원본 링크를 공개하지 않는다. 계약·수집·DB·화면 변경은 소유자 승인 필요다.
4. 효과 순 상위 5개(추정치는 아래 가정 참조): ① 운영 이미지 보존 정책(현재 약 92 MiB, 증가 억제), ② Chrome 캐시 약 96 MiB 후보 조사(로그인 유지 미확인), ③ 초기 이미지 다운로드의 제한된 병렬화·시간 예산(첫 실행 약 33분), ④ 테스트 병목 분리와 재사용(아래 측정), ⑤ 홈·월드컵 이미지에서 기존 WebP 크기 활용(예시 각각 77 KB·118 KB 차이; 실제 전송 절감은 미측정).

## 1. 삭제된 두 건과 공개 스냅숏

`git show origin/{lab,main}:data/ggongbab/latest.json` 각각을 JSON으로 읽고 원문에 `대학원 입학예정자 오리엔테이션`, `G-inK 환경소통창구`, `엔제리너스`, `De9Af2IEq8u`, `DfCRCEskwzw`, `4454148888659858349`, `4454148913657667791`을 검색한 결과, 두 브랜치 모두 각 검색어 0건, 이벤트 10건이다. 두 파일의 `generatedAt`은 **2026-10-29 04:24:19 KST**다.

`git log -1 --format='%H %aI %cI %an' <ref> -- data/ggongbab/latest.json`:

| 브랜치 | 마지막 파일 변경 커밋 | 커밋 시각 KST |
| --- | --- | --- |
| lab | `af8b47e79ff79991558cd0e1f13fe55ae37f1f24` | 2026-10-29 04:24:27, babdoduk-content-bot |
| main | `cf588c9722e53dda475a6bd7c5ae992da1d69cc1` | 2026-10-29 04:24:30, babdoduk-content-bot |

두 스냅숏 모두 22:18 이후 갱신이 없으므로 결과는 사전 스냅숏에서의 부재만 뜻한다. 공개 JSON의 10건은 모두 `dooray`로 표기되어 실제 인스타 유래 여부를 판별할 수 없다. DB에서 현재 `human_confirmed`·`auto_confirmed`는 0건이며, 이 사실만으로 다른 경로나 공개 DB에 게시된 행사가 없다고 단정할 수 없다. 실 사이트, 공개 DB 및 Dooray는 요청대로 접속하지 않았다.

## 2. 운영 레이더

`git -C ~/Babdoduk-ops log -1`은 `577497fdca1903b593b14d9a431f2bdd2198d10e`; `git merge-base --is-ancestor 577497f HEAD` 종료 0. `systemctl --user show babdoduk-ig-radar.service -p ActiveEnterTimestamp -p ActiveState`: `active`, 2026-10-29 22:46:20 KST.

`.local/ops-ig-radar.log`의 재시작 이후 주기(시각 KST):

| 시각 | 코드 | counts |
| --- | --- | --- |
| 22:46:36 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 22:51:38 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 22:56:50 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:02:03 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:07:24 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:13:01 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:18:11 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:23:38 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:28:58 | IG_RADAR_CYCLE_OK | 기록 없음 |
| 23:34:22 | IG_RADAR_CYCLE_OK | 마지막 상태: month_cost_usd 0.1288 |

23:34 상태 JSON은 마지막 값만 보존한다(`observed=1793284462.134`, `slow_factor=1`, `backoff_until=0`). 이전 사이클별 counts는 로그와 상태 JSON에서 복원할 수 없다. `rg 'IG_[A-Z_]*(FAILED|RATE_LIMITED|TOKEN_INVALID|MODEL_UNAVAILABLE|OPENAI_ERRORS)' .local/ops-ig-radar.log` 0건. 코드가 없다는 것은 그 로그 범위에서의 관찰이며 외부 API의 현재 건강성을 뜻하지 않는다.

SQLite는 `sqlite3.connect('file:/home/joshuali/Babdoduk-ops/.local/ig-radar.sqlite3?mode=ro', uri=True)`로만 읽었다. 기준 시각은 `1793281580.0`(22:46:20 KST). `updated_at`은 최초 판정 시각이 아니라 마지막 수정 시각이고 판정 이력 전체가 아니므로 아래 쿼리는 현재 행의 관찰에 한정된다.

```sql
SELECT count(*) FROM food_event_candidates
 WHERE status='auto_confirmed' AND updated_at>=1793281580
 AND coalesce(json_extract(extraction_json,'$.start_at'),'')=''
 AND coalesce(json_extract(extraction_json,'$.end_at'),'')=''; -- 0
SELECT count(*) FROM food_event_candidates
 WHERE status='auto_confirmed' AND updated_at>=1793281580; -- 0
SELECT count(*) FROM food_event_candidates
 WHERE status IN ('pending_human','queued_digest')
 AND coalesce(dooray_post_id,'')<>''; -- 0
SELECT status,count(*) FROM food_event_candidates GROUP BY status;
-- auto_rejected 78, expired 31, human_rejected 2
SELECT status,active,count(*) FROM ig_accounts GROUP BY status,active; -- ok, 1, 32
SELECT username,status FROM ig_accounts WHERE status<>'ok'; -- 0행
SELECT count(*),max(max_percent) FROM api_usage_log; -- 41, 38.0%
SELECT count(*),sum(cost_usd) FROM analysis_runs WHERE created_at>=1793199600;
-- 10-29 KST 하루: 103, 추정 $0.1288107
```

`human_reviews`를 `ig_posts` 및 `food_event_candidates`와 `media_id`로 조인해 `r.id DESC`로 확인했다. 최신 4행은 `De9Af2IEq8u` reject 1건(정정 메모 있음), `DfCRCEskwzw` reject 3건이며 두 후보의 현재 상태는 모두 `human_rejected`다. `store.recent_labels()`도 같은 조인·역순·4개 제한이며 `analyze.user_content()`는 action을 판정 문구로 변환하므로 네 예시는 모두 현재 판정과 맞는다. 같은 게시물의 중복 3건이 다양성을 줄이며 최신 상태가 달라진 이후에도 이전 action이 노출될 수 있는 구조는 별도 검토가 필요하다. 캡션과 메모 전문은 옮기지 않았다.

수정 코드 `radar.py`는 무시각 confirm을 ask로 바꾸고, bridge는 생성 직전 후보를 다시 읽는다. 합성 테스트 `tests/ggongbab/test_instagram_radar.py`에 재읽기와 판정 테스트가 있다. 재읽기와 외부 생성은 원자적 트랜잭션은 아니다. 이후 실제 신규 사례가 없어 실제 무시각 질문·재읽기 경쟁 상황·프롬프트의 오탐 억제는 검증되지 않았다.

## 3. 인스타 출처 및 원본 링크: 조사만

- `scripts/ggongbab/instagram/radar.py`의 bridge는 제목·본문에 원본을 넣어 Dooray 업무를 만든다. `scripts/ggongbab/collectors/dooray.py`는 `RawItem(source_type="dooray")`를 만든다. 단순 제목 문자열만 신뢰해 임의의 Dooray 업무를 Instagram으로 재분류하면 출처 위조 위험이 있다. 신뢰할 수 있는 원본 표식·퍼머링크 검증·중복 병합 시 출처 연결 설계가 선행돼야 한다.
- `scripts/ggongbab/db/repository.py`, 원본 모델·수집/파이프라인, `scripts/ggongbab/exporter.py`: 검증된 인스타 원본과 URL을 보존·병합하고 공개 허용한다. 현재 exporter는 URL을 `kaist_public`·`manual`에만 남긴다. canonical DB source enum/seed 및 기존 행 호환이 필요할 수 있으므로 마이그레이션 영향도 검토한다.
- `schemas/ggongbab-feed.schema.json`, `schemas/ggongbab-archive.schema.json`, `schemas/content-labels.schema.json`, `scripts/validate_content.py`의 `GG_SOURCE_TYPES`·`GG_PUBLIC_URL_SOURCES`와 URL/개인정보 검증을 함께 변경해야 한다. `data/content/labels.json`에 `sources.instagram`과 표시 그룹의 한국어·영어를 추가하고 `scripts/sync_site_chrome.py`로 해당 `gg.source.*`, `home.cal.src.*`를 생성한다. 독립 문자열은 `i18n/ko.json`, `i18n/en.json`에 추가한다.
- `js/ggongbab.js`의 `sourceLabel`과 원본 링크 필터, `js/home-calendar.js`의 출처 키 및 링크 필터를 바꿔야 한다. 출처 우선순위·여러 원본과 안전한 링크 처리를 정의한다.
- lab 공개 DB 경로도 고려해야 한다. `scripts/ggongbab/public_feed.py`, `js/ggongbab-public-feed.js`, `supabase/migrations/004_ggongbab_public_feed.sql`의 source_types 허용 집합 및 현재 URL을 담지 않는 투영 계약을 함께 검토해야 한다. DB 변경·공개 계약·수집기는 보호 경계다.
- `tests/ggongbab/`의 수집·출처·export·validator·공개 투영·프런트 테스트에 합성 인스타 정상/위조 표식/비공개 URL/중복/KO·EN·기존 Dooray 사례를 추가한다. **모두 소유자 승인 필요, 이번에는 변경하지 않음.**

## 4. 저장 공간과 효율

| 항목 | 위치 | 현재 크기·시간 | 근거 | 제안 | 위험 | 분류 |
| --- | --- | --- | --- | --- | --- | --- |
| 레이더 이미지 | 운영 `.local/ig-media/` | `du` 92 MiB, 파일별 합 약 90.8 MiB | `save_images` → `save_image`; 삭제·상한 검색 0건; 상태별 아래 참조 | 최종 거절·만료 후 7일 등 승인된 TTL; 링크·판정·리뷰는 보존, 중복 해시 참조 확인 | 늦은 사람 재검토·재분석·첨부에 이미지 필요 | 소유자 승인 필요 |
| Chrome 캐시 | 운영 `.local/ops-browser-profile/` | Cache 73 MiB, Code Cache 19 MiB, GPU·shader 등 약 4.7 MiB | `find`로 디렉터리 크기만 조회 | 로그인 유지와 Chrome 재생성 동작 검증 후 별도 결정 | 세션 손실 여부 확인 필요 | 소유자 승인 필요 |
| 첫 이미지 수집 | `instagram/radar.py`, `meta_graph.py` | 첫 서비스 사이클 21:45:48–22:18:50 약 33분 | 이미지 순차, 각 요청 timeout 30초, 15 MiB 상한; 계정 API 2초 간격 | 계정별 API 호출 속도는 유지; CDN 전용 소수 동시 작업·전체 시간 예산·실패/만료 URL 재시도 정책을 합성 테스트와 함께 설계 | CDN 및 API 제한, 순서·메모리·누락 위험. 33분 중 다운로드 비중은 계측되지 않음 | 코드 변경 필요 |
| 사람 판정 예시 중복 | `instagram/store.py`, `analyze.py` | 최신 4개 중 같은 거절 3개 | 리뷰 SQL 및 action 역순 LIMIT 4 | 게시물별 최신 리뷰로 선택하고 정정·재판정 테스트 | 잘못된 예시 또는 예시 다양성 손실 | 코드 변경 필요 |
| 이미지 전송 | `index.html`, `js/worldcup.js` | 찌개 JPG 129,661 B vs 기존 520px WebP 52,682 B; manakish JPG 144,550 B vs 320px WebP 26,632 B | `srcset`과 동적 썸네일은 이미 존재 | 실제 표시 폭·DPR·네트워크를 측정해 적정 variant 활용 | 예시 차이 76,979 B / 117,918 B는 대체 가능 상한일 뿐 실제 절감 아님; 화질과 visual baseline | 코드 변경 필요 |
| 추적 캐시 | Git 추적 파일 | 0개 | `git ls-files`에서 `__pycache__`, `.pytest_cache`, `.pyc`, `.pyo` 검색 | 조치 없음 | 무시된 로컬 캐시는 별개 | 바로 정리 가능 |
| 오탐 미참조 후보 | `tests/fixtures/ggongbab/gold/seed-v0.jsonl` | 11,055 B | 파일명 `rg -F` 0건이나 `scripts/eval_ggongbab.py`가 `*.jsonl` glob, `test_gold_eval.py`가 소비 | 삭제하지 말 것 | gold 검증 손실 | 미확인 |
| 오탐 미참조 후보 | `tests/fixtures/ggongbab/{misses,dedup}/` | 각각 3,132 B / 1,627 B | 파일명 `rg -F` 0건이나 `test_miss_registry.py`, `test_dedup_slot.py`가 glob 로드 | 삭제하지 말 것 | 테스트 근거 손실 | 미확인 |
| 동적 코드 | `scripts/windows/ggongbab_workers.py` 및 Python 모듈 | 문자열 검색만으로 판정 불가 | PowerShell이 `watch`·`radar` 액션 호출; 모듈은 파일명 대신 import | CLI/동적 import/스케줄·외부 소비까지 확인한 후 판단 | 실제 운영 경로 삭제 | 미확인 |
| 연구 데이터 | `research/magazine/` | 4.5 MiB | registry·discovery 실행 기록 등 데이터. `docs/DATA.md`에서 generated research로 분류 | 유지 | provenance와 재현성 손실 | 소유자 승인 필요 |
| 페이지 중복 | `food.html`, `lab.html`, `history.html` 등 | 페이지별 inline style/script 존재 | 공통 메뉴·푸터·번역은 sync 생성이며 제외. 비공통 정확 일치 스타일 4개 이상인 페이지 쌍은 단순 정규화 조사에서 없음 | 실제 공통 기능과 변화 시점이 확인된 후만 통합 | 페이지별 차이 및 lab-only 경계 | 미확인 |
| DB 증가 | 운영 `.local/ig-radar.sqlite3` | 파일 1.2 MiB; 게시물 111, 분석 103, 사용량 41, 이미지 참조 457 | 쿼리 아래 | 장기 수집 후 일일 증가량·DB 페이지별 크기 관측. raw_json의 만료 서명 URL 보존 필요성 검토 | 근거·재현성 삭제 | 소유자 승인 필요 |
| 로그·상태 | `scripts/ggongbab/ops_storage.py`, `web/state.py` | ops 로그 각 4–108 KiB 할당, mail-state 172 KiB, portal-list-state 36 KiB | SafeLog 각 파일 5 MiB + 백업 3개; atomic_json은 교체이지 상한 아님. mail state는 호출 시 400일 prune | 상태별 크기와 prune 호출을 관찰 | ledger 삭제 시 재처리 위험 | 소유자 승인 필요 |

리터럴 경로 또는 파일명 검색에서 스크립트 37개와 fixture 4개가 후보로 나왔지만 Python import, CLI 및 glob를 놓친다. 예를 들어 `portal_discovery.py`와 `instagram/analyze.py`는 import되어 사용 중이다. `images/home/`은 0개 후보, worldcup 이미지·썸네일은 데이터와 조합된 경로로 소비된다. `research/magazine/`은 생성 연구 데이터다. 조사 범위에서 **삭제 가능한 추적 파일이나 죽은 Python·JS 코드를 확정하지 못했다**. 모든 동적 소비자와 외부 호출에 대한 완전한 증명은 하지 않았다.

### 운영 PC 저장공간 및 보존 계산

`du -sh ~/Babdoduk-ops/.local`은 433 MiB, 그중 Chrome 프로필 340 MiB, ig-media 92 MiB. 프로필 내부는 크기만 확인했고 로그인 세션이나 내용을 읽지 않았다. 크기는 디스크 할당량(`du`), DB 이미지별 수치는 논리 바이트이므로 합이 정확히 같지 않다.

DB의 이미지 참조를 상태별 해시로 묶고 존재하는 경로의 파일 크기만 합하면 `auto_rejected` 309개 75,792,127 B, `expired` 137개 17,240,628 B, `human_rejected` 10개 2,205,338 B다. 해시 중복은 상태 간에도 가능해 이 수치를 무조건 더해 삭제 가능량으로 취급하지 않는다. `ask_pending`은 첫 이미지를 텔레그램에, `bridge`는 확정 게시물의 최대 6개를 두레이에 사용하고 `analyze`도 이미지를 사용한다. 이 시점의 최종 거절·만료는 일반 사이클에서 재전송하지 않지만 Telegram 버튼을 통한 후속 상태 변경이나 재분석 가능성이 있으므로 TTL은 유예와 재검토 정책이 필요하다. 콘텐츠 주소 SHA를 공유하는 파일은 **모든** 참조가 제거 가능할 때만 후보로 삼아야 한다. permalink·판정·사람 리뷰·필요한 근거 메타데이터는 남긴다.

한 달 추정은 관측不足: 111 게시물 중 90건은 09시 첫 시험 백필, 21건은 21–22시 수집이다. 이미지가 09시 약 68.6 MiB, 이후 약 22.1 MiB로 첫날 자료는 일일 정상 증가율이 아니다. 시나리오 계산만 하면 증가 0이면 약 433 MiB, 매일 신규 92 MiB가 계속되면 30일 뒤 약 3,193 MiB(433+30×92; DB·프로필 변동 제외). 7일 TTL이 신규 최종 자료 모두에 적용되고 매일 92 MiB가 일정하다는 가정이면 정상 상태 약 341+7×92=985 MiB. 실제 시작 백필, 미결/확정 보존, 중복, 수집량, 재검토가 달라지면 달라진다. 오늘 당장 삭제 가능한 양이나 예측치가 아니다.

`SELECT count(*),sum(length(raw_json)),min(fetched_at),max(fetched_at) FROM ig_posts`는 111행, 441,526 문자; `analysis_runs`는 103행, `sum(length(result_json))` 70,946 문자다. 09시·21–22시 백필이 섞여 일일 성장률 산정 불가. 사용 로그 41행도 단일일 관찰이다. raw_json은 길이만 집계하고 내용을 보고서에 복사하지 않았다.

### 페이지별 정적 자원 무게

HTML 파싱으로 직접 선언된 로컬 외부 JS·CSS·`img src`를 파일별 중복 제거하여 **비압축 바이트**를 합산한 정적 상한성 목록이다. HTML 안의 스타일/스크립트는 HTML에 포함된다. 요청 실제량은 아니다: `srcset`, lazy/hidden, 런타임 이미지, JSON, 폰트, 외부 SDK, 캐시·압축·화면 크기·랩 공개 DB 경로에 따라 다르다.

| 페이지 | HTML | JS | CSS | img src | 합계 B |
| --- | ---: | ---: | ---: | ---: | ---: |
| index | 35,745 | 90,303 | 58,854 | 372,337 | 557,239 |
| ggongbab | 20,079 | 99,235 | 40,400 | 0 | 159,714 |
| lab-ggongbab | 19,980 | 99,235 | 40,400 | 0 | 159,615 |
| mukbang | 41,775 | 73,158 | 42,322 | 0 | 157,255 |
| worldcup | 278,648 | 147,902 | 68,809 | 0 | 495,359 |
| event | 38,527 | 12,586 | 42,879 | 0 | 93,992 |
| history | 21,179 | 5,312 | 19,820 | 66,149 | 112,460 |
| food | 49,658 | 5,312 | 19,820 | 0 | 74,790 |
| lab | 39,384 | 5,312 | 19,820 | 0 | 64,516 |
| choose | 637 | 0 | 0 | 0 | 637 |

추가 JSON 예: 홈의 latest 14,836 B + archive 6,774 B + 매거진 index 932 B + 해당 날짜 14,435 B = 36,977 B; 꽁밥의 latest + archive + news 128 B = 21,738 B. 매거진과 선택기, 월드컵의 JSON·이미지는 조건부/동적이며 음식 catalog 991 B와 7개 pack 총 895,014 B를 모두 받는 경로가 있을 수 있다. 페이지별 실제 최초 로딩의 JS·CSS·JSON·이미지 합계는 브라우저 네트워크 측정이 없어 **미확인**이다. HTML 합은 전송보다 넓은 지표며 외부 자원과 동적 자원은 제외했다.

### 검증과 테스트 시간

첫 명령 `PYTHONDONTWRITEBYTECODE=1 BABDODUK_CHROME_VISUAL=skip python -m pytest tests -o addopts='' -q -p no:cacheprovider --durations=30`은 `python: command not found`, exit 127로 테스트를 시작하지 못했다. 재시도에 `~/Babdoduk-ops/.venv/bin/python` 인터프리터만 사용했다(운영 checkout을 테스트 대상으로 쓰지는 않음). 결과 **2401 passed, 6 skipped, 389.06초, exit 0**. `BABDODUK_CHROME_VISUAL=skip`은 공유 chrome 이미지 기준 비교를 생략한다. 그 외 브라우저 기반 테스트는 실행됐지만 이것은 배포된 사이트 검증이 아니다. `-p no:cacheprovider`는 로컬 pytest 캐시 생성을 억제하기 위한 설정이다.

`--durations=30` 실측(괄호는 초, 전부 call 단계):

1. `test_site_ui.py::test_all_public_pages_windows_scrollbars_and_overflow` 308.14 — `run_checks()`는 10개 페이지 × 5개 크기와 추가 상호작용·guardian을 검사한다. 가장 큰 비용의 근거는 반복 브라우저 렌더링이며 개별 하위 단계별 계측은 없다.
2. `test_home_calendar.py::test_the_last_second_and_the_first_second_of_a_month` 3개 날짜 매개변수 1.70, 1.67, 1.63.
3. `test_e2e_ggongbab_flow.py::test_every_fixture_follows_its_expected_path_from_mail_to_card` 1.61.
4. 홈 달력 `test_giveaway_rows_name_no_food_and_lead_with_a_deadline` 1.09, `test_month_navigation_bounds_and_return_to_today` 1.04, `test_selected_future_and_past_days` 1.04, `test_giveaway_english_strings` 1.03.
5. `test_alerts.py::test_the_alert_file_stays_readable_and_recovers_from_an_oversized_one` 1.01.
6. `test_web_agent.py`의 `test_D_identity_provider_still_blocks`, `test_unrendered_page_is_ignored`, `test_other_host_is_ignored`, `test_timeout_message_says_what_was_last_seen`, `test_log_reports_the_identity_provider_only_from_a_real_url`, `test_closed_popup_is_ignored`, `test_E_root_flash_then_idp_is_not_a_login`, `test_case3_root_flash_is_not_mistaken_for_login`, `test_timeout_reports_context_escape`, `test_setup_timeout_lists_what_was_seen`, `test_detection_timeout_is_restored_even_on_timeout`, `test_timeout_recommends_the_resident_mode`는 각각 1.00.
7. 홈 달력 `test_a_deadline_only_draw_on_the_last_day_is_live_until_its_deadline` 0.96, `test_rows_open_inline_one_at_a_time` 0.96, `test_keyboard_follows_the_date_grid_pattern` 0.96, `test_english_strings` 0.95, `test_links_are_public_only_and_first_come_is_never_inferred` 0.95, `test_markers_live_past_multiple_and_labels` 0.93, `test_today_with_events_is_selected_and_counted` 0.92, `test_rendered_grid_is_sunday_first_with_muted_overflow` 0.92.

절감 제안: 먼저 `run_checks()` 내부의 페이지·크기·guardian·상호작용별 시간과 페이지 로드/대기 비용을 계측하고, 동일 환경에서 브라우저/서버/fixture 재사용 및 독립 시나리오의 자원 제한 병렬화를 검토한다. 결과 안정성·상태 격리·동일한 KO/EN/뷰포트/접근성 보장을 검증한다. 일부 1초 테스트는 timeout 경로일 가능성이 있으나 원인별 추가 계측 전 단정하지 않는다. 단언을 줄이거나 테스트를 삭제하지 않는다.

별도 검사 최초 결과: `~/Babdoduk-ops/.venv/bin/python scripts/validate_content.py` exit 0, `content validation ok`; 같은 Python으로 `scripts/sync_site_chrome.py --check` exit 0, `site chrome in sync: 9 pages, 4 scripts`. validator 실행에서 작업 트리에 무시된 Python bytecode 캐시 네 디렉터리가 생겼다. 요청의 삭제 금지에 따라 그대로 두었다.

## 5. 확인하지 못한 것

- 22:18 이후 실제 피드 갱신, 배포된 lab/production의 화면, 공개 DB 또는 Dooray의 현재 상태: 실서비스 호출 금지와 오래된 스냅숏 때문이다. 다음 갱신 뒤 두 브랜치를 재확인해야 한다.
- 재시작 뒤 신규 자동확정·실제 Telegram 질문·경쟁 조건, 새 프롬프트 정확도: 관찰할 신규 사례가 없다. API 실제 상태도 호출하지 않았다.
- 사이클별 과거 counts: 상태 JSON은 마지막 사이클만 갖고 로그에는 코드만 있다.
- Chrome 캐시 삭제 시 로그인 유지; 이미지 TTL의 안전성과 장기 성장률; URL 만료 뒤 재수집 가능 여부: 운영 상태 변경·외부 호출을 하지 않았다.
- 브라우저 네트워크에서 실제 페이지별 최초 전송량, 이미지별 렌더 크기·화질, 모든 외부/동적 파일 소비, JS/Python 죽은 코드 전수 증명: 정적 조사만 수행했다. 스냅숏의 다른 인스타 유래 행사도 현재 출처 필드로 구분하지 못한다.
- 정적 조사에서 홈 이미지 원본과 썸네일의 크기 차이는 측정했지만, 기존 srcset이 선택되는 실제 상황은 확인하지 않았다. 생성 데이터나 기준 이미지는 불필요한 파일로 분류하지 않았다.

## 6. 끝 상태와 인계

- 작업 트리 `/home/joshuali/workspaces/Babdoduk-wt/codex-check`, 브랜치 `agent/codex/radar-check`, 시작 HEAD `e6130a1ae2a6db87c17c4aa6680819c68035e41b`. 이 보고서 한 파일만 커밋; 정확한 결과 커밋 SHA는 `git rev-parse HEAD`와 인계 메시지에서 확인한다(커밋 안에 자신의 SHA를 고정해서 넣을 수 없음). 푸시하지 않는다.
- 최초 원본 checkout: `main` 92900522dda3af160be9ebae7e8ef18813bbbd2b, clean, origin/main 대비 0 ahead / 54 behind; 사전 stash 0개, 다른 worktree 4개, 인덱스 잠금/진행 중 merge·rebase 없음. 다른 작업 트리는 건드리지 않았다.
- 마지막 fetch 기준 `origin/lab` e6130a1ae2a6db87c17c4aa6680819c68035e41b, `origin/main` 455c041570d5c92d7064b50420ef85dccca4a4c6: 시작과 변화 없음. main에만 있는 `455c041`, `8c7fdd5`, `cf588c9`은 모두 `babdoduk-content-bot` 생성 데이터 커밋이다. 소스 drift는 없다. 별도 브랜치에서 보고서만 한 커밋 ahead 예정.
- `git status --short`는 커밋 전 `?? reports/`, 커밋 후에는 비어 있어야 한다. `git status --short --ignored`에서 이번 검사로 생긴 `scripts/__pycache__/`, `scripts/discovery/__pycache__/`, `scripts/ggongbab/__pycache__/`, `scripts/ggongbab/parsers/__pycache__/`가 보인다. 삭제 금지에 따라 남겼으며 추적·커밋하지 않는다.
- 단계: 보고서 전용 task branch. lab 통합·배포·소유자 승인·main 반영·back-sync는 수행하거나 요청받지 않았다. 보호 경계와 운영 정리는 별도 소유자 승인 후 진행한다.
