# -*- coding: utf-8 -*-
"""Fetch public RSS into data/magazine/{date}.json for the 10:00 KST edition.

Blogs and YouTube official feeds only. No news-search firehose.
Instagram is not scraped; the edition keeps idea-desk links instead.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "magazine"
UA = "BabdodukMagazine/1.0 (+https://github.com/joshualikaist/Babdoduk)"
KST = timezone(timedelta(hours=9))
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
YT_ID = re.compile(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{11})")
IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)

LANE_LEADS = {
    "tips": "밥이 더 맛있어지는 작은 조리 팁",
    "trend": "요즘 사람들이 뭘 먹고 있는지",
    "health": "맛도 포기하지 않는 건강식",
    "habit": "잘 먹는 법에 대한 작은 이야기",
}

BLOGS = [
    {"name": "엄마표 집밥", "url": "https://irisblossomlife.tistory.com/rss", "lanes": ["tips", "habit"]},
    {"name": "Korean Bapsang", "url": "https://koreanbapsang.com/feed/", "lanes": ["tips", "health"]},
    {"name": "My Korean Kitchen", "url": "https://www.mykoreankitchen.com/feed", "lanes": ["health", "habit"]},
]

# Public Atom feeds only. Do not scrape watch pages.
YOUTUBE_CHANNELS = [
    {"id": "UCC9pQY_uaBSa0WOpMNJHbEQ", "name": "자취요리신", "lanes": ["tips"]},
    {"id": "UCtby6rJtBGgUm-2oD_E7bzw", "name": "쿠킹트리 Cooking tree", "lanes": ["tips"]},
    {"id": "UCPWFxcwPliEBMwJjmeFIDIg", "name": "하루한끼", "lanes": ["health"]},
    {"id": "UCPKNKldggioffXPkSmjs5lQ", "name": "햄지 Hamzy", "lanes": ["trend"]},
]

YT_QUERIES = ["먹방", "요즘 음식", "신상 음식", "편의점 신상", "야식 먹방", "혼밥", "한국 길거리 음식", "신메뉴", "간편식 신상"]

LANE_SIZE = 8

TIPS_WORDS = ("레시피", "만드는", "만들기", "볶음", "끓이", "양념", "손질", "불 조절", "식감", "조리", "how to", "recipe", "자취요리")
TREND_WORDS = ("먹방", "신상", "편의점", "유행", "신메뉴", "핫한", "요즘", "길거리", "혼밥", "야식", "asmr")
HEALTH_WORDS = ("건강", "단백질", "샐러드", "저염", "저당", "채소", "영양", "두부", "균형", "vegan", "fiber")
HABIT_WORDS = ("아침", "야식", "습관", "천천히", "포만", "식사", "루틴", "물 한", "시간")
DESSERT_WORDS = ("케이크", "쿠키", "디저트", "티라미수", "빵", "마카롱", "cake", "cookie")

BLOCK_SOURCES = {"vietnam.vn", "google news"}
BLOCK_TITLE = (
    "위장 학대",
    "경고:",
    "dangerous trend",
    "지원을 받아",
    "쿠팡파트너스",
    "맛집",
    "리조트",
    "호텔",
    "3x Speed",
    "위글위글",
    "주방템",
    "콜라보",
    "출장",
    "노포",
    "장터",
    "비하인드",
    "꼬칫집",
    "영수증만",
    "이벤트안내",
    "유동골뱅이",
)

INSTAGRAM_IDEAS = [
    {"title": "밥도둑 인스타", "url": "https://www.instagram.com/babdodukms/", "source": "Instagram"},
    {"title": "쿠킹트리", "url": "https://www.instagram.com/cooking_tree/", "source": "Instagram"},
    {"title": "탐색 · #집밥", "url": "https://www.instagram.com/explore/tags/%EC%A7%91%EB%B0%A5/", "source": "Instagram"},
    {"title": "탐색 · #먹방", "url": "https://www.instagram.com/explore/tags/%EB%A8%B9%EB%B0%A9/", "source": "Instagram"},
    {"title": "탐색 · #편의점조합", "url": "https://www.instagram.com/explore/tags/%ED%8E%B8%EC%9D%98%EC%A0%90%EC%A1%B0%ED%95%A9/", "source": "Instagram"},
    {"title": "탐색 · #자취요리", "url": "https://www.instagram.com/explore/tags/%EC%9E%90%EC%B7%A8%EC%9A%94%EB%A6%AC/", "source": "Instagram"},
]

FALLBACK = {
    "tips": [
        {"title": "김치볶음밥은 왜 찬밥으로 해야 맛있을까?", "summary": "밥알을 살리고 양념은 제대로 배게 만드는 기본 원리.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "라면 물 50ml가 맛을 바꾸는 이유", "summary": "국물과 면의 농도는 물 한 국자에 더 크게 흔들린다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "계란찜이 식당처럼 부풀어 오르는 법", "summary": "거품, 중탕, 뚜껑. 세 가지만 맞춰도 폭신해진다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "팬이 예열되기 전에 고기를 올리지 않는 이유", "summary": "겉은 잡고 속은 남기는 건 온도에서 갈린다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "밥물에 참기름 한 방울이 하는 일", "summary": "윤기만 아니라 밥알이 달라붙는 속도도 바뀐다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "냉동 만두를 바삭하게 굽는 물 한 숟갈", "summary": "뚜껑을 덮는 타이밍이 껍질의 물을 가른다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "계란프라이 가장자리가 레이스처럼 되는 불", "summary": "기름 온도와 내리는 속도만 맞춰도 식당 느낌이 난다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "된장찌개에 멸치를 먼저 넣는 이유", "summary": "국물 바탕이 잡히면 나물은 나중에 넣어도 늦지 않다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
    ],
    "trend": [
        {"title": "요즘 편의점에서 가장 많이 보이는 조합", "summary": "삼각김밥만으로는 끝나지 않는 야식 코너의 최근 공식들.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "한동안 안 보이던 맵부심이 다시 돌아왔다", "summary": "매운맛은 유행이 아니라 주기처럼 돌아온다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "SNS에서 유행하는 한 그릇 레시피", "summary": "설거지가 적은 한 그릇이 지금 잘 팔리는 형식이다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "컵라면이 다시 메인 메뉴가 되는 밤", "summary": "토핑 하나만 더해도 야식이 저녁처럼 보인다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "김밥이 도시락을 밀어내는 계절", "summary": "한 줄로 끝나는 점심이 다시 잘 팔린다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "마라가 한 철 지나고 남은 것", "summary": "맵기보다 향신료 국물이 메뉴판에 남는 방식.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "김밥보다 짧은 한입 메뉴가 뜨는 이유", "summary": "수업 사이에 끝나는 간편이 다시 잘 팔린다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "편의점 냉면이 여름만의 메뉴가 아닌 밤", "summary": "계절 메뉴가 야식 코너에 남는 속도를 본다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
    ],
    "health": [
        {"title": "닭가슴살 없이도 단백질 챙기는 한 끼", "summary": "두부, 계란, 콩. 이미 냉장고에 있는 것들로도 충분할 때가 많다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "늦은 밤 먹어도 부담이 덜한 음식", "summary": "참는 대신 속이 덜 무거운 쪽으로 바꾸는 선택.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "샐러드가 지겨울 때 먹는 건강식", "summary": "잎채소만 고집하지 않아도 가볍게 먹는 방법은 남아 있다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "국물이 있는 쪽이 더 가볍게 느껴질 때", "summary": "기름을 줄이고 국물로 부피를 채우는 한 끼.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "밥을 조금 줄일 때 먼저 손대는 반찬", "summary": "단백질을 남기고 탄수를 줄이는 쪽이 배가 덜 허하다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "나트륨을 줄이려면 국물부터 덜어 보기", "summary": "반찬을 바꾸기 전에 국 한 국자가 더 크다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "달걀 두 개가 한 끼를 버티는 방식", "summary": "조리만 바꿔도 간이식이 식사가 된다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "단맛을 줄일 때 과일을 먼저 두는 이유", "summary": "디저트를 금지하기보다 순서를 바꾼다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
    ],
    "habit": [
        {"title": "천천히 먹으면 정말 덜 먹게 될까?", "summary": "속도만 바꿔도 포만감이 다르게 온다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "아침을 꼭 먹어야 할까?", "summary": "정답보다 리듬. 수업·랩 시간에 맞춰 아침을 다시 배치해 본다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "야식을 끊기보다 시간을 바꿔보는 방법", "summary": "같은 간식이라도 언제 먹느냐가 다음 날을 가른다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "물 한 컵을 밥 전에 두는 습관", "summary": "허기인지 갈증인지 먼저 가른 다음 수저를 든다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "같은 메뉴를 사흘 연속 먹지 않는 이유", "summary": "질리면 배달 앱만 늘고, 집밥이 더 멀어진다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "수저를 놓기 전 물 한 모금의 효과", "summary": "한 끼의 끝을 입으로 확인하면 간식이 덜 당긴다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "점심을 거른 날의 저녁이 커지는 이유", "summary": "빈 속이 다음 끼를 과하게 부른다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "주말만 배달을 쓰는 규칙", "summary": "평일을 지키면 주말이 보상이 된다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
    ],
}


def now_kst() -> datetime:
    return datetime.now(KST)


def ctx() -> ssl.SSLContext:
    context = ssl.create_default_context()
    return context


def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx()) as res:
        return res.read()


def clean_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def medium_from_url(url: str, source: str) -> str:
    u = (url or "").lower()
    s = (source or "").lower()
    if "youtube.com" in u or "youtu.be" in u or "youtube" in s:
        return "youtube"
    if "instagram.com" in u:
        return "instagram"
    if source == "밥도둑 데스크":
        return "desk"
    if any(token in u for token in ("tistory.com", "blog.", "wordpress", "bapsang", "koreankitchen")):
        return "blog"
    if s and s not in {"google news"}:
        return "blog"
    return "blog"


def youtube_id(url: str) -> str:
    match = YT_ID.search(url or "")
    return match.group(1) if match else ""


def youtube_thumb(url: str) -> str:
    vid = youtube_id(url)
    return f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg" if vid else ""


def usable_image(url: str) -> str:
    src = html.unescape((url or "").strip())
    if src.startswith("//"):
        src = "https:" + src
    if not src.startswith("http"):
        return ""
    low = src.lower()
    if low.startswith("data:") or "1x1" in low or low.endswith(".svg"):
        return ""
    return src


def node_xml(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return ET.tostring(node, encoding="unicode")


def extract_image(node: ET.Element, page_url: str) -> str:
    yt = youtube_thumb(page_url)
    if yt:
        return yt
    candidates: list[str] = []
    for path in ("media:group/media:thumbnail", "media:thumbnail", "media:content"):
        el = node.find(path, NS)
        if el is not None:
            candidates.append(el.get("url") or el.get("href") or "")
    enclosure = node.find("enclosure")
    if enclosure is not None and (enclosure.get("type") or "").startswith("image"):
        candidates.append(enclosure.get("url") or "")
    for el in (
        node.find("description"),
        node.find("content:encoded", NS),
        node.find("atom:content", NS),
        node.find("atom:summary", NS),
    ):
        blob = node_xml(el)
        candidates.extend(match.group(1) for match in IMG_SRC.finditer(blob))
    for raw in candidates:
        src = usable_image(raw)
        if src:
            return src
    return ""


HASH_RE = re.compile(r"(?<![&=])#([A-Za-z가-힣][0-9A-Za-z가-힣_]{1,20})")
TAG_SKIP = {
    "유동",
    "유동골뱅이",
    "알고보면쉬운친구",
    "쿠팡",
    "쿠팡파트너스",
    "이벤트",
    "광고",
    "위글위글",
}
INGREDIENT_SKIP = {
    "물",
    "소금",
    "식용유",
    "후추",
    "설탕",
    "약간",
    "적당량",
    "맛술",
    "후춧가루",
    "그리고",
    "또는",
}
SEASONING = {"고춧가루", "고추장", "들기름", "굴소스", "마늘", "대파", "참기름"}
INGREDIENT_WORDS = sorted(
    [
        "골뱅이",
        "소면",
        "오리",
        "능이",
        "백숙",
        "통닭",
        "샤브용 고기",
        "다진 고기",
        "돼지고기",
        "소고기",
        "닭가슴살",
        "닭고기",
        "해물믹스",
        "멸치칼국수",
        "사리곰탕",
        "냉동만두",
        "떡국떡",
        "신김치",
        "묵은지",
        "소시지",
        "마스카포네",
        "아몬드가루",
        "알룰로스",
        "에스프레소",
        "초콜릿",
        "브라우니",
        "바나나",
        "밀가루",
        "고춧가루",
        "고추장",
        "들기름",
        "굴소스",
        "미나리",
        "칼국수",
        "김치",
        "만두",
        "오뎅",
        "당면",
        "라면",
        "두부",
        "달걀",
        "계란",
        "대파",
        "양파",
        "부추",
        "마늘",
        "잣",
        "쌀",
        "무",
        "닭",
    ],
    key=len,
    reverse=True,
)
EN_INGREDIENT = (
    ("pine nut", "잣"),
    ("pork", "돼지고기"),
    ("chicken", "닭"),
    ("radish", "무"),
    ("banana", "바나나"),
    ("chocolate", "초콜릿"),
    ("mascarpone", "마스카포네"),
    ("almond", "아몬드가루"),
    ("rice", "쌀"),
    ("egg", "달걀"),
    ("kimchi", "김치"),
)
DISH_ALIASES = (
    (r"골뱅이", "골뱅이소스면"),
    (r"오리백숙|능이오리", "능이오리백숙"),
    (r"jatjuk|pine nut porridge", "잣죽"),
    (r"kkakdugi|cubed radish", "깍두기"),
    (r"makgeolli", "막걸리"),
    (r"tiramisu", "티라미수"),
    (r"banana pudding brownie|바나나 푸딩 브라우니", "바나나 푸딩 브라우니"),
    (r"부대찌개", "부대찌개"),
    (r"닭볶음탕", "닭볶음탕"),
    (r"해물순두부", "해물순두부찌개"),
    (r"동그랑땡", "동그랑땡"),
    (r"돼지불고기", "돼지불고기"),
    (r"김치찜", "김치찜"),
    (r"떡만둣국", "떡만둣국"),
    (r"소시지야채볶음", "소시지야채볶음"),
    (r"등촌칼국수", "등촌칼국수"),
)
SOURCE_TAG = {
    "햄지 Hamzy": "먹방",
    "자취요리신": "자취요리",
    "쿠킹트리 Cooking tree": "디저트",
    "하루한끼": "집밥",
    "엄마표 집밥": "집밥",
    "Korean Bapsang": "한식",
    "My Korean Kitchen": "한식",
}


def clip_line(text: str, limit: int = 42) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def particle_i_ga(word: str) -> str:
    if not word:
        return "가"
    ch = word[-1]
    if "가" <= ch <= "힣":
        return "이" if (ord(ch) - 0xAC00) % 28 else "가"
    return "가"


def tagify(word: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", word)[:12]


def dish_name(title: str, body: str) -> str:
    blob = f"{title} {body[:240]}"
    for pattern, name in DISH_ALIASES:
        if re.search(pattern, blob, re.I):
            return name
    if "브이로그" in title:
        return "밥 브이로그"
    after = re.search(r"(?:땐|엔)\s*([가-힣]{3,16})", title)
    if after:
        name = after.group(1).rstrip("에은는을를")
        if name not in {"입맛", "오늘", "여름", "이번"}:
            return name
    made = re.search(r"([가-힣A-Za-z0-9 ]{2,16})을?를?\s*만들어", body)
    if made:
        return made.group(1).strip()
    head = title.split("|")[0]
    head = re.sub(r"[\"“”]", "", head)
    named = re.search(r"([가-힣0-9A-Za-z· ]{2,18}?)(?:\s*레시피|\s*만들기|\s*끓이는 법|\s*만드는 법)", head)
    if named:
        return re.sub(r"\s+", " ", named.group(1)).strip(" !?")
    hangul = re.search(r"[가-힣]{2,12}", head)
    if hangul:
        return hangul.group(0)
    return clip_line(head, 16)


DISH_INGS = {
    "부대찌개": ["스팸", "소시지", "김치"],
    "골뱅이소스면": ["골뱅이", "소면", "통닭"],
    "해물순두부찌개": ["해물믹스", "순두부"],
}


def collect_ingredients(title: str, body: str, dish: str = "") -> list[str]:
    found: list[str] = list(DISH_INGS.get(dish, []))
    block = re.search(r"\[재료\]\s*(.+?)(?:\[만드는|\n\d+\.|만드는 법|$)", body, re.S)
    if block:
        for part in re.split(r"[,，/·\n]", block.group(1)):
            name = re.sub(r"\d+\s*(컵|스푼|큰술|작은술|g|ml|장|개|줌).*", "", part, flags=re.I)
            name = clean_text(name).strip(" .")
            name = re.sub(r"^(약|또는)\s*", "", name)
            if name and name not in INGREDIENT_SKIP and 1 < len(name) <= 12:
                found.append(name)
    blob = f"{title} {body}"
    for word in INGREDIENT_WORDS:
        compact = word.replace(" ", "")
        if word not in blob and compact not in blob.replace(" ", ""):
            continue
        if re.search(re.escape(word) + r"\s*없이", blob) or re.search(re.escape(compact) + r"없이", blob):
            continue
        if compact in {"백숙", "찌개", "볶음탕", "국", "볶음", "찜", "면"}:
            continue
        if any(compact in item.replace(" ", "") or item.replace(" ", "") in compact for item in found):
            continue
        found.append(compact)
        if len(found) >= 8:
            break
    low = blob.lower()
    for en, ko in EN_INGREDIENT:
        if en in low and ko not in found:
            found.append(ko)
    seen: set[str] = set()
    mains: list[str] = []
    extras: list[str] = []
    for item in found:
        key = item.replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        if key in SEASONING:
            extras.append(item)
        else:
            mains.append(item)
    return (mains + extras)[:4]


def trait_line(title: str, body: str, dish: str, source: str = "") -> str:
    blob = title + body
    minutes = re.search(r"(\d+분)", title)
    if minutes:
        return f"{dish}. {minutes.group(1)}이면 된다."
    if source.startswith("쿠킹트리") or any(token in blob for token in ("브라우니", "케이크", "디저트", "티라미수")):
        if "꾸덕" in blob:
            return f"{dish}. 꾸덕한 한 조각."
        return f"{dish}. 집에서 굽는 디저트."
    if "초보" in blob:
        return f"{dish}. 처음 해도 손이 덜 간다."
    if "초간단" in title or "간단" in title[:18]:
        return f"{dish}. 손이 적은 한 끼."
    if "자취" in blob:
        return f"{dish}. 자취 저녁으로 좋다."
    if "저당" in blob:
        return f"{dish}. 단맛을 줄인 디저트."
    if "밀가루 없이" in blob or "밀가루없이" in blob:
        return f"{dish}. 밀가루 없이 만든다."
    if "브이로그" in title:
        return f"{dish}. 그날 먹은 밥을 그대로."
    return f"{dish}. 오늘 밥상에 올리기 좋다."


def vibe_line(title: str, body: str, source: str, ings: list[str]) -> str:
    blob = title + body
    if "도시락" in blob:
        return "반찬·도시락으로도 무난하다."
    if "명절" in blob:
        return "명절 음식이지만 평소에도 자주 올린다."
    if "자취" in blob or source == "자취요리신":
        return "설거지가 적고, 한 그릇으로 끝낸다."
    if source.startswith("쿠킹트리"):
        return "밥 말고, 집에서 굽는 간식."
    if "햄지" in source:
        return "지금 타임라인에서 자주 보이는 먹방."
    if "브이로그" in title:
        return "레시피보다 밥 분위기를 먼저 본다."
    if ings:
        return f"{ings[0]}{particle_i_ga(ings[0])} 주인공인 집밥."
    return "자세한 손맛은 본문에서 보면 된다."


def dish_tag(dish: str) -> str:
    compact = tagify(dish.replace(" ", ""))
    parts = [part for part in dish.split() if part]
    if len(compact) > 8 and parts:
        return tagify(parts[-1])
    return compact


def make_tags(dish: str, ings: list[str], title: str, body: str, source: str) -> list[str]:
    tags = [dish_tag(dish)]
    added = 0
    for ing in ings:
        token = tagify(ing.replace(" ", ""))
        if not token or token == tags[0]:
            continue
        tags.append(token)
        added += 1
        if added >= 2:
            break
    tags.append(SOURCE_TAG.get(source, "집밥"))
    if "자취" in f"{title}{body}":
        tags.append("자취요리")
    for raw in HASH_RE.findall(f"{title} {body}"):
        if raw.isdigit() or raw in TAG_SKIP:
            continue
        tags.append(raw)
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if len(tag) < 2 or tag.lower() in seen or tag in TAG_SKIP:
            continue
        seen.add(tag.lower())
        out.append(tag)
        if len(out) >= 4:
            break
    return out


def compose_card(title: str, body: str, source: str = "") -> dict:
    dish = dish_name(title, body)
    ings = collect_ingredients(title, body, dish)
    line1 = clip_line(trait_line(title, body, dish, source))
    line2 = "메인 · " + ", ".join(ings) if ings else "메인 · 밥상에 올리는 그 음식."
    line3 = clip_line(vibe_line(title, body, source, ings))
    return {
        "summary": f"{line1}\n{line2}\n{line3}",
        "tags": make_tags(dish, ings, title, body, source),
    }


def longest_body(node: ET.Element) -> str:
    chunks: list[str] = []
    for el in (
        node.find("description"),
        node.find("content:encoded", NS),
        node.find("atom:summary", NS),
        node.find("atom:content", NS),
        node.find("media:group/media:description", NS),
    ):
        if el is None:
            continue
        chunks.append(clean_text(node_xml(el)))
    body = max(chunks, key=len) if chunks else ""
    body = html.unescape(html.unescape(body))
    body = re.sub(r"[^.]*지원을 받아[^.]*", " ", body)
    if body.startswith("*본 영상"):
        body = re.sub(r"^\*본 영상[^.]*\.?", "", body)
    return body[:2000]


def pack_item(title: str, body: str, source: str, url: str, image: str) -> dict | None:
    if is_blocked({"title": title, "summary": body, "source": source}):
        return None
    card = compose_card(title, body, source)
    item = {
        "title": title,
        "summary": card["summary"],
        "tags": card["tags"],
        "source": source,
        "url": url,
        "medium": medium_from_url(url, source),
    }
    if image:
        item["image"] = image
    return item


def parse_rss_items(payload: bytes, default_source: str) -> list[dict]:
    items: list[dict] = []
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return items

    for node in root.findall("./channel/item"):
        title_el = node.find("title")
        link_el = node.find("link")
        desc_el = node.find("description")
        source_el = node.find("source")
        title = clean_text(title_el.text if title_el is not None else "")
        source = default_source
        if source_el is not None and (source_el.text or "").strip():
            source = clean_text(source_el.text)
        url = (link_el.text or "").strip() if link_el is not None else ""
        body = longest_body(node)
        if not title:
            continue
        packed = pack_item(title, body, source or default_source, url, extract_image(node, url))
        if packed:
            items.append(packed)

    for node in root.findall("atom:entry", NS):
        title_el = node.find("atom:title", NS)
        title = clean_text(title_el.text if title_el is not None else "")
        url = ""
        for link in node.findall("atom:link", NS):
            if link.get("rel") in (None, "alternate") and link.get("href"):
                url = link.get("href")
                break
        summary_el = node.find("atom:summary", NS)
        if summary_el is None:
            summary_el = node.find("media:group/media:description", NS)
        body = longest_body(node)
        if not title:
            continue
        packed = pack_item(title, body, default_source, url, extract_image(node, url))
        if packed:
            items.append(packed)
    return items


def fingerprint(title: str) -> str:
    compact = re.sub(r"[^0-9a-z가-힣]+", "", (title or "").lower())
    return compact[:24]


def normalize_title(title: str) -> str:
    text = re.sub(r"[\U0001F300-\U0001FAFF]", "", title or "")
    text = re.sub(r"[^0-9a-z가-힣\s]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[i : i + 3] for i in range(max(0, len(padded) - 2))}


def similar(a: str, b: str) -> float:
    ta, tb = trigrams(normalize_title(a)), trigrams(normalize_title(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def canonical_url(url: str) -> str:
    raw = (url or "").split("#")[0].split("?")[0].rstrip("/").lower()
    return raw


def classify_lane(item: dict, preferred: str | None = None) -> str | None:
    blob = f"{item.get('title') or ''} {item.get('summary') or ''} {item.get('source') or ''}".lower()
    scores = {"tips": 0, "trend": 0, "health": 0, "habit": 0}
    for word in TIPS_WORDS:
        if word.lower() in blob:
            scores["tips"] += 2
    for word in TREND_WORDS:
        if word.lower() in blob:
            scores["trend"] += 2
    for word in HEALTH_WORDS:
        if word.lower() in blob:
            scores["health"] += 2
    for word in HABIT_WORDS:
        if word.lower() in blob:
            scores["habit"] += 2
    if any(word.lower() in blob for word in DESSERT_WORDS):
        scores["health"] -= 4
        scores["tips"] += 1
    if item.get("medium") == "youtube" and "먹방" in blob:
        scores["trend"] += 3
    if preferred in scores:
        scores[preferred] += 3
    source = (item.get("source") or "").lower()
    if "hamzy" in source or "햄지" in source:
        scores["trend"] += 8
    if "먹방" in blob or "asmr" in blob:
        scores["trend"] += 4
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return preferred or "tips"
    return best


def fetch_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx()) as res:
        return json.loads(res.read().decode("utf-8"))


def youtube_discovery() -> list[dict]:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        return []
    after = (now_kst() - timedelta(days=10)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: list[dict] = []
    for query in YT_QUERIES:
        params = urllib.parse.urlencode(
            {
                "part": "snippet",
                "type": "video",
                "regionCode": "KR",
                "relevanceLanguage": "ko",
                "publishedAfter": after,
                "q": query,
                "maxResults": 8,
                "order": "date",
                "key": key,
            }
        )
        try:
            payload = fetch_json("https://www.googleapis.com/youtube/v3/search?" + params)
        except Exception as exc:
            print(f"[warn] youtube search {query}: {exc}")
            continue
        for row in payload.get("items") or []:
            vid = ((row.get("id") or {}).get("videoId")) or ""
            snip = row.get("snippet") or {}
            if not vid:
                continue
            found.append(
                {
                    "title": snip.get("title") or "",
                    "summary": snip.get("description") or "",
                    "source": snip.get("channelTitle") or "YouTube",
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "image": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "medium": "youtube",
                    "publishedAt": snip.get("publishedAt") or "",
                    "channelId": snip.get("channelId") or "",
                    "videoId": vid,
                    "query": query,
                }
            )
    ids = [item["videoId"] for item in found if item.get("videoId")]
    stats: dict[str, dict] = {}
    for i in range(0, len(ids), 40):
        chunk = ids[i : i + 40]
        params = urllib.parse.urlencode({"part": "statistics,snippet", "id": ",".join(chunk), "key": key})
        try:
            payload = fetch_json("https://www.googleapis.com/youtube/v3/videos?" + params)
        except Exception as exc:
            print(f"[warn] youtube videos: {exc}")
            continue
        for row in payload.get("items") or []:
            stats[row.get("id") or ""] = row
    out = []
    now = datetime.now(timezone.utc)
    for item in found:
        meta = stats.get(item["videoId"]) or {}
        st = (meta.get("statistics") or {})
        views = int(st.get("viewCount") or 0)
        published = item.get("publishedAt") or ""
        hours = 12.0
        try:
            pub = datetime.fromisoformat(published.replace("Z", "+00:00"))
            hours = max(1.0, (now - pub).total_seconds() / 3600)
        except ValueError:
            pass
        item["views"] = views
        item["trendScore"] = views / hours
        packed = pack_item(item["title"], item.get("summary") or "", item["source"], item["url"], item.get("image") or "")
        if packed:
            packed.update({k: item[k] for k in ("videoId", "channelId", "trendScore", "views") if k in item})
            packed["laneHint"] = "trend"
            out.append(packed)
    out.sort(key=lambda row: -float(row.get("trendScore") or 0))
    return out


def is_near_dup(title: str, seen_titles: list[str]) -> bool:
    for other in seen_titles:
        if similar(title, other) > 0.72:
            return True
    return False


def unique(items: list[dict], limit: int, seed: int = 0, banned: set[str] | None = None) -> list[dict]:
    return take_diverse(items, limit, seed, DedupState(banned or set()))


class DedupState:
    def __init__(self, banned: set[str]):
        self.urls: set[str] = set()
        self.videos: set[str] = set()
        self.prints: set[str] = set(banned)
        self.titles: list[str] = []
        self.channels: set[str] = set()
        self.domains: dict[str, int] = {}
        self.foods: dict[str, int] = {}


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def take_diverse(items: list[dict], limit: int, seed: int, state: DedupState, lane: str = "") -> list[dict]:
    cleaned = rotate(clean_pool(items), seed)
    out: list[dict] = []
    lane_channels: set[str] = set()
    lane_foods: set[str] = set()
    for item in cleaned:
        title = item.get("title") or ""
        url = canonical_url(item.get("url") or "")
        vid = item.get("videoId") or youtube_id(item.get("url") or "")
        fp = fingerprint(title)
        source = item.get("source") or ""
        domain = host_of(item.get("url") or "")
        dish = (item.get("tags") or [""])[-1]
        if fp in state.prints or (url and url in state.urls) or (vid and vid in state.videos):
            continue
        if is_near_dup(title, state.titles):
            continue
        if source and source in lane_channels and item.get("medium") != "desk":
            continue
        if source and source in state.channels and item.get("medium") == "youtube":
            continue
        if domain and state.domains.get(domain, 0) >= 2:
            continue
        if dish and dish in lane_foods and item.get("medium") != "desk":
            continue
        out.append(item)
        state.prints.add(fp)
        if url:
            state.urls.add(url)
        if vid:
            state.videos.add(vid)
        state.titles.append(title)
        if source:
            state.channels.add(source)
            lane_channels.add(source)
        if domain:
            state.domains[domain] = state.domains.get(domain, 0) + 1
        if dish:
            lane_foods.add(dish)
        if len(out) >= limit:
            break
    return out


def fill_lane(fetched: list[dict], lane: str, seed: int, banned: set[str]) -> list[dict]:
    return take_diverse(fetched, LANE_SIZE, seed, DedupState(banned), lane)


def is_blocked(item: dict) -> bool:
    source = (item.get("source") or "").strip().lower()
    blob = f"{item.get('title') or ''} {item.get('summary') or ''}"
    if source in BLOCK_SOURCES:
        return True
    return any(token in blob for token in BLOCK_TITLE)


def tidy_item(item: dict) -> dict:
    title = item["title"]
    source = item.get("source") or ""
    if not item.get("tags"):
        card = compose_card(title, item.get("summary") or "", source)
        item["summary"] = card["summary"]
        item["tags"] = card["tags"]
    item["medium"] = medium_from_url(item.get("url") or "", source)
    image = item.get("image") or youtube_thumb(item.get("url") or "")
    if image:
        item["image"] = image
    else:
        item.pop("image", None)
    return item


def korean_weight(title: str) -> int:
    return sum(1 for ch in title if "가" <= ch <= "힣")


def clean_pool(items: list[dict]) -> list[dict]:
    ranked = sorted(items, key=lambda item: -korean_weight(item.get("title") or ""))
    seen: set[str] = set()
    out: list[dict] = []
    for item in ranked:
        item = tidy_item(dict(item))
        if is_blocked(item):
            continue
        key = fingerprint(item["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def day_seed(date_s: str) -> int:
    return int(hashlib.md5(date_s.encode("utf-8")).hexdigest(), 16)


def rotate(items: list, seed: int) -> list:
    if not items:
        return items
    k = seed % len(items)
    return items[k:] + items[:k]


def previous_keys(before_date: str) -> set[str]:
    keys: set[str] = set()
    dated = [
        path
        for path in sorted(OUT.glob("20*.json"))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem) and path.stem < before_date
    ]
    for path in dated[-7:]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        featured = data.get("featured") or {}
        if featured.get("title"):
            keys.add(fingerprint(featured["title"]))
    return keys


def unique(items: list[dict], limit: int, seed: int = 0, banned: set[str] | None = None) -> list[dict]:
    return take_diverse(items, limit, seed, DedupState(banned or set()))


def fill_lane(fetched: list[dict], lane: str, seed: int, banned: set[str]) -> list[dict]:
    state = DedupState(banned)
    picked = take_diverse(fetched, LANE_SIZE, seed, state, lane)
    if len(picked) < 6:
        extras = [tidy_item(dict(row)) for row in rotate(FALLBACK[lane], seed)]
        picked = picked + take_diverse(extras, LANE_SIZE - len(picked), seed, state, lane)
    return picked[:LANE_SIZE]


def featured_score(item: dict, lane: str) -> int:
    title = item.get("title") or ""
    source = item.get("source") or ""
    score = {"youtube": 4, "blog": 3, "instagram": 2, "desk": 0}.get(item.get("medium"), 1)
    if any(token in title for token in ("레시피", "만들기", "끓이는", "볶음", "한끼", "자취")):
        score += 3
    if any(token in title for token in ("출장", "노포", "장터", "꼭 갑니다")):
        score -= 6
    if source in {"자취요리신", "하루한끼", "엄마표 집밥"}:
        score += 2
    if lane == "tips":
        score += 1
    if item.get("image") or youtube_id(item.get("url") or ""):
        score += 4
    return score


def collect_sources() -> dict[str, list[dict]]:
    buckets = {lane: [] for lane in LANE_LEADS}
    blog_pool: list[dict] = []
    youtube_pool: list[dict] = []
    flat: list[dict] = []

    for blog in BLOGS:
        try:
            items = parse_rss_items(fetch(blog["url"]), blog["name"])
        except Exception as exc:
            print(f"[warn] blog {blog['name']}: {exc}")
            continue
        blog_pool.extend(items)
        for item in items:
            item["laneHint"] = blog["lanes"][0]
            lane = classify_lane(item, item["laneHint"])
            item["lane"] = lane
            buckets[lane].append(item)
            flat.append(item)

    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}"
        try:
            items = parse_rss_items(fetch(url), ch["name"])
        except Exception as exc:
            print(f"[warn] youtube {ch['name']}: {exc}")
            continue
        youtube_pool.extend(items)
        for item in items:
            item["laneHint"] = ch["lanes"][0]
            item["channelId"] = ch["id"]
            item["videoId"] = youtube_id(item.get("url") or "")
            lane = classify_lane(item, item["laneHint"])
            item["lane"] = lane
            buckets[lane].append(item)
            flat.append(item)

    for item in youtube_discovery():
        lane = classify_lane(item, "trend")
        item["lane"] = lane
        buckets[lane].append(item)
        youtube_pool.append(item)
        flat.append(item)

    return {"buckets": buckets, "blog": blog_pool, "youtube": youtube_pool, "flat": flat}


def pick_featured(lanes: dict, seed: int, banned: set[str]) -> dict:
    ranked = []
    for lane, spec in lanes.items():
        for item in spec["items"]:
            if not item.get("url"):
                continue
            ranked.append((featured_score(item, lane), lane, item))
    ranked.sort(key=lambda row: -row[0])
    fresh = [row for row in ranked if fingerprint(row[2]["title"]) not in banned]
    pool = fresh or ranked
    if pool:
        _score, lane, item = pool[seed % min(5, len(pool))]
        featured = dict(item)
        featured["category"] = lane
        return featured
    featured = dict(FALLBACK["tips"][seed % len(FALLBACK["tips"])])
    featured["category"] = "tips"
    return featured


def drop_item(items: list[dict], featured: dict) -> list[dict]:
    url = canonical_url(featured.get("url") or "")
    fp = fingerprint(featured.get("title") or "")
    vid = featured.get("videoId") or youtube_id(featured.get("url") or "")
    out = []
    for item in items:
        if fingerprint(item.get("title") or "") == fp:
            continue
        if url and canonical_url(item.get("url") or "") == url:
            continue
        if vid and (item.get("videoId") or youtube_id(item.get("url") or "")) == vid:
            continue
        out.append(item)
    return out


def pad_lane(items: list[dict], lane: str, seed: int, state: DedupState) -> list[dict]:
    if len(items) >= 6:
        return items[:LANE_SIZE]
    extras = [tidy_item(dict(row)) for row in rotate(FALLBACK[lane], seed)]
    return items + take_diverse(extras, LANE_SIZE - len(items), seed, state, lane)


def build_edition(day: datetime, collected: dict | None = None) -> dict:
    date_s = day.strftime("%Y-%m-%d")
    seed = day_seed(date_s)
    banned = previous_keys(date_s)
    if collected is None:
        collected = collect_sources()
    state = DedupState(banned)
    lanes = {}
    offsets = {"trend": 17, "tips": 1, "health": 31, "habit": 47}
    for lane in ("trend", "tips", "health", "habit"):
        lead = LANE_LEADS[lane]
        picked = take_diverse(collected["buckets"].get(lane) or [], LANE_SIZE, seed + offsets[lane], state, lane)
        if len(picked) < 6:
            leftovers = [
                item
                for item in collected.get("flat") or []
                if canonical_url(item.get("url") or "") not in state.urls
                and classify_lane(item, lane) == lane
            ]
            picked = picked + take_diverse(leftovers, LANE_SIZE - len(picked), seed + offsets[lane] + 9, state, lane)
        lanes[lane] = {"lead": lead, "items": picked}

    featured = pick_featured(lanes, seed, banned)
    for lane, spec in lanes.items():
        spec["items"] = drop_item(spec["items"], featured)
        spec["items"] = pad_lane(spec["items"], lane, seed + offsets[lane], state)

    instagram = []
    ideas = [INSTAGRAM_IDEAS[0]] + INSTAGRAM_IDEAS[1:]
    rotated = ideas[1:]
    rot = seed % len(rotated)
    rotated = rotated[rot:] + rotated[:rot]
    for idea in [ideas[0]] + rotated[:3]:
        tag_match = HASH_RE.search(idea["title"])
        instagram.append(
            {
                "title": idea["title"],
                "summary": "계정 글을 긁지 않는다.\n태그로 직접 들어가 보는 창구.\n오늘의 밥 감 참고용.",
                "tags": [tag_match.group(1)] if tag_match else ["집밥", "인스타"],
                "source": idea["source"],
                "url": idea["url"],
                "medium": "instagram",
            }
        )

    return {
        "date": date_s,
        "generatedAt": day.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
        "schedule": "Daily 10:00 KST",
        "featured": featured,
        "lanes": lanes,
        "desks": {
            "blog": unique(collected["blog"], 5, seed, banned),
            "youtube": unique(collected["youtube"], 5, seed * 3 + 1, banned),
            "instagram": instagram,
        },
    }


def write_index(latest: str) -> None:
    dates = sorted(
        {p.stem for p in OUT.glob("20*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)},
        reverse=True,
    )
    payload = {"latest": latest, "dates": dates}
    (OUT / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "latest.json").write_text(
        (OUT / f"{latest}.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def write_edition(day: datetime, collected: dict) -> dict:
    edition = build_edition(day, collected)
    path = OUT / f"{edition['date']}.json"
    path.write_text(json.dumps(edition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return edition


def latest_date(now: datetime) -> str:
    if now.hour < 10:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = now_kst()
    collected = collect_sources()
    backfill = "--backfill" in sys.argv
    if backfill:
        existing = sorted(p.stem for p in OUT.glob("20*.json") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))
        dates = [datetime.strptime(stamp, "%Y-%m-%d").replace(tzinfo=KST) for stamp in existing]
        if not dates:
            dates = [day]
        for when in dates:
            write_edition(when, collected)
    else:
        target = day if day.hour >= 10 else day - timedelta(days=1)
        write_edition(target, collected)
    write_index(latest_date(day))
    print(f"latest {latest_date(day)}")


if __name__ == "__main__":
    main()
