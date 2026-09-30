# -*- coding: utf-8 -*-
"""Validate generated magazine / KAIST menu / ggongbab JSON before production push."""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
LANES = ("tips", "trend", "health", "habit")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def video_id(url: str) -> str:
    match = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{11})", url or "")
    return match.group(1) if match else ""


MAGAZINE_LANE_MAX = 8
MAGAZINE_MEDIA = {"blog", "youtube", "instagram", "news", "research"}
TREND_EVIDENCE = {"explicit_source_claim", "corroborated", "engagement", "sales_data"}
MAGAZINE_RULES = "lanes-v1"
TREND_MAX_DAYS = 30
FABRICATED_SOURCES = {"밥도둑 데스크", "Babdoduk desk"}


def magazine_item_errors(item: dict, where: str) -> list[str]:
    """Every public story is source-backed: real source name, real http(s) URL, the source's
    title, no desk/filler medium (docs/MAGAZINE_DISCOVERY.md)."""
    errors = []
    url = str(item.get("url") or "")
    if not item.get("title"):
        errors.append(f"{where}: story without title")
    if not re.match(r"^https?://[^/\s]+", url):
        errors.append(f"{where}: story without a real source URL")
    if item.get("medium") == "desk" or item.get("source") in FABRICATED_SOURCES or not item.get("source"):
        errors.append(f"{where}: fabricated or unsourced story")
    elif item.get("medium") not in MAGAZINE_MEDIA:
        errors.append(f"{where}: unknown medium {item.get('medium')!r}")
    if item.get("image") and not re.match(r"^https?://", str(item.get("image"))):
        errors.append(f"{where}: image is not an http(s) URL")
    if len(str(item.get("summary") or "")) > 200:
        errors.append(f"{where}: summary longer than a source excerpt")
    if item.get("trendEvidence") is not None and not (
            isinstance(item["trendEvidence"], list) and item["trendEvidence"]
            and set(item["trendEvidence"]) <= TREND_EVIDENCE):
        errors.append(f"{where}: trendEvidence must list known evidence kinds")
    return errors


def lane_rule_errors(item: dict, lane: str, edition_date: str, where: str) -> list[str]:
    """Trend and habit are evidence lanes (docs/MAGAZINE_DISCOVERY.md): a trend story carries
    its trendEvidence and is at most 30 days older than the edition; every trend or habit story
    shows its publication date."""
    errors = []
    if lane not in ("trend", "habit"):
        return errors
    published = str(item.get("publishedAt") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        errors.append(f"{where}: {lane} story without a publication date")
        return errors
    if lane == "trend":
        if not item.get("trendEvidence"):
            errors.append(f"{where}: trend story without trendEvidence")
        try:
            age = (date.fromisoformat(edition_date) - date.fromisoformat(published)).days
        except ValueError:
            age = None
        if age is not None and age > TREND_MAX_DAYS:
            errors.append(f"{where}: trend story older than {TREND_MAX_DAYS} days")
    return errors


def story_url_key(url: str) -> str:
    """Scheme, www. and fragment dropped, tracking parameters removed; the rest of the query
    stays (a news CMS puts the article id there: articleView.html?idxno=123)."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    query = "&".join(sorted(f"{k}={v}" for k, v in parse_qsl(parsed.query) if not k.lower().startswith("utm_")))
    return f"{host}{parsed.path.rstrip('/')}" + (f"?{query}" if query else "")


def validate_magazine(path: Path) -> list[str]:
    errors = []
    data = load(path)
    name = path.name
    if not data.get("date"):
        errors.append("magazine missing date")
    if "desks" in data:
        errors.append(f"{name}: idea desks are not source-backed stories")
    lanes = data.get("lanes") or {}
    for lane in LANES:
        if lane not in lanes:
            errors.append(f"missing lane {lane}")
            continue
        items = lanes[lane].get("items")
        if not isinstance(items, list):
            errors.append(f"{name}: {lane} items missing")
        elif len(items) > MAGAZINE_LANE_MAX:
            errors.append(f"{name}: {lane} has more than {MAGAZINE_LANE_MAX} items")
    featured = data.get("featured") or {}
    if featured:
        errors.extend(magazine_item_errors(featured, f"{name} featured"))
    if data.get("rules") == MAGAZINE_RULES and featured:
        if featured.get("heroKind") not in ("trend", "pick"):
            errors.append(f"{name}: featured heroKind must be trend or pick")
        if featured.get("heroKind") == "trend" and (featured.get("category") != "trend" or not featured.get("trendEvidence")):
            errors.append(f"{name}: a trend hero needs a trend story with trendEvidence")
        errors.extend(lane_rule_errors(featured, featured.get("category") or "", data.get("date") or "", f"{name} featured"))
    used_urls = set()
    used_vids = set()
    used_titles = set()
    feat_url = story_url_key(featured.get("url") or "") if featured.get("url") else ""
    feat_title = featured.get("title") or ""
    for lane in LANES:
        sources = []
        for item in (lanes.get(lane) or {}).get("items") or []:
            errors.extend(magazine_item_errors(item, f"{name} {lane}"))
            errors.extend(lane_rule_errors(item, lane, data.get("date") or "", f"{name} {lane}"))
            title = item.get("title") or ""
            url = story_url_key(item.get("url") or "") if item.get("url") else ""
            vid = video_id(item.get("url") or "")
            src = item.get("source") or ""
            if title in used_titles:
                errors.append(f"duplicate title {title[:40]}")
            if url and url in used_urls and not vid:
                errors.append(f"duplicate url {url}")
            if vid and vid in used_vids:
                errors.append(f"duplicate video {vid}")
            if feat_title and title == feat_title:
                errors.append("featured repeated in lane " + lane)
            if feat_url and url and url == feat_url and not vid:
                errors.append("featured url repeated in lane " + lane)
            sources.append(src)
            used_titles.add(title)
            if url:
                used_urls.add(url)
            if vid:
                used_vids.add(vid)
    return errors


def validate_magazine_archive(folder: Path) -> list[str]:
    """Every stored edition is browsable from the calendar, so none may carry a fabricated story."""
    errors = []
    for path in sorted(folder.glob("20*.json")):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        data = load(path)
        items = [data.get("featured")] + [i for spec in (data.get("lanes") or {}).values() for i in spec.get("items") or []]
        for item in filter(None, items):
            errors.extend(magazine_item_errors(item, path.name))
        if "desks" in data:
            errors.append(f"{path.name}: idea desks are not source-backed stories")
        lanes = data.get("lanes") or {}
        # Browsable history never shows a trend without evidence, nor the old builder's
        # keyword-routed habit picks (select.sanitize removes both).
        if any(not i.get("trendEvidence") for i in (lanes.get("trend") or {}).get("items") or []):
            errors.append(f"{path.name}: trend story without trendEvidence")
        if data.get("rules") != MAGAZINE_RULES and (lanes.get("habit") or {}).get("items"):
            errors.append(f"{path.name}: habit stories from before the lane rules")
    return errors


RESEARCH_FORBIDDEN_KEYS = {"cookie", "cookies", "token", "session", "authorization", "password", "apikey", "api_key"}


def validate_magazine_research(folder: Path) -> list[str]:
    """The discovery store: registry schema, candidates with real URLs and no session material,
    and a health report that never counts a fabricated story."""
    errors = []
    sys.path.insert(0, str(ROOT / "scripts"))
    from discovery import registry
    errors.extend("scripts/discovery/sources.json: " + e for e in registry.validate(registry.load()))
    source_health = folder / "source-health.json"
    if source_health.exists():
        for sid, entry in (load(source_health).get("sources") or {}).items():
            if entry.get("status") not in registry.STATUSES:
                errors.append(f"source-health.json: {sid} has status {entry.get('status')!r}")
    candidates = folder / "candidates.jsonl"
    if candidates.exists():
        seen = set()
        for number, line in enumerate(candidates.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                errors.append(f"candidates.jsonl:{number}: not JSON")
                continue
            if {k.lower() for k in row} & RESEARCH_FORBIDDEN_KEYS:
                errors.append(f"candidates.jsonl:{number}: session or credential field")
            if not row.get("candidateId") or row["candidateId"] in seen:
                errors.append(f"candidates.jsonl:{number}: candidateId missing or duplicate")
            seen.add(row.get("candidateId"))
            if not re.match(r"^https?://", str(row.get("sourceUrl") or "")):
                errors.append(f"candidates.jsonl:{number}: sourceUrl is not http(s)")
    health = folder / "health.json"
    if health.exists() and (load(health).get("summary") or {}).get("fabricated", 0) != 0:
        errors.append("health.json: fabricated stories counted")
    return errors


def validate_kaist(path: Path) -> list[str]:
    errors = []
    data = load(path)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("date") or "")):
        errors.append("kaist date invalid")
    restos = data.get("restaurants")
    if not isinstance(restos, list) or not restos:
        errors.append("kaist restaurants empty")
        return errors
    for row in restos:
        if not row.get("name") or not row.get("id"):
            errors.append("kaist restaurant missing name/id")
    status = data.get("status")
    if status is not None and status != "AVAILABLE":
        errors.append("kaist daily status must be AVAILABLE")
    coverage = data.get("coverage")
    if coverage is not None:
        numbers = [coverage.get(key) for key in ("requested", "fetched")]
        if not all(isinstance(n, int) and n >= 0 for n in numbers) or numbers[1] > numbers[0]:
            errors.append("kaist coverage counts invalid")
        for key in ("failed", "carried"):
            if not isinstance(coverage.get(key), list) or not all(isinstance(i, str) for i in coverage.get(key)):
                errors.append(f"kaist coverage {key} invalid")
        if isinstance(coverage.get("carried"), list) and not set(coverage["carried"]) <= set(coverage.get("failed") or []):
            errors.append("kaist coverage carried a restaurant that did not fail")
    return errors


KAIST_DAY_STATUSES = {"AVAILABLE", "NOT_PUBLISHED_YET", "FETCH_FAILED", "STALE_SAVED_DATA"}
KAIST_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def kaist_menu_count(data: dict) -> int:
    return sum(1 for row in data.get("restaurants") or []
               if any(((row.get(meal) or {}).get("items")) for meal in ("breakfast", "lunch", "dinner")))


def validate_kaist_dir(folder: Path) -> list[str]:
    """Every dated daily file, latest.json (today's compatibility copy) and the week index."""
    errors = []
    dated = {}
    for path in sorted(folder.glob("*.json")):
        match = KAIST_DATED.match(path.name)
        if not match:
            continue
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            errors.append(f"kaist {path.name}: not a calendar date")
            continue
        found = validate_kaist(path)
        data = load(path)
        if data.get("date") != match.group(1):
            found.append("kaist daily date does not match its filename")
        errors.extend(f"kaist {path.name}: {e}" for e in found)
        dated[match.group(1)] = data
    latest = folder / "latest.json"
    if latest.exists():
        latest_date = load(latest).get("date")
        twin = folder / f"{latest_date}.json"
        if twin.exists() and twin.read_text(encoding="utf-8") != latest.read_text(encoding="utf-8"):
            errors.append("kaist latest.json does not match its dated file")
    week = folder / "week.json"
    if week.exists():
        errors.extend(validate_kaist_week(load(week), dated))
    return errors


def validate_kaist_week(week: dict, dated: dict) -> list[str]:
    errors = []
    try:
        start = datetime.strptime(str(week.get("weekStart")), "%Y-%m-%d").date()
        end = datetime.strptime(str(week.get("weekEnd")), "%Y-%m-%d").date()
    except ValueError:
        return ["kaist week.json weekStart/weekEnd invalid"]
    if start > end:
        errors.append("kaist week.json weekStart after weekEnd")
    if start.weekday() != 0 or end != start + timedelta(days=6):
        errors.append("kaist week.json is not a Monday-Sunday week")
    if week.get("timezone") != "Asia/Seoul":
        errors.append("kaist week.json timezone must be Asia/Seoul")
    try:
        generated = datetime.fromisoformat(str(week.get("generatedAt")))
        if generated.tzinfo is None:
            raise ValueError
        if not start <= generated.astimezone(KST).date() <= end:
            errors.append("kaist week.json was not generated during its own week")
    except ValueError:
        errors.append("kaist week.json generatedAt invalid")
    days = week.get("days")
    if not isinstance(days, list):
        return errors + ["kaist week.json days missing"]
    expected = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    got = [row.get("date") if isinstance(row, dict) else None for row in days]
    if len(set(got)) != len(got):
        errors.append("kaist week.json has duplicate days")
    if got != expected:
        errors.append("kaist week.json days are not exactly Monday-Sunday of weekStart")
    for row in days:
        if not isinstance(row, dict):
            continue
        count, available, status = row.get("restaurantCount"), row.get("available"), row.get("status")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"kaist week.json {row.get('date')}: restaurantCount invalid")
            continue
        if not isinstance(available, bool) or status not in KAIST_DAY_STATUSES:
            errors.append(f"kaist week.json {row.get('date')}: available/status invalid")
            continue
        saved = dated.get(row.get("date"))
        if available != (saved is not None) or (available and count != kaist_menu_count(saved)):
            errors.append(f"kaist week.json {row.get('date')}: does not match its dated file")
        if available != (status in {"AVAILABLE", "STALE_SAVED_DATA"}):
            errors.append(f"kaist week.json {row.get('date')}: status contradicts availability")
        if not available and count:
            errors.append(f"kaist week.json {row.get('date')}: count without a menu")
    return errors

# ---------------------------------------------------------------------------
# ggongbab (free-food events)
# ---------------------------------------------------------------------------
KST = timezone(timedelta(hours=9))
GG_PRIVATE_KEYS = {
    "sender_email", "sender_name", "recipient", "to", "cc", "raw_html", "raw_text", "rawHtml", "rawText",
    "dooray_post_id", "dooray", "external_id", "externalId", "raw_item_id", "prompt", "system_prompt",
    "api_key", "apiKey", "service_role", "secret_key", "secretKey", "attachment_url", "file_id",
    "metadata", "review_reason",
}
GG_FOOD_TYPES = {"meal", "lunchbox", "snack", "refreshment", "beverage", "coupon", "other", "unknown"}
GG_SOURCE_TYPES = {"dooray", "dooray_mailbox", "kaist_public", "manual", "portal"}
GG_TRI = {"true", "false", "unknown"}
KST_OFFSET = timedelta(hours=9)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?82[-\s.]?)?0?1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|dooray-api\s+\S+)")
DOORAY_LINK_RE = re.compile(r"dooray\.com|/files/[A-Za-z0-9]{8,}", re.I)
GG_PUBLIC_URL_SOURCES = {"kaist_public", "manual"}

# ---------------------------------------------------------------------------
# Public event schema and the structure-aware privacy scan (latest.json and the archive)
# ---------------------------------------------------------------------------
# Every field of a public ggongbab event and the kind of value it holds. The privacy
# patterns (e-mail, phone, token, Dooray/private link) run on "text" fields only: the words
# a person wrote or the extractor copied. Ids, timestamps, enums and numbers are checked by
# shape and URLs by URL rules, so a UUID such as ...-4b18-8387-8430... (read as
# 018-8387-8430) or a numeric link path is never mistaken for a phone number. A key that is
# not listed here is refused until it is reviewed for privacy and classified
# (tests/ggongbab/test_privacy_validator.py keeps this schema and the exporter in step).
GG_TEXT, GG_URL, GG_ID, GG_TIME, GG_ENUM, GG_NUMBER = "text", "url", "id", "time", "enum", "number"
GG_EVENT_SCHEMA = {
    "id": GG_ID,
    "title": GG_TEXT, "summary": GG_TEXT, "dateText": GG_TEXT, "timeText": GG_TEXT,
    "organizer": GG_TEXT, "eligibility": GG_TEXT,
    "startAt": GG_TIME, "endAt": GG_TIME,
    "location": {"name": GG_TEXT, "building": GG_TEXT, "room": GG_TEXT},
    "food": {"provided": GG_ENUM, "type": GG_ENUM, "description": GG_TEXT},
    "registration": {"required": GG_ENUM, "deadline": GG_TIME, "url": GG_URL},
    "confidence": GG_NUMBER,
    "sources": [{"type": GG_ENUM, "name": GG_TEXT, "url": GG_URL}],
}
# Top-level keys; `_preview` holds only the local preview's numeric diagnostics.
GG_LIVE_TOP_LEVEL = {"generatedAt", "timezone", "count", "events", "_preview"}
GG_ARCHIVE_TOP_LEVEL = {"generatedAt", "timezone", "windowDays", "count", "events"}
GG_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
# A whole query/fragment value that is a dialable Korean mobile number: it needs a real
# prefix (0, +82, or 82 plus a separator), so a numeric id such as mng_no=1712345678 is not one.
GG_URL_PHONE_RE = re.compile(r"(?:\+82[-\s.]?|82[-\s.]|0)1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}")
GG_TEXT_PATTERNS = ((EMAIL_RE, "an e-mail address"), (PHONE_RE, "a phone number"),
                    (SECRET_RE, "a token-like string"), (DOORAY_LINK_RE, "a Dooray/private file link"))


def gg_schema_fields(value, schema=GG_EVENT_SCHEMA, path=""):
    """(path, kind, value) for each field present in a public event, walked by the schema.

    kind is None for a key the schema does not know, and "shape" where a value has the
    wrong container type. Values are never searched blindly: only the schema decides.
    """
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            yield path, "shape", value
            return
        for key, item in value.items():
            where = f"{path}.{key}" if path else key
            if key not in schema:
                yield where, None, item
            else:
                yield from gg_schema_fields(item, schema[key], where)
    elif isinstance(schema, list):
        if not isinstance(value, list):
            yield path, "shape", value
            return
        for idx, item in enumerate(value):
            yield from gg_schema_fields(item, schema[0], f"{path}[{idx}]")
    else:
        yield path, schema, value


def gg_public_text_fields(schema=GG_EVENT_SCHEMA, path="") -> tuple[str, ...]:
    """The explicit allowlist of privacy-scanned text fields, e.g. "location.name", "sources[].name"."""
    fields: list[str] = []
    for key, kind in schema.items():
        where = f"{path}.{key}" if path else key
        if isinstance(kind, dict):
            fields += gg_public_text_fields(kind, where)
        elif isinstance(kind, list):
            fields += gg_public_text_fields(kind[0], where + "[]")
        elif kind == GG_TEXT:
            fields.append(where)
    return tuple(fields)


GG_PUBLIC_TEXT_FIELDS = gg_public_text_fields()


def gg_text_errors(prefix: str, where: str, text) -> list[str]:
    """Personal data in public text: strict, for every text field."""
    if text is None:
        return []
    if not isinstance(text, str):
        return [f"{where} must be text"]
    return [f"{prefix} contains {label} in {where}" for pattern, label in GG_TEXT_PATTERNS if pattern.search(text)]


def gg_url_errors(prefix: str, where: str, url) -> list[str]:
    """URL rules instead of text rules: digits in a host or path are ids, not phone numbers.

    Refused: a non-http(s) or host-less URL, credentials, a Dooray/private file link, an
    e-mail address or a token anywhere in the URL (percent-decoded too), and a query or
    fragment value that is itself a dialable mobile number, such as a prefilled form field.
    """
    if url in (None, ""):
        return []
    if not isinstance(url, str):
        return [f"{where} invalid"]
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return [f"{where} invalid"]
    errors = [f"{where} carries credentials"] if (parsed.username or parsed.password) else []
    decoded = unquote(url)
    for pattern, label in ((DOORAY_LINK_RE, "a Dooray/private file link"), (EMAIL_RE, "an e-mail address"),
                           (SECRET_RE, "a token-like string")):
        if pattern.search(url) or pattern.search(decoded):
            errors.append(f"{prefix} contains {label} in {where}")
    values = [value for _, value in parse_qsl(parsed.query, keep_blank_values=True)]
    values += [value for _, value in parse_qsl(parsed.fragment, keep_blank_values=True)] or [unquote(parsed.fragment)]
    if any(GG_URL_PHONE_RE.fullmatch(value.strip()) for value in values if value.strip()):
        errors.append(f"{prefix} contains a phone number in {where} (query or fragment value)")
    return errors


def gg_id_errors(prefix: str, where: str, value) -> list[str]:
    """An id is structural: a plain identifier, never scanned as text (no phone pattern)."""
    if not isinstance(value, str) or not value:
        return []  # a missing id is reported by the validator itself
    errors = [] if GG_ID_RE.fullmatch(value) else [f"{where} is not a plain identifier"]
    for pattern, label in ((SECRET_RE, "a token-like string"), (DOORAY_LINK_RE, "a Dooray/private file link")):
        if pattern.search(value):
            errors.append(f"{prefix} contains {label} in {where}")
    return errors


def gg_public_field_errors(prefix: str, tag: str, event: dict) -> list[str]:
    """Privacy and schema-ownership errors for one public event (shared by the live feed and the archive)."""
    errors: list[str] = []
    for path, kind, value in gg_schema_fields(event):
        where = f"{tag}.{path}"
        if kind is None:
            errors.append(f"{where} is not in the reviewed public schema; privacy review required")
        elif kind == "shape":
            errors.append(f"{where} has an unexpected shape")
        elif kind == GG_TEXT:
            errors += gg_text_errors(prefix, where, value)
        elif kind == GG_URL:
            errors += gg_url_errors(prefix, where, value)
        elif kind == GG_ID:
            errors += gg_id_errors(prefix, where, value)
        # time, enum and number values are checked by the validators' own rules
    for src in event.get("sources") if isinstance(event.get("sources"), list) else []:
        if isinstance(src, dict) and src.get("url") and src.get("type") not in GG_PUBLIC_URL_SOURCES:
            errors.append(f"{tag} exposes a {src.get('type')} source URL; only public notice links may be kept")
    return errors


def gg_top_level_errors(label: str, data: dict, allowed: set[str]) -> list[str]:
    errors = [f"{label} top-level {key!r} is not in the reviewed public schema; privacy review required"
              for key in data if key not in allowed]
    preview = data.get("_preview")
    if "_preview" in allowed and preview is not None and not (
            isinstance(preview, dict)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in preview.values())):
        errors.append(f"{label} _preview must hold numeric counters only")
    return errors


def _walk_keys(obj, path: str, errors: list[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in GG_PRIVATE_KEYS:
                errors.append(f"ggongbab private field {path}.{key}")
            _walk_keys(value, f"{path}.{key}", errors)
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _walk_keys(value, f"{path}[{idx}]", errors)


def _iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def _norm_title(title: str) -> str:
    return re.sub(r"[^\w가-힣]+", "", (title or "").lower())


def validate_ggongbab(path: Path, now: datetime | None = None) -> list[str]:
    try:
        data = load(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"ggongbab JSON invalid: {exc}"]
    return validate_ggongbab_payload(data, now)


def validate_ggongbab_payload(data: dict, now: datetime | None = None) -> list[str]:
    """Validate in memory too, so local preview rejects PII before writing JSON."""
    errors: list[str] = []
    now = now or datetime.now(KST)
    generated = _iso(data.get("generatedAt"))
    if generated is None:
        errors.append("ggongbab generatedAt missing or not ISO with offset")
    elif generated.utcoffset() != KST_OFFSET:
        errors.append("ggongbab generatedAt is not +09:00 (Asia/Seoul)")
    if data.get("timezone") != "Asia/Seoul":
        errors.append("ggongbab timezone must be Asia/Seoul")
    events = data.get("events")
    if not isinstance(events, list):
        return errors + ["ggongbab events must be a list"]
    if data.get("count") is not None and data.get("count") != len(events):
        errors.append("ggongbab count does not match events length")
    # Privacy is checked field by field (gg_public_field_errors), never over the serialized
    # JSON: structural values such as UUID ids must not be read as phone numbers.
    errors += gg_top_level_errors("ggongbab export", data, GG_LIVE_TOP_LEVEL)
    _walk_keys(data, "$", errors)
    ids: set[str] = set()
    seen: list[tuple[str, str]] = []
    for idx, ev in enumerate(events):
        tag = f"events[{idx}]"
        if not isinstance(ev, dict):
            errors.append(f"{tag} not an object")
            continue
        errors += gg_public_field_errors("ggongbab export", tag, ev)
        eid = ev.get("id")
        if not eid or not isinstance(eid, str):
            errors.append(f"{tag} missing id")
        elif eid in ids:
            errors.append(f"{tag} duplicate id {eid}")
        else:
            ids.add(eid)
        if not isinstance(ev.get("title"), str) or not ev["title"].strip():
            errors.append(f"{tag} missing title")
        start = _iso(ev.get("startAt"))
        if start is None:
            errors.append(f"{tag} startAt missing or not ISO with offset")
        end = _iso(ev.get("endAt")) if ev.get("endAt") else None
        if ev.get("endAt") and end is None:
            errors.append(f"{tag} endAt not ISO")
        if start and end and end < start:
            errors.append(f"{tag} endAt before startAt")
        last = end or start
        if last and last + timedelta(hours=6) < now:
            errors.append(f"{tag} expired ({last.isoformat()})")
        for label, value in (("startAt", start), ("endAt", end)):
            if value is not None and value.utcoffset() != KST_OFFSET:
                errors.append(f"{tag} {label} is not +09:00 (Asia/Seoul)")
        conf = ev.get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= float(conf) <= 1:
            errors.append(f"{tag} confidence out of range")
        food = ev.get("food") or {}
        # tri-state, never boolean: "unknown" must not be collapsed into false.
        if food.get("provided") not in GG_TRI:
            errors.append(f"{tag} food.provided must be true/false/unknown")
        if food.get("type") not in GG_FOOD_TYPES:
            errors.append(f"{tag} food.type invalid")
        if food.get("provided") != "true" and food.get("type") not in (None, "", "unknown"):
            errors.append(f"{tag} food.type set while food.provided is not true")
        reg = ev.get("registration") or {}
        if reg.get("required") not in GG_TRI:
            errors.append(f"{tag} registration.required must be true/false/unknown")
        # registration.url: URL rules in gg_public_field_errors ("... registration.url invalid")
        deadline = _iso(reg.get("deadline")) if reg.get("deadline") else None
        if reg.get("deadline") and deadline is None:
            errors.append(f"{tag} registration.deadline not ISO")
        elif deadline is not None and deadline.utcoffset() != KST_OFFSET:
            errors.append(f"{tag} registration.deadline is not +09:00 (Asia/Seoul)")
        sources = ev.get("sources") or []
        if not sources:
            errors.append(f"{tag} has no sources")
        for src in sources if isinstance(sources, list) else []:
            if not isinstance(src, dict):
                errors.append(f"{tag} source not an object")
                continue
            if src.get("type") not in GG_SOURCE_TYPES:
                errors.append(f"{tag} source type invalid")
            if set(src.keys()) - {"type", "name", "url"}:
                errors.append(f"{tag} source has unexpected keys")
        key_title = _norm_title(ev.get("title") if isinstance(ev.get("title"), str) else "")
        day = start.date().isoformat() if start else ""
        for other_title, other_day in seen:
            if day and day == other_day and SequenceMatcher(None, key_title, other_title).ratio() >= 0.9:
                errors.append(f"{tag} looks like a duplicate of another event on {day}")
                break
        seen.append((key_title, day))
    return errors


# ---------------------------------------------------------------------------
# ggongbab past listings (data/ggongbab/archive/index.json)
# ---------------------------------------------------------------------------
GG_ARCHIVE_WINDOW_DAYS = 30


def validate_ggongbab_archive(path: Path, live_ids: set[str] | None = None) -> list[str]:
    try:
        data = load(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"ggongbab archive JSON invalid: {exc}"]
    return validate_ggongbab_archive_payload(data, live_ids)


def validate_ggongbab_archive_payload(data: dict, live_ids: set[str] | None = None) -> list[str]:
    """Past listings: ended, inside the public window, public fields only, nothing to sign up for.

    Times are checked against the file's own generatedAt, not the clock: a snapshot
    that is not regenerated still describes the same moment (the page applies the
    window again), so it never starts failing and blocking other publishing.
    `live_ids`, when given, must not overlap: a row is live or archived, never both.
    """
    if not isinstance(data, dict):
        return ["ggongbab archive must be an object"]
    errors: list[str] = []
    generated = _iso(data.get("generatedAt"))
    if generated is None:
        errors.append("ggongbab archive generatedAt missing or not ISO with offset")
    elif generated.utcoffset() != KST_OFFSET:
        errors.append("ggongbab archive generatedAt is not +09:00 (Asia/Seoul)")
    if data.get("timezone") != "Asia/Seoul":
        errors.append("ggongbab archive timezone must be Asia/Seoul")
    if data.get("windowDays") != GG_ARCHIVE_WINDOW_DAYS:
        errors.append(f"ggongbab archive windowDays must be {GG_ARCHIVE_WINDOW_DAYS}")
    events = data.get("events")
    if not isinstance(events, list):
        return errors + ["ggongbab archive events must be a list"]
    if data.get("count") != len(events):
        errors.append("ggongbab archive count does not match events length")
    # The same field-by-field privacy scan as the live feed; never a weaker rule.
    errors += gg_top_level_errors("ggongbab archive", data, GG_ARCHIVE_TOP_LEVEL)
    _walk_keys(data, "$archive", errors)
    ids: set[str] = set()
    order: list[tuple[str, str]] = []
    for idx, ev in enumerate(events):
        tag = f"archive[{idx}]"
        if not isinstance(ev, dict):
            errors.append(f"{tag} not an object")
            continue
        errors += gg_public_field_errors("ggongbab archive", tag, ev)
        eid = ev.get("id")
        if not eid or not isinstance(eid, str):
            errors.append(f"{tag} missing id")
        elif eid in ids:
            errors.append(f"{tag} duplicate id {eid}")
        else:
            ids.add(eid)
            if live_ids and eid in live_ids:
                errors.append(f"{tag} is also in the live feed")
        if not isinstance(ev.get("title"), str) or not ev["title"].strip():
            errors.append(f"{tag} missing title")
        start = _iso(ev.get("startAt"))
        if start is None:
            errors.append(f"{tag} startAt missing or not ISO with offset")
        end = _iso(ev.get("endAt")) if ev.get("endAt") else None
        if ev.get("endAt") and end is None:
            errors.append(f"{tag} endAt not ISO")
        if start and end and end < start:
            errors.append(f"{tag} endAt before startAt")
        for label, value in (("startAt", start), ("endAt", end)):
            if value is not None and value.utcoffset() != KST_OFFSET:
                errors.append(f"{tag} {label} is not +09:00 (Asia/Seoul)")
        last = end or start
        if last and generated:
            if last >= generated:
                errors.append(f"{tag} had not ended at generatedAt; live listings stay in latest.json")
            elif last < generated - timedelta(days=GG_ARCHIVE_WINDOW_DAYS):
                errors.append(f"{tag} ended outside the {GG_ARCHIVE_WINDOW_DAYS}-day public window")
        food = ev.get("food") or {}
        if food.get("provided") != "true":
            errors.append(f"{tag} food.provided must be true: only explicit-food listings are archived")
        if food.get("type") not in GG_FOOD_TYPES:
            errors.append(f"{tag} food.type invalid")
        for key in ("registration", "confidence"):
            if key in ev:
                errors.append(f"{tag} carries {key}; a past listing has nothing to sign up for")
        sources = ev.get("sources") or []
        if not sources:
            errors.append(f"{tag} has no sources")
        for src in sources:
            if not isinstance(src, dict):
                errors.append(f"{tag} source not an object")
                continue
            if src.get("type") not in GG_SOURCE_TYPES:
                errors.append(f"{tag} source type invalid")
            if set(src.keys()) - {"type", "name", "url"}:
                errors.append(f"{tag} source has unexpected keys")
            # sources[].url: URL rules and the public-notice-only rule in gg_public_field_errors
        order.append((ev.get("endAt") or ev.get("startAt") or "", eid if isinstance(eid, str) else ""))
    expected = sorted(sorted(order, key=lambda key: key[1]), key=lambda key: key[0], reverse=True)
    if order != expected:
        errors.append("ggongbab archive is not in most-recently-ended order (ties by id)")
    return errors


def main() -> None:
    mag_index = ROOT / "data" / "magazine" / "index.json"
    errors = []
    if mag_index.exists():
        index = load(mag_index)
        latest = index.get("latest")
        mag = ROOT / "data" / "magazine" / f"{latest}.json"
        if not mag.exists():
            errors.append("index.latest file missing")
        else:
            errors.extend(validate_magazine(mag))
            latest_copy = ROOT / "data" / "magazine" / "latest.json"
            if latest_copy.exists() and latest_copy.read_text(encoding="utf-8") != mag.read_text(encoding="utf-8"):
                errors.append("latest.json does not match dated edition")
        errors.extend(validate_magazine_archive(ROOT / "data" / "magazine"))
    research = ROOT / "research" / "magazine"
    if research.is_dir():
        errors.extend(validate_magazine_research(research))
    kaist = ROOT / "data" / "kaist-menu" / "latest.json"
    if kaist.exists():
        errors.extend(validate_kaist(kaist))
    if (ROOT / "data" / "kaist-menu").is_dir():
        errors.extend(validate_kaist_dir(ROOT / "data" / "kaist-menu"))
    ggongbab = ROOT / "data" / "ggongbab" / "latest.json"
    news = ROOT / "data" / "ggongbab" / "news.json"
    if news.exists():
        from ggongbab.food_news import validate_news_payload
        try:
            errors.extend(validate_news_payload(load(news)))
        except (ValueError, TypeError):
            errors.append("news JSON invalid (values suppressed)")
    if ggongbab.exists():
        errors.extend(validate_ggongbab(ggongbab))
    # Past listings are optional until the first export writes them. The live/archive
    # overlap is checked when both are staged together (refresh_ggongbab.export).
    archive = ROOT / "data" / "ggongbab" / "archive" / "index.json"
    if archive.exists():
        errors.extend(validate_ggongbab_archive(archive))
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print("content validation ok")


if __name__ == "__main__":
    main()
