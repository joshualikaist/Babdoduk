# -*- coding: utf-8 -*-
"""Collect KAIST free-food events into Supabase and export data/ggongbab/latest.json.

    python scripts/refresh_ggongbab.py                 # full run (needs secrets)
    python scripts/refresh_ggongbab.py --export-only   # DB -> latest.json without collecting
    python scripts/refresh_ggongbab.py --review-report # list events waiting for review
    python scripts/refresh_ggongbab.py --dry-run       # in-memory DB, no AI, no file write
    python scripts/refresh_ggongbab.py --check         # verify configured services respond

Exit codes: 0 ok · 1 hard failure · 2 nothing safe to publish (previous JSON kept).
Nothing private (mail text, addresses, tokens) is printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.collectors.dooray import DoorayClient, DoorayCollector  # noqa: E402
from ggongbab.collectors.kaist_public import KaistPublicCollector  # noqa: E402
from ggongbab.collectors.manual import ManualCollector  # noqa: E402
from ggongbab.collectors.portal import PortalCollector  # noqa: E402
from ggongbab.config import DATA_DIR, KST, Settings, load_settings  # noqa: E402
from ggongbab.db.repository import MemoryRepository, SupabaseRepository  # noqa: E402
from ggongbab.db.supabase_client import SupabaseClient, SupabaseError  # noqa: E402
from ggongbab.exporter import build_payload, write_payload  # noqa: E402
from ggongbab.pipeline import Pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def build_repo(settings: Settings, dry_run: bool):
    if dry_run or not settings.has_supabase:
        if not dry_run:
            print("[warn] SUPABASE_URL / SUPABASE_SECRET_KEY missing; using in-memory repository (nothing persists)")
        return MemoryRepository()
    if settings.supabase_key_is_legacy:
        print("[warn] using legacy SUPABASE_SERVICE_ROLE_KEY; rename the secret to SUPABASE_SECRET_KEY")
    client = SupabaseClient(settings.supabase_url, settings.supabase_secret_key)
    client.ping()
    return SupabaseRepository(client)


def build_extractor(settings: Settings, dry_run: bool):
    if dry_run or not settings.has_openai:
        if not dry_run:
            print("[warn] OPENAI_API_KEY missing; AI parsing disabled (raw items are stored and retried later)")
        return None
    from ggongbab.parsers.ai_parser import OpenAIExtractor

    return OpenAIExtractor(settings.openai_api_key)


def build_collectors(settings: Settings, repo, only: str) -> list:
    collectors = []
    if only in ("all", "dooray"):
        # Attachments are fetched lazily by the pipeline, after its cache check.
        collectors.append(DoorayCollector(settings))
    if only in ("all", "kaist"):
        collectors.append(KaistPublicCollector(settings))
    if only in ("all", "manual"):
        collectors.append(ManualCollector(settings))
    if only in ("all", "portal"):
        collectors.append(PortalCollector(settings))
    return collectors


def validate_export(path: Path) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_content import validate_ggongbab  # type: ignore

    return validate_ggongbab(path)


def export(settings: Settings, repo, dry_run: bool) -> int:
    rows = repo.publishable_events()
    payload = build_payload(rows, settings)
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        return 0
    tmp_dir = DATA_DIR / ".staging"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    staged = write_payload(payload, tmp_dir)
    errors = validate_export(staged)
    if errors:
        print("[error] export validation failed; keeping previous latest.json")
        for err in errors:
            print("  -", err)
        staged.unlink(missing_ok=True)
        return 2
    final = write_payload(payload, DATA_DIR)
    staged.unlink(missing_ok=True)
    try:
        tmp_dir.rmdir()
    except OSError:
        pass
    print(f"wrote {final.relative_to(ROOT)} events={payload['count']}")
    return 0


def review_report(repo) -> None:
    rows = repo.review_events()
    if not rows:
        print("review queue empty")
        return
    print(f"{len(rows)} event(s) need review\n")
    for row in rows:
        start = row.get("event_start") or "(no date)"
        srcs = ",".join(sorted({s.get("type", "?") for s in row.get("_sources") or []})) or "-"
        print(f"- [{row.get('status')}] {start} · {row.get('title')}")
        print(f"    id={row.get('id')} conf={row.get('confidence')} food={row.get('food_provided')} sources={srcs}")
        print(f"    reason: {row.get('review_reason')}")


def check(settings: Settings) -> int:
    ok = True
    print(f"Dooray:   {'configured' if settings.has_dooray else 'missing DOORAY_API_TOKEN'}")
    if settings.has_dooray:
        try:
            me = DoorayClient(settings.dooray_base, settings.dooray_token).me()
            print(f"          members/me ok (id present: {bool(me.get('id'))})")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"          FAILED: {exc}")
    print(f"Supabase: {'configured' if settings.has_supabase else 'missing SUPABASE_URL / SUPABASE_SECRET_KEY'}")
    if settings.has_supabase:
        print(f"          key from {settings.supabase_key_env}" + (" (legacy name)" if settings.supabase_key_is_legacy else ""))
        try:
            SupabaseClient(settings.supabase_url, settings.supabase_secret_key).ping()
            print("          rest/v1/sources ok")
        except SupabaseError as exc:
            ok = False
            print(f"          FAILED: {exc}")
    print(f"OpenAI:   {'configured' if settings.has_openai else 'missing OPENAI_API_KEY'} (model={settings.ai_model}, fallback={settings.ai_fallback_model})")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="in-memory repository, no AI, no file write")
    parser.add_argument("--export-only", action="store_true", help="skip collectors; export DB -> latest.json")
    parser.add_argument("--review-report", action="store_true", help="print events with needs_review=true")
    parser.add_argument("--check", action="store_true", help="verify configured services respond")
    parser.add_argument("--only", choices=["all", "dooray", "kaist", "manual", "portal"], default="all")
    args = parser.parse_args()

    settings = load_settings()
    if args.check:
        return check(settings)
    try:
        repo = build_repo(settings, args.dry_run)
    except SupabaseError as exc:
        print(f"[error] supabase unreachable: {exc}")
        return 2
    if args.review_report:
        review_report(repo)
        return 0

    started = datetime.now(KST)
    if not args.export_only:
        extractor = build_extractor(settings, args.dry_run)
        pipeline = Pipeline(settings, repo, extractor, build_collectors(settings, repo, args.only))
        stats = pipeline.run()
        print(stats.summary())
        if stats.collector_errors:
            print("collector errors: " + ", ".join(f"{k}: {v[:80]}" for k, v in stats.collector_errors.items()))
        if stats.collector_errors and len(stats.collector_errors) == len([c for c in pipeline.collectors if c.enabled()]):
            print("[error] every collector failed; not exporting")
            return 2
    code = export(settings, repo, args.dry_run)
    print(f"done in {(datetime.now(KST) - started).total_seconds():.1f}s")
    return code


if __name__ == "__main__":
    sys.exit(main())
