# -*- coding: utf-8 -*-
"""Editorial precision rules (owner decision, 2026-09-29): classify the ITEM, never the publisher.

A story belongs under a heading only when a normal reader would agree:
  요즘 먹방 유행  there is evidence it is actually happening now (demand, stockouts, measured sales
                or search growth, strong engagement, independent reporting) - a product launch or a
                round-up of launches is not a trend (PRODUCT_ANNOUNCEMENT_ONLY), and company PR
                language ("트렌드에 맞춰", "인기 상품", "소비자 니즈") is not evidence;
  요리 비법      it teaches something - ASMR, mukbang and compilations without instructions do not
                (NOT_INSTRUCTIONAL);
  건강한 한 끼   the source itself frames food and health or nutrition - healthiness is never
                inferred from ingredients (NO_HEALTH_BASIS);
  식습관         it is about how people eat - celebrity weight stories are not
                (CELEBRITY_DIET_GOSSIP), nor company promotion.
Fewer good stories beat more weak ones; there is no quota.
"""
from __future__ import annotations

import re

LAUNCH_TITLE = re.compile(r"(출시|선보|선봬|신제품|신상품|새상품|새 상품|신메뉴|론칭|런칭|내놔|내놓|출격|한정\s*판매|판매\s*시작|"
                          r"리뉴얼|새 단장|앞세워|라인업|포트폴리오|launch(es|ed)?\b|introduc(es|ed)\b|debuts?\b)", re.I)
# The lead sentence reports that someone launched something ("…를 출시했다", "…선보인다고 밝혔다");
# "최근 출시된 크림빵이 …" in a story about demand is not a launch.
LAUNCH_LEAD = re.compile(r"(출시(했|한다|하며|해\s|했다고|한다고|에\s*나섰|를\s*늘)|선보(였|인다|여\s|인다고|였다고|이며)|선봬|"
                         r"내놓(았|는다|아\s|으며)|내놨|잇달아\s*(출시|선보|내놓)|출간(했|한다|한다고)|론칭(했|한다)|런칭(했|한다)|"
                         r"판매를\s*시작|개발(돼|됐다|했다고|해\s*출시))")
LEAD_SENTENCES = 3          # a launch is often announced in the second or third sentence
ROUND_UP = re.compile(r"(^\s*\[[^\]]*(신상품|신제품|새상품|새 상품|신상)[^\]]*\]|\btop\s*\d+\b|[’'”\"]\s*외\s*$|\s외\s*$|"
                      r"신상\s*(모음|정리|총정리))", re.I)
# A sentence that speaks for the seller: attribution, plans, or stock PR phrases.
PR_SENTENCE = re.compile(r"(밝혔다|말했다|설명했다|강조했다|전했다|덧붙였다|계획이다|방침이다|예정이다|관계자|측은|라며|이라며|"
                         r"고\s*말|트렌드에\s*(맞춰|발맞춰)|트렌드를\s*반영|소비자\s*니즈|고객\s*니즈|니즈를\s*반영|인기\s*(제품|상품)|"
                         r"선보이게|출시하게|according to the company|said in a statement)", re.I)
DEMAND_WORDS = re.compile(r"(판매|매출|주문|거래액|출고|소비량|검색량|검색\s*수요|예약|이용자|방문객|sales|orders|searches)", re.I)
INCREASE_WORDS = re.compile(r"(증가|늘어|늘었|늘며|늘고|급증|성장|돌파|기록|올랐|오른|상승|신장|치솟|껑충|뛰었|뛰어|\d+\s*배|1위|누적|"
                            r"완판|품절|\bup\b|rose|jumped|grew|doubled|record)", re.I)
FIGURE = re.compile(r"\d")
# Safety and regulation: a recall "5배 검출" is not demand.
REGULATION = re.compile(r"(검출|회수|리콜|위반|적발|초과|부적합|기준치|판매\s*중단|판매\s*금지|행정처분|recall)", re.I)
# Words that mean popularity only when the sentence is about people wanting something:
# "오메가6를 급증시켜" or "환자가 급증" is not a food trend.
AMBIGUOUS_CLAIMS = ("급증", "트렌드", "trend", "역대급", "인기 급상승")
DEMAND_CONTEXT = re.compile(r"(수요|판매|매출|검색|관심|소비|구매|주문|이용|방문|찾는|찾아|줄을|줄 서|몰리|몰려|인기|손님|"
                            r"고객|팬|sns|유행|demand|sales|search|buy|queue)", re.I)
CELEBRITY = re.compile(r"((배우|가수|개그맨|개그우먼|방송인|아이돌|코미디언|모델|유튜버|인플루언서|걸그룹|보이그룹)\s*[가-힣A-Za-z]{2,6}\s*"
                       r"\(\d{2}\)|(배우|가수|개그맨|개그우먼|방송인|아이돌|코미디언)\s+[가-힣]{2,4}(이|가|은|는|의)?\s)")
WEIGHT = re.compile(r"(다이어트|요요|감량|\d+\s*kg|몸무게|체중|살\s*빠|살을\s*뺀|뱃살|몸매|식단\s*공개)", re.I)
ASMR_MUKBANG = re.compile(r"(asmr|먹방|mukbang|eating show|몰아보기|playlist|브이로그|vlog|montage)", re.I)
COMPILATION = re.compile(r"(compilation|모음|\d+\s*시간|\d+\s*hours?\b|\brecipes\b|\bideas\b|round-?up)", re.I)
# Instructions, not the word "ingredients" in an intro: numbered steps, a method heading, amounts.
STEPS = re.compile(r"(만드는\s*(방법|법)|조리\s*(순서|방법)|재료\s*[:：]|ingredients\s*[:\n]|instructions\s*[:\n]|"
                   r"directions\s*:|\bstep\s*\d|(^|\s)\d\.\s|\d+\s*(tbsp|tsp|큰술|작은술|컵)|how to make)", re.I)
SHOPPING_TITLE = re.compile(r"(best .{0,40} to buy|where to buy|what to buy|buying guide|gift guide|souvenir|shopping guide|"
                            r"구매\s*가이드|기념품|선물\s*추천|추천템|살\s*만한)", re.I)
HEALTH_BASIS = ("영양", "단백질", "식이섬유", "칼로리", "열량", "나트륨", "저염", "당류", "혈당", "혈압", "콜레스테롤", "비타민",
                "소화", "포만감", "비만", "건강", "식단", "다이어트", "균형 잡힌", "nutrition", "nutrient", "protein",
                "fiber", "calorie", "sodium", "cholesterol", "vitamin", "blood sugar", "healthy", "digest",
                "balanced diet", "low-sodium", "low-sugar")
EVENT_LEAD = re.compile(r"((교육|행사|캠페인|체험|대회|축제|간담회|세미나|강연|특강|워크숍|시식회)[’'”\"]?(을|를|에|에서)?\s*"
                        r"(실시|진행|개최|참여|열었|마련|펼쳤)|(대상|최우수상|우수상|금상|은상|장려상)(을|를)?\s*(받았|수상|차지)|"
                        r"수상했다)")
# Opinion columns and contributed pieces: someone's view, not reporting or evidence.
COLUMN = re.compile(r"(칼럼|인사이트\s*\(\d+\)|\[기고\]|\[시론\]|\[논단\]|\[사설\]|오피니언|기고문|\bop-ed\b)", re.I)
# A measured behavior sentence is about people (not a product's specification).
PEOPLE = re.compile(r"(소비자|응답자|가구|학생|청소년|직장인|국민|성인|어린이|노인|이용자|고객|사람|남성|여성|20대|30대|MZ|1인|"
                    r"구매|섭취|식사|끼니|혼밥|외식|배달|respondents|people|adults|students|consumers|households)", re.I)
RESEARCH = re.compile(r"(조사|설문|응답|통계|연구|보고서|리포트|실태|survey|study|respondents|report)", re.I)
CHANGE = re.compile(r"(비율|비중|증가|감소|늘었|줄었|늘어|줄어|성장|매출|소비|급증|percent|increase|decline|share)", re.I)


def _lead(row: dict) -> str:
    """The first LEAD_SENTENCES sentences of the excerpt (RSS text often has no space after a period)."""
    text = row.get("sourceExcerpt") or ""
    parts = re.split(r"(?<=다\.)|(?<=[.!?])\s", text)
    return " ".join(p for p in parts[:LEAD_SENTENCES] if p)


def round_up(row: dict) -> bool:
    """A list of launches ("[신상품] … 외", "[09/22 오늘의 새상품]", "TOP12")."""
    return bool(ROUND_UP.search(row.get("title") or ""))


def announcement(row: dict) -> bool:
    """A product or company launch: the title announces it, or the lead sentence reports that a
    company launched/released something."""
    return round_up(row) or bool(LAUNCH_TITLE.search(row.get("title") or "")) or bool(LAUNCH_LEAD.search(_lead(row)))


def pr_sentence(sentence: str) -> bool:
    return bool(PR_SENTENCE.search(sentence or ""))


def demand_sentence(sentence: str) -> bool:
    """Measured demand or adoption: a sales/orders/search/reservation measure with a figure and an
    increase or record - not a product spec ("당도를 68% 낮췄다") or a share ("매출의 70%")."""
    text = sentence or ""
    return bool(DEMAND_WORDS.search(text) and FIGURE.search(text) and INCREASE_WORDS.search(text)
                and not REGULATION.search(text))


def popularity_claim(sentence: str, strong_words) -> bool:
    """A strong claim word that, in this sentence, describes people wanting a food."""
    low = HASHTAG.sub(" ", sentence or "").lower()
    found = [w for w in strong_words if w.lower() in low]
    if not found or REGULATION.search(low):
        return False
    if all(w in AMBIGUOUS_CLAIMS for w in found):
        return bool(DEMAND_CONTEXT.search(low.replace("트렌드", "").replace("trend", "")))
    return True


def celebrity_diet(row: dict) -> bool:
    blob = (row.get("title") or "") + " " + (row.get("sourceExcerpt") or "")
    return bool(CELEBRITY.search(blob) and WEIGHT.search(blob))


def shopping_guide(row: dict) -> bool:
    return bool(SHOPPING_TITLE.search(row.get("title") or "") or "souvenir" in (row.get("sourceExcerpt") or "").lower())


HASHTAG = re.compile(r"#\S+")
MERCH = re.compile(r"(굿즈|키링|피규어|인형|에코백|텀블러|머그|스티커|포토카드|캐릭터\s*상품|merch)", re.I)
PURCHASE = re.compile(r"(구매하기|구매처|제품\s*정보\s*및\s*구매|shop now|buy now|shop the)", re.I)


def claim_counts(sentence: str, title: str, is_food) -> bool:
    """A creator's own hashtags (#ViralDessert) are labels, not a claim; a sold-out sentence about
    merchandise (굿즈) is not about food even in a food-industry story."""
    text = HASHTAG.sub(" ", sentence or "")
    if not re.search(r"[가-힣A-Za-z]{2}", text):
        return False
    if MERCH.search(text):
        return is_food(text)
    return is_food(text) or is_food(title or "")


def purchase_links(row: dict) -> bool:
    return bool(PURCHASE.search(row.get("sourceExcerpt") or ""))


# A video's views say something about a food only when the video is about what is popular.
TREND_TITLE = re.compile(r"(유행|요즘|신상|핫한|핫하다는|화제|인기|트렌드|품절|난리|대란|챌린지|오픈런|viral|trending|trend|hype)",
                         re.I)


def trend_titled(row: dict) -> bool:
    return bool(TREND_TITLE.search(row.get("title") or ""))


STOCKOUT = re.compile(r"(품절|오픈런|완판|대란|매진|줄을\s*서|줄\s*서|sold out|sell-?out)", re.I)


def stockout(sentence: str) -> bool:
    """Observed demand in a sentence: sold out, open-run, queues."""
    return bool(STOCKOUT.search(sentence or ""))


def opinion_column(row: dict) -> bool:
    return bool(COLUMN.search(row.get("title") or ""))


def behavior_sentence(sentence: str) -> bool:
    """Something measured about how people eat: a survey/study/report, or a figure with a change
    that concerns people - not a product's specification ("당도를 68% 낮췄다")."""
    text = sentence or ""
    return bool(RESEARCH.search(text) or (FIGURE.search(text) and CHANGE.search(text) and PEOPLE.search(text)))


def event_recap(row: dict) -> bool:
    return bool(EVENT_LEAD.search((row.get("sourceExcerpt") or "")[:220]))


def instructional(row: dict, kind: str) -> bool:
    """Does it teach something? ASMR, mukbang and montages never; a compilation or a video only
    when its retrieved text shows instructions (ingredients, steps, amounts); a recipe post from a
    recipe publication is a recipe."""
    title = row.get("title") or ""
    blob = title + " " + (row.get("sourceExcerpt") or "")
    if ASMR_MUKBANG.search(blob):
        return False
    shows_steps = bool(STEPS.search(row.get("sourceExcerpt") or "")) or int(row.get("howToMarkers") or 0) >= 2
    if COMPILATION.search(title):
        return shows_steps
    if kind == "video":
        return shows_steps or bool(STEPS.search(title))
    return kind in ("recipe", "post")


def health_basis(row: dict) -> list[str]:
    """Health/nutrition framing the source itself gives, in its title and retrieved text."""
    blob = ((row.get("title") or "") + " " + (row.get("sourceExcerpt") or "")).lower()
    return sorted({w for w in HEALTH_BASIS if w.lower() in blob})


def health_story(row: dict) -> bool:
    """The story is ABOUT eating and health: its title says so and the text supports it, or the
    text frames it strongly (3+ terms). Nutrition words in an administrative story ("식단관리와
    영양상담 항목") are incidental."""
    words = health_basis(row)
    in_title = [w for w in HEALTH_BASIS if w.lower() in (row.get("title") or "").lower()]
    return (bool(in_title) and len(words) >= 2) or len(words) >= 3


def how_to_markers(text: str) -> int:
    """Instruction markers in the full retrieved text (stored at discovery; the store keeps
    only a short excerpt)."""
    return len(STEPS.findall(text or ""))
