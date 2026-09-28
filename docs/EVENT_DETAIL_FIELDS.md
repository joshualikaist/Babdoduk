# 이벤트 상세 필드 (고정)

`event.html`의 `STR` 안 `event.e0.detail`, `event.e1.detail`, … 같은 **상세 본문**을 작성·수정할 때, 아래 **네 가지 라벨만** 사용합니다. (다른 이름으로 바꾸지 않습니다.)

## 페이지 구조

제목 **03 밥도둑 소식** 아래에 설명 문단 없이 바로 두 목록이 옵니다.

- **지금** (`#now`): 작성된 공지(`#eventNotices`)와 진행 중·예정 활동(`#eventUpcoming`). 둘 다 없으면 “예정된 활동 없음 · Instagram ↗” 한 줄만 보입니다.
- **지난 활동** (`#archive`, 목록 `#eventList`): 번호 · 날짜 · 제목 · 짧은 상태 · 당시 게시물 링크. 당시 안내 전문과 상태 설명은 **자세히**(`<details>`) 안에 접혀 있습니다.
- 꽁밥 일정은 제목 옆 작은 링크(“꽁밥 일정 → 오늘의 꽁밥”)로만 가리킵니다. 이 페이지는 밥도둑이 직접 연 활동만 다룹니다.

## 목록 정렬 규칙

행사는 모두 `#eventList` 안의 `<li class="event-item">` 로 작성합니다. 스크립트가 날짜를 보고 진행 중·예정 행을 **지금**으로 옮기고, 목록마다 번호(01, 02, …)를 다시 매깁니다.

1. **시작일이 빠른 행사가 위**에 오도록 정렬합니다.
2. **시작일이 같으면** **종료일이 빠른 행사**를 위에 둡니다.
3. HTML의 `.event-item` **물리적 순서**와 `STR`의 `event.e0`…`event.e{N}` **키 순서가 1:1로 같아야** 합니다. (`event.e0` = 맨 위 행)
4. 행사를 추가·삭제하면 날짜 기준으로 다시 정렬한 뒤 `e` 인덱스를 **연속으로** 맞춥니다.

## 현재 저장소 예시 (참고)

| 순서 | `event.eN` | 날짜 | 확인 상태 |
|------|------------|------|-----------|
| `e0` | 밥도둑 팔로워 100명 이벤트 | 2026.05.13 — 05.20 | `announced` |
| `e1` | KAKI × 밥도둑 〈카빙〉 · 태울석림제 부스 | 2026.05.19 — 05.20 | `tentative` |
| `e2` | STROKE × 밥도둑 〈언빌리버블 버블티〉 · 태울석림제 부스 | 2026.05.19 — 05.21 | `tentative` |

## 행 하나의 모양

```html
<li class="event-item" data-start="2026-05-19" data-end="2026-05-20" data-confirmation="tentative">
  <span class="event-num" aria-hidden="true">02</span>
  <p class="event-date"><time datetime="2026-05-19">2026.05.19</time> — <time datetime="2026-05-20">05.20</time>
    <span class="event-place" data-i18n="event.e1.place">태울석림제 부스</span></p>
  <h3 class="event-name" data-i18n="event.e1.summary">KAKI × 밥도둑 〈카빙〉</h3>
  <p class="event-state" data-event-state hidden></p>
  <a class="event-link" href="https://www.instagram.com/…" target="_blank" rel="noopener noreferrer"><span data-event-cta>당시 게시물</span> <span aria-hidden="true">↗</span><span class="event-sr" data-i18n="event.newTab">(새 창)</span></a>
  <details class="event-more">
    <summary data-i18n="event.more">자세히</summary>
    <p class="event-note" data-event-note></p>
    <div class="event-detail" data-i18n-html="event.e1.detail"></div>
  </details>
</li>
```

- 날짜는 숫자로 씁니다(`2026.05.19 — 05.20`). 같은 해면 끝 날짜에서 연도를 뺍니다. 한·영 공통이라 `STR` 에 날짜 키를 두지 않습니다.
- 장소가 있으면 `event.eN.place` 한 줄 메타데이터로 둡니다. 제목에 섞지 않습니다.
- 사진은 실제 사진이 있을 때만 넣습니다. 자리표시 이미지를 만들지 않습니다.

## 날짜 구간과 확인 상태 (분리)

| 속성 | 값 | 의미 |
|------|----|------|
| `data-start`, `data-end` | `YYYY-MM-DD` (KST) | 날짜 구간: 오늘보다 뒤면 **예정**, 기간 안이면 **진행 중**, 지났으면 **지난 활동** |
| `data-confirmation` | `announced` · `tentative` · `held` · `cancelled` | 안내·확인된 사실. 날짜가 지났다는 것만으로 `held`로 바꾸지 않습니다 |

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

- 참여 방법 행에는 `data-detail="participation"` 를 붙입니다(한·영 모두). 스크립트가 지난 활동일 때만 표시를 붙이고, 언어를 바꿔도 다시 붙입니다.
- 상세 본문은 당시 안내를 그대로 둡니다. 다만 화면 조작(“카드 오른쪽 버튼” 등)을 가리키는 문장은 쓰지 않습니다.

## 한국어 (`event-detail-label`)

1. **이벤트 내용**
2. **진행 기간**
3. **이벤트 상품**
4. **참여 방법**

## 영어 (`html lang="en"` 대응 문자열)

1. **Event summary**
2. **Duration**
3. **Prizes**
4. **How to participate**

## HTML 조각 예시

```html
<div class="event-detail-sheet">
  <div class="event-detail-row">
    <div class="event-detail-label">이벤트 내용</div>
    <div class="event-detail-value">…</div>
  </div>
  <div class="event-detail-row">
    <div class="event-detail-label">진행 기간</div>
    <div class="event-detail-value">…</div>
  </div>
  <div class="event-detail-row">
    <div class="event-detail-label">이벤트 상품</div>
    <div class="event-detail-value">…</div>
  </div>
  <div class="event-detail-row" data-detail="participation">
    <div class="event-detail-label">참여 방법</div>
    <div class="event-detail-value">…</div>
  </div>
</div>
```

- 네 줄이 맞지 않는 미정 이벤트는 `event-detail-row--solo` 한 블록만 써도 됩니다.
- 외부 안내 링크는 행의 `.event-link` `href`를 수정합니다.

## 레이아웃 메모

- 스타일은 `css/event.css`, 공통 제목·섹션 제목은 `css/site.css`(`.page-head`, `.page-section-title`)에 있습니다.
- 지난 활동은 카드 없이 얇은 구분선으로 나눕니다. 진행 중·예정 행만 옅은 면으로 강조합니다.
- `.event-page-wrap` 은 `max-width: 760px` 로 중앙 정렬합니다.

## 에이전트 / 작업 시 메모

이 저장소에서 이벤트 카피를 다룰 때는 위 순서와 표기를 유지하고, 라벨을 임의로 줄이거나 바꾸지 않습니다. 화면 문구는 제목·날짜·짧은 상태·링크로 충분하게 두고, 긴 설명은 자세히 안에만 둡니다(`DESIGN_SYSTEM.md` “Copy”).
