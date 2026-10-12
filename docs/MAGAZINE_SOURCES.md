# 매거진 자료원 기준

밥도둑 매거진의 모든 이야기는 `scripts/discovery/sources.json`에 등록된 자료원에서 나옵니다. 이 문서는 다음을 정합니다.

- 어떤 자료원을 등록하는지
- 무엇을 보여 주는지
- 누가 어떻게 제안하고 빠지는지

수집 방식은 `docs/MAGAZINE_DISCOVERY.md`, 등록부의 형식은 `schemas/magazine-sources.schema.json`, 기여 절차는 `CONTRIBUTING.md`에 있습니다.
아래 규칙은 소유자가 2026-10-12에 정한 매거진 수집 계획의 결정 3~9번을 따릅니다.

## 등록하는 자료원

자료원 하나가 등록부의 항목 하나입니다. 다음을 모두 만족해야 합니다.

1. **발행처가 직접 낸 길.** 발행처가 공개한 RSS·Atom 피드나 공식 API만 씁니다. 티스토리 블로그의 `/rss`, WordPress의 `/feed/`도 여기에 들어갑니다.
   다음은 쓰지 않습니다.
   - 다른 서비스가 만든 피드, 구글 뉴스 RSS
   - 페이지를 긁어 오는 방식
   - YouTube 채널 RSS와 yt-dlp
2. **robots.txt가 허용.** 피드 주소를 일반 수집기에 허용해야 합니다.
   - 같은 사이트에는 2초 이상 간격을 둡니다(`common.HostPacer`).
   - 403이나 429가 오면 그 자료원은 그날 더 묻지 않습니다.
   - IP를 바꾸거나 캡차를 풀지 않습니다.
3. **살아 있는 자료원.** 최근 14일 안에 새 글이 있어야 합니다. 120일 동안 새 글이 없으면 상태가 STALE로 바뀝니다.
4. **음식 이야기.** 최근 글 가운데 음식·식생활 이야기의 비중이 이만큼은 되어야 합니다.
   - 음식 전문 매체·블로그: 70% 이상
   - 종합 매체의 섹션 피드: 30% 이상
5. **사람이 쓴 글.** AI가 쓴 글, 다른 글을 다시 쓴 글, 광고 글을 올리는 사이트는 등록하지 않습니다.
6. **네이버 블로그는 주인의 허락이 있을 때만.** 블로그 주인이 낸 RSS를 쓰고, 누가 언제 어디서 허락했는지 `"permission"`에 적습니다.
   허락이 없으면 검사가 등록을 막습니다.
7. **신문협회 회원사는 그 회원사의 허락이 있을 때만.** 한국온라인신문협회의 「디지털뉴스 이용규칙」을 따릅니다(소유자 결정, 2026-10-12).
   - 규칙은 비영리·일반 개인·한정적 범위라는 조건을 모두 갖춘 사용자에게만 허락 없는 직접링크(기사 주소로 바로 가는 링크)를 허용합니다.
     법인·단체, 많은 사람이 찾는 사이트는 회원사의 허락을 받아야 합니다.
   - RSS로 받은 기사를 허락 없이 공중에 다시 내보내는 것도 금지합니다. 기사 제목과 본문 일부를 함께 반복해 싣는 것도 금지합니다.
   - 밥도둑은 여러 사람이 보는 공개 사이트이므로, 허락이 없는 회원사 기사는 모으지도, 저장하지도, 싣지도 않습니다.
     웹 검색으로 찾은 기사도 마찬가지입니다.
   - 그 협회 회원은 한국신문협회 회원사여야 하므로, 한국신문협회 회원사 55곳과 디지털타임스를 회원사로 봅니다.
   - 목록과 근거는 `scripts/discovery/newspaper-members.json`에 있습니다(2026-10-12 확인).
   - 허락을 받으면 누가 언제 어디서 허락했는지 `"permission"`에 적고 `"excerpt": false`로 등록합니다. 그렇지 않으면 검사가 등록을 막습니다.

신뢰 등급(`trustTier`)은 이렇게 정합니다.

| 등급 | 자료원 | 실릴 수 있는 갈래 |
| --- | --- | --- |
| A | 정부·공공기관, 전문가 단체 | 모든 갈래 |
| B | 자리 잡은 언론·전문지, 이름이 알려진 요리 블로그·채널 | 모든 갈래 |
| C | 검색으로 찾은 글, 출처가 덜 알려진 블로그 | 요즘 유행·요리 비법 (건강 조언은 싣지 않음) |

## 쓰지 않는 길

- **네이버·카카오 검색 API.** 지금은 쓰지 않습니다(결정 3). 두 API의 약관은 결과를 저장하거나 고쳐 싣는 것을 막습니다.
- **열린 검색으로 네이버 페이지 읽기.** 네이버 약관은 허락 없는 자동 수집을 금지합니다.
  - 웹 검색(Exa)에 나온 네이버 페이지(블로그, 포스트, 카페, 뉴스)는 읽기 전에 버립니다.
  - 그전에 모인 것은 `HOST_NOT_COLLECTED`로 탈락시킵니다(`hosts.collectable`, 결정 4).

## 보여 주는 것

- **기본:** 링크가 걸린 제목, 화면에 보이는 그대로의 출처 이름, 날짜, 매체 종류.
- **한 문장:** 발행처가 직접 쓴 미리보기에서 **한 문장(120자 이하)**만 덧붙입니다.
  - 등록된 피드는 그 피드에 실린 글을 미리보기로 봅니다.
  - 인사말처럼 내용이 없는 첫 문장은 건너뛰고, 다음 문장을 씁니다.
  - 본문을 옮기지 않습니다.
- **웹 검색으로 찾은 글:** 검색이 가져온 본문은 갈래 판단에만 씁니다.
  - 카드의 문장은 그 이야기가 실릴 때 발행처 페이지의 `og:description`(또는 meta description)에서 한 번 읽습니다(`discovery.preview`).
  - 이때도 robots.txt를 먼저 확인하고 2초 간격을 지킵니다.
  - 읽지 못하면 문장 없이 싣습니다.
- **신문협회 회원사 기사:** 그 회원사의 허락이 없으면 싣지 않습니다(결정 5).
  - 회원사 도메인은 `scripts/discovery/newspaper-members.json`에 있고, 어떤 경로로 들어온 기사에든 적용됩니다.
    다른 회사가 운영하는 하위 도메인(예: 헬스조선 `health.chosun.com`)은 회원사로 보지 않습니다.
  - 저장소에 남아 있던 회원사 기사와 지난 호에 실렸던 회원사 기사도 다음 실행 때 지웁니다.
- **허락받은 회원사 기사와 `"excerpt": false` 자료원:** 제목·출처·날짜·링크만 보여 주고, 문장과 사진은 싣지 않습니다.
  - 이런 기사는 사진이 필요한 대표 이야기 자리에 오지 않습니다. 갈래 판단에는 그대로 쓰입니다.
  - 등록부나 회원사 목록이 바뀌면 이미 모아 둔 이야기에도 다음 실행부터 적용됩니다.
- **이미지:** 원본 주소로 보여 주기만 하고 복사하지 않습니다. YouTube 썸네일은 API에서 받은 것만 씁니다.
- **YouTube:** YouTube Data API로만 모으고, API 약관을 따릅니다.
  - API에서 받은 정보는 30일 넘게 보관하지 않습니다. 저장소에서 지우고, 업로드 28일이 지난 영상은 싣지 않으며, 28일 지난 호에서는 YouTube 영상을 뺍니다.
  - 카드에는 매체를 "YouTube"로 표시하고 채널 이름과 YouTube 링크를 답니다.
- 한 번 실은 이야기는 다시 싣지 않습니다. 밥도둑은 이야기를 지어내지 않습니다.

## 공개 저장소에 남기는 것

저장소가 공개되어 있으므로, 후보 기록(`research/magazine/candidates.jsonl`)에는 남의 글을 쌓지 않습니다(결정 6).

- **남기는 것:** 제목, 주소, 판정(갈래, 탈락 이유, 근거의 종류), 지문입니다.
  - 지문 1: 같은 이야기를 알아보는 낱말 목록(순서 없음, 30일 동안).
  - 지문 2: 글이 음식 이야기인지 등 판정에 필요한 몇 가지 사실.
- **남기지 않는 것:** 발췌와 근거 문장은 그 글을 읽은 실행 동안만 메모리에 둡니다.
- **다시 피드에 나온 글:** 다시 읽어 처음부터 판정합니다.
- **피드에서 사라진 글:** 남긴 판정을 그대로 쓰되, 나이와 다른 이야기의 뒷받침만 다시 봅니다.
  이런 글이 실릴 때 카드의 문장은 발행처 페이지의 미리보기에서 읽습니다.

## 5건을 못 채우는 날

갈래마다 5건을 싣습니다. 채우는 순서는 이렇습니다.

1. 새 이야기를 먼저 씁니다.
2. 모자라면 아직 싣지 않은 예전 이야기를 씁니다.
3. 그래도 모자라면 있는 만큼만 싣고, 지어낸 이야기로 채우지 않습니다(결정 9).

모자란 갈래는 알립니다.

- 수집 보고(`research/magazine/health.json`의 `shortLanes`)
- 실행 기록의 `[warn]` 줄
- GitHub Actions 실행 화면의 경고와 작업 요약 표

## 자료원 제안하기

누구나 자료원을 제안할 수 있습니다(결정 7). 방법은 둘 중 하나입니다.

- **이슈:** "매거진 자료원 제안" 양식을 씁니다.
- **변경(PR):** 등록부 항목 하나를 더하거나 고칩니다. 변경 하나에 자료원 하나입니다.
  항목에는 이름, 피드 주소, 종류, 채울 갈래, 신뢰 등급을 적습니다.

등록 전 검사는 세 단계입니다.

1. **CI:** 형식과 위 규칙을 검사합니다(`registry.validate`, 스키마 테스트).
2. **`scripts/check_source.py`:** robots.txt를 확인하고 피드를 한 번 읽어, 갈래마다 몇 편이 실릴 수 있는지 보여 줍니다.
3. **관리자 확인:** 피드와 음식 비중을 보고 등록합니다.

## 출처 주인이 빠지기

블로그·매체 주인은 언제든 등록부에서 빠질 수 있습니다. "자료원에서 빠지기" 이슈 양식이나 사이트 아래의 문의 메일로 알려 주세요.

- 7일 안에 항목을 끄고(`"enabled": false`), `"withdrawn"`에 요청 날짜와 경로를 적습니다.
- 다음 매거진 실행이 그 자료원의 이야기를 지난 호에서도 지웁니다(`select.sanitize`).
- 주인임을 증명할 서류는 받지 않습니다.

## 라이선스

- 등록부 `scripts/discovery/sources.json`은 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)으로 내놓습니다.
  누구나 출처 표시 없이 다시 쓸 수 있습니다.
- 코드는 MIT 라이선스(`LICENSE`)입니다(결정 8).
- 매거진에 실린 제목과 문장의 권리는 각 발행처에 있습니다.

## English summary

Sources are registered one entry each in `scripts/discovery/sources.json` (contract
`schemas/magazine-sources.schema.json`). These rules follow the owner's decisions 3-9 of
2026-10-12.

**What we collect**

- Only the publisher's own RSS/Atom feed or an official API, only where robots.txt allows it.
- At most once a day, two seconds apart per host.
- The public candidate store keeps no text of the source beyond the title: decisions, a few facts
  and, for 30 days, an unordered word list (decision 6).
- A source must be active (a post within 14 days), about food, and written by people.
- A Naver blog is registered only with its owner's permission, recorded in `"permission"`.
- Open web search never reads a Naver page.
- Naver's and Kakao's search APIs are not used.

**What a card shows**

- The linked title, the source name as displayed and the date.
- One sentence (at most 120 characters) of the publisher's own preview: the feed item's text, or,
  for a web search result, the page's `og:description`, read once when the story is published.
- A newspaper association member's article runs only with that member's permission. The usage rule
  is the Korea Online Newspaper Association's: only a non-commercial individual may link to a member's
  article without permission, and a member's RSS may not be republished, so Babdoduk, a public site,
  collects, keeps and shows none of their articles without it. Its members must belong to the Korea
  Newspaper Association (한국신문협회), so all 55 of those members plus 디지털타임스 count
  (`scripts/discovery/newspaper-members.json`, with evidence).
- A member that gave permission, or any source registered with `"excerpt": false`, is shown by
  title, source, date and link only, with no sentence and no photo.
- Images are linked, never copied. Nothing is AI-written.
- A lane short of five stories runs with what it has and is announced in the run report and on
  the GitHub Actions run.

**Proposing and leaving**

- Anyone can propose a source with the issue form or a one-source PR. CI checks the rules, and
  `scripts/check_source.py` reads the feed once and reports how many items would qualify per lane.
- An owner can ask to leave through the issue form or the site's contact email. Within seven days
  the entry is turned off and marked `"withdrawn"`, and the next run removes its stories from past
  editions.

**License**

The registry is dedicated to the public domain (CC0 1.0). The code is MIT. The headlines and
sentences shown belong to their publishers.
