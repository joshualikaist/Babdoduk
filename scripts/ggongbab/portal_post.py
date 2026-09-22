"""POST evidence is memory-only. Templates require correlation and field approval."""
import copy
import json
import re
from urllib.parse import parse_qsl

from .portal_diagnostics import safe_key_name, safe_json_path, REDACTED, UNNAMEABLE


def leaves(body, prefix="", depth=0):
    if depth > 12 or not isinstance(body, dict):
        raise ValueError("unsupported body schema")
    for key, value in body.items():
        if safe_key_name(key) in (REDACTED, UNNAMEABLE):
            raise ValueError("unsafe body schema")
        path = prefix + "." + key if prefix else key
        if isinstance(value, dict):
            if not value:
                raise ValueError("empty nested object")
            yield from leaves(value, path, depth + 1)
        elif value is None or type(value) in (str, int, float, bool):
            yield path, value
        else:
            raise ValueError("unsupported body container")


def set_path(body, path, value):
    if not safe_json_path(path):
        raise ValueError("invalid body path")
    parts = path.split(".")
    target = body
    for part in parts[:-1]:
        target = target[part]
        if not isinstance(target, dict):
            raise ValueError("invalid body path")
    if parts[-1] not in target:
        raise ValueError("missing body path")
    target[parts[-1]] = value


def correlation_fields(body, prefix="", depth=0):
    """Safe scalar subset for evidence; omitted fields still block full replay."""
    if depth > 12 or not isinstance(body, dict):
        return
    for key, value in list(body.items())[:100]:
        if safe_key_name(key) in (REDACTED, UNNAMEABLE):
            continue
        path = prefix + "." + key if prefix else key
        if isinstance(value, dict):
            yield from correlation_fields(value, path, depth + 1)
        elif type(value) in (str, int):
            yield path, value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate body key")
        result[key] = value
    return result


def read_body(request, diagnostics):
    """Read only Content-Type and POST data; never read cookie/auth headers."""
    try:
        mime = request.header_value("content-type").split(";", 1)[0].strip().lower()
        if mime not in ("application/json", "application/x-www-form-urlencoded"):
            raise ValueError("unsupported body encoding")
        raw = request.post_data
        if not isinstance(raw, str) or len(raw) > 262144:
            raise ValueError("unsupported body size")
        body = (json.loads(raw, object_pairs_hook=_unique_object) if mime == "application/json"
                else _unique_object(parse_qsl(raw, keep_blank_values=True, max_num_fields=100)))
        if not isinstance(body, dict):
            raise ValueError("unsupported body schema")
        kind = "json" if mime == "application/json" else "form"
        diagnostics.note_post_schema(body)
        # Correlation may inspect safe ID fields even if a credential field is
        # also present. body_template uses strict leaves() and refuses replay;
        # it never silently drops those credential fields from a request.
        fields = list(correlation_fields(body))
        if len(fields) > 100:
            raise ValueError("body schema too large")
        return kind, body
    except Exception:
        diagnostics.rejected["POST body unsupported"] += 1
        return "", None


def structural_primitive(value):
    from .portal_discovery import structural_value_ok
    if type(value) is bool or value is None:
        return True
    if type(value) is int:
        return abs(value) <= 1000000
    return (isinstance(value, str) and (value == "" or structural_value_ok("field", value))
            and not re.fullmatch(r"[0-9a-fA-F]{16,}", value)
            and not (len(value) >= 20 and re.search(r"[a-zA-Z]", value) and re.search(r"\d", value)))


def body_template(calls, *, id_path="", approved=(), dynamic_path=""):
    """Return a safe template or None. Approval alone never validates a value."""
    if not calls or any(r.get("_method") != "POST" or r.get("_body_type") not in ("json", "form") for r in calls):
        return None
    try:
        fields = [dict(leaves(r["_request_body"])) for r in calls]
        if any(set(f) != set(fields[0]) for f in fields) or len({r["_body_type"] for r in calls}) != 1:
            return None
        template = copy.deepcopy(calls[0]["_request_body"])
        for path, value in fields[0].items():
            if path == id_path:
                if any(type(f[path]) is not type(value) for f in fields):
                    return None
                set_path(template, path, "{id}")
            elif path == dynamic_path:
                # Pagination evidence is validated separately; persist only its initial value.
                if not structural_primitive(value):
                    return None
            elif (path not in approved or len(calls) < 2
                  or any(type(f[path]) is not type(value) or f[path] != value for f in fields)
                  or not structural_primitive(value)):
                return None
        return template
    except (ValueError, KeyError, TypeError):
        return None


def body_pagination(c, calls, diagnostics):
    """Only a selected notice list can reach here. Dates are never pagination."""
    from .portal_discovery import PAGE, CURSOR, at_path, walk, notice_date
    if len(calls) < 2:
        return ""
    first = dict(leaves(calls[0]["_request_body"]))
    for nxt in calls[1:]:
        other = dict(leaves(nxt["_request_body"]))
        changed = [p for p in first.keys() | other.keys() if first.get(p) != other.get(p)]
        for path in changed:
            if path.split(".")[-1] not in PAGE | CURSOR:
                diagnostics.note_post_filter(path)
        if len(changed) != 1 or calls[0]["_url"] != nxt["_url"]:
            continue
        path = changed[0]
        key = path.split(".")[-1]
        if key not in PAGE | CURSOR or path not in first or path not in other:
            continue
        a, b = first[path], other[path]
        numeric = type(a) in (int, str) and type(b) is type(a) and str(a).isdigit() and str(b).isdigit()
        diagnostics.note_post_pagination(path, numeric and int(b) > int(a))
        if key in PAGE and numeric:
            step = int(b) - int(a)
            mode = "offset" if key in ("offset", "start") else "page"
            expected = len(at_path(calls[0]["_payload"], c.list_array_path)) if mode == "offset" else 1
            if step != expected or step <= 0:
                continue
            c.pagination, c.page_step = mode, step
        elif key in CURSOR and a == "" and isinstance(b, str) and b:
            paths = [p for p, v in walk(calls[0]["_payload"]) if isinstance(v, str) and v == b]
            if len(paths) != 1:
                continue
            c.pagination, c.cursor_path = "cursor", paths[0]
        else:
            continue
        c.pagination_location, c.list_page_param = "body", path
        dates = [notice_date(row.get(c.list_date_key)) for call in (calls[0], nxt)
                 for row in at_path(call["_payload"], c.list_array_path)]
        c.list_date_descending = bool(c.list_date_key and dates and all(dates)
                                     and all(a >= b for a, b in zip(dates, dates[1:])))
        return path
    return ""
