# 이벤트 상세 필드 (고정)

`event.html`의 `STR` 안 `event.e0.detail`, `event.e1.detail`, … 같은 **상세 본문**을 작성·수정할 때, 아래 **네 가지 라벨만** 사용합니다. (다른 이름으로 바꾸지 않습니다.)

## 목록(탭) 정렬 규칙

`event.html` 상단 **이벤트 카드(탭) 목록**을 고칠 때는 **반드시** 아래 순서를 지킵니다.

1. **시작일이 빠른 행사가 위**에 오도록 정렬합니다.
2. **시작일이 같으면** **종료일이 빠른 행사**(더 먼저 끝나는 항목)를 위에 둡니다.
3. HTML의 `.event-tab-row`·`eventTab0`…·`eventPanel0`… **물리적 순서**와 `STR`의 `event.e0`…`event.e{N}` **키 순서가 1:1로 같아야** 합니다. (`event.e0` = 맨 위 카드)
4. 행사를 추가·삭제하면 날짜 기준으로 다시 정렬한 뒤, `e` 인덱스와 `eventTabN` 번호를 **연속으로** 맞춥니다.

에이전트·편집자는 새 일정을 반영할 때마다 이 규칙을 **기본**으로 적용합니다.

## 현재 저장소 예시 (참고)

실제 `event.html` 구성은 바뀔 수 있으나, **2026년 5월 기준** 예시는 다음과 같습니다.

| 순서 | `event.eN` | 요약 |
|------|------------|------|
| 맨 위 (`e0`) | 팔로워 100명 이벤트 | 2026. 5. 13 ~ 5. 20 |
| 그다음 (`e1`) | 태울석림제 부스 〈카빙〉 KAKI X 밥도둑 **(예정)** | 2026. 5. 19 ~ 5. 20 |
| 마지막 (`e2`) | 태울석림제 부스 〈언빌리버블 버블티〉 STROKE X 밥도둑 **(예정)** | 2026. 5. 19 ~ 5. 21 |

플레이스홀더용 빈 탭은 두지 않습니다. 행사를 없앨 때는 카드·`eventTabN` / `eventPanelN`·`STR`의 해당 `event.eN` 항목을 함께 제거합니다.

### 레이아웃 메모

- 본문 영역 **`.event-page-wrap`** 은 `max-width: 760px` 로 중앙 정렬합니다.
- 탭 카드 제목(`.event-tab-title`)은 기본 **한 줄**(`white-space: nowrap`), **380px 이하** 좁은 화면에서는 줄바꿈을 허용합니다.

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

- **미정 이벤트**처럼 네 줄이 맞지 않으면 `event-detail-row--solo` 한 블록만 써도 됩니다. (플레이스홀더 탭을 쓰지 않을 때는 목록에서 해당 카드·`event.eN` 항목을 제거합니다.)
- **외부 안내 링크**는 목록 카드 오른쪽 pill 링크의 `href`를 수정합니다 (`event-tab-outlink`).

## 에이전트 / 작업 시 메모

이 저장소에서 이벤트 카피를 다룰 때는 위 순서와 표기를 유지하고, 라벨을 임의로 줄이거나 바꾸지 않습니다.
