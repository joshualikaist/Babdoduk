# 매거진 자료원 기준

밥도둑 매거진의 모든 이야기는 `scripts/discovery/sources.json`에 등록된 자료원에서 나옵니다. 이 문서는 어떤 자료원을
등록하는지, 무엇을 보여 주는지, 출처 주인이 어떻게 빠질 수 있는지를 정합니다. 수집 방식은
`docs/MAGAZINE_DISCOVERY.md`, 등록부의 형식은 `schemas/magazine-sources.schema.json`에 있습니다.

## 등록하는 자료원

자료원 하나가 등록부의 항목 하나입니다. 다음을 모두 만족해야 합니다.

1. **발행처가 직접 낸 길.** 발행처가 공개한 RSS·Atom 피드(티스토리 블로그의 `/rss`, WordPress의 `/feed/` 포함)나
   공식 API만 씁니다. 다른 서비스가 만든 피드, 구글 뉴스 RSS, 페이지를 긁는 방식, YouTube 채널 RSS·yt-dlp는 쓰지 않습니다.
2. **robots.txt가 허용.** 피드 주소를 일반 수집기에 허용해야 합니다. 같은 사이트에는 2초 이상 간격을 두고
   (`common.HostPacer`), 403·429가 오면 그 자료원은 그날 더 묻지 않습니다. IP를 바꾸거나 캡차를 풀지 않습니다.
3. **살아 있는 자료원.** 최근 14일 안에 새 글이 있어야 합니다. 120일 동안 새 글이 없으면 상태가 STALE로 바뀝니다.
4. **음식 이야기.** 음식 전문 매체·블로그는 최근 글의 70% 이상, 종합 매체의 섹션 피드는 30% 이상이 음식·식생활
   이야기여야 합니다.
5. **사람이 쓴 글.** AI가 쓴 글, 다른 글을 다시 쓴 글, 광고 글을 올리는 사이트는 등록하지 않습니다.

신뢰 등급(`trustTier`)은 이렇게 정합니다.

| 등급 | 자료원 | 실릴 수 있는 갈래 |
| --- | --- | --- |
| A | 정부·공공기관, 전문가 단체 | 모든 갈래 |
| B | 자리 잡은 언론·전문지, 이름이 알려진 요리 블로그·채널 | 모든 갈래 |
| C | 검색으로 찾은 글, 출처가 덜 알려진 블로그 | 요즘 유행·요리 비법 (건강 조언은 싣지 않음) |

## 보여 주는 것

- 링크가 걸린 제목, 화면에 보이는 그대로의 출처 이름, 날짜, 매체 종류.
- 글에서 가져온 한 문장(120자 이하)만 덧붙이고, 본문 전체를 옮기지 않습니다. 이 문장을 발행처가 쓴 미리보기로만 한정하는 것은 결정 5·6번(매거진 수집 계획) 뒤에 바꿉니다.
- 발췌를 싣지 않기로 한 자료원(신문협회 회원사 등)은 등록부에 `"excerpt": false`를 두어 제목·출처·날짜·링크만
  보여 줍니다. 그 글도 갈래 판단에는 쓰입니다.
- 이미지는 원본 주소로 보여 주기만 하고 복사하지 않습니다. YouTube 썸네일은 API에서 받은 것만 씁니다.
- 한 번 실은 이야기는 다시 싣지 않습니다. 밥도둑은 이야기를 지어내지 않습니다.

## 자료원 제안하기

등록부의 항목 하나를 더하거나 고치는 변경으로 제안합니다(변경 하나에 자료원 하나). 항목에는 이름, 피드 주소, 종류,
채울 갈래, 신뢰 등급과 robots.txt를 확인한 결과를 적습니다. CI가 형식을 검사하고(`validate_content.py --only
magazine`), 사람이 피드·robots.txt·음식 비중을 확인한 뒤 등록합니다.

## 출처 주인이 빠지기 (제안, 소유자 결정 전)

블로그·매체 주인은 언제든 등록부에서 빠질 수 있습니다. 사이트 아래의 문의 메일로 알려 주시면 7일 안에 항목을 끄고
(`"enabled": false`와 사유), 이미 실린 이야기도 지웁니다.

## English summary

Sources are registered one entry each in `scripts/discovery/sources.json` (contract
`schemas/magazine-sources.schema.json`). A source is collected only through its publisher's own
RSS/Atom feed or an official API, only where robots.txt allows it, at most once a day with two
seconds between requests to a host. It must be active (a post within 14 days) and about food. The
magazine shows the linked title, the source name as displayed, the date and at most one sentence
taken from the item (120 characters); images are linked, never copied; nothing is AI-written.
Proposed, pending the owner's decision: a source owner can ask to be removed through the contact
address on the site; the entry is disabled and its stories withdrawn within seven days.
