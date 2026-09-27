# 브랜치 작업 · lab 통합 · main 반영 체크리스트

제품 변경은 **작업 브랜치 → `lab` → babdoduk-lab 확인 → 소유자 승인 → `main` 에 승인된 커밋만 → lab back-sync**
순서로만 본편에 갑니다(`AGENTS.md` “Lab-first lifecycle”, 절차: `.claude/skills/release-babdoduk`,
배포 정책: **`DEPLOYMENT_AND_BRANCHES.md`**). `main` 에 push 하는 것이 곧 production 배포입니다.

비교용 URL:

- 스테이징: https://babdoduk-lab.vercel.app (`babdoduk-lab` 프로젝트, `lab` 브랜치)
- 공개: https://babdoduk.vercel.app (`babdoduk` 프로젝트, `main` 브랜치)

---

## 0. 매번 지킬 것

- [ ] 작업 브랜치는 **최신 `origin/lab`** 에서 만들었다. 본편이 목적지라는 이유로 `main` 에서 시작하지 않았다
- [ ] `main` 에서 시작했다면, 소유자가 lab 우회를 **명시적으로** 허락한 경우(긴급 hotfix, main 에서만 가능한 인프라 복구, 저장소 긴급 수정)이며 그 허락을 기록했다
- [ ] 드리프트 확인이 비어 있다: `git log --format='%h %an %s' origin/lab..origin/main` 에 bot 이 아닌 커밋이 없다
- [ ] 생성 데이터(`data/magazine/**`, `data/kaist-menu/**`, `data/ggongbab/latest.json`, `data/ggongbab/archive/**`)는 bot 이 lab·main 에 직접 푸시한다. 이 JSON 커밋을 기능 커밋과 섞지 않았다
- [ ] `lab.html` / `lab-ggongbab.html` 은 두 브랜치에 있어도 되지만, 홈 내비에는 실험 링크를 걸지 않는다

---

## 1. lab 에 통합하기 전

- [ ] `git status` — 의도하지 않은 파일(대용량 zip, `__pycache__`, 로컬 설정)이 커밋에 없다
- [ ] 변경 파일이 이번 작업 범위와 맞고, 보호 영역(`supabase/`, workflow, collector 등)은 승인이 있을 때만 들어 있다
- [ ] 게이트 첫 실행 결과를 기록했다(`/verify-babdoduk`): pytest, `validate_content.py`, `check_site_ui.py`, `check_ggongbab_ui.py`, 레이아웃·문구 변경이면 `check_real_fonts.py`
- [ ] 공통 내비·푸터·i18n(STR)을 여러 HTML 에 반영했다면 같은 패턴인지 모든 페이지를 훑었다

---

## 2. lab 통합 후 (본편 반영 전 필수)

- [ ] 그 `lab` 커밋의 `Vercel – babdoduk-lab` 상태가 **성공**이다
- [ ] https://babdoduk-lab.vercel.app 에서 바뀐 페이지와 내비의 주요 페이지를 한·영, 1440·390·360 으로 확인했다(가로 넘침·JS 오류 없음)
- [ ] 공통 페이지는 babdoduk.vercel.app 과 비교했다. lab 은 최소한 본편 기준선이며, 다른 점은 lab 전용 실험이나 이번 변경으로 설명된다
- [ ] 소유자가 lab 에 배포된 결과를 **승인**했다

---

## 3. main 반영 (release)

- [ ] release 브랜치는 **최신 `origin/main`** 에서 만들었다
- [ ] 승인된 커밋만 `git cherry-pick -x` 로 옮겼다. `git merge lab` 이나 `origin/lab` merge 를 하지 않았다
- [ ] 옮긴 커밋은 모두 lab 에 있다(`git merge-base --is-ancestor <sha> origin/lab`)
- [ ] 충돌 해결이 lab 에서 승인된 화면·동작을 바꾸지 않았다(바꿨다면 멈추고 lab 으로 다시 보냄)
- [ ] 보호 경로·브라우저 백엔드 guard 가 비어 있다(release 절차 3절)
- [ ] 최신 main 위 통합 후보에서 게이트를 다시 돌렸고, push 직전에 fetch 했다(bot 데이터만 늘었으면 다시 합치고 재검증, 사람 소스 변경이면 멈춤)
- [ ] `main` 에 일반 push 만 했다. `vercel --prod` 는 쓰지 않는다

---

## 4. main 반영 직후

- [ ] `Vercel – babdoduk` 상태가 성공이고, https://babdoduk.vercel.app 에서 바뀐 기능이 lab 에서처럼 동작한다
- [ ] **back-sync:** 최신 `origin/main` 을 `lab` 에 일반 merge 해 push 했고, 그 커밋의 babdoduk-lab 배포가 성공했다
- [ ] 드리프트 확인이 다시 비어 있다. 이것까지 끝나야 릴리스 완료다
- [ ] 끝난 작업·release 브랜치와 worktree 를 `REPOSITORY_HYGIENE.md` 대로 분류해 보고했다. 삭제는 소유자 승인 뒤에만 한다

---

## 5. 이 프로젝트에서 특히 신경 쓸 곳

- HTML 이 페이지마다 비슷한 블록(헤더, 메가메뉴, 푸터, `STR` 객체)을 각자 들고 있다. 한 파일만 고치면 다른 페이지와 어긋날 수 있다
- 점검할 때 `index.html`, `ggongbab.html`, `mukbang.html`, `event.html`, `food.html`, `history.html` 을 번갈아 열어 본다(lab 작업이면 `lab-ggongbab.html` 도)
- lab 전용 실험(Realtime·공개 projection·Portal LIST poller·Windows worker)은 본편 release 에 섞이지 않게 한다
- 이미지·데이터 경로의 대소문자·상대 경로가 배포 환경과 맞는지 본다
