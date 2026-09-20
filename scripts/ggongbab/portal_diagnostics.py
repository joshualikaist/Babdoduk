"""Value-free Portal diagnostics. Only fixed counter/reason names are exported."""
from collections import Counter
from urllib.parse import urlparse

COUNTS = (
    "total responses", "xhr/fetch responses", "document responses", "other responses",
    "same-host responses", "kaist-host responses", "json-parsed responses",
    "GET responses", "POST responses", "list-schema candidates", "detail-schema candidates",
    "replayable list candidates", "replayable detail candidates",
    "observed notice-like POST candidate", "pagination parameter observed",
    "pagination progression observed",
)
REJECTED = (
    "host mismatch", "method unsupported", "json parse failed", "schema ambiguous",
    "unsafe request shape", "unsafe query key count", "unsafe path component count",
    "multiple list identities", "pagination unverified", "detail shape rejected",
    "detail host mismatch", "body path ambiguous", "id path ambiguous", "id path missing",
    "same id repeated", "multiple detail shapes", "resource unsupported", "status unsupported",
    "observer errors", "list schema ambiguous",
)


class Diagnostics:
    def __init__(self):
        self.counts = Counter({key: 0 for key in COUNTS})
        self.rejected = Counter({key: 0 for key in REJECTED})

    def export(self):
        # Allowlist prevents accidentally serializing payload-derived keys/values.
        return {"counts": {k: int(self.counts[k]) for k in COUNTS},
                "rejected": {k: int(self.rejected[k]) for k in REJECTED}}


def capture_response(response, expected_host, diagnostics):
    """Observe all resource types on Portal/KAIST hosts, never request bodies/headers."""
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
    if method != "GET":
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
        if resource not in ("xhr", "fetch"):
            d.rejected["resource unsupported"] += 1
    return row
