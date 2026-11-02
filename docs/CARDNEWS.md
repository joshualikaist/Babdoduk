# 주간 꽁밥 카드뉴스 (lab 전용)

소유자 결정(2026-11-01): 매주 일요일 꽁밥 카드뉴스를 올린다. 표지 한 장과 월~금 다섯 장, 그날 어떤 꽁밥 행사가 있는지 알린다. 텔레그램으로 먼저 받아 보고, 인스타그램(@babdodukms)에 올린다.
소유자(2026-11-02): 이번 주 것부터 먼저 만들고, 텔레그램으로 보내기 전에 사이트에서 시안을 본다. 서울캠퍼스·외부 장소 행사는 "서울" 표시를 붙여 싣는다.

**lab 전용**입니다. `cardnews.html` 과 `data/cardnews/` 는 `vercel.json` 이 babdoduk-lab 이 아닌 모든 주소에서 404 로 답합니다(`tests/test_deploy_config.py`).

## 카드

`scripts/render_cardnews.py` 가 그립니다. 시험은 `tests/test_cardnews.py`.

- 1080×1350(4:5) PNG 6장: 1 표지, 2~6 월~금. 인스타그램 캐러셀은 모든 장을 첫 장 비율로 자르므로 6장이 같은 크기입니다.
- 내용은 공개된 꽁밥 목록 `data/ggongbab/latest.json` 에서만 가져옵니다. 행사는 시작 시각의 한국 날짜로 요일에 나눕니다. 주말 행사는 싣지 않습니다.
- 표지: "이번 주 꽁밥", 월~금 날짜 범위, 요일별 개수(없는 날은 –), 총 개수.
- 요일 카드: 시작~끝 시간(끝이 같은 날일 때만), 행사 이름(두 줄까지), 음식 종류(`data/content/labels.json` 의 `freeFood`, 제공이 확인된 경우만), "서울" 표시(장소에 서울이 있을 때), 건물·호실, 대상(원문에 적힌 경우만).
- 3개 이상이면 촘촘한 배치, 한 장에 4개까지. 더 많으면 "외 N개 더 · 사이트에서 확인하세요". 4개를 채우면 대상 줄은 뺍니다.
- 없는 날: "아직 알려진 꽁밥이 없어요"와 제보 안내.
- 모든 장 아래: "일정은 바뀔 수 있어요. 자세한 내용은 사이트에서 확인하세요."와 쪽 번호. 원본 포스터는 싣지 않습니다.
- 글꼴은 운영 PC 에 설치된 Noto Sans CJK KR(시간은 DejaVu Sans). Chrome 으로 그립니다(`BABDODUK_BROWSER`, 기본 `chrome`).

## 만들기

```
python scripts/render_cardnews.py                    # 이번 주(토요일부터는 다음 주)
python scripts/render_cardnews.py --week 2026-11-02  # 그 월요일부터의 주
```

`data/cardnews/<월요일>/1.png`~`6.png` 를 쓰고, `data/cardnews/index.json` 맨 앞에 그 주를 넣습니다(같은 주를 다시 그리면 바꿔 넣고, 최근 26주까지 남김). 각 주는 `counts`(월~금 개수), `total`, `feedGeneratedAt`(그린 목록의 시각), `renderedAt`, `images` 를 가집니다.

## 시안 페이지 (`cardnews.html`, `js/cardnews.js`, `css/cardnews.css`)

- `index.json` 의 가장 최근 주 6장을 순서대로 보여 줍니다. 카드를 누르면 원래 크기로 열립니다.
- 위에 날짜 범위, 개수, 그린 꽁밥 목록의 시각을 적습니다. 페이지 글은 언어 전환을 따르고, 카드 속 글은 한국어입니다.
- 진입: lab 주소에서 모든 페이지의 더보기 "카드뉴스"(`js/site.js` LAB_LINKS, 실험 페이지는 `scripts/sync_site_chrome.py` LAB_LINKS).

## 다음 단계 (아직 없음)

1. 소유자가 시안을 확인하면 텔레그램으로 6장을 앨범(`sendMediaGroup`, 2~10장)으로 보냅니다.
2. 매주 일요일 18:00(Asia/Seoul) 운영 PC 의 systemd 타이머가 그리고 보냅니다. 버튼: ✅ / 🔁 다시 만들기 / ❌. 운영 PC 는 지금 로그인 전에는 사용자 서비스가 돌지 않으므로(`Linger=no`) `loginctl enable-linger` 를 함께 정리합니다.
3. 인스타그램은 처음에는 소유자가 직접 올립니다(A안). 자동 게시(B안)는 Meta 앱에 `instagram_content_publish` 추가, 새 토큰, 게시에 한한 POST 허용, 공개 주소의 JPEG 가 필요해 소유자 승인 뒤에만 합니다.
