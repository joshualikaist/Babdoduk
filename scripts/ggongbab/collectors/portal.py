# -*- coding: utf-8 -*-
"""KAIST portal collector - disabled stub.

The portal requires SSO login. Credentials must never live in this repository
or in GitHub secrets for this project, so this collector only defines the
interface. When a sanctioned integration exists (e.g. an official feed or an
approved service account), implement `collect()` here and flip `enabled()`.
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
