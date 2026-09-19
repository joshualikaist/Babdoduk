# -*- coding: utf-8 -*-
"""KAIST portal collector — cloud/GitHub Action path stays disabled.

Portal requires interactive SSO. Credentials must never live in this repository
or in GitHub secrets. Production ingest is:

    Portal resident Chrome → scripts/portal_web_agent.py → Dooray collection
    Project (ingest marker source=portal) → DoorayCollector.normalize_post
    → RawItem(source_type="portal")

`enabled()` remains False so Actions never attempt a Portal login.
"""
from __future__ import annotations

from ..config import Settings
from ..models import RawItem
from .base import Collector


class PortalCollector(Collector):
    source_type = "portal"
    name = "KAIST Portal"

    def __init__(self, settings: Settings):
        self.settings = settings

    def enabled(self) -> bool:
        return False

    def collect(self) -> list[RawItem]:
        return []
