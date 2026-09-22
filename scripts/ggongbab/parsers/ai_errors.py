# -*- coding: utf-8 -*-
"""Classify OpenAI failures into categories that are safe to log.

A raw SDK error message can quote the request, and the request carries mail
text. Nothing here keeps the message: an exception becomes one of a fixed set of
category names, and only category counts are ever printed.

Categories:
  timeout              the request did not finish in time
  rate_limit           the account is being throttled right now (transient)
  quota_exhausted      the account is out of credit (retrying cannot help)
  connection           the request never reached the API
  server_error         the API answered 5xx
  bad_request          the API rejected the request (4xx that is not auth/rate)
  auth                 the key was missing, wrong or not permitted
  refusal              the model declined to answer
  no_parsed_output     a reply arrived but carried no parsed object
  schema_or_validation the reply did not satisfy the schema
  unknown              anything else
"""
from __future__ import annotations

import re

TIMEOUT = "timeout"
RATE_LIMIT = "rate_limit"
QUOTA = "quota_exhausted"
CONNECTION = "connection"
SERVER_ERROR = "server_error"
BAD_REQUEST = "bad_request"
AUTH = "auth"
REFUSAL = "refusal"
NO_PARSED_OUTPUT = "no_parsed_output"
SCHEMA = "schema_or_validation"
UNKNOWN = "unknown"

CATEGORIES = (TIMEOUT, RATE_LIMIT, QUOTA, CONNECTION, SERVER_ERROR, BAD_REQUEST, AUTH,
              REFUSAL, NO_PARSED_OUTPUT, SCHEMA, UNKNOWN)

# Transient failures are the ones a second attempt can plausibly fix. A rejected
# request or a refusal will fail again the same way, so retrying wastes calls.
RETRYABLE = frozenset({TIMEOUT, RATE_LIMIT, CONNECTION, SERVER_ERROR, NO_PARSED_OUTPUT})

# These do not fail one item, they fail the account. Sending the remaining
# candidates would produce the same rejection every time, so the run stops at
# the first one instead of turning a spent quota into 39 identical errors.
FATAL = frozenset({QUOTA, AUTH})

# Matched against the EXCEPTION CLASS NAME only, never the message.
_BY_CLASS = (
    ("APITimeoutError", TIMEOUT),
    ("Timeout", TIMEOUT),
    ("APIConnectionError", CONNECTION),
    ("ConnectionError", CONNECTION),
    ("InternalServerError", SERVER_ERROR),
    ("AuthenticationError", AUTH),
    ("PermissionDeniedError", AUTH),
    ("NotFoundError", BAD_REQUEST),
    ("UnprocessableEntityError", SCHEMA),
    ("ValidationError", SCHEMA),
    ("BadRequestError", BAD_REQUEST),
    ("ConflictError", BAD_REQUEST),
)

_STATUS = re.compile(r"\b(4\d{2}|5\d{2})\b")

# A bounded retry can wait out a per-minute window. Anything longer is a spent
# allowance wearing a throttling label, and retrying it only burns more calls.
RETRY_WINDOW_LIMIT_SECONDS = 300


def _retry_after_seconds(exc: BaseException):
    """Seconds the API asked us to wait, from response headers. None if absent.

    Only the numeric rate-limit headers are read. The response body is never
    touched, because an error body can quote the request.
    """
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:  # noqa: BLE001 - a mapping-like object we do not control
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _exhausted_for_a_long_time(exc: BaseException) -> bool:
    """True when the reported wait is far longer than a retry pass can cover.

    A daily or monthly allowance runs out under the same `rate_limit_exceeded`
    code as ordinary throttling; the wait it reports is what tells them apart.
    """
    seconds = _retry_after_seconds(exc)
    return seconds is not None and seconds > RETRY_WINDOW_LIMIT_SECONDS



def classify_exception(exc: BaseException) -> str:
    """Category for an SDK exception. Only its type, code and status are read.

    `insufficient_quota` arrives as a RateLimitError too, but no amount of
    waiting fixes an empty balance, so it gets its own non-retryable category.
    A used-up daily or monthly allowance is reported as ordinary throttling and
    is separated by how long the API says to wait.
    """
    code = str(getattr(exc, "code", "") or "")
    if code == "insufficient_quota":
        return QUOTA
    if code == "rate_limit_exceeded":
        # A daily or monthly allowance runs out with this same code. The headers
        # tell the two apart: a per-minute window resets in seconds, a spent
        # grant in hours. Only the first is worth a retry.
        return QUOTA if _exhausted_for_a_long_time(exc) else RATE_LIMIT
    name = exc.__class__.__name__
    if "RateLimitError" in name:
        return QUOTA if _exhausted_for_a_long_time(exc) else RATE_LIMIT
    for needle, category in _BY_CLASS:
        if needle in name:
            return category
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status == 408:
            return TIMEOUT
        if status == 429:
            return QUOTA if _exhausted_for_a_long_time(exc) else RATE_LIMIT
        if status in (401, 403):
            return AUTH
        if 500 <= status < 600:
            return SERVER_ERROR
        if 400 <= status < 500:
            return BAD_REQUEST
    return UNKNOWN


def classify_message(message: str) -> str:
    """Category for an error string this codebase produced itself.

    Only our own short markers are matched. A message that came from the SDK
    falls through to `unknown` rather than being pattern-matched, because its
    text is not ours to interpret and may quote the request.
    """
    text = (message or "").strip()
    if not text:
        return UNKNOWN
    head = text.split(":", 1)[0].strip()
    if head.startswith("refusal"):
        return REFUSAL
    if text.startswith("no parsed output"):
        return NO_PARSED_OUTPUT
    for needle, category in _BY_CLASS:
        if head == needle or head.endswith(needle):
            return category
    status = _STATUS.search(head)
    if status:
        code = int(status.group(1))
        if code == 429:
            return RATE_LIMIT
        if code in (401, 403):
            return AUTH
        if 500 <= code < 600:
            return SERVER_ERROR
        return BAD_REQUEST
    return UNKNOWN


def is_retryable(category: str) -> bool:
    return category in RETRYABLE


def is_fatal(category: str) -> bool:
    """True when the whole run should stop rather than try the next candidate."""
    return category in FATAL


def summary_lines(counts: dict[str, int]) -> list[str]:
    """Category counts, ordered, for the terminal. Never any message text."""
    rows = [(name, counts.get(name, 0)) for name in CATEGORIES if counts.get(name)]
    if not rows:
        return []
    return ["AI error summary:"] + [f"  {name}: {count}" for name, count in rows]
