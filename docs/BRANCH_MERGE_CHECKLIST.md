# 브랜치 작업 · main 반영 체크리스트

이 저장소는 **저장소 하나**에 **`main`(공개)** 과 **`lab`(실험)** 을 두는 흐름을 기본으로 합니다.  
실험·베타는 **`main`이 아닌 브랜치**(이 저장소에서는 **`lab`**)에서 하고, 괜찮아지면 **`main`에 merge**합니다.

비교용 URL:

- 실험: https://babdoduk-lab.vercel.app (`babdoduk-lab` 프로젝트)
- 공개: https://babdoduk.vercel.app (`babdoduk` 프로젝트)

전체 배포 정책: **`DEPLOYMENT_AND_BRANCHES.md`**

---

## 0. 이 저장소에서 매번 지킬 것 (main vs lab)

- [ ] **실험 커밋**은 **`lab`(또는 전용 실험 브랜치)** 에서 할 것 — `main`에서 바로 크게 실험하지 않기(작은 수정는 팀 규칙에 따름)
- [ ] **`lab`만 푸시**했을 때 — Vercel Production이 **`main`** 이면 **공식 사이트는 안 바뀜** (보통 Preview만)
- [ ] **공개 반영**은 **`main`에 merge + push** 한 뒤에만 “방문자에게 릴리스”로 간주할 것
- [ ] **예외:** `data/magazine/**`, `data/kaist-menu/**` 는 매일 액션이 lab/main에 직접 푸시한다. 이 JSON만 바뀐 커밋을 기능 merge와 섞지 말 것
- [ ] **`lab-ggongbab.html` → `ggongbab.html`** 처럼, merge 후에도 **본편 파일로 내용을 옮겨야 하는 작업**이 있는지 목록으로 확인할 것 (자동 동기화 아님)
- [ ] **`lab.html` / `lab-ggongbab.html`** 은 `main`에 둘 수 있으나, 홈 **`index.html` 내비에는 실험 링크를 걸지 않는 정책을 유지할 것**

---

## 1. 작업 시작 전

- [ ] **현재 브랜치 확인** — 실험은 `main`이 아닌 곳에서만 할 것  
- [ ] **`main`이 최신인지** — 작업 전에 `main`을 당겨 둔 뒤 브랜치를 새로 만들거나, 기존 실험 브랜치에 `main`을 merge해 **충돌을 미리** 해소할 것  
- [ ] **브랜치 이름** — 뭘 하는지 알 수 있게 (예: `lab` 고정, 또는 `feature/역사-타임라인`)  

---

## 2. 작업 중 (자주 하는 실수 방지)

- [ ] **한 브랜치에는 한 가지 목적**만 — 나중에 merge/revert하기 쉬움  
- [ ] **중간중간 커밋** — 문장 단위로 메시지 남기기 (예: `lab: calendar.ics 파서 추가`)  
- [ ] **공통 내비·푸터·i18n(STR)** 를 여러 HTML에 복붙했다면 — **같은 패턴인지** 한 번에 훑기  

---

## 3. main에 붙이기 직전 (merge / PR 전 필수)

### Git 상태

- [ ] `git status` — 의도하지 않은 파일(대용량 zip, `__pycache__`, 로컬만 쓰는 파일)이 **커밋에 포함되지 않았는지**  
- [ ] `git diff main...HEAD` (또는 GitHub PR Files changed) — **변경 범위가 이번 작업과 맞는지**  
- [ ] **`calendar.ics`** 를 repo에 둘지, `.gitignore`로 빼 둘지 — 민감·용량 정책 확인  

### 사이트 동작 (로컬에서)

- [ ] **수정한 페이지**뿐 아니라 **내비에서 들어가는 주요 페이지** 1~2개는 훑기  
- [ ] **언어 전환** — 한/영 전환 후 문구·레이아웃 깨짐 없는지  
- [ ] **짧은 콘텐츠 페이지** — 푸터가 화면 하단에 붙는지(해당 레이아웃을 건드렸을 때)  
- [ ] **새 파일·링크** — `href` 오타, 존재하지 않는 HTML 링크 없는지  

### 배포한다면 (선택)

- [ ] 배포 후 **직접 URL**로 한 번 더 열어보기 (경로 대소문자, `index.html` 생략 여부 등)  

---

## 4. merge 한 직후

- [ ] 로컬 `main`에서 **다시 한 번 핵심 페이지만** 열어보기  
- [ ] 실험 브랜치는 **삭제해도 되는지** 확인 후 삭제 (원격/로컬) — **`lab`을 상시 유지**할지 팀 규칙에 따름  

---

## 5. 명령어 치트시트 (참고)

**실험 브랜치 `lab` 최초 생성 (`main` 기준):**

```bash
git checkout main
git pull
git checkout -b lab
git push -u origin lab
```

**실험 작업 후 `main`에 합치기 (로컬에서 직접 merge할 때):**

```bash
git checkout main
git pull
git merge lab
```

충돌 나면: 충돌 파일을 열어 `<<<<` `====` `>>>>` 구간을 정리한 뒤 저장 → `git add` → `git merge --continue` (또는 merge 완료 후 커밋).

**기능 브랜치를 쓸 때 (예: `lab`에서 또 갈라서 작업):**

```bash
git checkout lab
git pull
git checkout -b feature/작업-이름
# … 작업 후 main에 넣을지 lab에 넣을지에 따라 merge 대상 선택
```

main과 차이만 보기:

```bash
git diff main...HEAD
```

---

## 6. 이 프로젝트에서 특히 신경 쓸 곳

- HTML이 **페이지마다 비슷한 블록**(헤더, 메가메뉴, 푸터, `STR` 객체)을 **각자 들고 있음** → 한 파일만 고치면 다른 페이지와 **어긋날 수 있음**  
- 로컬 점검 시 내비에서 **`index.html`**, **`food.html`**, **`event.html`**, **`ggongbab.html`**, **`history.html`**, **`lab.html`** 정도는 번갈아 한 번씩 열어 보기 (`lab` 작업 중이면 **`lab-ggongbab.html`** 도 포함)  
- 이미지·데이터 경로는 **대소문자·상대 경로**가 배포 환경과 맞는지  

**배포 시 방문자에게 어떤 브랜치가 보이는지**(main / lab)는 `DEPLOYMENT_AND_BRANCHES.md` 를 참고하세요.

이 문서는 필요하면 항목을 지우거나 추가해 **본인에게 맞게** 고치면 됩니다.
