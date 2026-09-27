# 배포·브랜치: 저장소 하나 — `main`(공개) + `lab`(스테이징)

이 프로젝트는 **저장소(폴더)는 하나**만 두고, **브랜치 두 개**로 공개용과 스테이징을 나눕니다.
별도 폴더를 복사해 “프로젝트 두 개”를 만들지 않습니다. 규칙 전문은 `AGENTS.md`(“Lab-first lifecycle”),
절차는 `.claude/skills/release-babdoduk`, merge 전후 점검은 **`BRANCH_MERGE_CHECKLIST.md`** 입니다.
끝난 브랜치·worktree·태그 정리는 **`REPOSITORY_HYGIENE.md`** 를 따릅니다.

---

## 1. 브랜치 역할 (고정)

| 브랜치 | 역할 | Vercel |
|--------|------|--------|
| **`main`** | production. 방문자가 보는 본편 | `babdoduk` → https://babdoduk.vercel.app |
| **`lab`** | 스테이징 = **본편 기준선 + 의도된 lab 전용 실험**(Realtime·공개 projection·Portal LIST poller·Windows worker 등) | `babdoduk-lab` → https://babdoduk-lab.vercel.app |

`lab` 은 본편의 미리보기입니다. 그래서 **lab 은 본편보다 뒤처지면 안 됩니다.** 본편에 있는 소스 커밋이 lab 에 없으면
babdoduk-lab 은 더 이상 production 을 미리 보여 주지 못합니다(2026-09 에 실제로 일어난 실패: 본편만 갱신되고
lab 의 `mukbang.html` 이 옛 화면에 머물렀음).

---

## 2. 제품 변경의 순서 (lab 먼저 — 필수)

제품·UI·프런트엔드·문구·내비·페이지 디자인·반응형 수정과, 제품 동작에 딸린 문서는 **반드시** 이 순서를 따릅니다.

1. **작업:** 최신 `origin/lab` 에서 `agent/<tool>/<task>` 브랜치와 전용 worktree 를 만든다.
2. **lab 통합:** 작업 브랜치를 `lab` 에 합친다(그 자체로 승인이 필요한 단계).
3. **lab 배포:** 그 `lab` 커밋의 `Vercel – babdoduk-lab` 상태가 성공할 때까지 기다린다.
4. **lab 확인:** https://babdoduk-lab.vercel.app 에서 한·영, 1440·390·360 등으로 화면과 동작을 확인한다.
5. **소유자 승인:** lab 에 배포된 결과를 소유자가 승인한다. 로컬 테스트 통과는 승인이 아니다.
6. **release 후보:** 최신 `origin/main` 에서 release 브랜치를 만들고, 승인된 **정확한 커밋만** `git cherry-pick -x` 로 옮긴다.
   lab 전체를 main 에 merge 하지 않는다. lab 에는 본편에 갈 준비가 안 된 실험도 있다.
7. **본편:** 그 후보에서 게이트를 다시 돌리고, `main` 에 일반 push(강제 push 금지) → production 확인.
8. **back-sync:** 방금 본편에 들어간 커밋을 `lab` 에 다시 합친다(최신 `origin/main` 을 `lab` 에 일반 merge,
   lab 전용 실험은 유지). babdoduk-lab 배포까지 확인해야 릴리스가 끝난 것이다.

**본편이 목적지라는 것만으로 `main` 에서 시작하지 않습니다.** “사이트 업데이트”, “production 반영”, “릴리스 준비”,
“고쳐서 배포” 는 모두 일반 릴리스이며 lab 을 거칩니다. `main` 에서 바로 시작해도 되는 것은 다음뿐이고,
그때도 같은 작업 안에서 `lab` 으로 back-sync 합니다.

- 소유자가 lab 우회를 **명시적으로** 허락한 긴급 production hotfix
- 생성 데이터 bot 발행(`babdoduk-content-bot`, 7절)
- 소유자가 **명시적으로** 허락한 production 인프라 복구(예: `main` 에서만 도는 workflow)
- 소유자가 lab 을 우회하라고 **명시적으로** 말한 저장소 긴급 수정

---

## 3. 명령 (PowerShell 예시)

**작업 시작 — 항상 최신 `origin/lab` 에서:**

```powershell
git fetch origin --prune
git worktree add --no-track -b agent/claude/<task> ..\Babdoduk-wt\<task> origin/lab
```

**lab 이 본편을 따라잡았는지(드리프트) 확인 — 출력이 없어야 한다:**

```powershell
git log --format='%h %an %s' origin/lab..origin/main | Select-String -NotMatch 'babdoduk-content-bot'
```

**lab 통합(승인된 단계):** 최신 `origin/lab` 에서 만든 임시 worktree 에 작업 브랜치를 일반 merge 하고, 게이트를 돌린 뒤
`git push origin HEAD:lab`(일반 push). 그 커밋의 babdoduk-lab 배포가 성공할 때까지 기다린다.

**본편 반영(lab 에서 승인된 뒤):**

```powershell
git fetch origin --prune
git worktree add --no-track -b release/<name> ..\Babdoduk-wt\release-<name> origin/main
git -C ..\Babdoduk-wt\release-<name> cherry-pick -x <승인된 커밋...>   # lab 에 있고 승인된 것만
# 게이트 → release 브랜치 push → 최신 main 위 통합 후보에서 게이트 재실행 → 일반 push → production 확인
```

**back-sync(본편 반영 직후, 필수):**

```powershell
git fetch origin --prune
git worktree add --no-track -b agent/claude/back-sync-<name> ..\Babdoduk-wt\back-sync-<name> origin/lab
git -C ..\Babdoduk-wt\back-sync-<name> merge --no-ff origin/main   # 충돌은 파일별로, lab 전용 실험 유지
# 게이트 → git push origin HEAD:lab (일반 push) → babdoduk-lab 배포 확인 → 드리프트 확인이 비어 있을 것
```

`git merge lab` 을 main 에서 실행하는 “lab 전체 승격”은 기본 절차가 아닙니다. lab 전체 차이를 검토하고 소유자가
그 승격을 따로 승인한 경우에만 고려합니다. `git push --force`, `git reset --hard`, main ref 직접 갱신은 하지 않습니다.

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
