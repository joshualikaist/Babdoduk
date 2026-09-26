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
| 그다음 (`e1`) | 태울석림제 부스 〈카빙〉 KAKI X 밥도둑 (`data-confirmation="tentative"`) | 2026. 5. 19 ~ 5. 20 |
| 마지막 (`e2`) | 태울석림제 부스 〈언빌리버블 버블티〉 STROKE X 밥도둑 (`data-confirmation="tentative"`) | 2026. 5. 19 ~ 5. 21 |

## 날짜 구간과 확인 상태 (분리)

각 `.event-tab-row`에는 다음 속성을 둡니다. 화면의 상태 칩과 상세 위 안내문은 이 값에서 계산됩니다.

| 속성 | 값 | 의미 |
|------|----|------|
| `data-start`, `data-end` | `YYYY-MM-DD` (KST) | 날짜 구간 계산: 오늘보다 뒤면 **예정**, 기간 안이면 **진행 중**, 지났으면 **지난 일정** |
| `data-confirmation` | `announced` · `tentative` · `held` · `cancelled` | 안내·확인된 사실. 날짜가 지났다는 것만으로 `held`로 바꾸지 않습니다 |

- `tentative`는 제목 뒤 “(예정)”을 대신합니다. 제목(`event.eN.summary`)에는 “(예정)”을 붙이지 않습니다.
- 실제로 진행되었거나 취소된 사실이 확인되면 그때 `held`/`cancelled`로 바꿉니다. 확인 전에는 지난 일정도 “결과 기록 없음”·“진행 여부 미확인”으로 표시됩니다.
- 상세 본문(`event.eN.detail`)은 당시 안내 그대로 둘 수 있습니다. 지난 일정에는 “당시 안내 기록” 안내문이 자동으로 붙습니다.
- 진행 중·예정 이벤트가 없으면 목록 위에 빈 상태 안내가 나옵니다. 빈 칸을 채우려고 행사를 만들지 않습니다.

## 지난 일정의 링크와 참여 방법 (자동 표시)

날짜 구간은 스크립트가 계산하므로, 아래 표시는 손으로 바꾸지 않습니다.

| 구간 | 카드 오른쪽 링크 (`[data-event-cta]`) | 상세의 참여 방법 행 |
|------|----------------------------------------|---------------------|
| 진행 중 · 예정 | **페이지로 이동** ↗ (`event.cta.live`) | 그대로 |
| 지난 일정 | **당시 게시물 보기** ↗ (`event.cta.past`), 점선·흐린 스타일 | 흐린 글씨 + “당시 안내 · 지금은 참여할 수 없어요” 표시 (`event.historical`) |

- 링크는 모두 외부(인스타그램) 새 창이라 ↗ 를 씁니다. 지난 일정의 링크는 참여 수단이 아니라 당시 게시물 기록입니다.
- 참여 방법 행에는 `data-detail="participation"` 를 붙입니다(한·영 모두). 스크립트가 이 행을 찾아 지난 일정일 때만 표시를 붙이고, 언어를 바꿔도 다시 붙입니다.
- 지난 행 카드는 흐린 바탕으로, 진행 중·예정 행과 공지 영역만 강조색을 씁니다.
- 날짜가 지났다는 이유로 결과를 적지 않습니다. `held`/`cancelled` 는 근거가 있을 때만 바꾸고, 그 전까지는 “결과 기록 없음”·“진행 여부 미확인”으로 남습니다.
- 이 페이지는 밥도둑이 직접 연 활동만 다룹니다. KAIST 무료 음식 행사(꽁밥)는 `ggongbab.html` 에만 싣고, 페이지 위쪽 안내 한 줄로 그쪽을 가리킵니다.

플레이스홀더용 빈 탭은 두지 않습니다. 행사를 없앨 때는 카드·`eventTabN` / `eventPanelN`·`STR`의 해당 `event.eN` 항목을 함께 제거합니다.

### 레이아웃 메모

- 스타일은 `css/event.css`에 있습니다(`css/app.css`는 이벤트 페이지에 쓰지 않습니다).
- 본문 영역 **`.event-page-wrap`** 은 `max-width: 760px` 로 중앙 정렬합니다.
- 목록은 `role="tablist"`이며 위·아래(또는 좌·우) 화살표, Home, End로 이동합니다.
- 탭 카드 제목(`.event-tab-title`)은 **여러 줄 줄바꿈**을 허용합니다(긴 제목이 오른쪽 **페이지로 이동** pill과 겹치지 않도록).

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
  <div class="event-detail-row" data-detail="participation">
    <div class="event-detail-label">참여 방법</div>
    <div class="event-detail-value">… (카드 오른쪽 <strong>페이지로 이동</strong> 안내 가능)</div>
  </div>
</div>
```

- **미정 이벤트**처럼 네 줄이 맞지 않으면 `event-detail-row--solo` 한 블록만 써도 됩니다. (플레이스홀더 탭을 쓰지 않을 때는 목록에서 해당 카드·`event.eN` 항목을 제거합니다.)
- **외부 안내 링크**는 목록 카드 오른쪽 pill 링크의 `href`를 수정합니다 (`event-tab-outlink`).

## 에이전트 / 작업 시 메모

이 저장소에서 이벤트 카피를 다룰 때는 위 순서와 표기를 유지하고, 라벨을 임의로 줄이거나 바꾸지 않습니다.
