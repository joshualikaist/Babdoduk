# -*- coding: utf-8 -*-
"""Collector interface. Every collector returns the same RawItem list."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import RawItem, SourceType


class CollectorError(Exception):
    """Raised when a source is unreachable. The pipeline records it and moves on."""


class Collector(ABC):
    source_type: SourceType
    name: str = ""

    @abstractmethod
    def collect(self) -> list[RawItem]:
        """Return normalized items. Must not raise for per-item problems; raise CollectorError for outage."""

    def enabled(self) -> bool:
        return True
