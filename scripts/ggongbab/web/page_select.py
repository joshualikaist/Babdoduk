# -*- coding: utf-8 -*-
"""Find the page (or frame) that is actually showing the mailbox.

Why this exists: the first setup implementation held the page object it opened at
launch and read `page.url` from it after the user pressed Enter. Dooray moves the
mail app somewhere else - a second tab, or a frame inside the shell - so that
reference still said `https://kaist.gov-dooray.com/` while the user was looking at
`/mail/systems/inbox`. The root URL was then saved as the mailbox.

So: never trust the page you started with. After the user confirms, look at every
open page and every frame, and pick the one that carries mail evidence.

Two kinds of evidence are used, both observable:
  * the URL path sits under the `/mail/` application area (confirmed against the
    live tenant), and
  * the DOM holds repeated containers that look like mail ROWS, not merely
    repeated containers.

The second point is the other half of the bug: 25 elements sharing a class is
something any home page has. A mail row also carries a date or time, readable
text, and usually a per-row id. Those are what get counted here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

# Rows are found structurally: siblings that share a tag+class signature. Class
# names are never hard-coded; only the shape of the content is inspected.
MAIL_ROW_JS = r"""
() => {
  const dateRe = /(\d{1,2}[:.]\d{2})|(\d{1,2}\s*월\s*\d{1,2}\s*일)|(\d{4}[-./]\d{1,2}[-./]\d{1,2})|((오전|오후)\s*\d{1,2})|(\b\d{1,2}\/\d{1,2}\b)/;
  const groups = [];
  const seen = new Set();
  const parents = document.querySelectorAll('*');
  for (const parent of parents) {
    const kids = Array.from(parent.children || []);
    if (kids.length < 5) continue;
    const bySig = new Map();
    for (const kid of kids) {
      const cls = (kid.getAttribute('class') || '').trim().split(/\s+/).slice(0, 2).join('.');
      const sig = kid.tagName + (cls ? '.' + cls : '');
      if (!bySig.has(sig)) bySig.set(sig, []);
      bySig.get(sig).push(kid);
    }
    for (const [sig, rows] of bySig) {
      if (rows.length < 5 || seen.has(sig)) continue;
      seen.add(sig);
      let withText = 0, withDate = 0, withId = 0;
      const ids = new Set();
      for (const row of rows) {
        let text = '';
        try { text = (row.innerText || '').trim(); } catch (e) { text = ''; }
        if (text.length >= 8 && text.length <= 800) withText++;
        if (dateRe.test(text)) withDate++;
        let rid = '';
        for (const attr of row.attributes) {
          if ((attr.name === 'id' || attr.name.startsWith('data-')) && attr.value && attr.value.length <= 120) {
            rid = attr.name; ids.add(attr.name + '=' + attr.value); break;
          }
        }
        if (rid) withId++;
      }
      groups.push({ selector: sig, rowCount: rows.length, rowsWithText: withText,
                    rowsWithDate: withDate, rowsWithId: withId, distinctIds: ids.size });
    }
  }
  groups.sort((a, b) => (b.rowsWithDate - a.rowsWithDate) || (b.rowCount - a.rowCount));
  return { groups: groups.slice(0, 12), title: document.title || '' };
}
"""

MAIL_PATH = re.compile(r"^/mail(/|$)", re.I)
MIN_ROWS = 5


def is_mail_row_group(group: dict[str, Any]) -> bool:
    """A group of siblings that behaves like a list of mail rows.

    Repetition alone is not enough. Most rows must carry readable text AND a
    date/time, plus either per-row ids or dates on nearly every row.
    """
    rows = int(group.get("rowCount") or 0)
    if rows < MIN_ROWS:
        return False
    with_text = int(group.get("rowsWithText") or 0)
    with_date = int(group.get("rowsWithDate") or 0)
    distinct_ids = int(group.get("distinctIds") or 0)
    if with_text < rows * 0.6:
        return False
    if with_date < max(3, rows * 0.5):
        return False
    return distinct_ids >= rows * 0.5 or with_date >= rows * 0.8


def summarise_rows(raw: dict[str, Any]) -> dict[str, Any]:
    groups = list(raw.get("groups") or [])
    mail_like = [g for g in groups if is_mail_row_group(g)]
    return {
        "groupCount": len(groups),
        "repeatedContainers": max((int(g.get("rowCount") or 0) for g in groups), default=0),
        "mailRowGroups": mail_like[:3],
        "strong": bool(mail_like),
        "groups": groups[:8],
    }


def mail_row_evidence(frame) -> dict[str, Any]:  # noqa: ANN001
    try:
        raw = frame.evaluate(MAIL_ROW_JS)
    except Exception as exc:  # noqa: BLE001 - a detached or cross-origin frame
        return {"groupCount": 0, "repeatedContainers": 0, "mailRowGroups": [],
                "strong": False, "groups": [], "error": exc.__class__.__name__}
    summary = summarise_rows(raw)
    summary["title"] = (raw.get("title") or "")[:80]
    return summary


# ---------------------------------------------------------------------------
@dataclass
class MailTarget:
    page: Any
    frame: Any
    url: str
    is_main: bool
    score: int = 0
    mail_path: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def location(self) -> str:
        """origin + path only. Query values never reach a log."""
        parsed = urlparse(self.url or "")
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else (self.url or "")

    @property
    def mail_candidate(self) -> bool:
        return self.mail_path or bool(self.evidence.get("strong"))

    def reload(self) -> None:
        """Re-issue the request that painted this view, to catch its list call."""
        try:
            if self.is_main:
                self.page.reload(wait_until="domcontentloaded")
            else:
                self.frame.goto(self.url, wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001 - reloading is best effort
            pass


def _same_host(url: str, host: str) -> bool:
    if not host:
        return True
    return urlparse(url or "").netloc.lower() == host.lower()


def collect_targets(context, origin_host: str = "", with_evidence: bool = True) -> list[MailTarget]:  # noqa: ANN001
    """Every open page and frame, scored as a mailbox candidate."""
    targets: list[MailTarget] = []
    for page in list(getattr(context, "pages", []) or []):
        try:
            if page.is_closed():
                continue
        except Exception:  # noqa: BLE001
            continue
        try:
            frames = list(page.frames)
        except Exception:  # noqa: BLE001
            frames = []
        main = frames[0] if frames else None
        for frame in frames:
            try:
                url = frame.url or ""
            except Exception:  # noqa: BLE001
                continue
            if not url or url.startswith("about:"):
                continue
            if origin_host and not _same_host(url, origin_host):
                continue
            path = urlparse(url).path or "/"
            target = MailTarget(page=page, frame=frame, url=url, is_main=frame is main,
                                mail_path=bool(MAIL_PATH.match(path)))
            if with_evidence:
                target.evidence = mail_row_evidence(frame)
            target.score = score_target(target)
            targets.append(target)
    targets.sort(key=lambda t: t.score, reverse=True)
    return targets


def score_target(target: MailTarget) -> int:
    score = 0
    if target.mail_path:
        score += 4                       # the confirmed mail application area
    if target.evidence.get("strong"):
        score += 4                       # rows that actually look like mail rows
    if not target.is_main:
        score += 1                       # the shell rarely is the mailbox itself
    if (target.evidence.get("repeatedContainers") or 0) >= MIN_ROWS:
        score += 1
    return score


def select_mail_page(context, origin_host: str = "", preferred=None) -> Optional[MailTarget]:  # noqa: ANN001
    """Pick the page/frame showing the mailbox, or None when none qualifies.

    Qualifying means the URL is inside the mail area or the DOM holds mail-row-like
    repetition. A page that is merely open, or merely repetitive, does not qualify.
    """
    targets = collect_targets(context, origin_host)
    if preferred is not None:
        for target in targets:
            if target.frame is preferred and target.mail_candidate:
                return target
    for target in targets:
        if target.mail_candidate:
            return target
    return None


def describe(targets: list[MailTarget]) -> list[str]:
    """Log lines with origin + path only: no query values, no mail content."""
    lines = [f"pages observed: {len(targets)}"]
    for index, target in enumerate(targets):
        lines.append(f"  [{index}] {target.location}")
        bits = [f"mailCandidate={'yes' if target.mail_candidate else 'no'}"]
        bits.append(f"mailPath={'yes' if target.mail_path else 'no'}")
        bits.append(f"mailRows={'yes' if target.evidence.get('strong') else 'no'}")
        rows = target.evidence.get("repeatedContainers") or 0
        if rows:
            bits.append(f"repeated={rows}")
        if not target.is_main:
            bits.append("frame")
        lines.append("        " + "  ".join(bits))
    return lines
