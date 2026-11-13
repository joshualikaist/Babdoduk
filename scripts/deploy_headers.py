"""Read the header-only Vercel routes for offline deployment-policy checks.

The deployed policy lives in vercel.json. This helper never serves files or handles
rewrites: it only supplies the same response headers to synthetic browser responses.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def response_headers(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    headers = {}
    routes = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))["routes"]
    for route in routes:
        if not route.get("headers") or not re.fullmatch(route["src"], parts.path or "/"):
            continue
        matched = True
        for condition in route.get("has", []):
            if condition["type"] != "query":
                raise ValueError("unsupported header condition in offline checker")
            values = query.get(condition["key"], [])
            if not values or ("value" in condition and not any(
                    re.fullmatch(condition["value"], value) for value in values)):
                matched = False
                break
        if matched:
            headers.update(route["headers"])
    return headers
