# 먹방 월드컵: 스토리 카드와 공유 (lab 먼저)

소유자 요청(2026-10-14): 1위가 정해지면 **인스타그램 스토리 전용**(1080×1920, 9:16, 피드 크기 없음) 이미지를 자동으로 만들고, 내려받거나 인스타 스토리·카카오톡으로 공유할 수 있게 합니다. 코드는 `js/worldcup.js` 의 "the story card" 부분, 화면은 `worldcup.html` 결과 화면입니다.

## 스토리 카드 (`prepareStory`, `drawStory`)

결과 화면이 뜨는 순간 캔버스에 그려 두고(언어를 바꾸면 다시 그림), 결과 화면에 작은 미리보기로 보여 줍니다. 미리 만들어 두는 까닭: 공유 시트는 누른 순간(사용자 활성화) 안에서만 열리므로, 누른 뒤에 그리기 시작하면 휴대폰에서 공유가 막힐 수 있습니다.

위에서 아래로:

1. 배경: 브랜드 분홍→남보라 그라데이션, 부드러운 빛, 사진 뒤 방사형 빛줄기, 색종이와 반짝이(같은 우승 메뉴면 같은 배치).
2. "🏆 나의 최애 메뉴" 유리 알약(Jua).
3. 우승 메뉴 사진: 크게, 둥근 흰 테두리, 살짝 기울임, 모서리에 금색 왕관.
4. 메뉴 이름: Jua 로 아주 크게(한 줄이 안 되면 두 줄, 사진이 그만큼 줄어듦), 아래에 다른 언어 이름.
5. "🍚 한식 32강 우승" 흰 알약.
6. 결승 상대와 4강 두 메뉴: 둥근 사진 칩 한 줄("결승 상대", "4강"). 대진 기록이 없는 옛 저장 판이면 결승 상대만.
7. "너의 최애는? 👉 babdoduk.vercel.app" 검은 알약(lab 에서는 lab 주소), 그 아래 Babdoduk 워드마크와 "밥도둑 먹방 월드컵".
8. 맨 아래 아주 작게 한 줄: "📷 Wikimedia Commons · 사진 출처 babdoduk.vercel.app/worldcup.html"(lab 에서는 lab 주소). 작가 이름과 라이선스는 카드에 적지 않고, CC BY / BY-SA 가 요구하는 표시는 그 주소의 결과 화면 "사진 출처"(우승·결승 상대·4강 사진 4장의 작가와 라이선스, 원본 링크 포함)로 합니다. 매체에 맞는 합리적인 방식의 표시(링크로 전체 출처를 안내)입니다.

인스타그램 스토리는 위아래 약 250px 를 자기 UI 로 덮으므로, 2~7은 모두 y 250~1670 안에 있습니다(바깥은 장식과 사진 출처 한 줄뿐).

- 사진은 이 사이트의 `images/worldcup/*.jpg`(같은 출처)만 씁니다. 그래서 캔버스가 오염되지 않고 PNG 로 내보낼 수 있습니다.
- 글꼴: 카드에 쓰는 글자만 담은 Jua 를 Google Fonts(`text=`)에서 따로 받아 카드 전용 이름의 FontFace 로 씁니다(페이지의 Jua 부분집합은 건드리지 않음). 4초 안에 못 받으면(오프라인 등) 카드 전체를 Noto Sans KR 굵게로 그립니다(글자마다 글꼴이 섞이지 않게).
- 파일: `babdoduk-worldcup-story.png`.

## 버튼과 공유 흐름

| 버튼 | 휴대폰(터치) | 컴퓨터 |
|------|--------------|--------|
| 📥 스토리 이미지 저장 | 파일 공유가 되면 공유 시트(파일만: "이미지 저장" 또는 바로 스토리), 아니면 내려받기 | PNG 내려받기, "저장했어요" |
| 📤 공유하기 | Web Share Level 2: 카드 파일 + 문구 + 친구 링크. 시트에 Instagram(스토리)·카카오톡이 나옵니다. `navigator.canShare({files})` 가 거짓이면 문구 + 링크만 | 친구 링크를 복사, "링크를 복사했어요" |

- 안내 한 줄: "인스타 스토리: 공유하기 → Instagram → 스토리".
- "저장했어요"·"링크를 복사했어요"는 화면 아래 토스트로 보이고 `role="status"` 로 한 번 읽힙니다. 공유 시트를 닫은 경우(AbortError)는 아무 말도 하지 않고, 다른 실패는 링크 복사로 넘어갑니다.
- 공유 문구: "나의 먹방 월드컵(한식) 우승 메뉴는 불고기! 너의 최애는?"(`wc.shareText`).

## 친구 도전 링크

`https://babdoduk.vercel.app/worldcup.html?from=<메뉴 id>&cat=<카테고리>` — 지금 주소의 origin 을 쓰므로 lab 에서 공유하면 lab 링크입니다.

- 열면 시작 화면 위에 "친구의 최애는 ○○! 🏆 너도 해봐"(메뉴 사진 포함)가 나오고 그 카테고리 타일이 골라져 있습니다.
- 두 값은 따로 검사합니다: `from` 은 풀의 메뉴, `cat` 은 알려진 카테고리(그 풀이 한 판 이상)일 때만 쓰고, 아니면 무시합니다.
- 절대 자동으로 시작하지 않습니다(`go=1` 만 시작, 링크에는 없음).
- 출시 전(`soon`, `js/worldcup-gate.js`): 배너는 보이지만 게임은 잠겨 있고 사진은 요청하지 않습니다.

## 링크 미리보기 (카카오톡 등)

`worldcup.html` 과 `event.html` 의 `og:*`·`twitter:*` 메타가 `images/worldcup/og-worldcup.jpg`(1200×630, 300KB 미만)를 가리킵니다. 출시 전 비공개 원칙에 맞춰 카테고리 타일은 보이지 않는 티저입니다: "오늘의 32강, 뭐가 나올까?", 캡슐 뽑기 기계, 트로피, 흐린 음식 사진. 이미지는 한 번 렌더링해 저장한 파일입니다(Playwright 로 HTML 을 찍어 JPEG 로 저장). 카카오톡은 미리보기를 캐시하므로, 바꾼 뒤에는 카카오 개발자 도구의 "공유 디버거"에서 캐시를 지워야 새 그림이 보입니다.

## 카카오톡 공유 카드 (Kakao JS SDK, lab 먼저)

결과 화면의 "💬 카카오톡" 버튼이 카카오톡 피드 카드를 보냅니다. 휴대폰 공유 시트(📤 공유하기)와는 별개의 길입니다.

- **SDK**: 공식 Kakao JS SDK `2.8.3` 하나만, `https://t1.kakaocdn.net/kakao_js_sdk/2.8.3/kakao.min.js`, `integrity="sha384-oroumrnFVE0xtgqyDZJARgERibXg2C28380uaUZz2kHDS5CR7tu20eGiOU6GkTpy"`, `crossorigin="anonymous"`. 해시는 Kakao 개발자 문서 다운로드 페이지의 값이고, 파일을 직접 받아 sha384 를 계산해 같은 값임을 확인했습니다.
- **언제 받나**: `js/worldcup.js` 의 `renderResult` → `showKakao()` → `loadKakao()` 만 받습니다(`<script>` 태그를 동적으로 만듦). 시작·대결 화면이나 다른 페이지에서는 받지 않고, HTML 에는 외부 스크립트 태그가 없습니다. 8초 안에 받아지지 않거나 무결성 검사·초기화가 실패하면 버튼은 계속 숨겨져 있고 다시 시도하지 않습니다. 누른 순간 SDK 가 쓸 수 없으면 버튼을 숨기고 기존 공유(`share()`)로 넘어갑니다.
- **키**: JavaScript 키는 `js/worldcup.js` 의 상수 `KAKAO_JS_KEY` 한 곳에만 있습니다. 공개값(도메인 제한)이라 코드에 둡니다. REST·Admin 키는 어디에도 쓰지 않고 받지도 않습니다. `Kakao.init` 은 `Kakao.isInitialized()` 로 지켜 한 번만 부릅니다.
- **등록된 도메인**(Kakao Developers → 앱 → 플랫폼 → Web): `https://babdoduk.vercel.app`, `https://babdoduk-lab.vercel.app`. 다른 주소(로컬 미리보기 등)에서는 카카오가 거절하므로 공유가 되지 않습니다.
- **키를 바꾸려면**: Kakao Developers 에서 앱의 JavaScript 키를 재발급(또는 새 앱을 만들어 같은 두 도메인을 등록)하고, `KAKAO_JS_KEY` 와 `tests/test_worldcup_share.py` 의 `KAKAO_KEY` 를 새 값으로 바꾼 뒤 lab 에서 확인하고 같은 순서(lab → 승인 → main)로 내보냅니다. 옛 키는 Kakao 쪽에서 폐기합니다. SDK 버전을 올릴 때는 다운로드 페이지의 새 버전과 해시를 쓰고 파일을 받아 직접 sha384 를 계산해 대조한 뒤, 코드의 `KAKAO_SDK` 와 테스트의 `KAKAO_SRC`·`KAKAO_INTEGRITY` 를 함께 바꿉니다.
- **카드 내용** (`kakaoFeed()`, `window.BabdodukWorldcupShare.kakaoFeed()`): 제목 "친구의 우승 메뉴는 ○○! 🏆", 설명 "한식 32강 · 너의 최애는?", 이미지 = 지금 origin 의 절대 https 주소(우승 메뉴 사진 `images/worldcup/<id>.jpg`, 없으면 `images/worldcup/og-worldcup.jpg`), 링크와 "너도 해보기" 버튼 = 친구 도전 링크(`worldcup.html?from=<메뉴 id>&cat=<카테고리>`, mobileWebUrl·webUrl 모두). 문구는 `i18n` 의 `wc.kakao*` 키입니다.
- **CSP**: 이 저장소의 `vercel.json` 에는 `Content-Security-Policy` 헤더도 `<meta>` CSP 도 없어서 따로 허용할 것이 없습니다. CSP 를 도입할 때는 `script-src https://t1.kakaocdn.net` 과 카카오 공유 창이 쓰는 주소를 허용해야 합니다.
- 카카오 서버가 카드 이미지를 가져가므로 lab 이든 production 이든 이미지 주소는 공개로 열려 있어야 합니다. 출시 전(`soon`)에는 결과 화면 자체가 없습니다.

## 시험

- `tests/test_worldcup_share.py`: 카드 크기 1080×1920, 버튼과 문구, 공유 흐름 분기, 친구 링크, og/twitter 메타와 이미지(크기·용량), 외부 스크립트 태그 없음, Kakao SDK 는 고정 주소·integrity·키 한 곳·결과 화면에서만 로드.
- `scripts/check_site_ui.py` `worldcup_share`: 우승까지 진행, 버튼, 생성된 카드가 1080×1920 이고 캔버스가 오염되지 않음, `navigator.share`/`canShare` 를 대신해 PNG 파일 공유 확인, 컴퓨터의 링크 복사와 토스트, 친구 링크(올바른 값·틀린 값), 출시 전 잠금, 페이지 오류 없음.
- `scripts/check_site_ui.py` `worldcup_kakao`: CDN 주소를 가짜 SDK 로 대신해, 결과 전에는 카카오 요청이 없고, `init` 이 키와 함께 한 번만 불리고, `sendDefault` 의 템플릿(제목·설명·절대 https 이미지·친구 링크 버튼)이 맞고, SDK 로딩 실패 시 버튼이 숨겨지고 페이지 오류가 없음.
