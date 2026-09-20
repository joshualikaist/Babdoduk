"""Discover exact JSON paths and replay templates. Payloads remain in memory."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date, datetime
from urllib.parse import parse_qsl, unquote, urlparse

from .config import KST
from .ingest_marker import portal_external_key
from .portal_contract import PortalContract, ID_KEYS, TITLE_KEYS, DATE_KEYS, BODY_KEYS, pick_key

KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
SENSITIVE = re.compile(r"token|auth|session|cookie|password|secret|jwt", re.I)
PAGE = {"page", "pageNo", "pageIndex", "offset", "start"}
CURSOR = {"cursor", "nextCursor", "pageToken"}
NUMERIC = PAGE | {"size", "pageSize", "limit", "count"}
ENUMS = {"order": {"asc", "desc", "ASC", "DESC"},
         "direction": {"asc", "desc", "ASC", "DESC"},
         "sort": DATE_KEYS | TITLE_KEYS | ID_KEYS}
READ_KEYS = {"read", "unread", "isread", "isunread", "seen", "isseen", "readat",
             "readcount", "viewcount", "hitcount", "readyn", "readstatus"}


def at_path(payload, path):
    if path == "$":
        return payload
    if not path:
        return None
    for key in path.split("."):
        if not isinstance(payload, dict) or key not in payload:
            return None
        payload = payload[key]
    return payload


def notice_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return stamp.astimezone(KST).date() if stamp.tzinfo else stamp.date()
    except ValueError:
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None


def stable_id(value):
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value) else ""


def walk(payload, path="$"):
    """Discovery only. Never follow dynamic/unsafe object keys into persisted paths."""
    yield path, payload
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and KEY.fullmatch(key) and not SENSITIVE.search(key):
                yield from walk(value, key if path == "$" else path + "." + key)


def has_read_state(payload):
    if isinstance(payload, dict):
        return any(str(k).replace("_", "").lower() in READ_KEYS or has_read_state(v)
                   for k, v in payload.items())
    if isinstance(payload, list):
        return any(has_read_state(v) for v in payload)
    return False


def list_schema(payload):
    candidates = []
    for path, rows in walk(payload):
        if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(r, dict) for r in rows):
            continue
        common = set.intersection(*(set(r) for r in rows))
        id_key, title_key = pick_key(common, ID_KEYS), pick_key(common, TITLE_KEYS)
        if not id_key or not title_key:
            continue
        ids = [stable_id(r[id_key]) for r in rows]
        if not all(ids) or len(set(ids)) < 2 or not all(isinstance(r[title_key], str) for r in rows):
            continue
        date_key = pick_key(common, DATE_KEYS)
        dates = [notice_date(r.get(date_key)) for r in rows] if date_key else []
        if not dates or not all(dates):
            date_key = ""
        candidates.append(dict(array=path, id=id_key, title=title_key, date=date_key))
    return candidates[0] if len(candidates) == 1 else None


def classify_observed(method, url, status, payload):
    if method != "GET" or not 200 <= status < 300:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    schema = list_schema(payload)
    bodies = [p for p, v in walk(payload) if p.split(".")[-1].lower() in BODY_KEYS
              and isinstance(v, str) and v.strip()]
    if not schema and len(bodies) != 1:
        return None
    # These observations are never serialized directly.
    return {"kind": "list" if schema else "detail", "_url": url, "_payload": payload,
            "_schema": schema, "_body": bodies[0] if len(bodies) == 1 else ""}


def request_shape(url, identifier="", cursor_param=""):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        return None
    parts = [unquote(p) for p in parsed.path.split("/")]
    if identifier:
        parts = ["{id}" if p == identifier else p for p in parts]
    # Refuse opaque path values rather than persisting them or inventing replacements.
    for part in parts:
        if part in ("", "{id}"):
            continue
        if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}(?:\.(?:json|do|php))?", part)
                or SENSITIVE.search(part)):
            return None
    query = {}
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if name in query:
            return None
        if identifier and value == identifier and name.lower() in ID_KEYS:
            query[name] = "{id}"
        elif name == cursor_param and name in CURSOR:
            # Initial cursor must be empty/absent. Never save a response cursor value.
            if value:
                return None
            query[name] = ""
        elif name in NUMERIC and value.isdigit() and len(value) <= 6:
            query[name] = value
        elif name in ENUMS and value in ENUMS[name]:
            query[name] = value
        else:
            return None
    return parsed.netloc, "/".join(parts), query


def _pagination(c, calls):
    """Require two observed requests linked by a single pagination change."""
    first = calls[0]
    first_query = dict(parse_qsl(urlparse(first["_url"]).query, keep_blank_values=True))
    for nxt in calls[1:]:
        query = dict(parse_qsl(urlparse(nxt["_url"]).query, keep_blank_values=True))
        changed = {k for k in first_query.keys() | query.keys() if first_query.get(k) != query.get(k)}
        if len(changed) != 1:
            continue
        key = next(iter(changed))
        if key in PAGE and str(first_query.get(key, "")).isdigit() and str(query.get(key, "")).isdigit():
            step = int(query[key]) - int(first_query[key])
            # Page steps must be consecutive; offsets must equal the observed row count.
            mode = "offset" if key in {"offset", "start"} else "page"
            expected = len(at_path(first["_payload"], c.list_array_path)) if mode == "offset" else 1
            if step != expected or step <= 0:
                continue
            c.pagination, c.list_page_param, c.page_step = mode, key, step
        elif key in CURSOR and not first_query.get(key) and query.get(key):
            paths = [p for p, value in walk(first["_payload"])
                     if isinstance(value, str) and value == query[key]]
            if len(paths) != 1:
                continue
            c.pagination, c.list_page_param, c.cursor_path = "cursor", key, paths[0]
        else:
            continue
        dates = [notice_date(r.get(c.list_date_key)) for call in (first, nxt)
                 for r in at_path(call["_payload"], c.list_array_path)]
        c.list_date_descending = bool(c.list_date_key and all(dates)
                                     and all(a >= b for a, b in zip(dates, dates[1:])))
        return


def build_discovery(rows, start_url):
    report = {"version": 2, "listEndpointObserved": False, "detailEndpointObserved": False,
              "paginationVerified": False, "contract": None}
    lists = [r for r in rows if r["kind"] == "list"]
    if not lists:
        return report
    # Multiple incompatible lists require another, focused discovery, not ranking guesses.
    identities = {(urlparse(r["_url"]).netloc, urlparse(r["_url"]).path,
                   tuple(sorted(r["_schema"].items()))) for r in lists}
    if len(identities) != 1:
        return report
    first = lists[0]
    schema = first["_schema"]
    cursor_names = [k for k, _ in parse_qsl(urlparse(first["_url"]).query, keep_blank_values=True)
                    if k in CURSOR]
    shape = request_shape(first["_url"], cursor_param=cursor_names[0] if len(cursor_names) == 1 else "")
    if not shape:
        return report
    host, path, query = shape
    # Dedicated Portal discovery never authorizes a request to an unrelated host.
    if host != urlparse(start_url).netloc:
        return report
    c = PortalContract(start_url=start_url, list_method="GET", list_host=host, list_path=path,
                       list_query=query, list_array_path=schema["array"], list_id_key=schema["id"],
                       list_title_key=schema["title"], list_date_key=schema["date"])
    _pagination(c, lists)
    # A detected pagination parameter without a verified progression is not replayable.
    if any(k in PAGE | CURSOR for k in query) and c.pagination == "none":
        return report
    ids = {stable_id(r[c.list_id_key]) for call in lists for r in at_path(call["_payload"], c.list_array_path)}
    groups = {}
    for detail in (r for r in rows if r["kind"] == "detail"):
        matches = [(p, stable_id(v)) for p, v in walk(detail["_payload"])
                   if p.split(".")[-1].lower() in ID_KEYS and stable_id(v) in ids]
        if len(matches) != 1:
            continue
        id_path, identifier = matches[0]
        shape = request_shape(detail["_url"], identifier)
        if not shape or shape[0] != host or not ("{id}" in shape[1] or "{id}" in shape[2].values()):
            continue
        group = (shape[0], shape[1], tuple(sorted(shape[2].items())), detail["_body"], id_path)
        groups.setdefault(group, {"hashes": set(), "state": False})
        groups[group]["hashes"].add(portal_external_key(identifier))
        groups[group]["state"] |= has_read_state(detail["_payload"])
    verified = [(k, v) for k, v in groups.items() if len(v["hashes"]) >= 2]
    # Even a single observation is reported accurately, but cannot pass detail_ready().
    selected = verified if verified else list(groups.items())
    if len(selected) == 1:
        (host, path, query, body_path, id_path), evidence = selected[0]
        c.detail_method, c.detail_host, c.detail_path = "GET", host, path
        c.detail_query, c.detail_body_path, c.detail_id_path = dict(query), body_path, id_path
        c.detail_id_hashes = sorted(evidence["hashes"])
        c.detail_verified_count = len(c.detail_id_hashes)
        state = evidence["state"] or any(has_read_state(r["_payload"]) for r in lists)
        c.detail_state = "requires-semantics-review" if state else "no-read-state-observed"
    report.update(listEndpointObserved=True, detailEndpointObserved=bool(groups),
                  paginationVerified=c.pagination != "none", contract=asdict(c))
    return report
