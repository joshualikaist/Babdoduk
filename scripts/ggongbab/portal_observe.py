# -*- coding: utf-8 -*-
"""Privacy-safe summaries of observed Portal network calls.

Never records titles, bodies, authors, emails, cookies, tokens, or raw ids.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlparse, urlunparse

_DIGITS = re.compile(r"\d+")
_HEX = re.compile(r"[0-9a-f]{8,}", re.I)
SENSITIVE_QUERY = re.compile(r"token|auth|session|cookie|key|password|jwt", re.I)
PRIMITIVE = (str, int, float, bool, type(None))


def path_template(path: str) -> str:
    path = _HEX.sub("<v>", path or "")
    path = _DIGITS.sub("<v>", path)
    return path


def url_template(url: str) -> dict[str, Any]:
    parsed = urlparse(url or "")
    query = []
    for name, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if SENSITIVE_QUERY.search(name):
            continue
        query.append(name)
    return {
        "host": parsed.netloc,
        "path": path_template(parsed.path),
        "method": "",
        "queryKeys": query,
    }


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def summarize_json(payload: Any, *, array_hint: int = 8) -> dict[str, Any]:
    """Top-level keys, array length, row key names, primitive types. No values."""
    out: dict[str, Any] = {"topKeys": [], "arrays": []}
    if not isinstance(payload, dict):
        if isinstance(payload, list):
            out["arrays"].append(_array_summary(".", payload, array_hint))
        else:
            out["kind"] = _type_name(payload)
        return out
    out["topKeys"] = sorted(str(k) for k in payload.keys())
    for key, value in payload.items():
        if isinstance(value, list):
            out["arrays"].append(_array_summary(str(key), value, array_hint))
        elif isinstance(value, dict):
            nested = [k for k, v in value.items() if isinstance(v, list)]
            for nested_key in nested:
                out["arrays"].append(_array_summary(f"{key}.{nested_key}", value[nested_key], array_hint))
    return out


def _array_summary(path: str, rows: list, limit: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"path": path, "length": len(rows), "rowKeys": [], "fieldTypes": {}}
    objects = [row for row in rows[:limit] if isinstance(row, dict)]
    keys: set[str] = set()
    types: dict[str, str] = {}
    for row in objects:
        for key, value in row.items():
            name = str(key)
            keys.add(name)
            types.setdefault(name, _type_name(value if not isinstance(value, PRIMITIVE) else value))
    summary["rowKeys"] = sorted(keys)
    summary["fieldTypes"] = types
    return summary


def sanitize_log_blob(text: str) -> str:
    """Tests assert this never keeps raw identifier-looking secrets in agent logs."""
    return _HEX.sub("<id>", text or "")
