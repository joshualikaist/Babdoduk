"""Passive alternative-source diagnostics. No fetch, navigation, or contract writes.

The existing detail response anchors the user's public-notice click. It is never
a candidate. Matching an alternative's shape does not prove absence of side effects.
"""
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qsl, unquote, urlparse

from .portal_contract import ID_KEYS, BODY_KEYS
from .portal_diagnostics import safe_key_name, REDACTED, UNNAMEABLE
from .portal_discovery import is_body_key
from .portal_known_schema import KNOWN_HOST, KNOWN_LIST_PATH, has_view_counter, scalar
from .web.exit_codes import AuthRequired

# Unknown URL segments are deliberately masked: an alphabetic segment can be an
# account ID/title too. These are display tokens, never endpoint guesses.
ROUTE_WORDS = {"wz", "api", "board", "boards", "notice", "notices", "post", "posts",
               "article", "articles", "detail", "details", "content", "body", "html", "json",
               "document", "documents", "preview", "render", "recents", "v1", "v2"}
FIELD_WORDS = ID_KEYS | BODY_KEYS | {"data", "result", "results", "response", "notice", "post",
                                   "article", "detail", "item", "record", "noticebody", "articlebody"}
EXCLUDED = re.compile(
    r"thumb|image|admin[/_-]?codes|collegeplan|localiz|locales?|i18n|l10n|bundle|"
    r"analytics|telemetry|tracking|beacon|readcount|viewcount|viewcnt|inqcnt|hitcount|hitcnt|"
    r"increment|increase|markread|markseen|mutation|update|delete|insert|create|"
    r"(?:^|/)(?:read|view|hit|track|assets|static)(?:/|$)|\.(?:png|jpg|jpeg|gif|svg|webp|js|css)$",
    re.I,
)
WINDOW_BEFORE, WINDOW_AFTER = 15, 30
MAX_RESPONSES, MAX_CANDIDATES = 200, 30


def excluded(value):
    return bool(EXCLUDED.search(value) or EXCLUDED.search(re.sub(r"[-_]", "", value)))


def template(url, identifier):
    parts = unquote(urlparse(url).path).split("/")
    return "/".join("{id}" if p == identifier else p if p.lower() in ROUTE_WORDS or not p else "{segment}"
                    for p in parts)


def display_path(path):
    return ".".join(p if p.lower() in FIELD_WORDS else "{key}" for p in path.split("."))


def json_evidence(payload):
    """Drop all text values immediately; retain only ID equality data in memory."""
    leaves = []
    stack = [("", payload, None, 0)]
    visited = 0
    while stack and visited < 2000:
        path, value, public, depth = stack.pop()
        visited += 1
        if depth > 12:
            continue
        if isinstance(value, dict):
            public = value.get("publicYn", public)
            for key, child in list(value.items())[:100]:
                if safe_key_name(key) in (REDACTED, UNNAMEABLE):
                    continue
                stack.append((path + "." + key if path else key, child, public, depth + 1))
        elif isinstance(value, (str, int)) and not isinstance(value, bool):
            leaves.append((path, value, public))
    bodies = [(p, public) for p, v, public in leaves if is_body_key(p.split(".")[-1]) and isinstance(v, str) and v.strip()]
    identifiers = [(p, scalar(v), public) for p, v, public in leaves if p.split(".")[-1].lower() in ID_KEYS and scalar(v)]
    result = []
    for path, value, public in identifiers:
        if sum(v == value for _, v, _ in identifiers) != 1:
            continue
        parent = path.rsplit(".", 1)[0] + "." if "." in path else ""
        own = [p for p, visible in bodies if p.startswith(parent) and visible in (None, "Y")]
        if len(own) == 1 and public in (None, "Y"):
            result.append((value, display_path(path), display_path(own[0])))
    # Request-bound JSON bodies without an echoed ID need a single unambiguous field.
    if not identifiers and len(bodies) == 1 and bodies[0][1] in (None, "Y"):
        result.append((None, "", display_path(bodies[0][0])))
    return result


class DocumentEvidence(HTMLParser):
    """Explicit notice containers or JSON script data; never execute JS or read DOM."""
    BODY_MARKERS = {"pstcn", "noticebody", "articlebody", "noticecontent", "articlecontent"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.bodies, self.embedded = [], set(), []
        self.stack = []
        self.script = None
        self.script_chunks = []
        self.private = False
        self.counter = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        name = attributes.get("name", "")
        if tag == "input" and name.lower() in ID_KEYS:
            value = scalar(attributes.get("value"))
            if value:
                self.ids.append((value, "html.input." + name))
        if tag == "input" and name == "publicYn" and attributes.get("value") != "Y":
            self.private = True
        marker = re.sub(r"[-_]", "", attributes.get("id", "")).lower()
        if marker in {"inqcnt", "viewcount", "readcount", "hitcount"}:
            self.counter = True
        body = marker if marker in self.BODY_MARKERS else ""
        if tag == "script":
            self.script = attributes.get("type", "") == "application/json"
            self.script_chunks = []
        if tag not in {"input", "br", "img", "meta", "link", "hr", "area", "source", "wbr"}:
            self.stack.append((tag, body))

    def handle_endtag(self, tag):
        if tag == "script":
            if self.script:
                try:
                    payload = json.loads("".join(self.script_chunks))
                    self.embedded.extend(json_evidence(payload))
                    self.counter |= has_view_counter(payload)
                except (ValueError, RecursionError):
                    pass
            self.script, self.script_chunks = None, []
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.script is not None:
            if self.script:
                self.script_chunks.append(data)
            return
        if data.strip():
            for _, marker in self.stack:
                if marker:
                    self.bodies.add("html.body." + marker)

    def evidence(self):
        if self.private:
            return []
        result = list(self.embedded)
        if len(self.bodies) == 1:
            body = next(iter(self.bodies))
            if len(self.ids) == 1:
                result.append((*self.ids[0], body))
            elif not self.ids:
                result.append((None, "", body))
        return result


class AlternativeObserver:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.total = 0
        self.known_seen = False
        self.pending, self.anchors, self.candidates = [], [], []

    def capture(self, response):
        self.total += 1
        try:
            self._capture(response)
        except Exception:
            # Browser errors may include full URLs, IDs, or response excerpts.
            return

    def _capture(self, response):
        request = response.request
        parsed = urlparse(response.url)
        if parsed.scheme != "https" or parsed.netloc != KNOWN_HOST or parsed.username or parsed.password:
            return
        path = unquote(parsed.path)
        prefix = KNOWN_LIST_PATH + "/"
        exact_known = path.startswith(prefix) and bool(path[len(prefix):]) and "/" not in path[len(prefix):].rstrip("/")
        if exact_known:
            self.known_seen = True
        if request.method != "GET" or not 200 <= response.status < 300:
            return
        page = request.frame.page  # No cross-tab or service-worker ID inference.
        stamp = self.clock()
        if exact_known:
            self.anchors = [a for a in self.anchors if a[0] is not page]
            payload = response.json()
            identifier = path[len(prefix):].rstrip("/")
            if (isinstance(payload, dict) and payload.get("publicYn") == "Y"
                    and scalar(payload.get("pstNo")) == identifier
                    and isinstance(payload.get("pstCn"), str) and payload["pstCn"].strip()):
                self.anchors.append((page, stamp, identifier))
                self.anchors = self.anchors[-20:]
                self._match()
            return  # The known endpoint is never an alternative.
        if (excluded(path)
                or request.resource_type in ("image", "stylesheet", "script", "font", "media")):
            return
        # Query values stay in memory; action parameters can signal mutations too.
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if any(excluded(k) or (k.lower() in {"action", "method", "operation", "cmd"} and excluded(v))
               for k, v in query):
            return
        resource = request.resource_type
        if resource not in ("xhr", "fetch", "document"):
            return
        try:
            payload = response.json()
            evidence, counter, response_type = json_evidence(payload), has_view_counter(payload), "JSON"
        except Exception:
            if resource != "document":
                return
            text = response.text()
            if len(text) > 2_000_000:
                return
            parser = DocumentEvidence()
            parser.feed(text)
            evidence, counter, response_type = parser.evidence(), parser.counter, "document"
        if not evidence:
            return
        # Retain only equality values + structural paths, never titles or bodies.
        self.pending.append((page, stamp, response.url, resource, response_type, evidence, counter))
        self.pending = [r for r in self.pending[-MAX_RESPONSES:] if stamp - r[1] <= WINDOW_AFTER + WINDOW_BEFORE]
        self._match()

    def _match(self):
        for page, stamp, url, resource, kind, evidence, counter in self.pending:
            parsed = urlparse(url)
            for anchor_page, clicked, identifier in self.anchors:
                if page is not anchor_page or not -WINDOW_BEFORE <= stamp - clicked <= WINDOW_AFTER:
                    continue
                for value, id_path, body_path in evidence:
                    request_path = ""
                    if value is None:
                        keys = [k for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                                if k.lower() in ID_KEYS and v == identifier]
                        if len(keys) == 1:
                            request_path = "request.query." + keys[0]
                        elif identifier in [unquote(p) for p in parsed.path.split("/")]:
                            request_path = "request.path.{id}"
                        else:
                            continue
                    elif value != identifier:
                        continue
                    row = {"method": "GET", "path template": template(url, identifier),
                           "resource type": resource, "response type": kind,
                           "body-like field path": body_path, "id-like field path": id_path or request_path,
                           "clicked-id correlated": True, "view-counter field present": bool(counter)}
                    if row not in self.candidates and len(self.candidates) < MAX_CANDIDATES:
                        self.candidates.append(row)

    def report(self):
        return {"total responses": self.total,
                "JSON candidates": sum(r["response type"] == "JSON" for r in self.candidates),
                "document candidates": sum(r["response type"] == "document" for r in self.candidates),
                "exact known-detail endpoint seen": self.known_seen,
                "candidates": list(self.candidates)}


def observe(session, log, seconds=60):
    observer = AlternativeObserver()
    if not any(urlparse(p.url).netloc == KNOWN_HOST for p in session.context.pages):
        raise AuthRequired("An existing Portal tab is required")
    session.context.on("response", observer.capture)
    log("For 60 seconds, manually open one public notice in the existing Portal tab; observing only")
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            pages = session.context.pages
            if not pages:
                raise AuthRequired("Portal browser has no open pages")
            pages[-1].wait_for_timeout(250)
    finally:
        session.context.remove_listener("response", observer.capture)
    return observer.report()


def report_lines(report):
    lines = ["Detail alternative observation:"]
    for key in ("total responses", "JSON candidates", "document candidates", "exact known-detail endpoint seen"):
        value = report[key]
        lines.append(f"  {key}: " + (("yes" if value else "no") if type(value) is bool else str(value)))
    for index, candidate in enumerate(report["candidates"], 1):
        lines.append(f"Candidate {index}:")
        for key, value in candidate.items():
            lines.append(f"  {key}: " + (("yes" if value else "no") if type(value) is bool else value))
    if not report["candidates"] or all(c["view-counter field present"] for c in report["candidates"]):
        lines.append("no safe alternative observed")
    if report["candidates"]:
        lines.append("Observed shapes only; side effects are unverified. Automatic detail replay remains blocked.")
    return lines
