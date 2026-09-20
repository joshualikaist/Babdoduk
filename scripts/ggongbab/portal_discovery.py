"""Discover exact JSON paths and replay templates. Payloads remain in memory."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date, datetime
from urllib.parse import parse_qsl, unquote, urlparse

from .portal_diagnostics import KEY, SENSITIVE, Diagnostics, safe_key_name
from .config import KST
from .ingest_marker import portal_external_key
from .portal_contract import PortalContract, ID_KEYS, TITLE_KEYS, DATE_KEYS, BODY_KEYS, pick_key

# KEY / SENSITIVE now live in portal_diagnostics so that the same rule governs
# what may be walked and what may be named in a log. Re-exported for callers.
PAGE = {"page", "pageNo", "pageIndex", "offset", "start"}
CURSOR = {"cursor", "nextCursor", "pageToken"}
NUMERIC = PAGE | {"size", "pageSize", "limit", "count"}
ENUMS = {"order": {"asc", "desc", "ASC", "DESC"},
         "direction": {"asc", "desc", "ASC", "DESC"},
         "sort": DATE_KEYS | TITLE_KEYS | ID_KEYS}
READ_KEYS = {"read", "unread", "isread", "isunread", "seen", "isseen", "readat",
             "readcount", "viewcount", "hitcount", "readyn", "readstatus"}
# A structural query value the local contract may keep: short, primitive, and
# plainly a URL identifier rather than a credential. Shape alone is not enough
# to authorize one - see allow_structural in request_shape().
STRUCTURAL_VALUE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def structural_value_ok(name, value):
    """Whether a query value is safe to persist, given its key was approved.

    Deliberately narrow. Anything long, punctuated or credential-shaped is
    refused, because a wrong yes here writes a secret into a contract file.
    """
    return bool(isinstance(value, str) and STRUCTURAL_VALUE.fullmatch(value)
                and not SENSITIVE.search(name) and not SENSITIVE.search(value))


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


def list_schema(payload, diagnostics=None):
    candidates = []
    for path, rows in walk(payload):
        if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(r, dict) for r in rows):
            continue
        common = set.intersection(*(set(r) for r in rows))
        id_key, title_key = pick_key(common, ID_KEYS), pick_key(common, TITLE_KEYS)
        if not id_key or not title_key:
            if diagnostics and any(k.lower() in ID_KEYS for k in common) and any(k.lower() in TITLE_KEYS for k in common):
                diagnostics.rejected["schema ambiguous"] += 1
                diagnostics.rejected["list schema ambiguous"] += 1
            continue
        ids = [stable_id(r[id_key]) for r in rows]
        if not all(ids) or len(set(ids)) < 2 or not all(isinstance(r[title_key], str) for r in rows):
            continue
        date_key = pick_key(common, DATE_KEYS)
        dates = [notice_date(r.get(date_key)) for r in rows] if date_key else []
        if not dates or not all(dates):
            date_key = ""
        candidates.append(dict(array=path, id=id_key, title=title_key, date=date_key))
    if diagnostics:
        diagnostics.counts["list-schema candidates"] += len(candidates)
        if len(candidates) > 1:
            diagnostics.rejected["schema ambiguous"] += 1
            diagnostics.rejected["list schema ambiguous"] += 1
    return candidates[0] if len(candidates) == 1 else None


_TOKENS = re.compile(r"[A-Z][a-z0-9]*|[a-z0-9]+")


def is_body_key(name):
    """Whether a field name denotes the record's own text.

    An exact BODY_KEYS name, or a compound whose LAST token is one, so that
    noticeBody and ntt_cont are found. A leading token is not enough:
    bodyClass and contentType are not text.

    Widening this is only safe because the body is now searched inside a
    correlated notice payload; a localization bundle never reaches it.
    """
    lowered = name.lower()
    if lowered in BODY_KEYS or lowered.replace("_", "") in BODY_KEYS:
        return True
    tokens = [t.lower() for t in _TOKENS.findall(name.replace("_", " "))]
    return bool(tokens) and tokens[-1] in BODY_KEYS


def stable_scalar(value):
    """A primitive usable for correlation. Booleans and containers are not."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    return str(value).strip()


def list_like_arrays(payload):
    """Every array of records, regardless of what its columns are called.

    A field-name whitelist is how the real endpoint gets missed: this portal may
    well call its title column nttSj. Names are consulted later, once
    correlation has proved which array is actually the notice list.
    """
    found = []
    for path, rows in walk(payload):
        if not isinstance(rows, list) or len(rows) < 2 or not all(isinstance(r, dict) for r in rows):
            continue
        common = set.intersection(*(set(r) for r in rows))
        keys = sorted(k for k in common
                      if isinstance(k, str) and KEY.fullmatch(k) and not SENSITIVE.search(k))
        if keys:
            found.append({"array": path, "keys": keys})
    return found


def key_like_columns(rows, keys):
    """Columns that behave like a primary key: present, scalar, unique per row."""
    columns = {}
    for key in keys:
        values = [stable_scalar(row.get(key)) for row in rows]
        if all(values) and len(set(values)) == len(values):
            columns[key] = values
    return columns


def url_identifiers(url):
    """Values the request itself carried: path segments and query values.

    This is the interaction evidence. A person who opened notice B fetched a URL
    containing B's identifier; a localization file and an unopened calendar
    widget carry no such value.
    """
    parsed = urlparse(url)
    values = [unquote(part).strip() for part in parsed.path.split("/")]
    values += [value.strip() for _name, value in parse_qsl(parsed.query, keep_blank_values=True)]
    return [value for value in dict.fromkeys(values) if value]


def scalar_paths(payload, value):
    """Static JSON paths holding exactly this scalar. Memory only."""
    return [path for path, found in walk(payload) if stable_scalar(found) == value]


def list_identity(row):
    parsed = urlparse(row["_url"])
    return parsed.netloc, parsed.path, row.get("_method", "GET")


def correlate_interactions(lists, details):
    """Group evidence that a list row and an opened detail are the same notice.

    Three things must line up for one observation to count:
      1. the detail REQUEST carried a value (path segment or query value),
      2. that value sits at exactly one path inside the detail payload,
      3. that value is the unique value of one column of one list array.

    A calendar widget nobody opened satisfies none of them; a localization file
    has no such identifier at all. Raw values never leave this function - the
    returned evidence holds salted hashes and counts.
    """
    groups = {}
    for detail in details:
        payload = detail["_payload"]
        sources = [(v, "", "url", "string") for v in url_identifiers(detail["_url"])]
        if detail.get("_method") == "POST" and detail.get("_body_type"):
            from .portal_post import correlation_fields
            try:
                fields = list(correlation_fields(detail["_request_body"]))
                sources += [(stable_scalar(v), p, "post-body", "int" if type(v) is int else "string")
                            for p, v in fields if stable_scalar(v)
                            and sum(stable_scalar(x) == stable_scalar(v) for _, x in fields) == 1]
            except ValueError:
                pass
        for value, request_id_path, via, id_type in sources:
            paths = scalar_paths(payload, value)
            if len(paths) != 1:
                continue
            id_path = paths[0]
            shape = request_shape(detail["_url"], value)
            if not shape or (not request_id_path and not ("{id}" in shape[1] or "{id}" in shape[2].values())):
                continue
            for listing_row in lists:
                for array in list_like_arrays(listing_row["_payload"]):
                    rows = at_path(listing_row["_payload"], array["array"])
                    for key, values in key_like_columns(rows, array["keys"]).items():
                        if values.count(value) != 1:
                            continue
                        group = (list_identity(listing_row), array["array"], key,
                                 shape[0], shape[1], tuple(sorted(shape[2].items())), id_path,
                                 detail.get("_method", "GET"), detail.get("_body_type", ""), request_id_path, id_type)
                        entry = groups.setdefault(
                            group, {"hashes": set(), "details": [], "pairs": 0, "url": 0, "post-body": 0})
                        entry["pairs"] += 1
                        entry[via] += 1
                        entry["hashes"].add(portal_external_key(value))
                        if all(seen is not detail for seen in entry["details"]):
                            entry["details"].append(detail)
    return groups


def classify_observed(method, url, status, payload, *, diagnostics=None, diagnostic_only=False):
    if not 200 <= status < 300:
        if diagnostics:
            diagnostics.rejected["status unsupported"] += 1
        return None
    if method != "GET" and not diagnostic_only:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    # Name-based schema detection is kept for diagnostics, but it no longer
    # decides what is a notice list: correlation does (see build_discovery).
    schema = list_schema(payload, diagnostics)
    arrays = list_like_arrays(payload)
    bodies = [p for p, v in walk(payload)
              if is_body_key(p.split(".")[-1]) and isinstance(v, str) and v.strip()]
    if diagnostics:
        diagnostics.counts["list-like JSON candidates"] += int(bool(arrays))
        diagnostics.counts["detail-like JSON candidates"] += int(not arrays)
        if bodies:
            diagnostics.counts["detail-schema candidates"] += int(not schema)
    if not arrays and not any(stable_scalar(v) for _p, v in walk(payload)):
        return None
    # A payload with several body fields is kept rather than dropped: only a
    # correlated notice id can say which of them is this notice's own text.
    return {"kind": "list" if arrays else "detail", "_method": method, "_url": url,
            "_payload": payload, "_schema": schema, "_arrays": arrays,
            "_body": bodies[0] if len(bodies) == 1 else "",
            "_bodies": [] if arrays else list(bodies)}


PATH_PART = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}(?:\.(?:json|do|php))?")


def path_template(url, identifier=""):
    """(template, unsafe_component_count) for a URL path.

    Split out of request_shape so that diagnostics can name a safe path even
    when the QUERY is what blocked the contract. Returns ("", n) when any
    component is opaque, so an unsafe path is never printed at all.
    """
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/")]
    if identifier:
        parts = ["{id}" if p == identifier else p for p in parts]
    unsafe = 0
    for part in parts:
        if part in ("", "{id}"):
            continue
        if not PATH_PART.fullmatch(part) or SENSITIVE.search(part):
            unsafe += 1
    return ("" if unsafe else "/".join(parts)), unsafe


def body_path_in_id_subtree(id_path, body_paths):
    """The body field sharing the closest object subtree with the verified id.

    Walking outward from the object that holds the matched notice id, the first
    level containing exactly one body candidate is structural evidence that the
    field belongs to this notice. Two candidates at that level stay ambiguous:
    choosing by key name or by string length would be a guess, and a wrong guess
    publishes the wrong text.
    """
    if not id_path or not body_paths:
        return ""
    segments = id_path.split(".")
    # Nearest ancestor first (the object holding the id), then widen.
    for depth in range(len(segments) - 1, -1, -1):
        prefix = segments[:depth]
        scope = [p for p in body_paths if p.split(".")[:depth] == prefix]
        if len(scope) == 1:
            return scope[0]
        if len(scope) > 1:
            return ""
    return ""


def request_shape(url, identifier="", cursor_param="", diagnostics=None, allow_structural=()):
    """Generalize a URL into a replay template, or refuse.

    `allow_structural` is an explicit, operator-supplied set of query key names.
    Nothing is added to it by observation: seeing a key repeatedly proves the
    page uses it, not that we understand what it selects.
    """
    def reject(counter=None, count=1):
        if diagnostics:
            diagnostics.rejected["unsafe request shape"] += 1
            if counter:
                diagnostics.rejected[counter] += count
        return None

    def unsafe_key(name):
        if diagnostics:
            diagnostics.note_unsafe_query_key(name)

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        return reject()
    template, unsafe_parts = path_template(url, identifier)
    if unsafe_parts:
        return reject("unsafe path component count", unsafe_parts)
    parts = template.split("/")
    query = {}
    unsafe_keys = 0
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if name in query:
            unsafe_keys += 1
            unsafe_key(name)
            continue
        if identifier and value == identifier and name.lower() in ID_KEYS:
            query[name] = "{id}"
        elif name == cursor_param and name in CURSOR:
            # Initial cursor must be empty/absent. Never save a response cursor value.
            if value:
                unsafe_keys += 1
                unsafe_key(name)
                continue
            query[name] = ""
        elif name in NUMERIC and value.isdigit() and len(value) <= 6:
            query[name] = value
        elif name in ENUMS and value in ENUMS[name]:
            query[name] = value
        elif name in allow_structural and structural_value_ok(name, value):
            # Approved by an operator who read the diagnostic key name, and the
            # value still has to look like a plain identifier.
            query[name] = value
        else:
            unsafe_keys += 1
            unsafe_key(name)
    if unsafe_keys:
        return reject("unsafe query key count", unsafe_keys)
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


def _query_of(row):
    return dict(parse_qsl(urlparse(row["_url"]).query, keep_blank_values=True))


def analyse_list_queries(lists, diagnostics):
    """Name which query keys vary and which stay put, never what they hold.

    A key that changes between two calls of the SAME endpoint is a pagination
    *candidate*; a key that never changes is a structural *candidate*. Both are
    reported for a human to read. Neither is authorized here: observing that a
    page increments something does not tell us what it selects.
    """
    if not diagnostics or len(lists) < 2:
        return
    queries = [_query_of(row) for row in lists]
    names = {name for query in queries for name in query}
    for name in sorted(names):
        seen = [query.get(name) for query in queries]
        present = [v for v in seen if v is not None]
        changes = len(set(seen)) > 1
        if not changes:
            diagnostics.note_static_structural_key(name)
            continue
        digits = [v for v in present if v.isdigit()]
        numeric_monotonic = (len(digits) == len(present) and len(digits) > 1
                             and all(int(a) < int(b) for a, b in zip(digits, digits[1:])))
        diagnostics.note_pagination_candidate(
            name, changes=True, numeric_monotonic=numeric_monotonic,
            opaque_changing=not numeric_monotonic)


def build_discovery(rows, start_url, diagnostics=None, allow_structural=(), approve_post=()):
    """Select the notice list/detail by what a person actually opened.

    Field names are not evidence. A calendar widget has rows with an id, a title
    and a date; a localization bundle has fields called content and text. Both
    satisfy every name heuristic and neither is a notice. What separates the
    real endpoints is the interaction: a row value the person clicked reappears
    inside the detail payload that was then fetched.

    One correlated id identifies the LIST. Two distinct ones are required before
    any DETAIL request template is authorized.
    """
    d = diagnostics or Diagnostics()
    reasons = []

    def finish(reason=None):
        if d.body_ambiguity_unresolved and "DETAIL_BODY_PATH_AMBIGUOUS" not in reasons:
            reasons.append("DETAIL_BODY_PATH_AMBIGUOUS")
        if reason and reason not in reasons:
            reasons.append(reason)
        report["reasons"] = list(dict.fromkeys(reasons))
        report["diagnostics"] = d.export()
        return report

    report = {"version": 2, "listEndpointObserved": False, "detailEndpointObserved": False,
              "paginationVerified": False, "paginationParameterObserved": False,
              "listReplayable": False, "detailReplayable": False, "contract": None}

    def eligible(row):
        return (row.get("_method", "GET") == "GET" or
                (row.get("_method") == "POST" and bool(row.get("_body_type")))) and row.get("_resource", "xhr") in ("xhr", "fetch")

    observed_lists = [r for r in rows if r["kind"] == "list"]
    observed_details = [r for r in rows if r["kind"] == "detail"]
    if diagnostics is None:
        # Direct builders have classified observations, but no transport totals.
        d.counts["list-schema candidates"] = sum(1 for r in observed_lists if r.get("_schema"))
        d.counts["detail-schema candidates"] = sum(1 for r in observed_details if r.get("_bodies"))
        d.counts["list-like JSON candidates"] = len(observed_lists)
        d.counts["detail-like JSON candidates"] = len(observed_details)
    report["listEndpointObserved"] = bool(observed_lists)
    report["detailEndpointObserved"] = bool(observed_details)
    lists = [r for r in observed_lists if eligible(r)]
    details = [r for r in observed_details if eligible(r)]
    if any(not eligible(r) for r in observed_lists):
        reasons.append("OBSERVATION_ONLY_LIST")
    if any(not eligible(r) for r in observed_details):
        reasons.append("OBSERVATION_ONLY_DETAIL")
    if not lists:
        return finish("NO_REPLAYABLE_LIST_CANDIDATE" if observed_lists else "NO_LIST_CANDIDATE")

    # ---- interaction correlation, before any field-name inference -----------
    groups = correlate_interactions(lists, details)
    d.counts["correlated via URL"] = sum(e["url"] for e in groups.values())
    d.counts["correlated via POST body"] = sum(e["post-body"] for e in groups.values())
    d.counts["correlated POST endpoints"] = len(
        {(g[3], g[4]) for g in groups if g[7] == "POST"}
        | {(g[0][0], g[0][1]) for g in groups if g[0][2] == "POST"})
    d.counts["correlated list/detail pairs"] = sum(e["pairs"] for e in groups.values())
    d.counts["correlated distinct ids"] = max((len(e["hashes"]) for e in groups.values()), default=0)
    list_host = urlparse(lists[0]["_url"]).netloc
    for detail in details:
        # A value the request carried that sits at several paths cannot name the
        # notice; report that separately from "nothing correlated at all".
        if any(len(scalar_paths(detail["_payload"], value)) > 1
               for value in url_identifiers(detail["_url"])):
            d.rejected["id path ambiguous"] += 1
            reasons.append("DETAIL_ID_PATH_AMBIGUOUS")
    if any(group[3] != list_host for group in groups):
        d.rejected["detail host mismatch"] += 1
        reasons.append("CROSS_ORIGIN_DETAIL")

    if not groups:
        d.rejected["list detail not correlated"] += 1
        if not details:
            reasons.append("NO_DETAIL_CANDIDATE")
        reasons.append("LIST_DETAIL_ID_NOT_CORRELATED")
        probe = lists[0]
        # Still name the endpoint that was observed, so the run is diagnosable.
        d.note_list_candidate(host=urlparse(probe["_url"]).netloc,
                              path=path_template(probe["_url"])[0],
                              query_keys=list(_query_of(probe)),
                              method=probe.get("_method", "GET"),
                              resource=probe.get("_resource", "xhr"))
        d.note_selected_list(correlated=False)
        d.note_selected_detail(correlated=False)
        # Name the unreplayable query keys, but NOT as pagination: pagination is
        # only meaningful once we know which endpoint is the notice list.
        if not request_shape(probe["_url"], diagnostics=d, allow_structural=allow_structural):
            reasons.append("UNSAFE_REQUEST_SHAPE")
        return finish()

    # The list is identified by (endpoint, array, id column). Competing answers
    # to that question are not ranked; a second, focused discovery is needed.
    list_keys = {group[:3] for group in groups}
    if len(list_keys) != 1:
        d.rejected["multiple correlated shapes"] += len(list_keys)
        d.note_selected_list(correlated=False)
        d.note_selected_detail(correlated=False)
        return finish("MULTIPLE_CORRELATED_NOTICE_SHAPES")
    list_ident, array_path, id_key = next(iter(list_keys))
    selected_lists = [r for r in lists if list_identity(r) == list_ident]
    first = selected_lists[0]

    # ---- the notice list is known; only now may names be consulted ----------
    row_keys = next((a["keys"] for a in list_like_arrays(first["_payload"])
                     if a["array"] == array_path), [])
    d.note_row_keys(row_keys)
    title_key = pick_key(row_keys, TITLE_KEYS)
    date_key = pick_key(row_keys, DATE_KEYS)
    if date_key:
        dates = [notice_date(r.get(date_key)) for call in selected_lists
                 for r in at_path(call["_payload"], array_path)]
        if not dates or not all(dates):
            date_key = ""
    d.note_selected_list(correlated=True, path=path_template(first["_url"])[0],
                         array_path=array_path, row_keys=row_keys, id_key=id_key,
                         title_key=title_key, date_key=date_key)

    d.selected_list["method"] = first.get("_method", "GET")

    # ---- detail: two distinct ids, one request template ---------------------
    verified = {key: entry for key, entry in groups.items() if len(entry["hashes"]) >= 2}
    if len(groups) > 1:
        d.rejected["multiple detail shapes"] += len(groups)
        reasons.append("MULTIPLE_DETAIL_SHAPES")
    if not verified:
        d.rejected["same id repeated"] += 1
        reasons.append("NOT_ENOUGH_DISTINCT_DETAILS")
    # A single observation is reported accurately, but cannot pass detail_ready().
    selected = verified if verified else groups
    body_path, id_path, detail_group, evidence = "", "", None, None
    if len(selected) == 1:
        detail_group, evidence = next(iter(selected.items()))
        id_path = detail_group[6]
        body_paths, candidates = set(), []
        for detail in evidence["details"]:
            # Only a correlated payload is searched. A localization bundle never
            # reaches this point, so its "content" field cannot become a body.
            bodies = [p for p, v in walk(detail["_payload"])
                      if is_body_key(p.split(".")[-1]) and isinstance(v, str) and v.strip()]
            candidates.extend(bodies)
            chosen = bodies[0] if len(bodies) == 1 else body_path_in_id_subtree(id_path, bodies)
            if len(bodies) > 1:
                d.rejected["body path ambiguous"] += 1
                for path in bodies:
                    d.note_body_candidate_path(path)
                if chosen:
                    d.body_disambiguated_by_id = True
                    d.body_ambiguity_resolved += 1
            body_paths.add(chosen)
        body_path = body_paths.pop() if len(body_paths) == 1 else ""
        d.note_selected_detail(correlated=True, path=detail_group[4], id_path=id_path,
                               body_candidates=candidates, body_path=body_path)
        d.selected_detail["method"] = detail_group[7]
        d.selected_detail["requestIdPath"] = detail_group[9]
        if not body_path:
            d.rejected["detail shape rejected"] += 1
            if len(set(candidates)) > 1:
                reasons.append("DETAIL_BODY_PATH_AMBIGUOUS")
            else:
                reasons.append("DETAIL_BODY_PATH_NOT_FOUND")
    else:
        d.note_selected_detail(correlated=False)

    # ---- list replay shape, and only now pagination -------------------------
    cursor_names = [k for k, _ in parse_qsl(urlparse(first["_url"]).query, keep_blank_values=True)
                    if k in CURSOR]
    d.note_list_candidate(host=urlparse(first["_url"]).netloc,
                          path=path_template(first["_url"])[0],
                          query_keys=list(_query_of(first)),
                          method=first.get("_method", "GET"),
                          resource=first.get("_resource", "xhr"))
    analyse_list_queries(selected_lists, d)
    page_parameter_seen = any(k in PAGE | CURSOR for row in selected_lists
                              for k, _ in parse_qsl(urlparse(row["_url"]).query, keep_blank_values=True))
    report["paginationParameterObserved"] = page_parameter_seen
    d.counts["pagination parameter observed"] = int(page_parameter_seen)
    shape = request_shape(first["_url"], cursor_param=cursor_names[0] if len(cursor_names) == 1 else "",
                          diagnostics=d, allow_structural=allow_structural)
    if not shape:
        return finish("UNSAFE_REQUEST_SHAPE")
    host, path, query = shape
    # Dedicated Portal discovery never authorizes a request to an unrelated host.
    if host != urlparse(start_url).netloc:
        return finish("CROSS_ORIGIN_LIST")
    if not title_key:
        d.rejected["title field unknown"] += 1
        reasons.append("NOTICE_LIST_CORRELATED_BUT_TITLE_FIELD_UNKNOWN")
    if not date_key:
        d.rejected["date field unknown"] += 1

    c = PortalContract(start_url=start_url, list_method=first.get("_method", "GET"), list_host=host, list_path=path,
                       list_query=query, list_array_path=array_path, list_id_key=id_key,
                       list_title_key=title_key, list_date_key=date_key)
    _pagination(c, selected_lists)
    from .portal_post import body_template, body_pagination, leaves
    if c.list_method == "POST":
        if len({h for e in groups.values() for h in e["hashes"]}) < 2 or not verified:
            return finish("POST_REQUIRES_TWO_DISTINCT_DETAILS")
        c.list_body_type = first["_body_type"]
        try:
            body_page_keys = [p for r in selected_lists for p, _ in leaves(r["_request_body"])
                              if p.split(".")[-1] in PAGE | CURSOR]
            body_page = body_pagination(c, selected_lists, d)
        except (ValueError, TypeError):
            return finish("POST_BODY_TEMPLATE_UNSAFE")
        report["paginationParameterObserved"] |= bool(body_page_keys)
        d.counts["pagination parameter observed"] = int(report["paginationParameterObserved"])
        if body_page_keys and not body_page:
            return finish("PAGINATION_NOT_VERIFIED")
        if body_page and any(k in PAGE | CURSOR for k in query):
            return finish("MULTIPLE_PAGINATION_MECHANISMS")
        template = body_template(selected_lists, approved=[p[5:] for p in approve_post if p.startswith("list:")],
                                 dynamic_path=body_page)
        if template is None:
            return finish("POST_STATIC_FIELDS_REQUIRE_APPROVAL_OR_VALIDATION")
        c.list_body = template
        c.list_post_evidence = sorted(next(iter(verified.values()))["hashes"])
    if any(k in PAGE | CURSOR for k in query) and c.pagination == "none":
        d.rejected["pagination unverified"] += 1
        return finish("PAGINATION_NOT_VERIFIED")
    report["listReplayable"] = c.list_ready()
    if report["listReplayable"]:
        d.counts["replayable list candidates"] += len(selected_lists)
    d.counts["pagination progression observed"] += int(c.pagination != "none")

    if detail_group and body_path and detail_group[3] == host:
        c.detail_method, c.detail_host, c.detail_path = detail_group[7], detail_group[3], detail_group[4]
        c.detail_query = dict(detail_group[5])
        if c.detail_method == "POST":
            c.detail_body_type, c.detail_request_id_path = detail_group[8], detail_group[9]
            c.detail_request_id_type = detail_group[10]
            template = body_template(evidence["details"], id_path=c.detail_request_id_path,
                                     approved=[p[7:] for p in approve_post if p.startswith("detail:")])
            if template is None:
                reasons.append("POST_STATIC_FIELDS_REQUIRE_APPROVAL_OR_VALIDATION")
            else:
                c.detail_body = template
                c.detail_post_evidence = sorted(evidence["hashes"])
        c.detail_body_path, c.detail_id_path = body_path, id_path
        c.detail_id_hashes = sorted(evidence["hashes"])
        c.detail_verified_count = len(c.detail_id_hashes)
        d.counts["replayable detail candidates"] += len(evidence["details"])
        state = any(has_read_state(r["_payload"]) for r in evidence["details"] + selected_lists)
        c.detail_state = "requires-semantics-review" if state else "no-read-state-observed"
        if state:
            reasons.append("DETAIL_STATE_REVIEW_REQUIRED")
    report.update(detailReplayable=c.detail_ready(),
                  paginationVerified=c.pagination != "none", contract=asdict(c))
    return finish()
