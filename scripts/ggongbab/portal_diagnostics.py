"""Value-free Portal diagnostics. Only fixed counter/reason names are exported.

Beyond counters this module carries a small amount of *structural* metadata:
query key names, JSON paths, host and method. None of it is derived from a
notice. A key name says which knob the page turned; a key value could be a
notice id, a board a person reads, or a credential, so values never enter.
"""
from collections import Counter
import re
from urllib.parse import urlparse

# A query/JSON key we are willing to name in a log or debug file. Anything with
# punctuation, spacing or unusual length is reported as a placeholder instead:
# a key name we cannot vouch for is not worth printing.
KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# Keys whose NAME alone suggests a credential. These are redacted even though
# only the name would be shown, because a name like "sso_session_token" already
# describes the account's authentication scheme.
SENSITIVE = re.compile(
    r"token|auth|session|cookie|password|passwd|pwd|secret|jwt|credential"
    r"|apikey|bearer|signature|nonce|otp", re.I)

REDACTED = "<sensitive>"
UNNAMEABLE = "<unnameable>"
# Bounds so that a hostile or merely odd page cannot turn diagnostics into a
# dump. Twenty names is far more than a real endpoint uses.
MAX_KEYS = 20
MAX_PATHS = 20
MAX_PATH_SEGMENTS = 12

COUNTS = (
    "total responses", "xhr/fetch responses", "document responses", "other responses",
    "same-host responses", "kaist-host responses", "json-parsed responses",
    "GET responses", "POST responses", "list-schema candidates", "detail-schema candidates",
    "replayable list candidates", "replayable detail candidates",
    "observed notice-like POST candidate", "pagination parameter observed",
    "pagination progression observed",
    # Interaction correlation: what the person actually opened.
    "list-like JSON candidates", "detail-like JSON candidates",
    "correlated list/detail pairs", "correlated distinct ids",
    "correlated via URL", "correlated via POST body", "correlated POST endpoints",
)
REJECTED = (
    "host mismatch", "method unsupported", "json parse failed", "schema ambiguous",
    "unsafe request shape", "unsafe query key count", "unsafe path component count",
    "multiple list identities", "pagination unverified", "detail shape rejected",
    "detail host mismatch", "body path ambiguous", "id path ambiguous", "id path missing",
    "same id repeated", "multiple detail shapes", "resource unsupported", "status unsupported",
    "observer errors", "list schema ambiguous",
    "list detail not correlated", "multiple correlated shapes",
    "title field unknown", "date field unknown",
    "POST body unsupported",
)


def safe_key_name(name):
    """A query/JSON key name that is safe to print, or a placeholder.

    Never returns anything derived from a value.
    """
    if not isinstance(name, str) or not KEY.fullmatch(name):
        return UNNAMEABLE
    if SENSITIVE.search(name):
        return REDACTED
    return name


def safe_json_path(path):
    """A dotted JSON path, or "" when any segment is not a plain static key.

    walk() already refuses dynamic keys, but a path reaching a debug file is
    checked again here rather than trusted.
    """
    if not isinstance(path, str) or not path:
        return ""
    segments = path.split(".")
    if len(segments) > MAX_PATH_SEGMENTS:
        return ""
    for segment in segments:
        if segment == "$":
            continue
        if not KEY.fullmatch(segment) or SENSITIVE.search(segment):
            return ""
    return path


def _add(target, value, limit):
    if value and value not in target and len(target) < limit:
        target.append(value)


class Diagnostics:
    def __init__(self):
        self.counts = Counter({key: 0 for key in COUNTS})
        self.rejected = Counter({key: 0 for key in REJECTED})
        # Names and shapes only; see the module docstring.
        self.unsafe_query_keys = []
        self.list_candidate = {}
        self.pagination_candidates = []
        self.static_structural_keys = []
        self.detail_body_candidate_paths = []
        self.body_disambiguated_by_id = False
        # An ambiguous body response is only a blocker while it stays
        # unresolved; the verified notice id can still single one path out.
        self.body_ambiguity_resolved = 0
        self.selected_list = {}
        self.selected_detail = {}
        self.row_keys = []
        self.post_scalar_paths = []
        self.post_keys = []
        self.post_pagination = []
        self.post_filters = []

    def note_post_schema(self, body, prefix="", depth=0):
        if depth > MAX_PATH_SEGMENTS or not isinstance(body, dict):
            return
        for key, value in list(body.items())[:MAX_KEYS]:
            name = safe_key_name(key)
            if name == UNNAMEABLE:
                continue
            _add(self.post_keys, name, MAX_KEYS)
            if name == REDACTED:
                _add(self.post_scalar_paths, REDACTED, MAX_PATHS)
                continue
            path = prefix + "." + name if prefix else name
            if isinstance(value, dict):
                self.note_post_schema(value, path, depth + 1)
            elif value is None or type(value) in (str, int, float, bool):
                _add(self.post_scalar_paths, safe_json_path(path), MAX_PATHS)

    def note_post_pagination(self, path, monotonic):
        if safe_json_path(path) and len(self.post_pagination) < MAX_PATHS:
            row = {"path": path, "numericMonotonic": bool(monotonic)}
            if row not in self.post_pagination:
                self.post_pagination.append(row)

    def note_post_filter(self, path):
        _add(self.post_filters, safe_json_path(path), MAX_PATHS)

    @property
    def body_ambiguity_unresolved(self):
        return max(0, int(self.rejected["body path ambiguous"]) - self.body_ambiguity_resolved)

    # -- recorders ---------------------------------------------------------
    def note_unsafe_query_key(self, name):
        """Record WHICH query key blocked the replay contract, never its value."""
        _add(self.unsafe_query_keys, safe_key_name(name), MAX_KEYS)

    def note_body_candidate_path(self, path):
        _add(self.detail_body_candidate_paths, safe_json_path(path), MAX_PATHS)

    def note_list_candidate(self, *, host, path, query_keys, method, resource):
        """Describe the observed list endpoint without any query value."""
        candidate = {"host": host if isinstance(host, str) else "",
                     "method": method if method in ("GET", "POST") else "",
                     "resourceType": resource if isinstance(resource, str) else "",
                     "queryKeys": []}
        # An unsafe path is omitted entirely rather than half-redacted: a
        # partially masked path still leaks its shape.
        candidate["templatedPath"] = path if isinstance(path, str) and path else ""
        for name in query_keys or ():
            _add(candidate["queryKeys"], safe_key_name(name), MAX_KEYS)
        self.list_candidate = candidate

    def note_pagination_candidate(self, name, *, changes, numeric_monotonic, opaque_changing):
        safe = safe_key_name(name)
        if not safe or len(self.pagination_candidates) >= MAX_KEYS:
            return
        if any(c["key"] == safe for c in self.pagination_candidates):
            return
        self.pagination_candidates.append({
            "key": safe,
            "changesBetweenListCalls": bool(changes),
            "numericMonotonic": bool(numeric_monotonic),
            "opaqueChanging": bool(opaque_changing),
        })

    def note_static_structural_key(self, name):
        _add(self.static_structural_keys, safe_key_name(name), MAX_KEYS)

    def note_row_keys(self, names):
        """Column names of the correlated list, so unknown schemas are readable.

        Portal field names are not guessable (nttSj, bbsNttSj, ...). Printing
        the names lets a human add support for them; printing the values would
        publish the notices.
        """
        self.row_keys = []
        for name in names or ():
            _add(self.row_keys, safe_key_name(name), MAX_KEYS)

    def note_selected_list(self, *, correlated, path="", array_path="", row_keys=(),
                           id_key="", title_key="", date_key=""):
        self.selected_list = {
            "correlated": bool(correlated),
            "candidatePath": path if isinstance(path, str) else "",
            "arrayPath": safe_json_path(array_path),
            "rowKeys": [safe_key_name(k) for k in list(row_keys)[:MAX_KEYS]],
            "idKey": safe_key_name(id_key) if id_key else "unknown",
            "titleKey": safe_key_name(title_key) if title_key else "unknown",
            "dateKey": safe_key_name(date_key) if date_key else "unknown",
        }

    def note_selected_detail(self, *, correlated, path="", id_path="",
                             body_candidates=(), body_path=""):
        self.selected_detail = {
            "correlated": bool(correlated),
            "candidatePath": path if isinstance(path, str) else "",
            "idPath": safe_json_path(id_path),
            "bodyCandidatePaths": list(dict.fromkeys(
                p for p in (safe_json_path(b) for b in body_candidates) if p))[:MAX_PATHS],
            "bodyPathSelected": safe_json_path(body_path) or "ambiguous",
        }

    # -- export ------------------------------------------------------------
    def export(self):
        # Allowlist prevents accidentally serializing payload-derived keys/values.
        return {"counts": {k: int(self.counts[k]) for k in COUNTS},
                "rejected": {k: int(self.rejected[k]) for k in REJECTED},
                "safe": self.export_safe()}

    def export_safe(self):
        """Structural metadata. Every string here is a name, a path or a host."""
        candidate = {}
        if self.list_candidate:
            candidate = {"host": self.list_candidate.get("host", ""),
                         "templatedPath": self.list_candidate.get("templatedPath", ""),
                         "queryKeys": list(self.list_candidate.get("queryKeys", [])),
                         "method": self.list_candidate.get("method", ""),
                         "resourceType": self.list_candidate.get("resourceType", "")}
        result = {
            "selectedList": dict(self.selected_list),
            "selectedDetail": dict(self.selected_detail),
            "rowKeys": list(self.row_keys),
            "unsafeQueryKeys": list(self.unsafe_query_keys),
            "listCandidate": candidate,
            "paginationCandidates": [dict(c) for c in self.pagination_candidates],
            "staticStructuralKeys": list(self.static_structural_keys),
            "detailBodyCandidatePaths": list(self.detail_body_candidate_paths),
            "bodyDisambiguatedByIdSubtree": bool(self.body_disambiguated_by_id),
        }
        if self.post_keys or self.post_scalar_paths or self.post_pagination or self.post_filters:
            result.update(postRequestKeys=list(self.post_keys), postRequestScalarPaths=list(self.post_scalar_paths),
                          postPaginationCandidates=list(self.post_pagination), postFilterPaths=list(self.post_filters))
        return result


def capture_response(response, expected_host, diagnostics):
    """Observe Portal/KAIST responses and memory-only JSON/form POST evidence."""
    from .portal_discovery import classify_observed
    d = diagnostics
    d.counts["total responses"] += 1
    req = response.request
    resource = req.resource_type
    bucket = "xhr/fetch" if resource in ("xhr", "fetch") else "document" if resource == "document" else "other"
    d.counts[bucket + " responses"] += 1
    method = req.method
    if method in ("GET", "POST"):
        d.counts[method + " responses"] += 1
    if method not in ("GET", "POST"):
        d.rejected["method unsupported"] += 1
    parsed = urlparse(response.url)
    same = parsed.netloc == expected_host
    host = (parsed.hostname or "").lower()
    kaist = host == "kaist.ac.kr" or host.endswith(".kaist.ac.kr")
    d.counts["same-host responses"] += int(same)
    d.counts["kaist-host responses"] += int(kaist)
    if not same:
        d.rejected["host mismatch"] += 1
    if not same and not kaist:
        return None
    try:
        payload = response.json()  # Discovery intentionally ignores MIME.
    except Exception:
        d.rejected["json parse failed"] += 1
        return None
    d.counts["json-parsed responses"] += 1
    row = classify_observed(method, response.url, response.status, payload,
                            diagnostics=d, diagnostic_only=True)
    if row:
        row["_resource"] = resource
        if method == "POST":
            d.counts["observed notice-like POST candidate"] += 1
            from .portal_post import read_body
            row["_body_type"], row["_request_body"] = read_body(req, d)
            if not row["_body_type"]:
                d.rejected["method unsupported"] += 1
        if resource not in ("xhr", "fetch"):
            d.rejected["resource unsupported"] += 1
    return row
