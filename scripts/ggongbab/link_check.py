# -*- coding: utf-8 -*-
"""Open the sign-up link of a new free-food event before it is listed (owner 2026-11-26: "인공지능이 직접
눌러보거나 그러지는 않는거야? … 당연히 해야지 우리 밥도둑의 목적이 그거 아니야?").

One GET per link, the way a student's phone would open it, and only to learn two facts:
  * the page is gone (404/410): the link is dropped and the event is held for the owner;
  * a Google form no longer takes answers: the event is held as "신청 마감".
Anything else (a login wall, a slow site, a server error) changes nothing: a sign-up page the
pipeline could not read is not evidence against the event.

Never opened: links that carry a per-recipient tracking id (a mailing tool's click link, such as
MathWorks' `elq…`/`rec_id`), since opening one tells the sender that this mailbox clicked; links on
a mailing tool's click-tracking host; anything not http(s). Nothing about the page is stored.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlsplit

TIMEOUT_SECONDS = 8
MAX_BYTES = 512 * 1024
USER_AGENT = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1")

# Query keys that identify the person a mail was sent to (Eloqua, Marketo, HubSpot, Mailchimp,
# Salesforce Marketing Cloud and similar). utm_* names a campaign, not a person, and is allowed.
TRACKING_KEYS = re.compile(r"^(elq\w*|rec_id|mkt_tok|_hsenc|_hsmi|mc_eid|mc_cid|sfmc_\w+|ecid|trk\w*|"
                           r"subscriber\w*|recipient\w*|email|e|uid|u|token)$", re.I)
TRACKING_HOSTS = re.compile(r"^(click|clicks|links?|email|e|go|trk|track|t)\.|\.list-manage\.com$|\.mkt\d*\.com$"
                            r"|\.hubspotlinks\.com$|\.sendgrid\.net$|\.mailchi\.mp$|^app\.go\.", re.I)
CLOSED_FORM = re.compile(r"더 이상 응답을 받지 않습니다|no longer accepting responses|응답을 받지 않습니다", re.I)

OK, DEAD, CLOSED, SKIPPED, UNKNOWN = "ok", "dead", "closed", "skipped", "unknown"


@dataclass(frozen=True)
class LinkCheck:
    state: str
    status: Optional[int] = None


def may_open(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return False
    if TRACKING_HOSTS.search(host):
        return False
    return not any(TRACKING_KEYS.match(key) for key, _ in parse_qsl(parts.query, keep_blank_values=True))


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko,en;q=0.8"})
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)


def check(url: str, *, opener: Callable = _open) -> LinkCheck:
    if not may_open(url):
        return LinkCheck(SKIPPED)
    try:
        with opener(url) as response:
            status = int(getattr(response, "status", 200) or 200)
            final = str(response.geturl() if hasattr(response, "geturl") else url)
            body = response.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return LinkCheck(DEAD if exc.code in (404, 410) else UNKNOWN, exc.code)
    except Exception:  # noqa: BLE001 - timeouts, DNS, TLS: not evidence against the event
        return LinkCheck(UNKNOWN)
    if status in (404, 410):
        return LinkCheck(DEAD, status)
    if "/closedform" in urlsplit(final).path or (_is_google_form(final) and CLOSED_FORM.search(body)):
        return LinkCheck(CLOSED, status)
    return LinkCheck(OK, status)


def _is_google_form(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return host == "forms.gle" or (host == "docs.google.com" and parts.path.startswith("/forms/"))


def apply(cand, *, opener: Callable = _open) -> Optional[LinkCheck]:
    """Check the candidate's sign-up link and record what it means on the candidate."""
    url = getattr(cand, "registration_url", None)
    if not url or not getattr(cand, "is_event", False):
        return None
    result = check(url, opener=opener)
    if result.state == DEAD:
        cand.registration_url = None
        cand.review_reasons.append(f"신청 링크가 열리지 않음 ({result.status}), 링크를 뺐음")
        cand.needs_review = True
    elif result.state == CLOSED:
        cand.review_reasons.append("신청 마감됨 (신청 설문이 더 이상 응답을 받지 않음)")
        cand.needs_review = True
    return result
