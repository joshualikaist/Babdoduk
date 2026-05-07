# Babdoduk

밥도둑 링크 모음 웹사이트 (`index.html` 단일 페이지).

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

### 5. 프로덕션(본 주소)에 반영

미리보기 주소만 나왔다면, 같은 폴더에서:

```powershell
vercel --prod
```

배포가 끝나면 `https://babdoduk.vercel.app` 형태의 주소가 표시됩니다. (프로젝트 이름이 다르면 URL도 그에 맞게 바뀝니다.)

### 6. 코드 수정 후 다시 올리기

`index.html` 을 저장한 뒤, 같은 폴더에서:

```powershell
vercel --prod
```

또는:

```powershell
vercel
```

---

## 로컬에서만 미리 보기

브라우저에서 `index.html` 파일을 더블클릭해 열거나, VS Code / Cursor의 **Live Preview**로 열어도 됩니다.  
**먹방 가계부**(`data/food-log.json` 을 불러옴)는 브라우저 보안 때문에 `file://` 로 열면 실패할 수 있습니다. 그럴 때는 Live Preview, `npx serve`, 또는 Vercel 배포 주소로 확인하세요.

---

## 먹방 가계부 데이터 (`data/food-log.json`)

인스타에 올린 글의 **Total** 금액을 이 파일에 날짜별로 적어 두면, 사이트에서 **월별·주차별 합계 표**와 **달력**이 자동으로 갱신됩니다.

- 인스타그램은 일반적으로 **게시 글을 자동으로 긁어오는 공개 API**가 없습니다. (본인 계정도 마찬가지인 경우가 많습니다.) 그래서 **포스팅 후 이 JSON에 한 줄씩 반영**하는 방식이 현실적입니다.
- **Google 캘린더 연동**은 가능은 하지만, 보통 **Google Calendar API + OAuth** 설정과 “하루 일정에 금액을 어떻게 적을지” 규칙이 필요합니다. 지금 구조는 서버 없이도 돌아가도록 **JSON만** 쓰도록 해 두었습니다. 나중에 스프레드시트 CSV 공개나 캘린더 연동으로 바꾸고 싶다면 그때 설계를 바꾸면 됩니다.

---

## 사이트에 들어 있는 것

1. 인스타그램 계정 링크  
2. 밥도둑 맛집 지도(네이버 지도)  
3. 문의 메일  
4. 먹방 가계부(일별 Total → 월·주 집계, 달력)  
5. (예정) 유튜브, 블로그, 카카오 오픈채팅 등
