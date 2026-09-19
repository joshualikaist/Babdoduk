# -*- coding: utf-8 -*-
"""Machine-readable provenance on Dooray collection-project tasks.

Portal local agent writes a block the cloud collector can parse without guessing
source type from the notice body. Mail tasks without the block stay Dooray mail.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

MARKER_HEAD = "[BABDODUK_INGEST_V1]"
_BLOCK = re.compile(
    r"\[BABDODUK_INGEST_V1\]\s*(.*?)(?:\n\s*\n|\nOriginal Notice|\Z)",
    re.S | re.I,
)
_LINE = re.compile(r"^([a-z_]+)=(.*)$", re.I)


@dataclass(frozen=True)
class IngestMarker:
    source: str
    external_key: str
    source_created_at: str = ""
    private_source: bool = False

    @property
    def is_portal(self) -> bool:
        return self.source == "portal"


def portal_external_key(stable_id: str) -> str:
    """Opaque, deterministic id. Raw portal ids never go into logs or public JSON."""
    return hashlib.sha256(f"portal:{stable_id}".encode("utf-8")).hexdigest()


def portal_content_hash(title: str, body: str) -> str:
    basis = re.sub(r"\s+", " ", f"{title or ''}\n{body or ''}").strip()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def render_portal_marker(*, external_key: str, source_created_at: str = "",
                         private_source: bool = True) -> str:
    lines = [
        MARKER_HEAD,
        "source=portal",
        f"external_key={external_key}",
    ]
    if source_created_at:
        lines.append(f"source_created_at={source_created_at}")
    if private_source:
        lines.append("private_source=true")
    return "\n".join(lines)


def parse_ingest_marker(text: str) -> Optional[IngestMarker]:
    if not text or MARKER_HEAD not in text:
        return None
    match = _BLOCK.search(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    for raw in match.group(1).splitlines():
        line = raw.strip()
        got = _LINE.match(line)
        if got:
            fields[got.group(1).strip().lower()] = got.group(2).strip()
    source = (fields.get("source") or "").strip().lower()
    key = (fields.get("external_key") or "").strip()
    if not source or not key:
        return None
    private = (fields.get("private_source") or "").lower() in {"1", "true", "yes"}
    return IngestMarker(
        source=source,
        external_key=key,
        source_created_at=fields.get("source_created_at") or "",
        private_source=private,
    )


def strip_ingest_marker(text: str) -> str:
    if not text or MARKER_HEAD not in text:
        return text or ""
    cleaned = _BLOCK.sub("", text)
    cleaned = re.sub(r"^\s*Original Notice\s*", "", cleaned, flags=re.I)
    return cleaned.strip()
