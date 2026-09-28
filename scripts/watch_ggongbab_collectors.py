#!/usr/bin/env python3
"""Cloud collector watch (last step of ggongbab-refresh). See scripts/ggongbab/cloud_watch.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.cloud_watch import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
