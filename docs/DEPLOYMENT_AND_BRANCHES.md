# 배포 브랜치: main(공개) vs beta(실험)

이 문서는 **“베타에서 실험하고, 완성되면 main에만 반영해서 일반 방문자에게는 완성본만 보이게”** 하려는 경우를 정리합니다.

---

## 1. 먼저 알아두면 좋은 것 (fast-forward와 무관)

**방문자가 어떤 코드를 보는지**는 Git의 merge 방식(fast-forward인지 아닌지)이 아니라, **배포 서비스가 “프로덕션”으로 정한 브랜치**가 무엇인지로 결정됩니다.

| 상황 | 공식 사이트(프로덕션 URL)에 반영되나 |
|------|----------------------------------------|
| `Babdoduk_beta_version`에만 커밋·푸시 | **프로덕션이 `main`이면 반영 안 됨** (Vercel이면 보통 프리뷰 URL만 갱신) |
| `main`에 merge 후 푸시 | 프로덕션에 반영됨 |
| 로컬에서만 beta로 checkout | 원격에 올리지 않으면 **배포와 무관** |

그래서 **beta 전용 HTML 파일을 따로 만들 필요는 없습니다.** 같은 `index.html` 등을 두 브랜치에서 **다른 시점의 스냅샷**으로 가져가면 됩니다.

---

## 2. 브랜치 역할 (권장)

| 브랜치 | 역할 |
|--------|------|
| **`main`** | 완성·공개용. 프로덕션 배포가 이 브랜치를 가리키게 설정. |
| **`Babdoduk_beta_version`** (또는 `beta` 등) | 실험·작업 중. 완성되면 `main`으로 merge. |

로컬에서만 쓸 때:

```powershell
git checkout Babdoduk_beta_version   # 실험
# … 수정 후 커밋 …
git checkout main
git merge Babdoduk_beta_version      # 준비됐을 때만
git push origin main                 # 원격·배포에 반영할 때
```

---

## 3. Vercel을 쓰는 경우 (README에도 나옴)

### Git 저장소와 연결해서 자동 배포하는 경우

1. Vercel 대시보드 → 해당 프로젝트  
2. **Settings → Git**  
3. **Production Branch**를 **`main`** 으로 설정 (다른 브랜치면 공식 URL이 그쪽을 따라감)  

이렇게 해 두면:

- **`main`에 푸시** → 프로덕션(공식 도메인)이 갱신됨  
- **`Babdoduk_beta_version`에 푸시** → 보통 **Preview 배포**만 생기고, 공식 주소는 그대로 `main` 기준  

### CLI로만 `vercel --prod` 하는 경우

로컬에서 돌리는 **그때 체크아웃된 브랜치** 내용이 올라갑니다.  
실수로 beta를 배포하지 않으려면:

- **`main`으로 checkout 한 뒤** `vercel --prod` 하거나  
- 가능하면 **Git 연동 배포**으로 바꾸고 Production을 `main`으로 고정하는 편이 안전합니다.

---

## 4. 다른 호스팅 (참고)

- **GitHub Pages**  
  - 저장소 설정에서 **어느 브랜치/폴더**를 게시할지 고릅니다. 보통 **`main` + `/ (root)`**.  
  - beta만 공개하고 싶지 않다면 **게시 원천을 `main`만** 쓰면 됩니다.

- **Netlify**  
  - Production branch를 **`main`** 등으로 지정하는 방식과 유사합니다.

---

## 5. 정리

- **별도의 “beta용 index.html” 디렉터리를 만들 필수는 없음** — 브랜치가 버전을 나눕니다.  
- **공개 여부는 “프로덕션 브랜치 = main” 설정**으로 맞추는 것이 핵심입니다.  
- 베타는 **프리뷰 URL**이나 로컬에서만 검증하고, 괜찮아진 뒤에만 **main merge + push** 하면 됩니다.

더 보편적인 merge 전 절차는 `BRANCH_MERGE_CHECKLIST.md` 를 참고하세요.
