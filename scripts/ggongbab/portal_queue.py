# -*- coding: utf-8 -*-
"""Idempotent Portal → collection-project queue. Hashes only, never titles or ids."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .ingest_marker import portal_content_hash, portal_external_key

Outcome = Literal["new", "update", "skip"]


@dataclass(frozen=True)
class QueueDecision:
    outcome: Outcome
    external_key: str
    content_hash: str


def decide(state: dict[str, str], stable_id: str, title: str, body: str) -> QueueDecision:
    key = portal_external_key(stable_id)
    digest = portal_content_hash(title, body)
    prev = state.get(key)
    if prev == digest:
        return QueueDecision("skip", key, digest)
    if prev:
        return QueueDecision("update", key, digest)
    return QueueDecision("new", key, digest)


class PortalQueue:
    def __init__(self, path: Path):
        self.path = path
        self.hashes: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        rows = data.get("notices") if isinstance(data, dict) else None
        if isinstance(rows, dict):
            self.hashes = {str(k): str(v) for k, v in rows.items() if k and v}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "note": "external_key -> content_hash only; no titles, bodies, or portal ids",
            "notices": self.hashes,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        handle, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=".portal-state-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def decide(self, stable_id: str, title: str, body: str) -> QueueDecision:
        return decide(self.hashes, stable_id, title, body)

    def record(self, decision: QueueDecision) -> None:
        self.hashes[decision.external_key] = decision.content_hash
