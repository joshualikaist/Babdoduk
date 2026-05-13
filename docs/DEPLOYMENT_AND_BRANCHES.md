# 배포·브랜치: 저장소 하나 — `main`(공개) + `lab`(실험)

이 프로젝트는 **저장소(폴더)는 하나**만 두고, **브랜치 두 개**로 공개용과 실험용을 나눕니다.  
별도 폴더를 복사해 “프로젝트 두 개”를 만들지 않아도 됩니다.

상세 절차·체크리스트는 다음도 함께 봅니다.

- **`BRANCH_MERGE_CHECKLIST.md`** … merge 전후 확인
- **README.md** … “Git: main vs lab” 요약

---

## 1. 브랜치 역할 (고정)

| 브랜치 | 역할 | 방문자(프로덕션) |
|--------|------|------------------|
| **`main`** | 완성·공개용. `index.html`, `ggongbab.html`, `food.html` 등 **본편** | Vercel Production이 이 브랜치를 가리키면 **공식 URL**이 여기를 따름 |
| **`lab`** | 실험용. `lab.html`, `lab-ggongbab.html`, `calendar.ics` 실험 등 **먼저 시험하는 변경** | Production이 `main`이면 **`lab`만 푸시해도 공식 사이트는 안 바뀜**. 보통 **Preview URL**만 갱신 |

**브랜치 이름:** 실험 브랜치는 이 저장소에서는 **`lab`** 을 기준으로 문서화했습니다. 이미 **`Babdoduk_beta_version`** 등 다른 이름을 쓰고 있다면, 그 브랜치를 **`lab`과 같은 역할(실험 전용)** 으로 취급하면 됩니다.

---

## 2. 매번 이렇게 한다 (기본 워크플로)

### 실험만 할 때

1. **`lab`으로 체카웃** (최초 1회: `main`에서 `lab` 브랜치 생성 후 푸시)
2. `lab.html`, `lab-ggongbab.html`, `calendar.ics` 등 **실험 관련 파일만** 수정해도 되고, 나중에 본편에 반영할 내용이면 같이 커밋 가능
3. **`lab`에 커밋·푸시** → Git 연동 Vercel이면 **프리뷰 배포**로 확인 (공식 도메인은 그대로 `main` 기준)

### 방문자 사이트에 반영할 때 (“명령할 때” / 릴리스)

1. 실험 결과가 안정적일 때 **`main`에 합친다**  
   - Pull Request로 리뷰 후 merge 하거나  
   - 로컬에서 `git checkout main` → `git pull` → `git merge lab` (또는 `lab`에서 온 PR merge)
2. **`main` 푸시** → Production 배포가 따라가면 **공식 사이트 갱신**
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
git add .
git commit -m "실험: lab ICS 연동 등"
git push origin lab
```

**실험을 공개에 반영:**

```powershell
git checkout main
git pull
git merge lab
# 충돌 나면 해결 후 커밋
git push origin main
```

---

## 4. Vercel

- **Settings → Git → Production Branch = `main`** 인지 확인합니다.
- **`lab`에 푸시** → 보통 **Preview**만 생성됩니다.
- **`main`에 푸시(또는 merge 결과 푸시)** → **Production(공식 URL)** 갱신

### CLI로만 `vercel --prod` 하는 경우

- 로컬 **체크아웃이 `main`인지** 확인한 뒤 실행합니다.  
- 실수로 `lab`에서 `--prod` 하면 실험이 공개될 수 있으니 주의합니다.

---

## 5. 다른 호스팅 (참고)

- **GitHub Pages / Netlify** … 게시 브랜치를 **`main`** 으로 두고, 실험은 다른 브랜치 + 프리뷰로 검증하는 패턴이 동일합니다.

---

## 6. 정리

- **한 저장소**, **`main` + `lab`(또는 기존 실험 브랜치)** 로 나눈다.
- **매번:** 실험은 `lab`에서, 공개 반영은 `main`에 merge 후 푸시.
- **파일 단위 복사 폴더 두 개**는 필수 아님 — Git 브랜치와 merge로 동일 목적을 달성한다.
