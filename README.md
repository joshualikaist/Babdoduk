# Babdoduk (밥도둑)

KAIST 밥도둑 링크·콘텐츠용 정적 사이트입니다. **HTML만**으로 동작하며, 배포는 Vercel 등 정적 호스팅에 그대로 올리면 됩니다.

---

## 페이지 구성

| 파일 | 역할 |
|------|------|
| **`index.html`** | 홈 — 프로필, **가로 캐러셀**(주요 링크), 하단 Apple 스타일 푸터 |
| **`food.html`** | **먹방 가계부** — 일별 지출 입력·월/주 표·달력 (`data/food-log.json` 등) |
| **`event.html`** | **이벤트** — 탭형 목록(날짜 순)·상세 패널, **페이지로 이동**으로 인스타 등 링크 열기 |
| **`ggongbab.html`** | **꽁밥 안내** — 왼쪽 지도(탭별 검색어·캡션 연동), 가운데·오른쪽 행사 탭·상세 |
| **`history.html`** | **밥도둑의 역사** — 연도별 타임라인. 예: `images/history-t1.png`(인스타 로고), `history-t2.png`(워드마크); 그림이 로고처럼 작을 때는 `timeline-item-media--contain` 로 전체가 보이게 맞춤. 문구는 `STR`의 `history.tN.*` 키 |
| **`lab-ggongbab.html`** | **실험용 꽁밥 안내** — `lab.html` 내비의 꽁밥 안내 링크 전용. 본편은 `ggongbab.html`. 상단 띠에서 실험실·본편 왕복. `noindex` |
| **`lab.html`** | **실험실** — 서버·로그인·`calendar.ics` 파싱(꽁밥 후보 일정) 등 본편과 분리해 시험. 메타 `noindex`. 접속은 `…/lab.html` 직접 입력·북마크(홈에는 링크 없음) |

상단 내비: **소개**(역사 페이지 링크 등) · **SNS**(인스타·유튜브·카카오톡 등) · **주요 기능** 메가 메뉴(맛집 지도 · 먹방 가계부 · 꽁밥 안내) · **이벤트** · 언어(EN/한국어). 꽁밥 페이지 운영 규칙은 **`docs/GGONGBAB_PAGE.md`** 를 참고합니다.  
문의는 푸터에 **이메일 주소 텍스트**로 표기되어 있습니다(메일to 링크 아님).

---

## 주요 동작·정책

- **언어** — `localStorage` 키 `babdoduk-lang`(`ko` / `en`). 모든 HTML에서 동일하게 적용됩니다.
- **환영 팝업** — **`index.html`(홈)** 에서만 표시합니다. `food.html`, `event.html`, `history.html`, `ggongbab.html` 등에서는 뜨지 않습니다.  
  **「하루 동안 보지 않기」** 한 번이면 약 24시간 동안 `babdoduk-welcome-snooze-until`로 숨깁니다.
- **캐러셀(홈)** — 슬라이드는 **왼쪽 이미지 / 오른쪽 설명**, 입체적인 카드 그림자·테두리, 하단 **페이지 점**은 카드와 간격을 두어 배치했습니다.
- **이벤트 탭** — 카드 **왼쪽**을 누르면 상세 패널이 바뀝니다. **오른쪽** pill **페이지로 이동**으로 인스타 등 링크를 엽니다. 목록은 **시작일·종료일** 기준으로 정렬합니다. 상세 본문 라벨·정렬 규칙은 **`docs/EVENT_DETAIL_FIELDS.md`** 참고.

---

## UTF-8 · `index.html` 다시 만들기

한글 깨짐이 생기면 **`food.html`을 UTF-8로 저장한 뒤** 아래를 실행하는 것이 안전합니다.

```powershell
cd C:\Users\joshu\Babdoduk
python rebuild_index.py
```

- 홈의 프로필·캐러셀 마크업 일부는 스크립트에 포함되어 있고, 나머지 레이아웃·스크립트는 `food.html`을 기준으로 합쳐 집니다.
- 공통 패치(내비 가계부, 팝업 로직 등)는 **`python patch_site.py`** 로 `index.html` · `food.html`에 적용할 수 있습니다. (`index.html`이 깨진 상태면 먼저 `rebuild_index.py` 권장)

---

## 터미널에서 뭘 치면 되는지 (Vercel 배포)

PowerShell 또는 명령 프롬프트를 연 뒤, **아래 순서대로** 입력하면 됩니다.

### 1. Node.js 확인

```powershell
node -v
```

버전이 안 나오면 [Node.js LTS](https://nodejs.org/) 를 설치한 뒤 다시 시도하세요.

### 2. Vercel CLI 설치 (한 번만)

```powershell
npm install -g vercel
```

### 3. 프로젝트 폴더로 이동

```powershell
cd C:\Users\joshu\Babdoduk
```

### 4. 배포 실행

```powershell
vercel
```

처음이면 브라우저로 로그인 안내가 뜹니다. 이후 질문이 나오면 대략 이렇게 답하면 됩니다.

| 질문 | 입력 |
|------|------|
| Set up and deploy? | `Y` (또는 yes) |
| Which scope? | 본인 계정 선택 |
| Link to existing project? | **처음이면 `N` (no)** |
| What’s your project’s name? | `babdoduk` (원하면 다른 이름) |
| In which directory is your code located? | **`.`** 만 입력 후 Enter (현재 폴더) |

**주의:** `Users\joshu\...` 같은 경로를 여기에 넣지 마세요. 이미 `C:\Users\joshu\Babdoduk` 에 있다면 반드시 **`.`** 만 입력하세요.

### 5. 실험 / 공개 URL (프로젝트 두 개)

| 용도 | Vercel 프로젝트 | URL |
|------|-----------------|-----|
| **실험** | `babdoduk-lab` | https://babdoduk-lab.vercel.app |
| **공개** | `babdoduk` | https://babdoduk.vercel.app |

```powershell
# 실험 (lab 브랜치)
vercel link --project babdoduk-lab --yes
vercel --prod

# 공개 (main 반영 후)
vercel link --project babdoduk --yes
vercel --prod
```

자세한 주의사항: **`docs/DEPLOYMENT_AND_BRANCHES.md`**

### 6. 코드 수정 후 다시 올리기

HTML을 저장한 뒤, 같은 폴더에서:

```powershell
vercel --prod
```

또는:

```powershell
vercel
```

### Git: 저장소 하나 — `main`(공개) + `lab`(실험)

**폴더를 두 개 복사해 프로젝트를 나누지 않습니다.** 같은 저장소에서 브랜치만 나눕니다.

| 브랜치 | 용도 |
|--------|------|
| **`main`** | 방문자용 본편. `index.html`, `ggongbab.html`, `food.html` 등. Vercel Production이 보통 이 브랜치. |
| **`lab`** | 실험용. `lab.html`, `lab-ggongbab.html`, `calendar.ics` 연동 등을 **먼저** 여기서 커밋. |

**매번 할 일:**

1. 실험할 때: `git checkout lab` → 수정 → `git push origin lab` (공식 사이트는 `main`이면 그대로이고, 보통 Preview만 갱신)
2. 본편에 반영할 때: `main`에 **`lab`을 merge**(또는 PR) → `git push origin main` → 공개 배포 갱신  
3. `lab-ggongbab.html` 내용을 `ggongbab.html`로 옮기는 것처럼 **파일별 수동 정리**가 필요하면 merge 후 diff로 처리

- 자세한 명령·주의사항: **`docs/DEPLOYMENT_AND_BRANCHES.md`**  
- merge 전 체크: **`docs/BRANCH_MERGE_CHECKLIST.md`**

---

## 로컬에서만 미리 보기

브라우저에서 `index.html`을 열거나, VS Code / Cursor의 **Live Preview**, `npx serve` 등으로 열어도 됩니다.  
**먹방 가계부**(`data/food-log.json` 로드)는 브라우저 보안 때문에 **`file://`** 로 열면 실패할 수 있습니다. 그럴 때는 Live Preview, `npx serve`, 또는 배포 URL로 확인하세요.

---

## 먹방 가계부 데이터 (`data/food-log.json`)

인스타에 올린 글의 **Total** 금액을 이 파일에 날짜별로 적어 두면, **`food.html`** 에서 **월별·주차별 합계**와 **달력**이 갱신됩니다.

- 인스타그램은 일반적으로 **게시를 자동으로 가져오는 공개 API**가 없어, **포스팅 후 JSON에 반영**하는 방식이 현실적입니다.
- **Google 캘린더 연동**은 API·OAuth 등 추가 설계가 필요합니다. 지금은 **정적 JSON** 기준으로 두었습니다.

---

## 스크립트 요약

| 파일 | 설명 |
|------|------|
| `rebuild_index.py` | `food.html` → `index.html` 재생성 (UTF-8, 홈 전용으로 가계부 UI 제거 등) |
| `patch_site.py` | `index.html` · `food.html` 공통 패치(예: 팝업/내비 관련) |

---

## 사이트에 들어 있는 것 (요약)

1. 인스타그램 · 네이버 맛집 지도 링크  
2. 유튜브·카카오톡(내비·캐러셀에서 이동)  
3. **먹방 가계부** (`food.html`)  
4. **꽁밥 안내** (`ggongbab.html`) — 지도·탭 연동, 자세한 편집 규칙은 `docs/GGONGBAB_PAGE.md`  
5. **이벤트** (`event.html`) — 탭·상세·인스타 연동, 필드 규칙은 `docs/EVENT_DETAIL_FIELDS.md`  
6. **밥도둑의 역사** (`history.html`) — 타임라인  
7. 다국어(한/영) · 스크롤 진행 표시줄 · Apple 스타일 푸터(정책 링크는 자리만, URL은 필요 시 수정)
