# 꽁밥 안내 페이지 (`ggongbab.html`) 운영 가이드

에이전트·편집자가 이 페이지를 고칠 때 **구조와 i18n 규칙**을 그대로 유지합니다. (대화 기록이 없어도 이 문서만 보면 동일한 방식으로 운영할 수 있게 정리했습니다.)

## 레이아웃 (3열)

1. **왼쪽 — 지도** (`ggongbab-map-col`): Google Maps 임베드. `applyLang`에서 한·영 검색어로 `src`를 갱신합니다.
2. **가운데 — 행사 탭** (`ggongbab-tabs-col`): 탭 목록만 세로로 쌓입니다. 데스크톱에서는 `position: sticky` + `overflow-y: auto`로 **탭 열 안에서 세로 스크롤**됩니다. 탭 버튼은 `scroll-snap-align: start`로 스냅됩니다.
3. **오른쪽 — 상세** (`ggongbab-detail-col`): 현재 선택된 탭에 대응하는 **하나의** `event-panel`만 보입니다.

탭을 바꾸면 **오른쪽 상세**와 함께 **왼쪽 지도 임베드·캡션**도 선택한 행사에 맞게 바뀝니다. (`syncGgongbabMapFromTab`, `gb.mapQ0` / `gb.mapQ1`, `gb.mapCaption0` / `gb.mapCaption1`)

## 상단 리드 문구 (`ggongbab.lead`)

페이지 맨 위 **`event-lead`** 한 줄은 **사용법 안내**만 씁니다. (어떤 탭이 있는지 **행사 이름으로 나열**하지 않습니다.) 문구는 `STR.ko` / `STR.en`의 **`ggongbab.lead`** 키만 수정합니다.

## 행사 일정 위 히어로 이미지 (선택)

오른쪽 상세에서 **`event-detail-sheet`(행사 일정 첫 줄) 바로 위**에 탭별 이미지를 둘 수 있습니다.

| 탭 | 기본 파일 경로 (저장소 기준) | 대체 문자열(`alt`) i18n 키 |
|----|------------------------------|---------------------------|
| 첫 번째 (`gbPanel0`) | `images/ggongbab-tab0.png` (또는 `.jpg` 등, `<img src>` 와 맞춤) | `gb.e0.imageAlt` |
| 두 번째 (`gbPanel1`) | 예: `images/ggongbab-samsung-sdi-lunch.png` (또는 다른 포스터 파일; `<img src>` 와 맞춤) | `gb.e1.imageAlt` |

- **파일 넣기**: 포스터·스크린샷 등을 위 경로 이름으로 `images/` 폴더에 추가합니다. (`jpg` 대신 `png`/`webp`를 쓰면 `ggongbab.html` 안 `<img src="...">`만 그 확장자에 맞게 수정하면 됩니다.)
- **문구**: 한·영 `alt` 는 `STR.ko` / `STR.en` 의 `gb.e0.imageAlt`, `gb.e1.imageAlt` 에서 수정합니다. (`data-i18n-alt` 로 연결됨.)
- **이미지가 없을 때**: 해당 탭을 쓰지 않거나, `<figure class="gb-detail-hero">` 블록 전체를 잠시 제거해도 됩니다. (파일 없이 두면 브라우저에 깨진 그림만 보일 수 있습니다.)

## 복합 스크린샷 업로드 (상단 텍스트 + 하단 포스터 한 장)

편집자가 **한 장의 이미지**로 안내를 줄 때가 많습니다. (예: 메일·메신저 캡처 — **위**는 일정·장소·링크가 **글자**로, **아래**는 **포스터·전단** 그래픽.)

**가능합니다.** 별도 파일을 달라고 하기 전에, 에이전트는 보통 아래처럼 **역할을 나누어** 반영합니다.

### 에이전트가 나누는 기준 (논리적 분리)

| 구분 | 웹 페이지에서의 처리 |
|------|---------------------|
| **텍스트 요약** (화면 위쪽 문단 등) | `STR.ko` / `STR.en`의 해당 탭 키와 **4행 시트**(`gb.value.*` 또는 `gb.eN.*`)에 반영. 꽁밥·장학·취업 등 **혜택 문구**는 행사 내용·일정 줄에 자연스럽게 녹임. |
| **포스터·전단** (화면 아래 그래픽) | 채팅에서 받은 파일을 `images/ggongbab-〈의미있는-슬러그〉.png` (등)으로 저장소에 **복사**하고, 해당 탭 패널의 `<figure class="gb-detail-hero">` → `<img src="...">`에 연결. `gb.eN.imageAlt`로 접근성 텍스트 유지. |

- **한 파일에 글자+포스터가 같이 있어도** 됩니다. 페이지 본문은 구조화된 텍스트로 정리하고, 이미지는 **히어로 한 장**으로 쓰는 패턴이 일반적입니다. (같은 캡처를 통째로 써도 되고, 나중에 포스터만 잘린 파일로 바꿔도 됩니다.)
- **픽셀 단위로 포스터만 자동 자르기**는 도구·이미지 형태에 따라 항상 되는 것은 아닙니다. 포스터 영역만 깔끔히 쓰고 싶다면 **포스터 원본만** 추가로 올리거나, 잘라낸 파일을 `images/`에 넣어 달라고 하면 그 경로로 바꿉니다.

### 정확도를 올리려면 (선택)

- 원본 **포스터 파일**(PNG/PDF) 또는 **본문 텍스트 복사**를 함께 주면 링크·날짜 오타가 줄어듭니다.
- 링크는 반드시 **완전한 URL**인지 확인합니다. (`naver.me/...` 등)

## 탭·패널 연결 규칙

- 탭 버튼: `id="gbTab0"`, `id="gbTab1"`, …  
  - `role="tab"`, `aria-controls="gbPanelN"`, `aria-selected`, `tabindex`는 스크립트가 맞춥니다.
- 패널: `id="gbPanel0"`, …, `role="tabpanel"`, `aria-labelledby="gbTabN"`.  
  - 비활성 패널에는 `hidden` 속성.
- 스크립트는 `.ggongbab-split` 안의 `.event-tab`과 `.event-panel`을 **같은 순서**로 짝지어 동작합니다. 탭을 추가/삭제할 때는 **반드시 탭과 패널을 쌍으로** 넣습니다.

## 상세 본문 마크업 (고정 필드 4행)

오른쪽 상세는 `event-detail-sheet` 안에 **항상 네 줄**을 맞춥니다.

| 왼쪽 라벨 (`data-i18n="gb.field.*"`) | 의미 |
|-------------------------------------|------|
| `gb.field.schedule` | 행사 일정 |
| `gb.field.location` | 행사 위치 |
| `gb.field.content` | 행사 내용 |
| `gb.field.apply` | 신청 링크 |

- **첫 번째 탭** 의 값 문자열은 `gb.value.schedule`, `gb.value.location`, **`gb.value.contentHtml`** (행사 내용에 줄 바꿈·강조가 필요하면 HTML), **`gb.value.applyHtml`** (HTML 허용).  
  - 행사 내용을 단순 텍스트만 쓸 경우에 한해 `data-i18n="gb.value.content"` 단일 키만 써도 되나, 안내 전단처럼 구조가 길면 **`contentHtml` + `data-i18n-html`** 패턴을 씁니다.
- **두 번째 탭 이후** 는 같은 라벨을 재사용하고, 값만 `gb.e1.schedule`, `gb.e1.location`, **`gb.e1.contentHtml`** (또는 단문이면 `gb.e1.content`), **`gb.e1.applyHtml`** 처럼 **`gb.eN.*`** 로 구분합니다 (`N` = 탭 인덱스).
- 신청/외부 링크 줄은 `<a class="gb-apply-link" href="..." target="_blank" rel="noopener">` 를 쓰면 기존 스타일이 적용됩니다.

네 줄이 맞지 않는 특수 케이스만 `event-detail-row--solo` 같은 변형을 검토합니다 (현재 기본은 4행 고정).

## 탭 라벨·접근성용 i18n

- 전체 탭리스트: `gb.tablistAria`
- 탭 *i*: `gb.e{i}.tabAria`, `gb.e{i}.date` (작은 줄), `gb.e{i}.summary` (제목 줄)

## 현재 저장소 예시

**탭은 두 개만** 둡니다. (예: 과거에 있던 「학기 중 부스」 같은 세 번째 탭은 사용하지 않습니다.)

- **탭0 · KAIST OverEdge:** 히어로 `images/ggongbab-tab0.png`, 참고용 `images/ggongbab-overedge-flyer.png`, 본문 키 `gb.value.*`, 지도 `gb.mapQ0` / `gb.mapCaption0`.
- **탭1 · 삼성SDI KSBP 런치 설명회:** 히어로 `images/ggongbab-samsung-sdi-lunch.png`, 본문 키 `gb.e1.*`, 지도 **`gb.mapQ1`** = Google 임베드 검색어 **`카이스트 응용공학동`** (`STR.ko` / `STR.en` 모두 동일 문자열로 두는 것을 권장), 캡션 `gb.mapCaption1`.

위를 바꿀 때에도 **탭 라벨(`gb.eN.*`)·4행 키(`gb.value.*` / `gb.eN.*`)·지도 `gb.mapQN` / `gb.mapCaptionN`** 를 같은 규칙으로 갱신하면 됩니다.

## `event.html` 과의 구분

- **`event.html`** 상세 필드(이벤트 내용 / 진행 기간 / …) 규칙은 [`EVENT_DETAIL_FIELDS.md`](./EVENT_DETAIL_FIELDS.md) 를 따릅니다.
- **`ggongbab.html`** 은 위 표의 **행사 일정·위치·내용·신청 링크** 네 가지만 사용합니다. 이름을 섞어 쓰지 않습니다.

## 지도·캡션 (탭별)

- 행사마다 장소가 다르므로 **`gb.mapQ0` / `gb.mapQ1`** (한·영 각 `STR`에 두어 Google 검색어로 임베드)와 **`gb.mapCaption0` / `gb.mapCaption1`** (지도 아래 설명 문구)를 씁니다. 삼성SDI 안내 탭은 장소 검색어를 **`카이스트 응용공학동`** 으로 맞춥니다.
- iframe `title`: `ggongbab.mapFrameTitle` (공통이어도 됨).
- 언어 전환·탭 전환 후에 `syncGgongbabMapFromTab()`이 임베드 `src`와 캡션을 맞춥니다.  
- HTML에 있는 iframe 초기 `src`는 첫 탭(또는 대표 행사) 기준으로 두어도 되며, 로드 직후 스크립트가 갱신합니다.

## 요약

- **탭 = 행사 종류**, **오른쪽 = (선택) 히어로 이미지 + 항상 4행 시트**, **문자열 = `STR` 객체의 `gb.*` 키**로만 넣는다.
- 한·영 동시 유지: `STR.ko` / `STR.en` 에 동일 키를 추가·수정한다.
