# 이벤트 상세 필드 (고정)

`event.html` 의 소식은 **`data/content/events.json`** 에 씁니다(계약 `schemas/content-events.schema.json`). 고친 뒤
`python scripts/sync_site_chrome.py` 를 실행하면 페이지의 행과 한·영 번역(`event.eN.*`, `event.nN.*`)이 다시 써집니다.
페이지의 행이나 번역 표(`window.BABDODUK_STR`)를 직접 고치지 않습니다. 고친 채로 두면 `sync_site_chrome.py --check`(CI)가 실패합니다.
상세 본문(`details`)은 아래 **네 가지 라벨만** 씁니다. (다른 이름으로 바꾸지 않습니다.)

## 페이지 구조

제목 **밥도둑 소식** 아래에 설명 문단 없이 바로 두 목록이 옵니다.

- **지금** (`#now`): 작성된 공지(`#eventNotices`)와 진행 중·예정 활동(`#eventUpcoming`). 둘 다 없으면 “예정된 활동 없음” 한 줄만 보입니다. Instagram 링크는 목록 아래 한 줄로 따로 있습니다.
- **지난 활동** (`#archive`, 목록 `#eventList`): 날짜 · 제목 · 짧은 상태 · 당시 게시물 링크. 당시 안내 전문과 상태 설명은 **자세히**(`<details>`) 안에 접혀 있습니다.
- 이 페이지는 밥도둑이 직접 연 활동만 다룹니다. 꽁밥 일정은 싣지 않습니다.

## 순서와 번호 (자동)

- 활동(`activities`)은 **시작일이 빠른 것이 위**, 시작일이 같으면 **종료일이 빠른 것이 위**입니다. 맨 위 행이 `event.e0` 입니다.
- 공지(`notices`)는 **최신이 위**입니다(`event.n0`).
- 순서와 번호는 스크립트가 정합니다. 파일 안의 순서는 상관없고, 활동을 더하거나 지워도 번호를 손으로 맞추지 않습니다.
- 스크립트가 날짜를 보고 진행 중·예정 행을 **지금**으로 옮깁니다. 행에는 번호가 보이지 않습니다.

## 현재 저장소 예시 (참고)

| 순서 | 제목 (`title.ko`) | 날짜 | `confirmation` |
|------|-------------------|------|----------------|
| `e0` | 밥도둑 팔로워 100명 이벤트 | 2026.05.13 — 05.20 | `announced` |
| `e1` | KAKI × 밥도둑 〈카빙〉 · 태울석림제 부스 | 2026.05.19 — 05.20 | `tentative` |

## 활동 하나 (`activities[]`)

```json
{
  "start": "2026-05-19",
  "end": "2026-05-20",
  "confirmation": "tentative",
  "link": "https://www.instagram.com/babdodukms/",
  "title": {"ko": "KAKI × 밥도둑 〈카빙〉", "en": "KAKI × Babdoduk: Carving"},
  "place": {"ko": "태울석림제 부스", "en": "Taeul Seoklim Festival booth"},
  "details": {
    "summary": {"ko": "…", "en": "…"},
    "duration": {"ko": "…", "en": "…"},
    "prizes": {"ko": "…", "en": "…"},
    "participation": {"ko": "…", "en": "…"}
  }
}
```

| 필드 | 값 |
|------|----|
| `start`, `end` | `YYYY-MM-DD` (KST). 하루 행사면 같은 날을 씁니다 |
| `confirmation` | `announced` · `tentative` · `held` · `cancelled` (아래 “날짜 구간과 확인 상태”) |
| `link` | 당시 게시물 주소(`https://`) |
| `title` | 제목. “(예정)”을 붙이지 않습니다 |
| `place` | 선택. 장소는 제목에 섞지 않고 여기에 둡니다 |
| `details` | 네 줄(`summary` 필수, `duration`·`prizes`·`participation` 선택) **또는** `note` 한 블록 |

- 모든 글은 `ko` 와 `en` 을 함께 씁니다. 한쪽만 있으면 계약 검사가 실패합니다.
- 날짜는 스크립트가 숫자로 씁니다(`2026.05.19 — 05.20`). 같은 해면 끝 날짜에서 연도를 빼고, 하루 행사는 날짜 하나만 씁니다. 한·영 공통이라 날짜 번역 키는 없습니다.
- 사진은 실제 사진이 있을 때만 넣습니다(지금은 필드가 없어, 생기면 계약에 먼저 더합니다). 자리표시 이미지를 만들지 않습니다.

## 만들어지는 행

```html
<li class="event-item" data-start="2026-05-19" data-end="2026-05-20" data-confirmation="tentative">
  <p class="event-date"><time datetime="2026-05-19">2026.05.19</time> — <time datetime="2026-05-20">05.20</time> <span class="event-place" data-i18n="event.e1.place">태울석림제 부스</span></p>
  <h3 class="event-name" data-i18n="event.e1.summary">KAKI × 밥도둑 〈카빙〉</h3>
  <p class="event-state" data-event-state hidden></p>
  <a class="event-link" href="https://www.instagram.com/…" target="_blank" rel="noopener noreferrer"><span data-event-cta>당시 게시물</span> <span aria-hidden="true">↗</span><span class="event-sr" data-i18n="event.newTab">(새 창)</span></a>
  <details class="event-more">
    <summary data-i18n="event.more">자세히</summary>
    <p class="event-note" data-event-note></p>
    <div class="event-detail" data-i18n-html="event.e1.detail">(한국어 상세 본문)</div>
  </details>
</li>
```

한국어 글은 마크업에 바로 들어가 자바스크립트 없이도 읽히고, 영어는 번역 표에서 언어를 바꿀 때 씁니다.

## 날짜 구간과 확인 상태 (분리)

| 필드 (행의 속성) | 값 | 의미 |
|------------------|----|------|
| `start`, `end` (`data-start`, `data-end`) | `YYYY-MM-DD` (KST) | 날짜 구간: 오늘보다 뒤면 **예정**, 기간 안이면 **진행 중**, 지났으면 **지난 활동** |
| `confirmation` (`data-confirmation`) | `announced` · `tentative` · `held` · `cancelled` | 안내·확인된 사실. 날짜가 지났다는 것만으로 `held`로 바꾸지 않습니다 |

화면에 보이는 상태는 짧은 명사구 하나입니다(스크립트가 계산).

| 구간 · 확인 | 보이는 상태 (`[data-event-state]`) | 자세히 안 설명 (`event.note.*`) |
|-------------|-----------------------------------|--------------------------------|
| 지난 · `announced` | 없음 | 결과는 기록되지 않았고, 참여 방법은 지금 적용되지 않는다는 설명 |
| 지난 · `tentative` | 진행 여부 미확인 | 당시 ‘예정’으로 안내했고 진행 여부는 기록되지 않았다는 설명 |
| 지난 · `held` | 진행됨 | 진행된 이벤트 |
| `cancelled` (모든 구간) | 취소됨 | 취소된 이벤트 |
| 진행 중 · 예정 | 진행 중 / 예정 (`tentative` 면 “· 일정 미확정”) | 미확정이면 그 사실 |

- `tentative`는 제목 뒤 “(예정)”을 대신합니다. 제목에는 “(예정)”을 붙이지 않습니다.
- 실제로 진행·취소된 사실이 확인될 때만 `held`/`cancelled`로 바꿉니다. “진행됨”은 `held` 에서만 나옵니다.
- 진행 중·예정 활동과 공지가 없으면 빈 상태 한 줄이 나옵니다. 빈 칸을 채우려고 행사나 공지를 만들지 않습니다.

## 링크와 참여 방법 (자동 표시)

| 구간 | 링크 문구 (`[data-event-cta]`) | 자세히 안 참여 방법 행 |
|------|--------------------------------|------------------------|
| 진행 중 · 예정 | **게시물 보기** ↗ (`event.cta.live`) | 그대로 |
| 지난 활동 | **당시 게시물** ↗ (`event.cta.past`) | 흐린 글씨 + “당시 안내 · 지금은 참여할 수 없어요” 표시 (`event.historical`) |

- `participation` 은 스크립트가 `data-detail="participation"` 행으로 씁니다(한·영 모두). 페이지 스크립트가 지난 활동일 때만 표시를 붙이고, 언어를 바꿔도 다시 붙입니다.
- 상세 본문은 당시 안내를 그대로 둡니다. 다만 화면 조작(“카드 오른쪽 버튼” 등)을 가리키는 문장은 쓰지 않습니다.
- 상세 값에는 강조 `<strong>…</strong>` 만 쓸 수 있습니다. 다른 마크업이나 닫히지 않은 `<strong>` 은
  `python scripts/validate_content.py --only authored` 가 막습니다. 제목·장소·공지는 글자 그대로 씁니다.

## 네 가지 라벨

| 필드 | 한국어 (`event-detail-label`) | 영어 |
|------|------------------------------|------|
| `summary` | **이벤트 내용** | **Event summary** |
| `duration` | **진행 기간** | **Duration** |
| `prizes` | **이벤트 상품** | **Prizes** |
| `participation` | **참여 방법** | **How to participate** |

라벨은 `scripts/page_content.py` 가 정해 둔 것이라 파일에는 값만 씁니다. 상세 본문은 이 순서로 만들어집니다.

```html
<div class="event-detail-sheet">
  <div class="event-detail-row"><div class="event-detail-label">이벤트 내용</div><div class="event-detail-value">…</div></div>
  <div class="event-detail-row"><div class="event-detail-label">진행 기간</div><div class="event-detail-value">…</div></div>
  <div class="event-detail-row"><div class="event-detail-label">이벤트 상품</div><div class="event-detail-value">…</div></div>
  <div class="event-detail-row" data-detail="participation"><div class="event-detail-label">참여 방법</div><div class="event-detail-value">…</div></div>
</div>
```

- 네 줄이 맞지 않는 미정 이벤트는 `"details": {"note": {"ko": "…", "en": "…"}}` 로 `event-detail-row--solo` 한 블록만 씁니다.

## 공지 (`notices[]`)

```json
{"date": "2026-10-12", "title": {"ko": "제목", "en": "Title"}, "text": {"ko": "내용", "en": "Text"}}
```

소유자가 실제로 알린 것만 씁니다. 최신이 위에 오고, 하나도 없으면 공지 목록은 숨겨집니다.

## 레이아웃 메모

- 스타일은 `css/event.css`, 공통 제목·섹션 제목은 `css/site.css`(`.page-head`, `.page-section-title`)에 있습니다.
- 지난 활동은 카드 없이 얇은 구분선으로 나눕니다. 진행 중·예정 행만 옅은 면으로 강조합니다.
- `.event-page-wrap` 은 `max-width: 760px` 로 중앙 정렬합니다.

## 에이전트 / 작업 시 메모

이벤트 카피는 `data/content/events.json` 에서만 고치고 동기화합니다. 위 순서와 표기를 유지하고, 라벨을 임의로 줄이거나
바꾸지 않습니다. 화면 문구는 제목·날짜·짧은 상태·링크로 충분하게 두고, 긴 설명은 자세히 안에만 둡니다(`DESIGN_SYSTEM.md` “Copy”).
`history.html` 의 타임라인은 같은 방식으로 `data/content/history.json` 에서 만들어집니다(`docs/DATA.md`).
