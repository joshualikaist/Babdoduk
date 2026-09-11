# -*- coding: utf-8 -*-
"""Fetch public RSS into data/magazine/{date}.json for the 10:00 KST edition.

Blogs and YouTube official feeds only. No news-search firehose.
Instagram is not scraped; the edition keeps idea-desk links instead.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import ssl
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
    {"id": "UCC9pQY_uaBSa0WOpMNJHbEQ", "name": "자취요리신", "lanes": ["tips", "habit"]},
    {"id": "UCtby6rJtBGgUm-2oD_E7bzw", "name": "쿠킹트리 Cooking tree", "lanes": ["health", "tips"]},
    {"id": "UCPWFxcwPliEBMwJjmeFIDIg", "name": "하루한끼", "lanes": ["health", "habit"]},
    {"id": "UCPKNKldggioffXPkSmjs5lQ", "name": "햄지 Hamzy", "lanes": ["trend"]},
]

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
    ],
    "trend": [
        {"title": "요즘 편의점에서 가장 많이 보이는 조합", "summary": "삼각김밥만으로는 끝나지 않는 야식 코너의 최근 공식들.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "한동안 안 보이던 맵부심이 다시 돌아왔다", "summary": "매운맛은 유행이 아니라 주기처럼 돌아온다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "SNS에서 유행하는 한 그릇 레시피", "summary": "설거지가 적은 한 그릇이 지금 잘 팔리는 형식이다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
    ],
    "health": [
        {"title": "닭가슴살 없이도 단백질 챙기는 한 끼", "summary": "두부, 계란, 콩. 이미 냉장고에 있는 것들로도 충분할 때가 많다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "늦은 밤 먹어도 부담이 덜한 음식", "summary": "참는 대신 속이 덜 무거운 쪽으로 바꾸는 선택.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "샐러드가 지겨울 때 먹는 건강식", "summary": "잎채소만 고집하지 않아도 가볍게 먹는 방법은 남아 있다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
    ],
    "habit": [
        {"title": "천천히 먹으면 정말 덜 먹게 될까?", "summary": "속도만 바꿔도 포만감이 다르게 온다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "아침을 꼭 먹어야 할까?", "summary": "정답보다 리듬. 수업·랩 시간에 맞춰 아침을 다시 배치해 본다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
        {"title": "야식을 끊기보다 시간을 바꿔보는 방법", "summary": "같은 간식이라도 언제 먹느냐가 다음 날을 가른다.", "source": "밥도둑 데스크", "url": "", "medium": "desk"},
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
    compact = re.sub(r"[^0-9a-z가-힣]+", "", title.lower())
    return compact[:18]


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


def unique(items: list[dict], limit: int) -> list[dict]:
    cleaned = clean_pool(items)
    by_source: dict[str, list[dict]] = {}
    order: list[str] = []
    for item in cleaned:
        source = item.get("source") or "desk"
        if source not in by_source:
            by_source[source] = []
            order.append(source)
        by_source[source].append(item)
    out: list[dict] = []
    while order and len(out) < limit:
        next_order: list[str] = []
        for source in order:
            bucket = by_source.get(source) or []
            if bucket:
                out.append(bucket.pop(0))
                if bucket and len(out) < limit:
                    next_order.append(source)
            if len(out) >= limit:
                break
        order = next_order
    return out[:limit]


def fill_lane(fetched: list[dict], lane: str) -> list[dict]:
    blogs = unique([item for item in fetched if medium_from_url(item.get("url") or "", item.get("source") or "") == "blog"], 3)
    videos = unique([item for item in fetched if medium_from_url(item.get("url") or "", item.get("source") or "") == "youtube"], 3)
    mixed: list[dict] = []
    seen: set[str] = set()
    while blogs or videos:
        for pool in (blogs, videos):
            if not pool:
                continue
            item = pool.pop(0)
            key = fingerprint(item["title"])
            if key in seen:
                continue
            seen.add(key)
            mixed.append(item)
    if len(mixed) < 3:
        for fb in FALLBACK[lane]:
            mixed.append(tidy_item(dict(fb)))
            if len(mixed) >= 3:
                break
    return mixed[:5]


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

    for blog in BLOGS:
        try:
            items = parse_rss_items(fetch(blog["url"]), blog["name"])
        except Exception as exc:
            print(f"[warn] blog {blog['name']}: {exc}")
            continue
        blog_pool.extend(items)
        for lane in blog["lanes"]:
            buckets[lane].extend(items)

    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}"
        try:
            items = parse_rss_items(fetch(url), ch["name"])
        except Exception as exc:
            print(f"[warn] youtube {ch['name']}: {exc}")
            continue
        youtube_pool.extend(items)
        for lane in ch["lanes"]:
            buckets[lane].extend(items)

    return {
        "buckets": buckets,
        "blog": unique(blog_pool, 5),
        "youtube": unique(youtube_pool, 5),
    }


def build_edition(day: datetime) -> dict:
    date_s = day.strftime("%Y-%m-%d")
    collected = collect_sources()
    lanes = {}
    for lane, lead in LANE_LEADS.items():
        lanes[lane] = {
            "lead": lead,
            "items": fill_lane(collected["buckets"][lane], lane),
        }

    featured = None
    ranked = []
    for lane, spec in lanes.items():
        for item in spec["items"]:
            if not item.get("url"):
                continue
            ranked.append((featured_score(item, lane), lane, item))
    ranked.sort(key=lambda row: -row[0])
    if ranked:
        _score, lane, item = ranked[0]
        featured = dict(item)
        featured["category"] = lane
    if featured is None:
        featured = dict(FALLBACK["tips"][0])
        featured["category"] = "tips"

    instagram = []
    seed = int(hashlib.md5(date_s.encode("utf-8")).hexdigest(), 16)
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
            "blog": collected["blog"],
            "youtube": collected["youtube"],
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = now_kst()
    edition = build_edition(day)
    path = OUT / f"{edition['date']}.json"
    path.write_text(json.dumps(edition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(edition["date"])
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
