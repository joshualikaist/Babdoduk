"""Strict read-state parsing and value-free nested schema inspection."""
from __future__ import annotations

from typing import Any

SEMANTIC_KEYS = {"read", "isread", "unread", "isunread", "seen", "isseen", "unreadflag", "readyn"}
MIN_ROWS = 5
# Unknown/dynamic object keys may themselves contain personal data. Only these
# schema names are displayed; values and arbitrary keys never reach diagnostics.
SAFE_KEYS = SEMANTIC_KEYS | {
    "annotations", "users", "user", "metadata", "flags", "state", "status",
    "id", "uid", "createdat", "updatedat", "subject", "version", "mailsummary",
    "threadmail", "filecount", "isemailoftenant", "approval", "senderip",
    "countrycode", "folderid", "receivedat", "email", "name", "type",
}


def safe_path(path: str) -> str:
    return ".".join(part if part.lower() in SAFE_KEYS or part == "[]" else "<key>"
                    for part in path.split("."))


def path_value(row: dict, path: str) -> Any:
    value: Any = row
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def unread_value(value: Any, path: str) -> bool | None:
    leaf = path.rsplit(".", 1)[-1].lower()
    if leaf not in SEMANTIC_KEYS:
        return None
    if isinstance(value, str):
        word = value.strip().lower()
        if word in {"read", "seen", "unread", "unseen"}:
            return word in {"unread", "unseen"}
        enums = {"true": True, "false": False, "y": True, "n": False}
        value = enums.get(word)
    if not isinstance(value, bool):
        return None
    return value if leaf in {"unread", "isunread", "unreadflag"} else not value


def inspect_read_schema(rows: list[dict]) -> tuple[dict[str, list[str]], list[dict], str]:
    """Return safe schema, candidate counts, and one fully validated dict path.

    Arrays are inspected but never selected: their entries may describe other
    recipients. Multiple semantic fields are ambiguous even if they agree.
    """
    schema: dict[str, set[str]] = {}
    candidates: set[str] = set()

    def walk(value, parts=()):
        if len(parts) > 12:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                # Dots would make a literal field indistinguishable from nesting.
                part = str(key)
                path = parts + (part,)
                if part.lower() in SEMANTIC_KEYS:
                    candidates.add(".".join(path))
                if "." not in part:
                    walk(child, path)
        elif isinstance(value, list):
            for child in value:
                walk(child, parts + ("[]",))
        else:
            kind = ("null" if value is None else "bool" if isinstance(value, bool)
                    else "string" if isinstance(value, str) else "number")
            schema.setdefault(safe_path(".".join(parts)), set()).add(kind)

    for row in rows:
        walk(row)
    reports = []
    valid = []
    for path in sorted(candidates):
        supported = "[]" not in path.split(".") and "<key>" not in safe_path(path)
        count = sum(unread_value(path_value(row, path), path) is not None for row in rows) if supported else 0
        accepted = supported and len(rows) >= MIN_ROWS and count == len(rows)
        reports.append({"path": safe_path(path), "validRows": count, "rows": len(rows),
                        "eligible": accepted})
        if accepted:
            valid.append(path)
    selected = valid[0] if len(valid) == 1 and len(candidates) == 1 else ""
    return {path: sorted(types) for path, types in sorted(schema.items())}, reports, selected


def crosscheck_dom(frame, rows: list[dict], path: str) -> dict:
    """Compare only explicit state attributes and exact, unique mail IDs.

    No text, titles, or class-name heuristics. IDs remain in memory; callers
    receive counts only. A missing explicit marker is not interpreted as read.
    """
    try:
        markers = frame.evaluate("""() => Array.from(document.querySelectorAll(
            '[data-mail-id], [data-message-id], [data-id]')).flatMap(el => {
            const id = el.getAttribute('data-mail-id') ||
                       el.getAttribute('data-message-id') || el.getAttribute('data-id');
            const unread = el.getAttribute('data-unread');
            const read = el.getAttribute('data-read');
            if (unread !== null && read !== null) return [];
            const value = unread !== null ? unread : read;
            if (value !== 'true' && value !== 'false') return [];
            return [{id, unread: unread !== null ? value === 'true' : value === 'false'}];
        })""")
    except Exception:
        return {"matched": 0, "agreement": 0, "verified": False}
    api = {}
    duplicate_ids = set()
    for row in rows:
        mail_id = str(row.get("id", ""))
        if mail_id in api:
            duplicate_ids.add(mail_id)
        api[mail_id] = unread_value(path_value(row, path), path)
    dom = {}
    for marker in markers:
        mail_id = marker.get("id", "")
        if mail_id in dom:
            duplicate_ids.add(mail_id)
        dom[mail_id] = marker.get("unread")
    matches = [key for key in api.keys() & dom.keys()
               if key and key not in duplicate_ids and isinstance(api[key], bool)
               and isinstance(dom[key], bool)]
    agreement = sum(api[key] == dom[key] for key in matches)
    return {"matched": len(matches), "agreement": agreement,
            "verified": len(matches) >= MIN_ROWS and agreement == len(matches)}
