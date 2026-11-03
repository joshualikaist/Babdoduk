# 공개 범위와 권리 표시

소유자 결정(2026-11-04): 사이트 주소만으로 화면과 데이터를 뽑아 가는 AI 역분석 도구(예: REA)가 흔해졌다. 밥도둑은 "무엇을 공개하는지, 무엇은 허락 없이 쓸 수 없는지"를 정확히 적어 둔다. 아래 네 가지는 이 문서와 `AGENTS.md` 가 고정하며, 넓히려면 소유자 결정이 필요하다.

## 1. 권리: 모든 권리 보유

- `LICENSE`: 코드, 문서, 디자인, 글, 이미지, 그리고 `data/` 아래 공개 데이터와 그 편집물은 모두 권리가 보호된다(All rights reserved). 복제, 수정, 배포, 상업적 이용, 자동 수집(스크래핑, 크롤링, AI 학습·분석·역분석), 다른 사이트에 데이터를 실시간으로 띄우는 일은 사전 서면 허락이 필요하다.
- 허락되는 일: 브라우저로 보기, 출처를 밝힌 짧은 인용과 링크 공유, GitHub 이용약관이 공개 저장소에 허용하는 보기와 포크.
- 제3자 자료(먹방 월드컵 사진, 글꼴, 행사 원문)는 각 권리자의 조건을 따른다. 매거진 자료원 등록부 `scripts/discovery/sources.json` 은 CC0 1.0.
- 2026-11-04 이전 커밋은 MIT 고지로 공개됐다. 그때 받아 간 사본의 MIT 허락은 되돌릴 수 없고, 이 고지는 그 뒤의 모든 버전에 적용된다.
- 사이트 하단의 "Copyright © 2026 밥도둑 · Babdoduk. 모든 권리 보유."(`shared/footer.html`, `footer.copyright`)가 같은 고지를 화면에 보인다.
- `LICENSE` 는 사이트에도 배포되어 `/LICENSE` 에서 글자로 열린다(`vercel.json` 이 `text/plain; charset=utf-8` 로 보낸다).

## 2. 다른 사이트의 브라우저가 데이터를 읽는 일

- `vercel.json` 은 `/data/` 아래 모든 응답에 `Access-Control-Allow-Origin: https://www.babdodukms.com` 을 붙인다. Vercel 의 기본값은 `*`(어느 사이트든)였고, 그래서 복제 사이트가 방문자의 브라우저에서 우리 꽁밥 데이터를 실시간으로 불러올 수 있었다.
- 우리 페이지는 모두 자기 주소의 `data/...` 를 상대 경로로 읽으므로(같은 출처) 이 머리말과 상관없이 동작한다. babdoduk.vercel.app, babdoduk-lab.vercel.app 도 마찬가지다.
- `/data/` 응답에는 `Link: </LICENSE>; rel="license"` 도 붙어, 데이터를 받아 간 쪽에 권리 고지를 알린다.
- 한계: 서버에서 직접 받아 가는 것과 진짜 브라우저를 움직이는 도구는 이 머리말로 막을 수 없다. 머리말은 "남의 사이트에 실시간으로 띄우기"를 막고, 받아 가려면 매번 직접 퍼 가야 하게 만든다.

## 3. 수집 로봇

- `robots.txt`(사이트 루트, `.vercelignore` 의 `!robots.txt` 로 배포): AI 학습·답변용 수집 로봇(GPTBot, ClaudeBot, CCBot, Google-Extended, PerplexityBot, Bytespider 등)은 사이트 전체를 거절하고, 모든 로봇에게 `/data/` 를 거절한다. 검색엔진은 페이지를 계속 색인할 수 있다.
- `robots.txt` 는 규칙을 지키는 로봇에만 효과가 있다. 지키지 않는 수집은 위 1번 `LICENSE` 가 금지한다.

## 4. 공개 데이터는 스키마가 허용한 칸만

- 배포되는 것은 페이지, `css/`, `js/`, `images/`, `data/`, `manifest.json`, `robots.txt`, `LICENSE` 뿐이다. 코드, 테스트, 문서, 입력, 스키마, `data/content/` 는 `.vercelignore` 가 뺀다(`tests/test_deploy_config.py`).
- `data/` 의 공개 JSON 은 각 스키마(`schemas/*.schema.json`, 목록은 `docs/DATA.md`)가 허용한 칸만 담는다. 스키마는 정해 두지 않은 칸을 거절하고(`additionalProperties: false`), `scripts/validate_content.py` 가 스키마를 통과하지 못한 파일을 잡는다.
- 새 공개 칸이나 파일은 스키마 변경이며, 보호 경계(`AGENTS.md`)라 소유자가 따로 승인한다. 2026-11-04 승인: 3D 캠퍼스 지도의 `data/campus/`(건물 표 `buildings.json`, 이후 모델과 정지 이미지). OpenStreetMap 의 공개 건물 위치와 이름뿐이다(`docs/CAMPUS_MAP.md`). 메일 원문, 주소, 토큰, 포털 ID, 비공개 원본 주소는 어떤 공개 파일에도 들어가지 않는다.
- 제보 게시판(`tip.html`)이 쓰는 Supabase 공개 주소와 publishable key, 함수 이름은 원래 공개용이다. 브라우저는 검사하는 함수와 게시판 보기만 부를 수 있다(`docs/GGONGBAB_TIPS.md`).

## 브라우저로 보이는 것의 한계

화면 코드(HTML, CSS, JS)와 공개 데이터는 브라우저가 내려받으므로 누구나 볼 수 있고, 저장소를 비공개로 해도 마찬가지다. 브라우저로 내려가지 않는 것(수집·분류 파이프라인, AI 지시문, 운영 PC, 두레이·포털·인스타 수집, DB 비공개 내용)은 공개 화면으로 알 수 없다. 밥도둑의 경쟁력은 수집망, 반영 속도, 확인의 정확도에 있다.

## 확인

- `tests/test_deploy_config.py`: `/data/` 머리말의 허용 출처와 권리 링크, `/LICENSE` 의 글자 형식, `robots.txt` 가 배포되고 AI 로봇과 `/data/` 를 거절하는지, `LICENSE` 가 모든 권리 보유 고지인지.
- 배포 뒤: `curl -sI https://babdoduk-lab.vercel.app/data/ggongbab/latest.json` 의 `access-control-allow-origin` 이 `https://www.babdodukms.com` 인지, `/robots.txt` 와 `/LICENSE` 가 200 인지.
