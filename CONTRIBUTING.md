# 기여 안내 · Contributing

밥도둑은 KAIST 학생을 위한 먹거리 사이트입니다. 지금 밖에서 받는 기여는 **매거진 자료원**입니다.
매거진에 실을 만한 음식 이야기를 꾸준히 내는 피드를 제안하거나, 등록된 자료원의 문제를 알려 주세요.
코드 변경은 먼저 이슈로 의논해 주세요.

## 자료원 제안하기

1. [자료원 기준](docs/MAGAZINE_SOURCES.md)을 확인합니다.
   - 발행처가 직접 낸 RSS·Atom 피드나 공식 API여야 합니다.
   - robots.txt가 그 피드를 허용해야 합니다.
   - 최근 14일 안에 새 글이 있고, 음식 이야기가 충분히 많아야 합니다.
   - 사람이 쓴 글이어야 합니다.
2. 둘 중 한 가지로 제안합니다.
   - **이슈:** "매거진 자료원 제안" 양식을 채웁니다. 피드 주소만 알아도 됩니다.
   - **PR:** `scripts/discovery/sources.json`에 항목 하나를 더합니다. PR 하나에 자료원 하나입니다.
     형식은 `schemas/magazine-sources.schema.json`에 있습니다.
3. PR이라면 올리기 전에 다음 둘을 돌려 봅니다.
   ```bash
   python -m pytest tests/test_schemas.py tests/test_magazine_discovery.py -q   # 형식과 규칙
   python scripts/check_source.py <자료원 id>                                   # robots.txt, 피드, 갈래별 수율
   ```
   `check_source.py`는 피드를 한 번 읽어, 등록되면 어느 갈래에 몇 편이 실릴 수 있는지 보여 줍니다.
   아무것도 저장하지 않습니다.
4. CI가 형식과 규칙을 검사합니다. 관리자가 `check_source.py`로 피드와 수율을 확인한 뒤 등록합니다.

다음 경우는 등록하지 않습니다.

- 네이버 블로그를 블로그 주인의 허락 없이 등록하는 경우. 허락받았다면 그 내용을 `"permission"`에 적습니다.
- 검색 결과나 다른 서비스가 만든 피드, 페이지를 긁어 오는 방식.
- 광고 글이 많거나 AI가 쓴 글을 올리는 사이트.

신문협회 회원사(`scripts/discovery/newspaper-members.json`)의 피드는 `"excerpt": false`로 등록합니다.
그 기사는 제목·출처·날짜·링크만 보여 줍니다.

## 자료원에서 빠지기 (블로그·매체 주인)

"자료원에서 빠지기" 이슈 양식을 쓰거나, 사이트 아래의 문의 메일로 알려 주세요. 7일 안에 처리합니다.

- 등록부 항목을 끄고, `"withdrawn"`에 요청 날짜와 경로를 남깁니다.
- 다음 매거진 실행에서 그 자료원의 이야기가 지난 호에서도 빠집니다.
- 주인임을 증명할 서류는 받지 않습니다.

## 라이선스

- 코드 기여는 [MIT 라이선스](LICENSE)로 받습니다.
- 자료원 등록부(`scripts/discovery/sources.json`) 기여는 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)으로 받습니다.

기여하면 이 조건에 동의하는 것으로 봅니다.

## 지켜 주세요

- 비밀값·쿠키·토큰·개인 정보·비공개 주소를 올리지 않습니다.
- 생성 데이터(`data/magazine/`, `data/kaist-menu/`, `data/ggongbab/`)를 손으로 고치지 않습니다.
- 저장소 작업 규칙은 [AGENTS.md](AGENTS.md)에 있습니다.

---

## English

Babdoduk is a food site for KAIST students. The outside contribution we take today is
**magazine sources**: propose a feed that regularly publishes food stories, or report a problem
with a registered source. Please open an issue before changing code.

### Proposing a source

1. Read the [source rules](docs/MAGAZINE_SOURCES.md):
   - the publisher's own RSS/Atom feed or an official API;
   - robots.txt allows the feed;
   - a new post within 14 days, and mostly about food;
   - written by people.
2. Propose it in one of two ways:
   - **Issue:** fill in the "Propose a magazine source" form. The feed address is enough.
   - **PR:** add one entry to `scripts/discovery/sources.json`, one source per PR. The format is
     `schemas/magazine-sources.schema.json`.
3. For a PR, run these first:
   - `python -m pytest tests/test_schemas.py tests/test_magazine_discovery.py -q` checks the format and rules.
   - `python scripts/check_source.py <id>` checks robots.txt, reads the feed once and shows how many
     items would qualify for each lane. It writes nothing.
4. CI checks the format and rules. A maintainer checks the feed with `check_source.py` before registering it.

We don't register:

- a Naver blog without its owner's permission (record the permission in `"permission"`);
- search results or feeds made by another service;
- scraping;
- sites full of ads or AI-written posts.

Register a newspaper association member's feed (`scripts/discovery/newspaper-members.json`) with
`"excerpt": false`. Its stories are shown by title, source, date and link only.

### Leaving (for blog and publication owners)

Use the "Remove my source" issue form, or the contact email at the bottom of the site. We act
within seven days:

- we turn the entry off and record the request in `"withdrawn"`;
- the next magazine run removes the source's stories from past editions too.

We ask for no proof of ownership.

### License

- Code contributions are accepted under the [MIT License](LICENSE).
- Contributions to the source registry (`scripts/discovery/sources.json`) are accepted under
  [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

Contributing means you agree to these terms. Never commit secrets, cookies, tokens, personal data
or private addresses, and never hand-edit generated data.
