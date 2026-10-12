# -*- coding: utf-8 -*-
"""Synchronize the sanitized public DB projection (ggongbab_public_events) from the canonical events.

The scheduled ggongbab-refresh workflow runs this AFTER it has published data/ggongbab/latest.json,
so a failure here never holds the static snapshot back: the job turns red and the snapshot stands.
It reads the canonical rows with the backend key, selects them with the exporter's own
publication policy (the same selection as the snapshot) and replaces the projection atomically
through ggongbab_replace_public_feed (migration 004, applied by hand). Prints counts only.

    python scripts/sync_public_feed.py

Exit codes: 0 synchronized · 21 Supabase not configured · 23 preparation or replacement failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.config import load_settings  # noqa: E402
from ggongbab.db.repository import SupabaseRepository  # noqa: E402
from ggongbab.db.supabase_client import SupabaseClient  # noqa: E402
from ggongbab.public_feed import PublicFeedError, sync_public_feed  # noqa: E402

EXIT_SUPABASE = 21
EXIT_SYNC = 23


def main(*, settings=None, repo=None, now=None) -> int:
    settings = settings or load_settings()
    if repo is None:
        if not settings.has_supabase:
            print("[error] SUPABASE_URL / SUPABASE_SECRET_KEY missing; the projection was not touched")
            return EXIT_SUPABASE
        repo = SupabaseRepository(SupabaseClient(settings.supabase_url, settings.supabase_secret_key))
    try:
        payload = sync_public_feed(repo, settings, now)
    except PublicFeedError as exc:
        # Value-free: the code says which half failed; the projection keeps its previous generation.
        print(f"[error] public feed synchronization failed ({exc}); the published snapshot stands")
        return EXIT_SYNC
    print(f"public feed synchronized events={payload['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
