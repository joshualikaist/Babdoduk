# 방문 수와 이용 통계

소유자 요청(2026-11-20): "내 사이트를 언제 제일 많이 이용하는지, 어디 콘텐츠가 반응이 좋은지. 별 누르는 꽁밥이
무엇인지" → 처리방침을 고친 뒤 **누구인지 알아볼 수 없는 합계만** 만든다("오케이").

## 무엇을 세나

| 부분 | 파일 | 하는 일 |
| --- | --- | --- |
| 방문 수 표 | `supabase/migrations/018_visit_counts.sql` | `visit_counts`: 한 시간 단위로 사이트·페이지·언어·휴대폰/태블릿/컴퓨터별 페이지 연 횟수. 사람·주소·쿠키·계정·브라우저 정보 열이 없다. 브라우저 역할은 `count_visit` 함수로만 1을 더하고, 읽기는 백엔드 키만. 셀 수 있는 페이지는 `visit_pages` |
| 세는 곳 | `api/visit.js` | `POST /api/visit` 를 받아 요청의 호스트가 우리 세 사이트일 때만 `count_visit` 를 부른다(공개 키). 주소·쿠키·브라우저 정보는 넘기지 않고, 검색 로봇은 세지 않으며, 언제나 204 |
| 페이지 | `js/site.js` | 페이지를 열 때 한 번 `navigator.sendBeacon('/api/visit', {page, lang, device})`. 자동화된 브라우저, 추적 거부(Do Not Track, Global Privacy Control), `?nocount=1` 로 끈 기기(소유자 휴대폰; `?nocount=0` 으로 다시 켬)는 보내지 않는다 |
| 보고서 | `scripts/usage_stats.py` | 방문 수, 별 누른 꽁밥, 알림 켠 꽁밥, 먹킷리스트, 메뉴 뽑기·월드컵 합계를 한국어 표로 |

## 보고서 보기 (운영 컴퓨터, 소유자가 실행)

```bash
cd ~/Babdoduk-ops && .venv/bin/python scripts/usage_stats.py report            # 최근 28일, 실제 사이트
cd ~/Babdoduk-ops && .venv/bin/python scripts/usage_stats.py report --days 7 --site lab --out .local/stats/week.md
```

백엔드 키(`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, 환경 또는 `.env`)를 `scripts/pick_stats.py` 와 같은 방식으로 읽고
출력하지 않는다. 읽는 표와 열은 `READS` 에 정해져 있고(별은 `event_id, saved_at` 만, 먹킷리스트는 `place_id, status`
만, 알림은 `events` 만), 계정·메모·기기 주소는 읽지 않는다. 사람이 저장한 내용에서 나온 숫자는 5 미만이면
"5 미만"으로만 보인다(처리방침 2번). 꽁밥 제목은 이 사본의 공개 파일(`data/ggongbab/latest.json`, `archive/index.json`)에서 찾는다.

새 페이지를 만들면 `python scripts/usage_stats.py pages` 로 `visit_pages` 에 넣는다(넣기 전에는 그 페이지가 세지지 않는다;
`tests/test_usage_stats.py` 가 018의 목록과 페이지 파일이 같은지 본다).

## 처리방침

2번(처리 목적)에 통계 항목과 규칙(합계만, 이메일·이름·계정 식별값·메모 안 씀, 5 미만 감춤, 더 받거나 주지 않음),
6번에 방문 수 세는 방법을 적었다. 바꾼 날짜(`privacy.meta`)는 실제 사이트에 올리는 날로 맞추고, 올리기 전에 공지한다.
`tests/test_usage_stats.py::test_the_policy_says_what_the_counter_and_the_report_do` 가 문구와 코드를 맞춘다.

## 한계

- 페이지 연 횟수이지 사람 수가 아니다. 사람 수를 세려면 식별값이 필요해서 세지 않는다.
- 018을 적용하고 사이트에 올린 날부터 쌓인다. 지난 방문은 없다.
- 공개 키로 `count_visit` 를 직접 부르면 숫자를 부풀릴 수 있다(줄 수는 페이지 목록과 시간으로 묶여 있어 표가 커지지는
  않는다). 흐름을 보는 숫자로 읽는다.
- 별·먹킷리스트 시각은 로그인한 사람만의 것이다.
