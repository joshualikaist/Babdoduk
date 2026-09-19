# -*- coding: utf-8 -*-
"""Deterministic pre-processor: dates, times, buildings, explicit food evidence.

These facts never come from the AI. The validator uses them to check the AI
output and to reject hallucinated dates / food claims.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from ..config import KST
from ..models import FoodType, RuleFacts

# --- dates -----------------------------------------------------------------
_FULL_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?")
_MONTH_DAY = re.compile(r"(?<![\d.])(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_SLASH_DATE = re.compile(r"(?<![\d.:/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/:])")
_DOT_DATE = re.compile(r"(?<![\d.])(\d{1,2})\s*\.\s*(\d{1,2})\s*(?:\.\s*)?(?=\s*[\(（]|\s*\d{1,2}:|\s*[월화수목금토일]|\s*$|\s)")
_DAY_RANGE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일?\s*[~\-–]\s*(\d{1,2})\s*일")
_EN_DATE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?",
    re.I,
)
_EN_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# --- times -----------------------------------------------------------------
_HM = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*:\s*([0-5]\d)(?!\d)")
_KO_HOUR = re.compile(r"(오전|오후|낮|저녁|밤|새벽|아침)?\s*(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분|(반))?")
_EN_HOUR = re.compile(r"(?<!\d)(\d{1,2})(?::([0-5]\d))?\s*(am|pm)\b", re.I)

# --- buildings ---------------------------------------------------------------
_BUILDING_CODE = re.compile(r"(?<![A-Za-z0-9])([NEWS]\d{1,2}(?:-\d{1,2})?)(?![A-Za-z0-9])")
_BUILDING_NAMES = [
    "KI빌딩", "KI 빌딩", "KI Building", "정문술빌딩", "정문술 빌딩", "창의학습관", "학술문화관", "대강당", "스포츠컴플렉스",
    "응용공학동", "기계공학동", "전산학동", "자연과학동", "산업경영학동", "정보전자공학동", "학생회관", "장영신학생회관",
    "카이마루", "동맛골", "서맛골", "교수회관", "영빈관", "류근철스포츠컴플렉스", "창업원", "본관", "교육지원동",
]
_BUILDING_ALIAS = {
    "ki 빌딩": "KI빌딩", "ki building": "KI빌딩", "정문술 빌딩": "정문술빌딩",
}

# --- food -------------------------------------------------------------------
_FOOD_WORDS = (
    r"점심(?!\s*시간)|중식|식사|저녁(?!\s*시간)|석식|조식|아침\s*식사|도시락|간식|다과|커피|음료|피자|샌드위치|햄버거|버거|치킨|김밥|떡|빵|"
    r"식권|밀쿠폰|쿠폰|기프티콘|케이터링|뷔페|음식|먹거리|Lunch|Dinner|Breakfast|Meal|Refreshments?|Snacks?|Pizza|Sandwich(?:es)?|"
    r"Coffee|Drinks?|Beverages?|Food|Catering|Lunch\s*box|Bento"
)
_PROVIDE_WORDS = r"제공|지급|드립니다|드려요|준비(?:되어|돼|합니다|했습니다)|나눠|나눔|증정|무료(?:로)?|배부|includ(?:ed|es)|provided|served|available|free|on us|complimentary"
# food word followed (within 30 chars) by a provision word, or provision word before food word
_FOOD_THEN_PROVIDE = re.compile(rf"((?:{_FOOD_WORDS})[^\n.。!?]{{0,30}}?(?:{_PROVIDE_WORDS}))", re.I)
_PROVIDE_THEN_FOOD = re.compile(rf"((?:무료|free|complimentary)\s*(?:{_FOOD_WORDS}))", re.I)
_FOOD_WITH = re.compile(r"((?:점심|간식|다과|피자|커피|도시락|음료)(?:과|와|을|를)?\s*(?:함께|드시면서|먹으면서|곁들여))")
_LUNCH_TIME = re.compile(r"점심\s*시간|런치\s*타임|lunch\s*(?:time|session|hour|break)|(?<!\d)12\s*시|12:00", re.I)
_NOT_PROVIDED = re.compile(r"(?:식사|점심|음식|다과)[^\n.]{0,10}(?:제공되지|제공하지|없습니다|미제공|not\s+provided)", re.I)

_FOOD_TYPE_RULES: list[tuple[re.Pattern[str], FoodType]] = [
    (re.compile(r"도시락|lunch\s*box|bento", re.I), "lunchbox"),
    (re.compile(r"식권|쿠폰|coupon|기프티콘|밀쿠폰|voucher", re.I), "coupon"),
    (re.compile(r"점심|중식|식사|저녁|석식|조식|피자|샌드위치|햄버거|버거|치킨|김밥|뷔페|케이터링|lunch|dinner|breakfast|meal|pizza|sandwich|catering|food", re.I), "meal"),
    (re.compile(r"간식|스낵|snack|빵|떡", re.I), "snack"),
    (re.compile(r"다과|refreshment", re.I), "refreshment"),
    (re.compile(r"커피|음료|coffee|drink|beverage", re.I), "beverage"),
]

# --- eligibility -------------------------------------------------------------
# A real audience restriction names who may attend. Words that merely refer to the
# people who show up ("참석자에게 점심 제공") are NOT eligibility.
_ELIGIBILITY_MARKERS = re.compile(
    r"대상|한정|이상|이하|재학생|학부생|대학원생|석사|박사|석·?박사|신입생|졸업|전공|학과|학부|과정생|"
    r"외국인|유학생|교직원|교수|연구원|직원|회원|선착순|자격|제한|만\s*\d+\s*세|\d\s*학년|"
    r"undergraduate|graduate|freshman|sophomore|junior|senior|faculty|staff|students?\s+(?:only|in|of)|"
    r"open\s+to|limited\s+to|eligible|eligibility|members?\s+only|first\s+\d+",
    re.I,
)
# Phrases that are only a way of saying "the people attending".
_ATTENDEE_ONLY = re.compile(
    r"^(?:행사\s*)?(?:참석자|참가자|참여자|방문자|참석\s*자|신청자|선착순)\s*(?:전원|모두|분들|여러분)?\s*"
    r"(?:에게|에겐|께|분들께|들에게|은|는|이|가|을|를)?\s*$|^(?:all\s+)?(?:attendees?|participants?|visitors?|everyone|all)\s*$",
    re.I,
)

# --- registration ------------------------------------------------------------
# Evidence that registration IS needed.
_REGISTRATION_YES = re.compile(
    r"사전\s*(?:신청|등록|접수|참가\s*신청)|"
    r"신청\s*(?:이|을|를)?\s*(?:필수|필요|바랍니다|해\s*주|하시기|링크|폼|서|기간|마감|방법)|"
    r"등록\s*(?:이|을|를)?\s*(?:필수|필요|바랍니다|해\s*주|하시기|링크|기간|마감)|접수\s*(?:기간|마감|방법|처)|참가\s*신청|"
    r"선착순|RSVP|registration\s*(?:required|link|form|closes|deadline)|register\s+(?:at|here|by|via)|"
    r"sign[\s-]?up|apply\s+(?:at|here|by|via)|신청서|구글\s*폼|google\s*form",
    re.I,
)
# Evidence that registration is NOT needed. Only these make "false" defensible.
_REGISTRATION_NO = re.compile(
    r"신청\s*(?:없이|불필요|필요\s*없|하지\s*않아도)|별도\s*(?:의\s*)?(?:신청|등록|접수)\s*(?:없|불필요|하지)|"
    r"사전\s*(?:신청|등록)\s*(?:없이|불필요|필요\s*없)|등록\s*(?:없이|불필요|필요\s*없)|"
    r"현장\s*(?:참여|참석|등록|접수)\s*(?:가능|하시면|만)|자유\s*(?:롭게\s*)?참(?:여|석)|누구나\s*(?:참여|참석|오)|"
    r"no\s+registration|without\s+registration|registration\s+(?:is\s+)?not\s+(?:required|needed)|"
    r"walk[\s-]?ins?\s+welcome|drop[\s-]?in|open\s+to\s+all\s+without",
    re.I,
)
_URL = re.compile(r"https?://[^\s<>\"'()\]]+")
_DEADLINE_CTX = re.compile(r"(마감|기한|까지|접수\s*기간|신청\s*기간|deadline|by\s+|until|RSVP)", re.I)
_EVENT_WORDS = re.compile(
    r"설명회|세미나|강연|특강|행사|워크숍|워크샵|간담회|채용|리크루팅|박람회|콜로퀴움|심포지엄|포럼|네트워킹|밋업|오리엔테이션|"
    r"info\s*session|seminar|talk|workshop|recruit|career\s*fair|colloquium|symposium|forum|networking|meetup|orientation|lecture",
    re.I,
)


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def infer_year(month: int, day: int, reference: date) -> Optional[date]:
    """Pick the year that puts month/day closest ahead of the reference date.

    Mails announce events that are usually within a few months; a date more
    than ~45 days in the past is assumed to be next year.
    """
    for year in (reference.year, reference.year + 1, reference.year - 1):
        candidate = _safe_date(year, month, day)
        if candidate is None:
            continue
        delta = (candidate - reference).days
        if -45 <= delta <= 330:
            return candidate
    return _safe_date(reference.year, month, day)


def extract_dates(text: str, reference: date) -> list[str]:
    found: list[str] = []

    def add(d: Optional[date]) -> None:
        if d and d.isoformat() not in found:
            found.append(d.isoformat())

    consumed = text
    for m in _FULL_DATE.finditer(text):
        add(_safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    consumed = _FULL_DATE.sub(" ", consumed)
    for m in _DAY_RANGE.finditer(consumed):
        month, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = infer_year(month, d1, reference)
        add(start)
        if start:
            end = _safe_date(start.year, month, d2)
            add(end)
    for m in _MONTH_DAY.finditer(consumed):
        add(infer_year(int(m.group(1)), int(m.group(2)), reference))
    consumed2 = _MONTH_DAY.sub(" ", consumed)
    for m in _SLASH_DATE.finditer(consumed2):
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            add(infer_year(month, day, reference))
    for m in _DOT_DATE.finditer(consumed2):
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            add(infer_year(month, day, reference))
    for m in _EN_DATE.finditer(text):
        month = _EN_MONTHS[m.group(1)[:3].lower()]
        day = int(m.group(2))
        if m.group(3):
            add(_safe_date(int(m.group(3)), month, day))
        else:
            add(infer_year(month, day, reference))
    return found


def extract_times(text: str) -> list[str]:
    found: list[str] = []

    def add(h: int, mi: int) -> None:
        if 0 <= h <= 23 and 0 <= mi <= 59:
            val = f"{h:02d}:{mi:02d}"
            if val not in found:
                found.append(val)

    for m in _HM.finditer(text):
        add(int(m.group(1)), int(m.group(2)))
    stripped = _HM.sub(" ", text)
    for m in _KO_HOUR.finditer(stripped):
        prefix, hour_s, minute_s, half = m.groups()
        hour = int(hour_s)
        if hour > 24:
            continue
        minute = int(minute_s) if minute_s else (30 if half else 0)
        if prefix in ("오후", "저녁", "밤") and hour < 12:
            hour += 12
        elif prefix == "낮" and hour < 11:
            hour += 12
        elif prefix in ("새벽", "아침", "오전") and hour == 12:
            hour = 0
        add(hour % 24, minute)
    for m in _EN_HOUR.finditer(text):
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3).lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        add(hour, minute)
    return found


def extract_buildings(text: str) -> list[str]:
    found: list[str] = []
    for m in _BUILDING_CODE.finditer(text):
        code = m.group(1).upper()
        if code not in found:
            found.append(code)
    lowered = text.lower()
    for name in _BUILDING_NAMES:
        if name.lower() in lowered:
            canon = _BUILDING_ALIAS.get(name.lower(), name)
            if canon not in found:
                found.append(canon)
    return found


def explicit_food_evidence(text: str) -> list[str]:
    """Phrases that explicitly say food/drink is provided. Time-of-day words alone never match."""
    if not text:
        return []
    if _NOT_PROVIDED.search(text):
        return []
    phrases: list[str] = []
    for pattern in (_FOOD_THEN_PROVIDE, _PROVIDE_THEN_FOOD, _FOOD_WITH):
        for m in pattern.finditer(text):
            phrase = re.sub(r"\s+", " ", m.group(1)).strip()
            if phrase and phrase not in phrases:
                phrases.append(phrase)
    return phrases


def food_type_hint(text: str) -> FoodType:
    for pattern, kind in _FOOD_TYPE_RULES:
        if pattern.search(text or ""):
            return kind
    return "unknown"


def is_real_eligibility(value: str) -> bool:
    """True only when the phrase actually restricts who may attend."""
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) < 2:
        return False
    if _ATTENDEE_ONLY.match(text):
        return False
    return bool(_ELIGIBILITY_MARKERS.search(text))


def registration_evidence(text: str) -> str:
    """Return 'true' / 'false' / 'unknown' from explicit wording only."""
    if not text:
        return "unknown"
    if _REGISTRATION_NO.search(text):
        return "false"
    if _REGISTRATION_YES.search(text):
        return "true"
    return "unknown"


def extract_deadline_dates(text: str, reference: date) -> list[str]:
    found: list[str] = []
    for line in re.split(r"[\n.。]", text):
        if _DEADLINE_CTX.search(line):
            for iso in extract_dates(line, reference):
                if iso not in found:
                    found.append(iso)
    return found


def analyze(text: str, reference: Optional[datetime] = None) -> RuleFacts:
    ref_dt = reference or datetime.now(KST)
    ref = ref_dt.astimezone(KST).date() if ref_dt.tzinfo else ref_dt.date()
    text = text or ""
    evidence = explicit_food_evidence(text)
    facts = RuleFacts(
        dates=extract_dates(text, ref),
        times=extract_times(text),
        buildings=extract_buildings(text),
        food_evidence=evidence,
        food_type_hint=food_type_hint(" ".join(evidence)) if evidence else "unknown",
        lunch_time_only=bool(_LUNCH_TIME.search(text)) and not evidence,
        urls=[u.rstrip(".,;)") for u in _URL.findall(text)],
        deadline_dates=extract_deadline_dates(text, ref),
        looks_like_event=bool(_EVENT_WORDS.search(text)),
        registration_state=registration_evidence(text),
    )
    return facts


def combine(date_iso: str, time_hm: str) -> datetime:
    y, m, d = (int(x) for x in date_iso.split("-"))
    h, mi = (int(x) for x in time_hm.split(":"))
    return datetime(y, m, d, h, mi, tzinfo=KST)


def next_occurrence_guard(dt: datetime, reference: datetime) -> bool:
    """True if dt is within a plausible announcement window."""
    delta = dt - reference
    return timedelta(days=-60) <= delta <= timedelta(days=365)
