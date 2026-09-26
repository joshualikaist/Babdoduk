# -*- coding: utf-8 -*-
"""Validate generated magazine / KAIST menu / ggongbab JSON before production push."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LANES = ("tips", "trend", "health", "habit")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def host(url: str) -> str:
    return urlparse(url or "").netloc.replace("www.", "")


def video_id(url: str) -> str:
    match = re.search(r"(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{11})", url or "")
    return match.group(1) if match else ""


def validate_magazine(path: Path) -> list[str]:
    errors = []
    data = load(path)
    if not data.get("date"):
        errors.append("magazine missing date")
    lanes = data.get("lanes") or {}
    for lane in LANES:
        if lane not in lanes:
            errors.append(f"missing lane {lane}")
            continue
        items = lanes[lane].get("items") or []
        if len(items) < 4:
            errors.append(f"{lane} has only {len(items)} items")
    featured = data.get("featured") or {}
    used_urls = set()
    used_vids = set()
    used_titles = set()
    feat_url = (featured.get("url") or "").split("?")[0].rstrip("/").lower()
    feat_title = featured.get("title") or ""
    for lane in LANES:
        sources = []
        for item in (lanes.get(lane) or {}).get("items") or []:
            title = item.get("title") or ""
            url = (item.get("url") or "").split("?")[0].rstrip("/").lower()
            vid = video_id(item.get("url") or "")
            src = item.get("source") or ""
            if title in used_titles:
                errors.append(f"duplicate title {title[:40]}")
            if url and url in used_urls:
                errors.append(f"duplicate url {url}")
            if vid and vid in used_vids:
                errors.append(f"duplicate video {vid}")
            if feat_title and title == feat_title:
                errors.append("featured repeated in lane " + lane)
            if feat_url and url and url == feat_url:
                errors.append("featured url repeated in lane " + lane)
            if src in sources and item.get("medium") == "youtube":
                errors.append(f"{lane} repeats youtube source {src}")
            sources.append(src)
            used_titles.add(title)
            if url:
                used_urls.add(url)
            if vid:
                used_vids.add(vid)
    trend = (lanes.get("trend") or {}).get("items") or []
    sources = {item.get("source") for item in trend if item.get("source")}
    if len(trend) >= 4 and len(sources) == 1:
        errors.append("trend is single-source-only")
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
    raw_text = json.dumps(data, ensure_ascii=False)
    if EMAIL_RE.search(raw_text):
        errors.append("ggongbab export contains an e-mail address")
    if PHONE_RE.search(raw_text):
        errors.append("ggongbab export contains a phone number")
    if SECRET_RE.search(raw_text):
        errors.append("ggongbab export contains a token-like string")
    if DOORAY_LINK_RE.search(raw_text):
        errors.append("ggongbab export contains a Dooray/private file link")
    _walk_keys(data, "$", errors)
    ids: set[str] = set()
    seen: list[tuple[str, str]] = []
    for idx, ev in enumerate(events):
        tag = f"events[{idx}]"
        if not isinstance(ev, dict):
            errors.append(f"{tag} not an object")
            continue
        eid = ev.get("id")
        if not eid or not isinstance(eid, str):
            errors.append(f"{tag} missing id")
        elif eid in ids:
            errors.append(f"{tag} duplicate id {eid}")
        else:
            ids.add(eid)
        if not (ev.get("title") or "").strip():
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
        url = reg.get("url") or ""
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{tag} registration.url invalid")
        deadline = _iso(reg.get("deadline")) if reg.get("deadline") else None
        if reg.get("deadline") and deadline is None:
            errors.append(f"{tag} registration.deadline not ISO")
        elif deadline is not None and deadline.utcoffset() != KST_OFFSET:
            errors.append(f"{tag} registration.deadline is not +09:00 (Asia/Seoul)")
        sources = ev.get("sources") or []
        if not sources:
            errors.append(f"{tag} has no sources")
        for src in sources:
            if src.get("type") not in GG_SOURCE_TYPES:
                errors.append(f"{tag} source type invalid")
            if set(src.keys()) - {"type", "name", "url"}:
                errors.append(f"{tag} source has unexpected keys")
        key_title = _norm_title(ev.get("title") or "")
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
GG_PUBLIC_URL_SOURCES = {"kaist_public", "manual"}


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
    raw_text = json.dumps(data, ensure_ascii=False)
    for pattern, label in ((EMAIL_RE, "an e-mail address"), (PHONE_RE, "a phone number"),
                           (SECRET_RE, "a token-like string"), (DOORAY_LINK_RE, "a Dooray/private file link")):
        if pattern.search(raw_text):
            errors.append(f"ggongbab archive contains {label}")
    _walk_keys(data, "$archive", errors)
    ids: set[str] = set()
    order: list[tuple[str, str]] = []
    for idx, ev in enumerate(events):
        tag = f"archive[{idx}]"
        if not isinstance(ev, dict):
            errors.append(f"{tag} not an object")
            continue
        eid = ev.get("id")
        if not eid or not isinstance(eid, str):
            errors.append(f"{tag} missing id")
        elif eid in ids:
            errors.append(f"{tag} duplicate id {eid}")
        else:
            ids.add(eid)
            if live_ids and eid in live_ids:
                errors.append(f"{tag} is also in the live feed")
        if not (ev.get("title") or "").strip():
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
            url = src.get("url") or ""
            if url:
                parsed = urlparse(url)
                if src.get("type") not in GG_PUBLIC_URL_SOURCES:
                    errors.append(f"{tag} exposes a {src.get('type')} source URL; only public notice links may be kept")
                elif parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    errors.append(f"{tag} source url invalid")
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
    kaist = ROOT / "data" / "kaist-menu" / "latest.json"
    if kaist.exists():
        errors.extend(validate_kaist(kaist))
    ggongbab = ROOT / "data" / "ggongbab" / "latest.json"
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
