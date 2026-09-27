# 저장소 정리: 브랜치 · worktree · stash · 태그

끝난 작업의 브랜치와 worktree 를 언제, 어떻게 지우는지 정합니다. 규칙 전문은 `AGENTS.md`, 배포 순서는
**`DEPLOYMENT_AND_BRANCHES.md`**, 릴리스 점검은 **`BRANCH_MERGE_CHECKLIST.md`** 입니다.

정리는 항상 **조사(읽기 전용) → 분류표 → 소유자에게 삭제 목록 보고 → 승인된 정확한 목록만 삭제** 순서입니다.
삭제 목록을 보고하고 승인받기 전에는 아무것도 지우지 않습니다.

---

## 1. 영구 브랜치

| 브랜치 | 역할 | 정리 |
|--------|------|------|
| `main` | production (babdoduk) | 지우지 않는다. 강제 push 하지 않는다 |
| `lab` | 스테이징 = 본편 기준선 + lab 전용 실험 (babdoduk-lab) | 지우지 않는다. 강제 push 하지 않는다 |

그 밖의 브랜치는 모두 임시입니다. `babdoduk-content-bot` 은 생성 데이터를 `main`·`lab` 에 직접 커밋하므로
따로 남는 브랜치가 없습니다.

기록은 브랜치가 아니라 **annotated 태그**로 남깁니다(8절). `release-*` 는 본편에 들어간 릴리스, `archive-*` 는
합치지 않았지만 보존해야 하는 작업입니다. 태그는 정리 대상이 아니며 옮기거나 다시 만들지 않습니다.

---

## 2. 임시 브랜치와 worktree 의 수명

| 종류 | 이름 | 시작점 | 끝나는 때 |
|------|------|--------|-----------|
| 작업 | `agent/<tool>/<task>` | 최신 `origin/lab` | lab 통합·배포, (본편 대상이면) main 반영, back-sync 까지 끝났을 때 |
| release | `release/<name>` | 최신 `origin/main` | main 반영·production 확인·back-sync 뒤. 태그로 대체한다(8절) |
| 통합·back-sync | `integration/<name>`, `agent/<tool>/back-sync-<name>`, detached worktree | 그때그때 | 만든 커밋이 `main`/`lab` 에 들어갔을 때 |
| 작업 worktree | `../Babdoduk-wt/<task>` | 그 브랜치와 함께 | 브랜치가 끝나고 `status --short` 가 비었을 때(5절) |
| 백업·스냅숏·실험 | `*-backup`, `*-snapshot`, 미완성 실험 | 사람이 판단 | 소유자가 결정한다. 보존할 것은 `archive-*` 태그로 남긴 뒤 정리한다(8절) |

브랜치나 worktree 하나는 다음을 **모두** 만족할 때만 `SAFE_TO_DELETE` 입니다.

1. 작업이 끝났다.
2. 그 내용을 담은 `lab` 커밋의 `Vercel – babdoduk-lab` 배포가 성공했다.
3. 본편 대상이면 main 반영과 production 확인이 끝났다.
4. main → lab back-sync 가 끝났고 드리프트 확인이 비어 있다.
5. 고유 패치가 남아 있지 않다. upstream 에 같은 커밋이나 같은 패치가 있다(4절).
6. worktree 라면 `status --short` 가 비어 있고, 무시된 파일도 다시 만들 수 있는 산출물뿐이다(5절).
7. 그 브랜치에 기대는 진행 중 작업이 없다(열린 PR, 승인 대기, 다른 worktree 의 기준점).
8. 소유자·다른 에이전트의 작업 보호(7절)를 지킨다.

분류는 넷 중 하나로 적습니다.

| 분류 | 뜻 | 다음 행동 |
|------|----|-----------|
| `ACTIVE` | 진행 중이거나 승인 대기 | 유지 |
| `SAFE_TO_DELETE` | 위 6개 조건을 증거와 함께 충족 | 소유자 승인 뒤 삭제 |
| `KEEP_FOR_RELEASE_HISTORY` | 본편에 들어간 release 브랜치 | 태그 제안 → 승인 → 태그 생성 뒤 삭제 후보 |
| `OWNER_REVIEW_REQUIRED` | 고유 커밋, 커밋 안 된 변경, 소유자·다른 도구의 것, 정체를 모르는 것 | 소유자가 결정. 에이전트는 건드리지 않음 |

---

## 3. 조사 (읽기 전용)

```powershell
git fetch origin --prune
git worktree list --porcelain
git branch -vv
git branch -r
git stash list
git tag -l
gh pr list --state open
```

worktree 마다 상태를 봅니다. `--no-optional-locks` 는 index 도 다시 쓰지 않습니다.

```powershell
git --no-optional-locks -C <worktree> status --short
git --no-optional-locks -C <worktree> status --short --ignored   # worktree 를 지우면 무시된 파일도 함께 지워진다
```

---

## 4. 패치 동치 확인

릴리스는 `cherry-pick -x` 로 옮기므로 `git branch --merged` 만으로는 판단할 수 없습니다.

```powershell
git merge-base --is-ancestor <branch> origin/lab   # 종료 코드 0 = lab 에 그대로 들어 있음
git cherry origin/lab <branch>                     # '+' = lab 에 같은 패치가 없음, '-' = 같은 패치가 있음
git cherry origin/main <branch>                    # 본편 대상이면 main 에도 확인
```

- `+` 커밋이 있으면 하나씩 확인합니다. 충돌을 해결하며 옮긴 커밋은 패치가 달라져 `+` 로 보입니다.
  같은 제목의 커밋을 찾고(`git log --grep`), 두 패치를 비교합니다(`git range-diff <A>^! <B>^!`).
  내용이 들어갔다고 증명하지 못하면 `OWNER_REVIEW_REQUIRED` 입니다.
- `git cherry` 는 merge 커밋을 보지 않습니다. merge 가 있으면 두 부모가 upstream 에 있는지
  (`git merge-base --is-ancestor`), merge 가 자체 변경을 더했는지(`git diff-tree --cc <merge>` 출력이 비어야 함)를 따로 봅니다.
- `origin/lab` 에서 시작한 작업 브랜치를 `origin/main` 과 비교하면 lab 전용 실험 커밋까지 `+` 로 나옵니다.
  main 쪽은 승인되어 옮긴 커밋(`-x` 의 "cherry picked from")만 확인합니다.

---

## 5. worktree 정리

- 지워도 되는 worktree: `status --short` 가 비어 있고, 작업을 위해 만든 것이며, 그 작업이 끝났다.
- `git worktree remove <path>` 로 하나씩 지우고, 끝나면 `git worktree prune` 을 실행합니다. `--force` 는 쓰지 않습니다(`.claude/hooks/git_guard.py` 가 막습니다).
- 커밋 안 된 변경이 있는 worktree 는 지우지 않습니다. 소유자가 커밋·스냅숏·폐기를 먼저 결정합니다.
- 무시된 파일은 `.local/ui-shots` 처럼 다시 만들 수 있는 산출물이어야 합니다. `.env`, 브라우저 프로필, 세션·인증 파일이 보이면 멈추고 소유자에게 묻습니다.
- 무시된 설정 파일(`.claude/settings.local.json` 등)은 산출물이 아닙니다. 소유자 체크아웃의 같은 파일과 바이트 단위로 비교하고(`Get-FileHash`, `cmp`),
  다르면 그 파일만 따로 보관한 뒤 worktree 를 지웁니다. "원래 체크아웃에도 있다"는 것만으로는 삭제 근거가 되지 않습니다.
- 브랜치가 어떤 worktree 에 checkout 되어 있으면 그 브랜치는 지워지지 않습니다. worktree 를 먼저 정리합니다.

---

## 6. 브랜치 삭제

- 로컬: `git branch -d <branch>`. merge 되지 않은 브랜치는 git 이 거부하며, 거부되면 그 브랜치는 멈추고 소유자에게 보고합니다.
  강제 삭제(`-D`)는 쓰지 않습니다(git_guard 가 막습니다). upstream 설정을 바꿔 거부를 피하지도 않습니다.
  cherry-pick 으로만 들어간 브랜치는 내용이 같아도 `-d` 가 거부할 수 있습니다. 그때도 결정은 소유자 몫입니다.
- 고유 커밋이 로컬에만 있으면, 소유자 승인 뒤 먼저 `archive-*` 태그로 원격에 보존하고 태그가 그 커밋을 가리키는지 확인합니다(8절).
  그다음에야 브랜치를 정리합니다.
- 원격: 원격 ref 를 지우는 push(`git push origin --delete <branch>`)는 git_guard 가 에이전트에게 막습니다.
  승인된 목록을 받아 **소유자가 직접** 실행하거나 GitHub 에서 지웁니다. 에이전트는 다른 방법(`gh api` 등)으로 우회하지 않습니다.
- 지운 뒤 `git fetch origin --prune` 으로 원격 추적 ref 를 맞춥니다. 열린 PR 이 있는 브랜치는 지우지 않습니다.

---

## 7. 보호 대상 — 자동으로 지우지 않는 것

정리 작업은 다음을 자동으로 지우지 않습니다. 소유자가 항목별로 결정합니다.

- 커밋 안 된 변경이 있는 worktree
- 소유자의 원래 체크아웃과 그 안의 커밋 안 된 변경
- stash 전부(`git stash drop`·`clear` 는 쓰지 않습니다. git_guard 가 막습니다)
- 정체를 모르는 작업(누가 왜 만들었는지 모르는 브랜치·worktree·파일)
- 로컬에만 있는 고유 커밋(원격 `archive-*` 태그로 보존·확인하기 전), 백업·스냅숏 브랜치
- 다른 도구(Codex 등)의 worktree·브랜치, 정체를 모르는 worktree
- lab 전용 실험(`lab` 브랜치의 Realtime·공개 projection·Portal LIST poller·Windows worker 코드)
- 생성 데이터(`data/magazine/**`, `data/kaist-menu/**`, `data/ggongbab/latest.json`, `data/ggongbab/archive/**`, `data/foods/**`). 보관 기간은 제품 결정입니다

---

## 8. release · archive 태그

release 브랜치를 영원히 두지 않고, 본편에 들어간 merge 커밋에 annotated 태그를 남깁니다.
합치지 않았지만 보존해야 하는 작업(미완성 실험, 채택되지 않은 스냅숏)은 `archive-*` 태그로 남깁니다.

- 이름: `release-YYYY-MM-DD-<slug>`. 브랜치 `release/<name>` 과 헷갈리지 않게 슬래시를 쓰지 않습니다.
- 메시지에 release 브랜치 이름과 옮긴 lab 커밋(cherry-pick 원본)을 적습니다.

```powershell
git tag -a release-YYYY-MM-DD-<slug> <main-merge-sha> -m "<요약> (release/<name>, cherry-pick of <lab-sha>)"
git push origin release-YYYY-MM-DD-<slug>
```

- archive 태그 이름은 `archive-YYYY-MM[-DD]-<slug>` 입니다. 메시지에 상태(미완성, 채택 안 됨, lab·main 에 merge 금지)와
  원래 브랜치·worktree 를 적습니다. 커밋 안 된 작업이면 먼저 그 작업의 브랜치에 WIP 커밋으로 남깁니다(lab·main 에는 합치지 않음).

```powershell
git tag -a archive-YYYY-MM-DD-<slug> <commit> -m "<무엇이었는지, 상태, merge 금지>"
git push origin archive-YYYY-MM-DD-<slug>
git ls-remote origin "refs/tags/archive-YYYY-MM-DD-<slug>^{}"   # <commit> 과 같아야 정리를 시작한다
```

- 태그를 만들거나 지우기 전에 목록을 보고하고 소유자 승인을 받습니다. 원격 태그 삭제도 git_guard 가 막으므로 소유자 몫입니다.
- 태그가 생긴 release 브랜치는 `SAFE_TO_DELETE` 후보가 됩니다.
- 이 정리에서 쓰지 않는 것: `git branch -D`, `git worktree remove --force`, `git reset --hard`, `git clean`, 강제 push,
  Vercel CLI 배포(`vercel --prod`). 모두 쓰지 않습니다.

---

## 9. 정리도 lab 을 먼저 거칩니다

- 추적 파일을 지우는 정리(오래된 스크립트·이미지·문서)는 제품 변경과 같습니다. 최신 `origin/lab` 에서 작업 브랜치를 만들고
  lab 통합 → babdoduk-lab 확인 → 소유자 승인 → main 에 `cherry-pick -x` → back-sync 순서로 갑니다.
- 오래돼 보인다는 이유만으로 추적 파일을 지우지 않습니다. 삭제 제안에는 다음 증거를 붙입니다.
  - 참조 검색: `git grep -F <파일 이름> origin/lab`, `origin/main`, 동적 경로를 대비한 접두사 검색
  - 마지막 참조가 사라진 커밋: `git log -S<이름> origin/lab`
  - 공개 URL 로 서빙되는 파일인지(`.vercelignore`). 외부에서 링크했을 수 있다는 점도 적습니다
- 레거시 스크립트·문서가 가리키는 것도 참조입니다. 사이트가 쓰지 않는 자산이라도 먼저 지우면 그 스크립트가 깨진 채 남습니다.
  참조하는 파일을 먼저 폐기하고, 참조 검색을 다시 돌린 뒤, 완전히 고아가 된 자산만 지웁니다.
- 유지 판정에도 증거(참조하는 `파일:줄`)를 붙입니다. 근거를 찾지 못하면 유지가 아니라 `OWNER_REVIEW_REQUIRED` 입니다.
- 한 원본에서 나온 파일 묶음(압축 파일과 풀린 파일)은 함께 판단합니다. 라이선스 파일이 없는 외부 자산은 공개 서빙 여부와 함께 보고합니다.
- 생성 데이터와 lab 전용 실험은 정리 대상이 아닙니다.

---

## 10. 보고 형식

삭제 전에 이 표를 소유자에게 보고하고 멈춥니다.

| 항목 | 종류 | 분류 | 증거 | 제안 |
|------|------|------|------|------|
| `<name>` | branch / remote branch / worktree / stash / tag / file | 2절 분류 | 조상 여부, `git cherry` 결과, `status --short`, 배포 상태, 참조 검색 | 유지 / 삭제 / 태그 후 삭제 / 소유자 결정 |

승인 뒤에는 승인된 항목만 지우고, `git worktree prune` 과 `git fetch origin --prune` 을 실행한 다음, 실제로 지운 것과 남긴 것을 다시 보고합니다.
