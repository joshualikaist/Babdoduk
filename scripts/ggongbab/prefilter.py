# -*- coding: utf-8 -*-
"""Cheap local filter that decides which mails are worth an AI call.

A mailbox backfill can hold hundreds of messages. Sending all of them to the
model would be slow, expensive and a needless privacy exposure, so a purely
local rule pass picks the candidates first.

This filter decides ONLY "is this worth looking at". It never decides whether
food is provided - that stays with the AI plus the deterministic validator, which
require explicit provision wording (see parsers/rule_parser.explicit_food_evidence).
It is tuned for recall: a flash hand-out ("방문자 전원 커피 제공", "커피차") is worth a
look even when the subject or preview carries no date (MISS-001).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# Recorded with every "filtered" mail decision, so a rule upgrade re-examines recent
# mail that an older version dismissed (web/state.py).
PREFILTER_VERSION = "2026-09-28.flash-1"

# Event-shaped wording.
EVENT_WORDS = re.compile(
    r"설명회|세미나|특강|강연|워크숍|워크샵|간담회|채용|리크루팅|박람회|콜로퀴움|심포지엄|포럼|네트워킹|밋업|"
    r"오리엔테이션|사업\s*설명|모집|초청|개최|행사|토크|데모데이|해커톤|부스|홍보|축제|페스티벌|이벤트|팝업|"
    r"경진\s*대회|캠퍼스\s*투어|방문|체험|다과회|파티|환영회|송년회|종강|개강|커피\s*챗|티\s*타임|"
    r"info\s*session|information\s*session|lunch\s*talk|tech\s*talk|seminar|colloquium|symposium|forum|"
    r"workshop|recruit(?:ing|ment)?|career\s*fair|networking|meetup|orientation|lecture|conference|"
    r"briefing|demo\s*day|hackathon|talk\s*series|session|booth|festival|pop[\s-]?up|coffee\s*chat|tea\s*time",
    re.I,
)

# Food nouns alone (no provision verbs), shared by the provision checks below.
_FOOD_NOUNS = (
    r"점심|중식|석식|조식|저녁|식사|도시락|간식차|간식|다과|음료수|음료|커피차|커피|피자|샌드위치|햄버거|버거|치킨|김밥|"
    r"뷔페|케이터링|식권|기프티콘|쿠폰|먹거리|음식|푸드\s*트럭|아이스크림|도넛|쿠키|과자|빵|떡|디저트|스낵|"
    r"meal|lunch|dinner|breakfast|food\s*trucks?|food|snacks?|refreshments?|coffee\s*trucks?|coffee|pizza|"
    r"sandwich(?:es)?|catering|beverages?|drinks?|bento|lunch\s*box|ice\s*cream|donuts?|cookies?|dessert"
)
# Food-shaped wording. Presence here does NOT mean food is provided.
FOOD_WORDS = re.compile(_FOOD_NOUNS + r"|제공|provided|complimentary", re.I)

# Wording that hands something out. Recall-first: "드림" and "선착순" are included here,
# while the stricter rule parser decides what counts as evidence.
_PROVISION = (
    r"제공|무료|공짜|증정|배부|배포|나눔|나눠\s*드|드림|드립니다|드려요|쏩니다|쏜다|선물|지급|"
    r"(?:방문자|참석자|참가자|참여자)\s*전원|소진\s*시|선착순|"
    r"free|complimentary|provided|on\s+us|giveaway|while\s+supplies\s+last"
)
# A food noun and a hand-out word close together, or a vehicle that exists to hand food out.
STRONG_PROVISION = re.compile(
    rf"(?:{_FOOD_NOUNS})[^\n.!?。]{{0,25}}?(?:{_PROVISION})|(?:{_PROVISION})[^\n.!?。]{{0,15}}?(?:{_FOOD_NOUNS})"
    r"|커피차|커피\s*트럭|푸드\s*트럭|간식차|coffee\s*truck|food\s*truck",
    re.I,
)
# Flash wording: the supply runs out or the event is happening now. Raises urgency only.
FLASH_WORDS = re.compile(
    r"소진\s*시|소진될\s*때|선착순\s*(?:제공|배부|배포|증정|지급|나눔)|(?:방문자|참석자)\s*전원|커피차|커피\s*트럭|"
    r"푸드\s*트럭|간식차|현장\s*(?:배부|증정|제공)|금일|오늘|지금\s*바로|while\s+supplies\s+last|today",
    re.I,
)

# Meal-time signals: enough to make a mail a candidate, never evidence of food.
MEAL_TIME = re.compile(r"점심\s*시간|런치|정오|(?<!\d)1[12]\s*시|(?<!\d)1[12]:\d{2}|lunch\s*(?:time|hour|break)|noon", re.I)

# Any date-ish token; an event mail says when.
DATE_HINT = re.compile(
    r"\d{1,2}\s*월\s*\d{1,2}\s*일|20\d{2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}|(?<!\d)\d{1,2}\s*/\s*\d{1,2}(?!\d)|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b|[월화수목금토일]요일",
    re.I,
)

# Obvious non-event mail. Checked first so personal and machine mail never costs a call.
DENY = re.compile(
    r"영수증|결제\s*(?:완료|내역)|카드\s*승인|주문\s*(?:확인|완료)|배송\s*(?:출발|완료|조회)|"
    r"비밀번호\s*(?:변경|재설정)|인증\s*(?:번호|코드)|로그인\s*알림|보안\s*알림|스팸|광고\s*메일|수신\s*거부|"
    r"뉴스레터\s*구독|급여\s*명세|연말\s*정산|국세청|청구서|대출|보험\s*안내|"
    r"receipt|invoice|payment\s*(?:received|confirmation)|order\s*(?:confirmation|shipped)|"
    r"password\s*reset|verification\s*code|security\s*alert|unsubscribe|out\s*of\s*office|"
    r"delivery\s*status\s*notification|undelivered\s*mail|mail\s*delivery\s*(?:failed|subsystem)",
    re.I,
)
# In the body only transactional/machine wording denies. Marketing footers ("수신거부",
# "unsubscribe", "광고 메일") also close legitimate campus promotions that hand out food.
DENY_BODY = re.compile(
    r"영수증|결제\s*(?:완료|내역)|카드\s*승인|주문\s*(?:확인|완료)|배송\s*(?:출발|완료|조회)|"
    r"비밀번호\s*(?:변경|재설정)|인증\s*(?:번호|코드)|로그인\s*알림|보안\s*알림|"
    r"급여\s*명세|연말\s*정산|국세청|청구서|대출|보험\s*안내|"
    r"receipt|invoice|payment\s*(?:received|confirmation)|order\s*(?:confirmation|shipped)|"
    r"password\s*reset|verification\s*code|security\s*alert|out\s*of\s*office|"
    r"delivery\s*status\s*notification|undelivered\s*mail|mail\s*delivery\s*(?:failed|subsystem)",
    re.I,
)


@dataclass
class Decision:
    candidate: bool
    reason: str
    has_event_word: bool = False
    has_food_word: bool = False
    has_meal_time: bool = False
    has_date: bool = False
    has_provision: bool = False       # a food noun next to a hand-out word, or a coffee/food truck
    urgency: str = "normal"           # "high" for flash hand-outs or same-day events; never a truth signal

    @property
    def strong(self) -> bool:
        """Event + explicit food wording + a date: the shape a ggongbab mail has."""
        return self.candidate and self.has_event_word and self.has_food_word and self.has_date


def urgency(text: str, now: Optional[datetime] = None) -> str:
    """'high' when a hand-out runs out soon or the event is today. Affects scan order and
    alerting only; it never relaxes evidence or publication rules."""
    if FLASH_WORDS.search(text or ""):
        return "high"
    if now is not None:
        from .parsers.rule_parser import extract_dates

        if now.date().isoformat() in extract_dates(text or "", now.date()):
            return "high"
    return "normal"


def classify(subject: str, body: str, now: Optional[datetime] = None) -> Decision:
    """Decide whether this mail is worth an AI call."""
    text = f"{subject or ''}\n{body or ''}"
    if not text.strip():
        return Decision(False, "empty")
    if DENY.search(subject or "") or DENY_BODY.search(text[:1500]):
        return Decision(False, "denylist: transactional/personal mail")

    has_event = bool(EVENT_WORDS.search(text))
    has_food = bool(FOOD_WORDS.search(text))
    has_time = bool(MEAL_TIME.search(text))
    has_date = bool(DATE_HINT.search(text))
    has_provision = bool(STRONG_PROVISION.search(text))
    d = Decision(False, "", has_event, has_food, has_time, has_date, has_provision, urgency(text, now))

    if has_provision:
        # A hand-out is worth a look without a date: a flash event's subject and
        # preview often carry none, and the hand-out may already have started.
        d.candidate = True
        d.reason = "food provision wording" + (" + event" if has_event else "") + (" + date" if has_date else "")
        return d
    if not has_event:
        d.reason = "no event wording"
        return d
    if not has_date:
        d.reason = "event wording but no date"
        return d
    if not (has_food or has_time):
        d.reason = "event with a date but no food or meal-time signal"
        return d
    d.candidate = True
    bits = []
    if has_food:
        bits.append("food wording")
    if has_time:
        bits.append("meal-time")
    d.reason = "event + date + " + " + ".join(bits)
    return d


def is_candidate(subject: str, body: str) -> bool:
    return classify(subject, body).candidate


def portal_list_warrants_detail(title: str, meta: str = "") -> bool:
    """Fetch a Portal notice body only when the list row already looks event/food-like.

    Title event wording is enough: food evidence may live only in the body
    ("도시락 제공") and must not be dropped before the detail fetch.
    """
    text = f"{title or ''}\n{meta or ''}"
    if not text.strip():
        return False
    if DENY.search(title or "") or DENY.search(text[:800]):
        return False
    from .food_news import is_news_candidate
    return bool(EVENT_WORDS.search(text) or FOOD_WORDS.search(text) or MEAL_TIME.search(text)
                or is_news_candidate(title))


def portal_detail_is_candidate(title: str, body: str, *, has_list_date: bool = False) -> Decision:
    """Same event+food rule as mail, with the list date allowed to satisfy DATE_HINT."""
    decision = classify(title, body)
    if decision.candidate:
        return decision
    if has_list_date and decision.has_event_word and (decision.has_food_word or decision.has_meal_time):
        return Decision(
            True,
            "event + list date + " + ("food wording" if decision.has_food_word else "meal-time"),
            decision.has_event_word,
            decision.has_food_word,
            decision.has_meal_time,
            True,
        )
    return decision
