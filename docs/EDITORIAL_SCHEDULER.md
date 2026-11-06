# 소식·이벤트 예약 게시

소유자 요청 2026-11-06: lab은 운영 화면을 확인하고 수정하는 곳으로 쓴다. 일반 메뉴의
실험실·꽁밥 실험·카드뉴스 링크를 없애고 **게시 관리** 하나를 둔다. `lab.html`은 이 관리
화면이다. 기존 테스트용 `lab-ggongbab.html`과 미출시 페이지/데이터는 링크 없이 보존한다.
수집기·DB·운영 PC 작업을 삭제하거나 운영에 승격하는 결정은 아니다.

## 사용

1. `https://babdoduk-lab.vercel.app/lab.html`에서 GitHub 관리자 계정으로 로그인한다.
2. 소식 또는 이벤트를 작성한다. 한국어와 영어를 모두 입력한다.
3. **초안 저장**은 서버에만 저장한다. 운영 소식 페이지에는 나타나지 않는다.
4. 한국 시간으로 게시 시각을 고르고 한영 미리보기를 확인한다.
5. **미리보기 확인 · 예약 확정**은 그 게시물의 자동 운영 게시를 승인한다.
6. 게시 전에는 예약 취소·수정·초안 삭제가 가능하다. 이미 `main`에 반영된 항목은 잠근다.

원고는 서버에서 불러오고 저장하며 localStorage에 저장하지 않는다. 네트워크 오류나 저장
충돌 때 입력을 유지한다. 서버가 바뀌었다면 입력을 보관한 뒤 다시 불러온다. 브라우저를
닫으면 아직 저장하지 않은 입력은 사라지며, 저장한 예약은 브라우저 없이도 처리된다.
로그인 연결 전 **작성 화면 미리보기**는 저장·예약 버튼을 비활성화한다.

현재 관리 화면은 새 소식/이벤트 작성과 게시 전 원고 수정을 다룬다. 기존 운영 게시물의
수정/삭제, 사진 업로드와 인터랙티브 행사 코드는 일반 lab 작업·승인 절차로 처리한다.
페이지에 표시할 날짜·행사 기간과 **게시 시각**은 별도 값이다.

## 보관 및 인증

이 GitHub 저장소는 공개이므로 **미게시 원고를 평문으로 커밋하지 않는다**.
`inputs/editorial/schedule.json`에는 AES-256-GCM 암호문만 저장한다. 초기 빈 파일만 평문
`{"schemaVersion":1,"items":[]}`을 허용한다. `inputs/`는 배포하지 않는다.
`inputs/editorial/published.json`에는 게시된 항목의 id·digest·반영 시각만 기록한다.

`api/editorial.js`는 정확히 babdoduk-lab.vercel.app에서만 응답한다. GitHub OAuth의 state와
PKCE를 확인하고 토큰을 암호화한 HttpOnly/Secure/SameSite 쿠키에 한 시간 보관한다.
요청마다 허용 계정과 저장소 쓰기 권한을 다시 확인한다. 변경 요청은 Origin과 CSRF도
확인한다. 저장은 lab의 정해진 암호화 파일 한 개만 가능하고 Git blob SHA와 정상 브랜치
ref 갱신으로 경합을 막는다.
서버 의존성 `lib/`는 `vercel.json`에서 모든 호스트에 404다. 브라우저에 GitHub 토큰,
OAuth client secret, 암호화 키를 보내지 않는다.

## 최초 연결 — 초기 기능 출시가 끝나기 전에는 자동 게시하지 않음

초기 코드도 lab에 배포해 확인하고 소유자 승인 후 선택 승격한다. 이 문서의 존재나
로컬 테스트 성공은 lab 배포·승인 또는 기능 활성화를 뜻하지 않는다.

GitHub OAuth App은 소유자가 등록한다. Homepage URL은
`https://babdoduk-lab.vercel.app`, Authorization callback URL은
`https://babdoduk-lab.vercel.app/api/editorial?action=callback`이다.
앱은 공개 저장소 쓰기를 위해 `public_repo` 범위를 요청한다. 허용 계정의 기본값은
`joshualikaist`다. 저장소 쓰기 권한도 필요하다.

Vercel **babdoduk-lab의 Production 환경에만** 다음을 설정한다. agent/release worktree를
Vercel 프로젝트에 연결하지 않고, Vercel Git 배포를 사용한다.

| 설정 | 값 |
| --- | --- |
| `EDITORIAL_GITHUB_CLIENT_ID` | 등록한 OAuth App의 client ID |
| `EDITORIAL_GITHUB_CLIENT_SECRET` | 그 App의 secret |
| `EDITORIAL_SESSION_SECRET` | 독립적인 무작위 비밀값, 최소 32자 |
| `EDITORIAL_QUEUE_KEY` | 독립적인 무작위 비밀값, 최소 32자; Actions와 같은 값 |
| `EDITORIAL_GITHUB_ADMINS` | 선택, 쉼표로 구분한 허용 GitHub login; 기본 joshualikaist |

GitHub Actions repository secret에도 **동일한 `EDITORIAL_QUEUE_KEY`**를 설정한다.
값은 채팅·커밋·로그에 붙이지 않는다. 암호화 키는 비밀 관리 도구에 백업한다. 키를 바꾸기
전에 기존 큐를 복호화해 새 키로 재암호화해야 하며, 키를 잃으면 기존 예약을 복구할 수 없다.
세션 키 변경은 기존 로그인을 만료시킨다. 이 기능은 Supabase나 새 DB를 사용하지 않는다.

## 자동 게시 경로

`.github/workflows/editorial-publish.yml`은 main에서만 실행한다. 매시 03·08·13…58분에
기한이 된 항목을 확인하며 수동 실행도 가능하다. 아직 기한이 아니면 브라우저 의존성을
설치하지 않고 끝낸다. GitHub 예약 지연, 검사 시간과 Vercel 배포 시간이 있으므로 정확한
분 단위 공개를 보장하지 않는다. 시간보다 빨리 공개하지 않는다.

`scripts/publish_editorial.py`가 실행한다:

1. 최신 main/lab을 fetch하고, lab의 큐를 메모리에서 복호화·검증한다.
2. 예약 확정 + 기한 도달 + 미게시 항목만 고른다. 시계는 시간대가 있는 UTC이며 KST와
   비교한다. 같은 id와 digest는 재게시하지 않는다. 게시된 id의 내용 변경은 실패한다.
3. 최신 main의 별도 작업 공간에서 기존 `data/content/events.json`에 항목을 추가하고
   기존 `sync_site_chrome.py`로 `event.html`을 생성한다. 허용 변경은 이 두 경로와
   `inputs/editorial/published.json`뿐이다. **lab의 코드나 다른 파일을 main에 복사하지 않는다.**
4. 최신 lab의 별도 작업 공간에 새 main을 정상 병합한다. 충돌은 원격 변경 전에 실패한다.
5. 정확한 main/lab 후보 각각에서 전체 pytest·콘텐츠·동기화·사이트 UI·꽁밥 UI·실제 글꼴
   검사를 순차 실행한다. 이 runner의 로컬 픽셀 비교는 문서대로 skip하며, 기존 pinned
   ui-guardian의 승인된 baseline과 assertion은 바꾸지 않는다.
6. 두 원격이 검사 시작점 그대로이고 작업 공간도 그대로인지 확인한다. 원격 이동이나
   예약 취소가 있으면 푸시하지 않고 실패한다. 다음 실행이 최신 상태에서 새로 준비한다.
7. **일반 atomic push**로 main과 lab을 함께 갱신한다. 한쪽만 반영하지 않으며 force나
   rebase는 하지 않는다. Vercel Git integration이 두 배포를 시작한다.
8. 정확한 커밋의 두 Vercel 상태를 기다리고, 각 호스트의 `event.html`이 검사한 파일과
   같은지 읽기만 해서 확인한다. 실패하면 Actions가 실패 상태로 남고 자동 revert하지 않는다.

GITHUB_TOKEN의 푸시로 다른 push-triggered Actions가 다시 실행된다고 기대하지 않는다.
필수 검사들은 이 workflow 안에서 직접 실행한다. Vercel Git 배포 동작은 최초 연결 때
실제로 확인해야 한다. 실패/지연 확인은 GitHub Actions의 editorial-publish 실행 기록과
Vercel 배포 기록을 사용한다. main 반영 영수증은 배포 성공 증명과 구분한다.

## 확인과 중지

합성 검사: `python -m pytest tests/test_editorial.py -q` 및
`node --test tests/editorial.test.cjs`. 실제 계정이나 운영 저장소를 테스트로 쓰지 않는다.
예약을 중지하려면 게시 전에 관리 화면에서 취소한다. 전체 자동화를 중지하려면 GitHub에서
editorial-publish workflow를 Disable한다. 이미 공개된 내용은 일반 lab 수정·승인 절차로
바로잡는다. main 이력과 후속 자동 생성 데이터는 삭제하지 않는다.

근거: [GitHub OAuth](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps),
[GitHub 예약 실행](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
[GITHUB_TOKEN의 후속 실행 제한](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow),
[Vercel Functions](https://vercel.com/docs/functions/runtimes/node-js).
