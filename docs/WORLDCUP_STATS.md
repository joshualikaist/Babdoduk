# 먹방 월드컵: 모두의 선택 (2단계, lab 전용)

소유자 결정(2026-10-13, "2단계 진행해"): 고른 메뉴가 다른 사람들 사이에서 얼마나 이기는지와 전체 우승 랭킹을 보여 줍니다.
레퍼런스는 PIKU 이상형 월드컵의 랭킹(우승 비율·승률)입니다. **lab 전용**이며, `main` 으로 옮기려면 따로 승인된 작업이 필요합니다.
`main` 의 페이지는 Supabase 설정을 갖지 않습니다(AGENTS.md).

## 무엇을 모으나

| 표 | 내용 | 브라우저 |
|----|------|----------|
| `worldcup_dish_stats` | 메뉴마다 1:1 경기 수, 이긴 수, 뽑힌 판 수, 우승 수 | 읽기만 |
| `worldcup_totals` | 끝난 판 수 | 읽기만 |
| `worldcup_rate` | 남용 제한: (주소+날짜+비밀 소금)의 해시, 시간 창, 판 수. 하루 지나면 지움 | 못 봄 |
| `worldcup_secret` | 해시 소금 | 못 봄 |

- 사람·판마다의 기록은 남기지 않고 **합계만** 늘립니다. 이름, 계정, 자유 입력은 없습니다.
- 브라우저는 표에 직접 쓸 수 없습니다. 끝난 한 판을 `worldcup_record_game(p_size, p_matches)` 로 보내면 함수가 검사한 뒤에만 합계를 늘립니다.
  - `p_matches` 는 경기 순서대로 `[이긴 메뉴, 진 메뉴]` 를 `p_size - 1` 개 담습니다.
  - 1라운드는 서로 다른 `p_size` 개 메뉴를 둘씩 짝짓고, 다음 라운드는 앞 라운드 승자를 순서대로 짝지어야 합니다.
  - 모든 메뉴가 풀(`worldcup_dish_stats` 의 행)에 있어야 합니다.
  - 같은 주소에서 한 시간에 30판을 넘으면 `WORLDCUP_RATE_LIMITED` 입니다.
- 페이지(`js/worldcup.js`)는 `js/ggongbab-public-config.js` 의 공개 URL·publishable 키가 있을 때만 통계를 읽고 씁니다. 설정이 비었거나 서버가 실패해도 게임은 그대로 됩니다.

## 화면

- 고른 뒤: "방금 고른 치킨: 모두의 승률 71% · 피자 64%" (경기 3번 미만이면 "아직 기록이 적어요")
- 처음 화면과 결과 화면: "모두의 우승 랭킹" 상위 10개(우승 비율 → 승률 순, 뽑힌 판 3번 이상), "지금까지 N판", 결과 화면에서는 "내 우승 메뉴는 N위"

## 적용 (소유자, 한 번)

1. Supabase 대시보드 → SQL Editor 에서 `supabase/migrations/005_worldcup_stats.sql` 내용을 붙여 넣고 실행합니다(004 다음).
2. 풀을 넣습니다(백엔드 키, 운영 사본 `.env`): `python scripts/worldcup_stats.py seed` → `pool 128 | counted dishes 128 | pool dishes missing 0`
3. 확인: `python scripts/worldcup_stats.py check`
4. 풀이 늘면 2를 다시 실행합니다. 이미 있는 메뉴의 합계는 바뀌지 않습니다.

## 시험

- `tests/test_worldcup_stats.py`: SQL 의 권한(브라우저는 두 표 읽기와 함수 실행뿐), 검사 코드, 저장 열, seed/check 스크립트(가짜 서버).
- `scripts/check_site_ui.py` `worldcup_stats`: 가짜 서버로 랭킹·직전 경기 승률·한 판 기록(올바른 대진)·서버 실패 시에도 게임 계속.
- 정적 검사는 모두 빈 설정으로 돌아 어떤 페이지도 DB 에 닿지 않습니다.
