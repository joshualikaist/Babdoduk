# -*- coding: utf-8 -*-
"""Local magazine discovery (operator PC): YouTube routes GitHub's runners cannot reach.

Writes research/magazine/inbox/ only. It never builds or publishes an edition; the normal
pipeline (scripts/refresh_magazine.py) reads the inbox. See docs/MAGAZINE_DISCOVERY.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery import pipeline, sidecar  # noqa: E402
from discovery.common import now_kst  # noqa: E402


def main() -> int:
    report = sidecar.run(pipeline.Paths(ROOT), now_kst())
    return 0 if report else 1


if __name__ == "__main__":
    sys.exit(main())
