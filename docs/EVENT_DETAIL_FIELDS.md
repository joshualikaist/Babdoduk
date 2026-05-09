# 이벤트 상세 필드 (고정)

`event.html`의 `STR` 안 `event.e0.detail`, `event.e1.detail`, … 같은 **상세 본문**을 작성·수정할 때, 아래 **네 가지 라벨만** 사용합니다. (다른 이름으로 바꾸지 않습니다.)

## 한국어 (왼쪽 열 · `event-detail-label`)

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

`event-detail-sheet` 안에 행을 네 줄 맞추는 패턴:

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
  <div class="event-detail-row">
    <div class="event-detail-label">참여 방법</div>
    <div class="event-detail-value">… (카드 오른쪽 <strong>페이지로 이동</strong> 안내 가능)</div>
  </div>
</div>
```

- **미정 이벤트**처럼 네 줄이 맞지 않으면 `event-detail-row--solo` 한 블록만 써도 됩니다.
- **외부 안내 링크**는 목록 카드 오른쪽 pill 링크의 `href`를 수정합니다 (`event-tab-outlink`).

## 에이전트 / 작업 시 메모

이 저장소에서 이벤트 카피를 다룰 때는 위 순서와 표기를 유지하고, 라벨을 임의로 줄이거나 바꾸지 않습니다.
