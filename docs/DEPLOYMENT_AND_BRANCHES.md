# 배포·브랜치: 저장소 하나 — `main`(공개) + `lab`(실험)

이 프로젝트는 **저장소(폴더)는 하나**만 두고, **브랜치 두 개**로 공개용과 실험용을 나눕니다.  
별도 폴더를 복사해 “프로젝트 두 개”를 만들지 않아도 됩니다.

제품·UI·운영 변경의 범위는 저장소 루트의 `AGENTS.md`와 `ARCHITECTURE.md`를 먼저
확인합니다. 아래 전체 브랜치 merge 예시는 **lab 전체 차이에 대한 검토와 공개 승인이 끝난
경우**에만 사용합니다. 생성 JSON만 양 브랜치에 보내는 자동화와 기능 승격은 별도 작업입니다.

**현재 작업 모델:** `main` = production, `lab` = 통합/스테이징입니다. 에이전트는 자기
`agent/<tool>/<task>` 브랜치와 worktree에서 작업하고, 본편 후보는 최신 `origin/main` 에서 만든
통합 worktree에 승인된 브랜치를 `--no-ff` 로 합친 뒤, 그 병합 결과에서 게이트를 다시 돌리고 **일반 push**로
`main` 에 올립니다. 배포는 그 push를 받은 Vercel Git 연동이 합니다(4절). 규칙 전문은 `AGENTS.md`,
절차는 `.claude/skills/release-babdoduk` 입니다. 아래 2·3절의 `lab` 직접 작업·`git merge lab` 예시는
이 모델 이전의 방식이며, 전체 lab 승격이 따로 승인된 경우에만 씁니다.

상세 절차·체크리스트는 다음도 함께 봅니다.

- **`BRANCH_MERGE_CHECKLIST.md`** … merge 전후 확인
- **README.md** … “Git: main vs lab” 요약

---

## 1. 브랜치 역할 (고정)

| 브랜치 | 역할 | 방문자(프로덕션) |
|--------|------|------------------|
| **`main`** | 완성·공개용. `index.html`, `ggongbab.html`, `food.html` 등 **본편** | Vercel Production이 이 브랜치를 가리키면 **공식 URL**이 여기를 따름 |
| **`lab`** | 실험용. `lab.html`, `lab-ggongbab.html`, `calendar.ics` 실험 등 **먼저 시험하는 변경** | Production이 `main`이면 **`lab`만 푸시해도 공식 사이트는 안 바뀜**. 보통 **Preview URL**만 갱신 |

**브랜치 이름:** 실험 브랜치는 이 저장소에서는 **`lab`** 을 씁니다.

---

## 2. 매번 이렇게 한다 (기본 워크플로)

### 실험만 할 때

1. **`lab`으로 체카웃** (최초 1회: `main`에서 `lab` 브랜치 생성 후 푸시)
2. `lab.html`, `lab-ggongbab.html`, `calendar.ics` 등 **실험 관련 파일만** 수정해도 되고, 나중에 본편에 반영할 내용이면 같이 커밋 가능
3. **`lab`에 커밋·푸시** → Git 연동 Vercel이면 **프리뷰 배포**로 확인 (공식 도메인은 그대로 `main` 기준)

### 방문자 사이트에 반영할 때 (“명령할 때” / 릴리스)

1. 실험 결과가 안정적이고 **승인된 변경 범위가 lab 전체 차이와 일치할 때** `main`에 합친다
   - Pull Request로 리뷰 후 merge 하거나  
   - 로컬에서 `git checkout main` → `git pull` → `git merge lab` (또는 `lab`에서 온 PR merge)
2. `main` 변경은 별도 승인과 보호 영역 검토 후 푸시한다. 실제 Production 배포 결과는 따로 확인한다.
3. **본편 HTML 반영:** `lab-ggongbab.html`의 내용을 **`ggongbab.html`** 로 옮기는 등, 필요한 파일은 **merge만으로 자동 동기화되지 않을 수 있음** — diff를 보면서 수동 편집·정리

**“lab 프로젝트 파일을 전부 index 쪽으로 옮긴다”**는 말은 Git 기준으로는 **`lab` 브랜치를 `main`에 merge**하는 것과 같습니다. 다만 **어느 파일을 본편에 쓸지**는 매번 정해야 하며, `lab.html`은 `main`에도 두되 홈에서는 링크하지 않을 수 있습니다.

---

## 3. 로컬에서 브랜치 전환 (PowerShell 예시)

**실험 브랜치 최초 생성 (`main` 기준):**

```powershell
git checkout main
git pull
git checkout -b lab
git push -u origin lab
```

**실험 작업할 때:**

```powershell
git checkout lab
git pull
# … 수정 …
git status --short
git add -- <이번 작업에서 검토한 파일 경로>
git commit -m "실험: lab ICS 연동 등"
git push origin lab
```

**본편 반영 (현재 절차, 소유자 승인 뒤):**

```powershell
git fetch origin --prune
# 최신 origin/main 에서 임시 통합 worktree 를 만들고 승인된 브랜치를 합친다
git worktree add --detach ..\Babdoduk-wt\integration origin/main
git -C ..\Babdoduk-wt\integration merge --no-ff origin/<approved-branch>
# 그 병합 결과에서 네 게이트를 다시 돌린다. push 직전에 한 번 더 fetch 한다:
#   main 에 생성 데이터 bot 커밋만 늘었다면 최신 main 으로 다시 합치고 게이트를 다시 돌리고,
#   사람이 만든 소스 변경이 들어왔다면 멈추고 확인한다.
git -C ..\Babdoduk-wt\integration push origin HEAD:main   # 일반 push. --force 는 쓰지 않는다
```

`git checkout main` → `git merge lab` → `git push origin main` 처럼 lab 전체를 합치는 방식은
lab 전체 차이를 검토하고 공개를 따로 승인한 경우에만 씁니다.

---

## 4. Vercel (프로젝트 두 개로 비교)

이 저장소는 **Vercel 프로젝트를 둘** 둡니다. 브랜치 `main`/`lab`과 짝을 맞춥니다.

| Vercel 프로젝트 | URL | 용도 |
|-----------------|-----|------|
| **`babdoduk`** | https://babdoduk.vercel.app | **공개(배포)** — `main` 내용 |
| **`babdoduk-lab`** | https://babdoduk-lab.vercel.app | **실험** — `lab`에서 먼저 확인 |

### 배포는 Git 연동으로만 합니다

- **`babdoduk`**: Production Branch = **`main`**
- **`babdoduk-lab`**: Production Branch = **`lab`**
- GitHub 배포 기록 기준(2026-09-23 확인, 2026-09 릴리스에서도 같은 동작)으로 `main` push는 `babdoduk` Production
  배포를, `lab` push는 `babdoduk-lab` Production 배포를 만들고, 두 프로젝트가 서로의 브랜치를 Preview로 빌드합니다.
- 그래서 **검증을 마친 정확한 병합 결과를 `main` 에 일반 push 하는 것이 곧 production 배포**입니다(2절 절차).
  배포 결과는 그 커밋의 `Vercel – babdoduk` 상태로 확인합니다.

```powershell
gh api repos/joshualikaist/Babdoduk/commits/<sha>/status --jq '.statuses[] | [.context, .state, .description] | @tsv'
```

**Vercel CLI로 배포하지 않습니다.** `vercel --prod`(또는 `vercel deploy --prod`)는 검증되지 않은 작업 폴더를
그대로 공개 URL에 올릴 수 있고, Git 기록에 없는 배포를 만듭니다. 이전 판의 “CLI로 올릴 때” 절차는 폐기했습니다.
`.claude/settings.json` 과 `.claude/hooks/git_guard.py` 도 이 명령을 막습니다. Vercel 프로젝트 설정 자체는
이 문서가 바꾸지 않으며, 설정 변경은 소유자가 Vercel 대시보드에서 합니다.

---

## 5. 다른 호스팅 (참고)

- **GitHub Pages / Netlify** … 게시 브랜치를 **`main`** 으로 두고, 실험은 다른 브랜치 + 프리뷰로 검증하는 패턴이 동일합니다.

---

## 6. 정리

- **한 저장소**, **`main` + `lab`(또는 기존 실험 브랜치)** 로 나눈다.
- **매번:** 실험은 `lab`에서, 공개 반영은 승인된 diff와 보호 영역을 검토한 뒤 진행.
- **파일 단위 복사 폴더 두 개**는 필수 아님 — Git 브랜치와 merge로 동일 목적을 달성한다.

---

## 7. 매일 생성되는 콘텐츠 (매거진 · 학식)

기능 코드와 생성된 JSON은 따로 움직인다.

| 경로 | 시각 (KST) | 브랜치 |
|------|------------|--------|
| `data/magazine/` | 매일 10:00 | lab **과** main에 같은 JSON만 푸시 |
| `data/kaist-menu/` | 06:00, 10:30, 16:30 | 동일 |
| `data/ggongbab/latest.json` | 30분마다 | 동일 (`.github/workflows/ggongbab-refresh.yml`, `python scripts/refresh_ggongbab.py`). `manual.json` 은 손으로 쓰는 입력이라 복사 대상이 아니다. 행사 내용이 같고 `generatedAt` 만 바뀌면 커밋하지 않는다. 2026-09-25 YAML 오류 복구, 2026-09-26 예약 재활성화 |

- 워크플로: `.github/workflows/magazine-daily.yml` (concurrency `babdoduk-content-refresh`)
- 생성: `python scripts/refresh_magazine.py`, `python scripts/refresh_kaist_menu.py`
- 검증: `python scripts/validate_content.py` — 실패하면 프로덕션 데이터는 그대로 둔다
- 배포: `python scripts/publish_generated.py` 가 워크트리로 `origin/lab`, `origin/main`에 **허용 경로만** 복사한다. `git merge lab` 을 쓰지 않는다
- YouTube 검색 소스는 저장소 secret `YOUTUBE_API_KEY`가 있을 때만 넓어진다. 화면의 가로 매거진 레일은 현재 lab에서 제거되었다
- 꽁밥 파이프라인(Dooray → OpenAI → Supabase → JSON)은 `docs/GGONGBAB_PAGE.md` 참고. 과거 메일 일괄 수집은 같은 문서 16절(메일함 backfill, 수동 1회 실행이며 cron 대상이 아님). Secrets: `DOORAY_API_TOKEN`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(옛 이름 `SUPABASE_SERVICE_ROLE_KEY` 는 fallback), `OPENAI_API_KEY`
- 이 액션은 기능 HTML/JS를 main에 실어 보내지 않는다. 슬롯·학식 UI 같은 코드는 기존처럼 lab에서 시험한 뒤 공개 반영할 때만 `main`에 merge한다
