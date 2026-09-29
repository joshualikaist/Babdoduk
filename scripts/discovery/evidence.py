# -*- coding: utf-8 -*-
"""Evidence rules for the trend and habit lanes, and audience relevance.

Nothing here scores a story from its title. Trend and habit evidence must be found in the
source's own retrieved text (or, for engagement, in platform metadata), and every signal keeps a
verbatim detail so a reviewer can see why a story qualified.

trendEvidence kinds (owner decision, 2026-09-29):
  explicit_source_claim  a sentence of the source text says a FOOD is popular, new, sold out,
                         trending (the sentence itself must be about food)
  corroborated           another independent recent source (different host) covers the same
                         thing: two distinctive (rare in this run) words shared both ways
  engagement             platform metadata shows real current popularity (views)
  sales_data             a sentence about food reports sales/adoption figures

A recipe is not a trend: for recipe content only strong claims count (a recipe blog calling a
dish "popular" is not evidence that anything is trending).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Optional

from . import editorial
from .common import parse_time

TREND_MAX_DAYS = 30
ENGAGEMENT_MIN_VIEWS = 100_000   # meaningful reach, not a channel's usual audience
HABIT_NEWS_MAX_DAYS = 90         # current lifestyle reporting
HABIT_RESEARCH_MAX_DAYS = 730    # research and survey evidence (always shown with its date)
DETAIL_CHARS = 110
RARE_SHARE = 0.02                # a word in more than 2% of this run's recent candidates is generic

STRONG_CLAIMS = ("유행", "화제", "급증", "품절", "트렌드", "열풍", "오픈런", "대란", "입소문", "인기몰이", "인기를 끌",
                 "인기 급상승", "돌풍", "신드롬", "완판", "역대급", "SNS를 달구", "sns를 달구", "viral", "trending",
                 "trend", "sold out", "craze", "all the rage")
WEAK_CLAIMS = ("인기", "신상", "신제품", "popular", "new release")
SALES_WORDS = ("판매", "매출", "주문", "거래액", "출고", "소비량", "sales", "orders")
SALES_FIGURE = re.compile(r"(\d[\d,\.]*\s*(%|％|배|만\s*(개|봉|병|잔|건|명|팩|캔|세트)?|억\s*원|천\s*개|개|봉|병|잔|건)"
                          r"|\d+\s*위|1위|percent)", re.I)
HABIT_WORDS = ("식습관", "식생활", "식사 습관", "식사 패턴", "먹는 습관", "끼니", "결식", "거르", "아침 식사", "아침밥", "혼밥",
               "1인 가구", "혼자 먹", "도시락", "간편식", "배달 음식", "배달음식", "외식", "식단", "섭취", "저당", "웰니스",
               "식품비", "식비", "지출", "소비 행태", "구매 행태", "소비 패턴", "장보기",
               "건강한 식", "eating habit", "dietary habit", "diet quality", "meal skipping", "skipping breakfast",
               "eating pattern", "food consumption", "meal timing", "snacking")
# A behavior sentence reports something measured: a survey, study, report or data, or a figure
# with a change (share, increase, sales).
RESEARCH_WORDS = ("조사", "설문", "응답", "통계", "연구", "보고서", "리포트", "데이터", "실태", "survey", "study",
                  "respondents", "report", "data")
CHANGE_WORDS = ("비율", "비중", "증가", "감소", "늘었", "줄었", "늘어", "줄어", "성장", "매출", "판매", "소비", "급증",
                "percent", "increase", "decline", "share")
FIGURE = re.compile(r"\d")
RECIPE_TITLE = re.compile(r"(레시피|만드는\s*법|만들기|recipe|how to make)", re.I)
RECIPE_TEXT = ("recipe", "레시피", "재료", "ingredients", "tbsp", "tsp", "큰술", "작은술", "cups", "tablespoon")
RESEARCH_TEXT = ("연구진", "연구팀", "논문", "학회지", "저널", "journal", "study participants", "cohort", "randomized")
FOOD_KO = ("레시피", "요리", "음식", "먹거리", "먹방", "먹는", "먹을", "먹어", "먹었", "먹고", "밥", "반찬", "국물", "국밥",
           "국수", "찌개", "볶음", "김치", "라면", "냉면", "고기", "채소", "간식", "디저트", "빵", "떡볶이", "떡국", "편의점",
           "맛있", "식품", "식사", "끼니", "도시락", "간편식", "과자", "음료", "우유", "커피", "치킨", "샐러드", "메뉴",
           "식단", "영양", "소스", "김밥", "만두", "케이크", "초콜릿", "아이스크림", "과일", "식재료", "외식", "급식",
           "식음료", "식생활", "푸딩", "요거트", "크림", "스낵", "밀키트", "주먹밥", "삼각김밥", "컵라면", "당류", "저당")
FOOD_EN = ("recipe", "recipes", "food", "foods", "cook", "cooking", "kimchi", "rice", "soup", "noodle", "noodles",
           "dish", "dishes", "banchan", "mukbang", "snack", "snacks", "meal", "meals", "porridge", "pancake",
           "chicken", "pork", "beef", "meat", "egg", "eggs", "tofu", "stew", "bread", "cake", "sauce", "kitchen",
           "bake", "baking", "dessert", "desserts", "diet", "diets", "eating", "nutrition", "dietary", "breakfast",
           "lunch", "dinner")
FOOD_WORDS = FOOD_KO + FOOD_EN
FOOD_EN_RE = re.compile(r"\b(" + "|".join(FOOD_EN) + r")\b", re.I)
AUDIENCE = {
    "korea": ("한국", "국내", "k-푸드", "k푸드", "케이푸드", "korean", "korea", "kimchi", "김치"),
    "convenience_store": ("편의점", "gs25", "세븐일레븐", "이마트24", "cu ", "cu편의점", "cu에서", "convenience store"),
    "students_young": ("대학생", "학생", "캠퍼스", "학식", "mz", "20대", "청년", "자취", "university", "college"),
    "single_household": ("1인 가구", "혼밥", "혼자", "1인분", "자취", "single-person", "living alone"),
    "quick_meal": ("간편식", "도시락", "hmr", "밀키트", "즉석", "삼각김밥", "컵라면", "초간단", "10분", "15분", "quick",
                   "easy", "meal prep", "15-minute", "one-pan"),
    "budget": ("가성비", "저렴", "알뜰", "1+1", "2+1", "할인", "budget", "cheap"),
}
HANGUL = re.compile(r"[가-힣]")
LINKS = re.compile(r"(https?://\S+|www\.\S+|\S+\.(com|co\.kr|kr|net|org|io)/\S*)", re.I)
# Paid placement anywhere in the text (a video description, a post footer), not only its lead.
SPONSORED = re.compile(r"(유료\s*광고|광고\s*포함|광고를\s*포함|협찬|(?<![a-z])ppl(?![a-z])|paid promotion|sponsored by)", re.I)
NOT_SPONSORED = re.compile(r"(내돈내산|협찬\s*(없|아님|아닌|을\s*받지\s*않|받지\s*않))")
# A title that is a business result, not something people eat.
BUSINESS_TITLE = re.compile(r"(본사|점주|가맹|영업이익|실적|주가|판로|수출|협약|투자|인수|상장|광고|\[동향\]|입점|공략|진출|박차|"
                            r"산업|공급망|로드쇼|공급|납품|계약|제휴|유통망|(?<![a-z])(mou|cf)(?![a-z]))", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n")
TOKEN = re.compile(r"[0-9A-Za-z가-힣+]+")
PARTICLES = ("에서", "으로", "까지", "부터", "이", "가", "은", "는", "을", "를", "의", "에", "로", "와", "과", "도", "만")
STOP_TOKENS = {
    "편의점", "신상", "신제품", "출시", "인기", "트렌드", "유행", "요즘", "먹방", "리뷰", "후기", "추천", "맛", "음식", "식품",
    "메뉴", "신메뉴", "오늘", "최근", "한국", "국내", "소비자", "업계", "브랜드", "제품", "판매", "시장", "네이버", "블로그",
    "뉴스", "기사", "가격", "정보", "행사", "이벤트", "1+1", "2+1", "올해", "대세", "화제", "품절", "등장", "공개", "맛집",
    "먹거리", "간식", "이번", "가장", "진짜", "솔직", "정체", "난리", "대박", "선보여", "선보인", "출시한", "매출", "증가",
    "인기몰이", "완판", "top", "best", "new", "the", "and", "with", "for", "of", "in", "to", "a", "food", "trend",
    "trends", "korean", "korea", "recipe", "편의점신상",
    # headline verbs and filler that say nothing about WHAT is being covered
    "입맛", "잡은", "사로잡은", "공략", "선택", "겨냥", "확대", "강화", "진출", "성과", "박차", "달군", "나선다", "나섰다",
    "입점", "현지", "시장", "성장", "기업", "업계", "소비", "소비자", "건강", "한끼", "식사", "간편", "메뉴",
}


def is_food(title: str, text: str = "") -> bool:
    blob = (title or "") + " " + (text or "")
    low = blob.lower()
    return any(w in low for w in FOOD_KO) or bool(FOOD_EN_RE.search(blob))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text or "") if s and s.strip()]


def _clip(sentence: str, at: int) -> str:
    if len(sentence) <= DETAIL_CHARS:
        return sentence
    lo = max(0, at - DETAIL_CHARS // 2)
    return sentence[lo:lo + DETAIL_CHARS].strip()


def _claim(text: str, words, food_story: bool) -> Optional[tuple[str, str]]:
    """(term, verbatim sentence) for the first sentence that uses one of the words and is about
    food: the sentence names a food, or the story's own title does ("품절이 이어졌다" in a story
    about a cream bun). A claim in a story about something else ("이공계 인기") does not count, and
    neither does the seller speaking ("…트렌드에 맞춰 선보였다", "…라고 밝혔다")."""
    for sentence in sentences(text):
        low = sentence.lower()
        hits = [(low.find(w.lower()), w) for w in words if w.lower() in low]
        if hits and (food_story or is_food(sentence)) and not editorial.pr_sentence(sentence) and                 (words is not STRONG_CLAIMS or editorial.popularity_claim(sentence, words)):
            at, word = min(hits)
            return word, _clip(sentence, at)
    return None


def content_kind(title: str, text: str, medium: str, default: str = "") -> str:
    """recipe | news | research | video | post: what kind of page this is. A registry kind
    (a recipe blog, a news feed) is authoritative; a news story that mentions a recipe is news."""
    if default in ("recipe", "news", "research"):
        return default
    if medium == "research":
        return "research"
    blob = (text or "").lower()
    if RECIPE_TITLE.search(title or "") or sum(1 for w in RECIPE_TEXT if w in blob) >= 3:
        return "recipe"
    if medium == "news":
        return "news"
    if medium == "youtube":
        return "video"
    return "post"


def trend_signals(text: str, *, title: str = "", meta: Optional[dict] = None, now: Optional[datetime] = None,
                  published: Optional[datetime] = None) -> dict:
    """Signals found in the retrieved text (never the title) and in platform metadata. The title
    only tells whether the story is about food. {kind: {"text", "term", "strong"}}"""
    signals: dict = {}
    body = LINKS.sub(" ", text or "")         # a claim is never read out of a URL ("utm_medium=viral")
    food_story = is_food(title)
    strong = _claim(body, STRONG_CLAIMS, food_story)
    weak = None if strong else _claim(body, WEAK_CLAIMS, food_story)
    if strong:
        signals["explicit_source_claim"] = {"term": strong[0], "text": strong[1], "strong": True}
    elif weak:
        signals["explicit_source_claim"] = {"term": weak[0], "text": weak[1], "strong": False}
    # Measured demand (a sales/orders/search figure that rose or set a record); an independent
    # sentence is preferred over one that speaks for the seller.
    demand = [s for s in sentences(body) if editorial.demand_sentence(s) and (food_story or is_food(s))]
    demand.sort(key=editorial.pr_sentence)
    if demand:
        figure = SALES_FIGURE.search(demand[0]) or re.search(r"\d", demand[0])
        signals["sales_data"] = {"term": figure.group(0).strip(), "text": _clip(demand[0], figure.start()),
                                 "strong": True, "pr": editorial.pr_sentence(demand[0])}
    meta = meta or {}
    views = meta.get("viewCount")
    if isinstance(views, int) and views >= ENGAGEMENT_MIN_VIEWS and published and now and \
            (now - published).days <= TREND_MAX_DAYS:
        likes = meta.get("likeCount")
        detail = f"views {views:,}" + (f" · likes {likes:,}" if isinstance(likes, int) else "") + \
                 f" · uploaded {published.date().isoformat()}"
        signals["engagement"] = {"term": "views", "text": detail, "strong": True}
    return signals


def habit_signals(title: str, text: str) -> dict:
    """{"words": habit words in title+text, "behavior": the first sentence that reports something
    measured about eating (a survey, study, report or data, or a figure with a change)}."""
    text = LINKS.sub(" ", text or "")
    blob = ((title or "") + " " + text).lower()
    words = sorted({w for w in HABIT_WORDS if w.lower() in blob})
    behavior = ""
    for sentence in sentences(text):
        low = sentence.lower()
        measured = any(w in low for w in RESEARCH_WORDS) or (FIGURE.search(sentence) and any(w in low for w in CHANGE_WORDS))
        if measured and is_food(sentence):
            behavior = _clip(sentence, 0)
            break
    return {"words": words, "behavior": behavior}


def sponsored(text: str) -> bool:
    """Paid placement anywhere in the text, including a PPL tracking link; "협찬 없이" or
    "내돈내산" (paid for myself) is the opposite."""
    return bool(SPONSORED.search(NOT_SPONSORED.sub(" ", text or "")))


def business_title(title: str) -> bool:
    """A company result, deal, market column or ad campaign: news about business, not about eating."""
    return bool(BUSINESS_TITLE.search(title or ""))


def is_research(row: dict) -> bool:
    if row.get("contentKind") == "research" or row.get("medium") == "research":
        return True
    blob = (row.get("sourceExcerpt") or "").lower()
    return row.get("sourceTrust") == "A" and any(w in blob for w in RESEARCH_TEXT)


def audience(title: str, text: str) -> dict:
    """Korea / KAIST audience relevance: {"score": 0..1, "signals": [...]}. International
    material is kept; this only ranks what a Korean student is likely to care about higher."""
    blob = ((title or "") + " " + (text or "")[:1500]).lower() + " "
    found = [name for name, words in AUDIENCE.items() if any(w in blob for w in words)]
    hangul = len(HANGUL.findall(title or "")) / max(1, len((title or "").replace(" ", "")))
    if hangul >= 0.3 and "korea" not in found:
        found.insert(0, "korea")
    score = (0.5 if "korea" in found else 0.0) + 0.15 * len([f for f in found if f != "korea"])
    return {"score": round(min(1.0, score), 3), "signals": found}


def _tokens(text: str) -> set[str]:
    out = set()
    for raw in TOKEN.findall((text or "").lower()):
        token = raw
        for particle in PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle) and HANGUL.search(token):
                token = token[: -len(particle)]
                break
        if len(token) < 2 or token in STOP_TOKENS or token.isdigit() or re.fullmatch(r"\d+(월|일|년|주차)?", token):
            continue
        out.add(token)
    return out


def _shared(a: set[str], b: set[str]) -> set[str]:
    """Shared words, allowing Korean compounds: "생크림빵" is inside "우유생크림빵" (3+ letters).
    Latin words match whole (a plural s aside): "butter" is not "butternut"."""
    shared = set()
    for x in a:
        for y in b:
            short, long_ = (x, y) if len(x) <= len(y) else (y, x)
            if x == y:
                shared.add(short)
            elif not (HANGUL.search(x) and HANGUL.search(y)):
                if long_ == short + "s":
                    shared.add(short)
            elif (len(short) >= 3 and short in long_) or (long_.startswith(short) and len(long_) - len(short) <= 2):
                shared.add(short)
    return shared


def host(row: dict) -> str:
    url = row.get("canonicalUrl") or row.get("sourceUrl") or ""
    part = url.split("/")[2] if url.count("/") >= 2 else ""
    return part[4:] if part.startswith("www.") else part


def corroborate(rows: list[dict], now: datetime) -> dict[str, list[str]]:
    """candidateId -> candidateIds of other recent food stories from a different host that share
    at least two distinctive words with it, both ways (this title against the other's title and
    text). Distinctive means rare in this run: a word used by more than RARE_SHARE of the recent
    candidates ("식품", "건강", "시장") says nothing about the same thing."""
    recent = []
    for row in rows:
        published = parse_time(row.get("publishedAt"))
        if row.get("duplicateOf") or row.get("rejectionReason") or not published:
            continue
        if (now - published).days > TREND_MAX_DAYS or not is_food(row.get("title") or "", row.get("sourceExcerpt") or ""):
            continue
        title_tokens = _tokens(row.get("title") or "")
        recent.append((row, title_tokens, title_tokens | _tokens(row.get("sourceExcerpt") or "")))
    frequency = Counter(token for _, _, everything in recent for token in everything)
    limit = max(3, int(RARE_SHARE * len(recent)))
    found: dict[str, list[str]] = {}
    for row, title_a, all_a in recent:
        rare_a = {t for t in title_a if frequency[t] <= limit}
        for other, title_b, all_b in recent:
            if other is row or not host(row) or host(row) == host(other):
                continue
            rare_b = {t for t in title_b if frequency[t] <= limit}
            one_way, other_way = _shared(rare_a, all_b), _shared(rare_b, all_a)
            # two shared words both ways, and at least one of them a real name (3+ letters)
            if len(one_way) >= 2 and len(other_way) >= 2 and any(len(t) >= 3 for t in one_way | other_way):
                found.setdefault(row["candidateId"], []).append(other["candidateId"])
    return found
