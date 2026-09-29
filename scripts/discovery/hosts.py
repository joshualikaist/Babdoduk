# -*- coding: utf-8 -*-
"""What a search result's host tells us: its trust tier, medium and display name.

Search routes (Exa, site:blog.naver.com, YouTube search) return pages from anywhere, so the
tier of a result comes from its host, never from the route. Registered RSS sources keep the
tier the registry gives them.

  A  government, public-health and research publishers (research medium)
  B  established news and food-industry publications (news medium)
  C  blogs, community posts, video search results and unknown hosts (discovery only; never
     published as factual health advice on its own)

Shopping and listing pages are not stories and are rejected (COMMERCE_PAGE).
"""
from __future__ import annotations

import re
import urllib.parse

RESEARCH_HOSTS = ("pmc.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "kci.go.kr",
                  "scienceon.kisti.re.kr", "dbpia.co.kr", "koreascience.kr", "e-jnh.org", "kjcn.org",
                  "nature.com", "sciencedirect.com", "mdpi.com", "bmj.com", "thelancet.com")
NEWS_HOSTS = {
    "yna.co.kr": "연합뉴스", "hankyung.com": "한국경제", "mk.co.kr": "매일경제", "chosun.com": "조선일보",
    "biz.chosun.com": "조선비즈", "health.chosun.com": "헬스조선", "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "sedaily.com": "서울경제", "edaily.co.kr": "이데일리",
    "news1.kr": "뉴스1", "newsis.com": "뉴시스", "mt.co.kr": "머니투데이", "fnnews.com": "파이낸셜뉴스",
    "heraldcorp.com": "헤럴드경제", "asiae.co.kr": "아시아경제", "kmib.co.kr": "국민일보", "seoul.co.kr": "서울신문",
    "munhwa.com": "문화일보", "nocutnews.co.kr": "노컷뉴스", "ytn.co.kr": "YTN", "sbs.co.kr": "SBS",
    "kbs.co.kr": "KBS", "imbc.com": "MBC", "jtbc.co.kr": "JTBC", "etnews.com": "전자신문", "ajunews.com": "아주경제",
    "newspim.com": "뉴스핌", "dailian.co.kr": "데일리안", "etoday.co.kr": "이투데이", "segye.com": "세계일보",
    "hankookilbo.com": "한국일보", "inews24.com": "아이뉴스24", "bizwatch.co.kr": "비즈워치", "thebell.co.kr": "더벨",
    "kormedi.com": "코메디닷컴", "hidoc.co.kr": "하이닥", "thinkfood.co.kr": "식품음료신문",
    "foodnews.co.kr": "식품저널", "foodbank.co.kr": "식품외식경제", "fsnews.co.kr": "대한급식신문",
    "foodtoday.or.kr": "푸드투데이", "dailyfood.co.kr": "데일리푸드", "v.daum.net": "다음뉴스",
    "n.news.naver.com": "네이버뉴스", "news.naver.com": "네이버뉴스", "univ20.com": "대학내일",
    "bbc.com": "BBC", "bbc.co.uk": "BBC", "reuters.com": "Reuters", "apnews.com": "AP", "nytimes.com": "New York Times",
    "theguardian.com": "The Guardian", "cnn.com": "CNN", "koreaherald.com": "The Korea Herald",
    "koreatimes.co.kr": "The Korea Times", "koreajoongangdaily.joins.com": "Korea JoongAng Daily",
    "hankooki.com": "한국일보", "sisajournal-e.com": "시사저널e", "sisajournal.com": "시사저널",
    "ddaily.co.kr": "디지털데일리", "wowtv.co.kr": "한국경제TV", "shinailbo.co.kr": "신아일보",
    "mbn.co.kr": "MBN", "tvchosun.com": "TV조선", "chosunbiz.com": "조선비즈", "zdnet.co.kr": "지디넷코리아",
    "econovill.com": "이코노믹리뷰", "ekn.kr": "에너지경제", "consumernews.co.kr": "소비자가만드는신문",
    "fetv.co.kr": "FETV", "newsprime.co.kr": "프라임경제", "womaneconomy.co.kr": "여성경제신문",
}
# Korean news sites on the common CMS (articleView.html) that are not listed above are news, but
# unknown publishers: Tier C, so they never lead the page or stand as habit/health evidence.
NEWS_PATH = re.compile(r"/news/articleView\.html|/article/\d|/view/AKR|/news/\d{6,}", re.I)
BLOG_HOSTS = {"blog.naver.com": "네이버 블로그", "m.blog.naver.com": "네이버 블로그", "post.naver.com": "네이버 포스트",
              "brunch.co.kr": "브런치", "tistory.com": "티스토리", "velog.io": "velog", "medium.com": "Medium"}
COMMERCE_HOSTS = ("coupang.com", "11st.co.kr", "gmarket.co.kr", "auction.co.kr", "ssg.com", "kurly.com",
                  "smartstore.naver.com", "shopping.naver.com", "brand.naver.com", "amazon.com", "musinsa.com",
                  "oliveyoung.co.kr", "lotteon.com", "wemakeprice.com", "tmon.co.kr", "baemin.com")
VIDEO_HOSTS = ("youtube.com", "youtu.be", "m.youtube.com")
TITLE_SUFFIX = re.compile(r"\s+(?:\||:|-|–|—)\s+([^|:\-–—]{2,24})\s*$")    # spaced: never "Stir-Fry"


def host_of(url: str) -> str:
    try:
        host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _match(host: str, names) -> str:
    for name in names:
        if host == name or host.endswith("." + name):
            return name
    return ""


def classify_host(url: str) -> dict:
    """{"tier", "medium", "name", "commerce", "known"} for a search result URL."""
    host = host_of(url)
    if _match(host, COMMERCE_HOSTS):
        return {"tier": "C", "medium": "blog", "name": host, "commerce": True, "known": True}
    if _match(host, VIDEO_HOSTS):
        return {"tier": "C", "medium": "youtube", "name": "YouTube", "commerce": False, "known": True}
    research = _match(host, RESEARCH_HOSTS)
    if research or host.endswith((".go.kr", ".re.kr")) or host in ("kosis.kr", "who.int") or host.endswith(".gov"):
        return {"tier": "A", "medium": "research", "name": host, "commerce": False, "known": True}
    news = _match(host, NEWS_HOSTS)
    if news:
        return {"tier": "B", "medium": "news", "name": NEWS_HOSTS[news], "commerce": False, "known": True}
    blog = _match(host, BLOG_HOSTS)
    if blog:
        return {"tier": "C", "medium": "blog", "name": BLOG_HOSTS[blog], "commerce": False, "known": True}
    medium = "news" if NEWS_PATH.search(urllib.parse.urlparse(url or "").path or "") else "blog"
    return {"tier": "C", "medium": medium, "name": host, "commerce": False, "known": False}


def split_title(title: str) -> tuple[str, str]:
    """"Headline | 한국경제" -> ("Headline", "한국경제"); the suffix is the site's own name. A news
    CMS breadcrumb ("Headline < 유통 < 기사본문 - 신아일보") is dropped with it."""
    text = (title or "").strip().replace("｜", " | ")
    wrapped = re.search(r"\s*::\s*([^:]{2,24}?)\s*::\s*$", text)       # "Headline :: 공감언론 뉴시스 ::"
    if wrapped:
        return text[:wrapped.start()].strip(), wrapped.group(1).strip()
    if " < " in text:
        head, _, tail = text.partition(" < ")
        site = re.split(r"\s+[-|]\s+", tail)[-1].strip() if re.search(r"\s[-|]\s", tail) else ""
        return head.strip(), site if 2 <= len(site) <= 24 else ""
    match = TITLE_SUFFIX.search(text)
    if match and len(text) - len(match.group(0)) >= 8:
        return text[:match.start()].strip(), match.group(1).strip()
    return text, ""
