# -*- coding: utf-8 -*-
"""Collect KAIST free-food events into Supabase and export data/ggongbab/latest.json
(live listings) and data/ggongbab/archive/index.json (listings that ended in the last 30 days).

    python scripts/refresh_ggongbab.py                 # full run (needs secrets)
    python scripts/refresh_ggongbab.py --export-only   # DB -> latest.json without collecting
    python scripts/refresh_ggongbab.py --review-report # list events waiting for review
    python scripts/refresh_ggongbab.py --dry-run       # in-memory DB, no AI, no file write
    python scripts/refresh_ggongbab.py --check         # verify configured services respond

One-off mailbox backfill from an exported mail archive (.eml / .mbox / .zip / folder).
Gov-Dooray has no mail REST API, so the archive is what the mail client exports:

    python scripts/refresh_ggongbab.py --backfill-mail-archive "C:\\mail-export" \\
        --mail-from 2026-09-01 --mail-to 2026-09-19 --event-until 2026-09-30 --dry-run

Exit codes: 0 ok · 1 hard failure · 2 nothing safe to publish (previous JSON kept).
Nothing private (mail text, addresses, tokens) is printed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.collectors.dooray import DoorayClient, DoorayCollector  # noqa: E402
from ggongbab.collectors.kaist_public import KaistPublicCollector  # noqa: E402
from ggongbab.collectors.manual import ManualCollector  # noqa: E402
from ggongbab.collectors.portal import PortalCollector  # noqa: E402
from ggongbab.config import DATA_DIR, KST, Settings, load_settings  # noqa: E402
from ggongbab.db.repository import MemoryRepository, SupabaseRepository  # noqa: E402
from ggongbab.db.supabase_client import SupabaseClient, SupabaseError  # noqa: E402
from ggongbab.exporter import (ARCHIVE_LOOKBACK_DAYS, build_archive, build_payload,  # noqa: E402
                               previously_listed_ids, write_archive, write_payload)
from ggongbab.parsers import ai_errors  # noqa: E402
from ggongbab.pipeline import Pipeline  # noqa: E402
from ggongbab.pricing import usage_lines  # noqa: E402

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


def validate_archive_export(path: Path, live_payload: dict) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_content import validate_ggongbab_archive  # type: ignore

    return validate_ggongbab_archive(path, {ev["id"] for ev in live_payload.get("events") or []})


def export(settings: Settings, repo, dry_run: bool) -> int:
    # One clock for both files: a row is live or archived, never both and never neither.
    now = datetime.now(KST)
    payload = build_payload(repo.publishable_events(), settings, now, food_only=True)
    # Evidence of past publication is read before latest.json is replaced.
    archive = build_archive(repo.recent_published_events(ARCHIVE_LOOKBACK_DAYS), settings,
                            previously_listed_ids(DATA_DIR), now)
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        print(f"archive: {archive['count']} ended listing(s) in the last {archive['windowDays']} days")
        return 0
    tmp_dir = DATA_DIR / ".staging"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    staged = write_payload(payload, tmp_dir)
    errors = validate_export(staged)
    if errors:
        print("[error] export validation failed; keeping previous latest.json and archive")
        for err in errors:
            print("  -", err)
        staged.unlink(missing_ok=True)
        return 2
    staged_archive = write_archive(archive, tmp_dir)
    archive_errors = validate_archive_export(staged_archive, payload)
    final = write_payload(payload, DATA_DIR)
    # The live feed matters more than the record: a bad archive keeps the previous
    # one (or none) and is reported, but does not hold back latest.json.
    if archive_errors:
        print("[warn] archive validation failed; keeping previous archive/index.json")
        for err in archive_errors:
            print("  -", err)
    else:
        write_archive(archive, DATA_DIR)
    staged.unlink(missing_ok=True)
    staged_archive.unlink(missing_ok=True)
    for folder in (staged_archive.parent, tmp_dir):
        try:
            folder.rmdir()
        except OSError:
            pass
    print(f"wrote {final.relative_to(ROOT)} events={payload['count']} "
          f"archive={'kept' if archive_errors else archive['count']}")
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


def _day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None


def backfill_mail_archive(settings: Settings, repo, args) -> int:
    """Read an exported mail archive and run the normal pipeline over the candidates."""
    from ggongbab.backfill import run_backfill
    from ggongbab.collectors.base import CollectorError
    from ggongbab.collectors.mail_archive import MailArchiveCollector

    path = Path(args.backfill_mail_archive).expanduser()
    if not path.exists():
        print(f"[error] mail archive not found: {path}")
        print("        Export the mails from the Dooray web client first (see docs/GGONGBAB_PAGE.md).")
        return 1
    collector = MailArchiveCollector(settings, path, mail_from=args.mail_from, mail_to=args.mail_to,
                                     read_state=args.read_state, max_mails=args.max_mails)
    try:
        items = collector.collect()
    except CollectorError as exc:
        print(f"[error] {exc}")
        return 1
    # A dry run still parses for real, so the report shows the decisions the
    # ingest would make. Its safety comes from the in-memory repository and from
    # not touching latest.json. Only --no-ai suppresses the model.
    extractor = None if args.no_ai else build_extractor(settings, False)
    if extractor is None and not args.no_ai:
        print("[error] OPENAI_API_KEY is required for a backfill; use --no-ai to only count candidates")
        return 1
    if not args.dry_run:
        try:
            repo.source_id("dooray_mailbox")
        except SupabaseError as exc:
            print(f"[error] cannot register the dooray_mailbox source: {exc}")
            print("        Apply supabase/migrations/002_ggongbab_mailbox_source.sql in the Supabase SQL editor first.")
            return 1
    report = run_backfill(settings, repo, extractor, items, event_until=args.event_until,
                          max_ai_candidates=args.max_ai_candidates, force=args.force,
                          use_ai=not args.no_ai)
    print(report.render(args.event_until, dry_run=args.dry_run))
    stats = collector.stats
    print(f"\narchive: {stats.messages} message(s) read · out of date range: {stats.out_of_range} · "
          f"read-state filtered: {stats.filtered_read_state} · unparsable: {stats.skipped_unparsable}")
    if report.stopped_reason:
        return 1
    if args.dry_run:
        print("\nNo database write and no latest.json change. Re-run without --dry-run to ingest.")
        return 0
    return export(settings, repo, False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="in-memory repository, no AI, no file write")
    parser.add_argument("--export-only", action="store_true", help="skip collectors; export DB -> latest.json")
    parser.add_argument("--review-report", action="store_true", help="print events with needs_review=true")
    parser.add_argument("--check", action="store_true", help="verify configured services respond")
    parser.add_argument("--only", choices=["all", "dooray", "kaist", "manual", "portal"], default="all")

    mail = parser.add_argument_group("mailbox backfill (one-off, read-only)")
    mail.add_argument("--backfill-mail-archive", metavar="PATH",
                      help="exported mail archive: .eml / .mbox / .zip file, or a folder of them")
    mail.add_argument("--mail-from", type=_day, metavar="YYYY-MM-DD", help="earliest mail received date")
    mail.add_argument("--mail-to", type=_day, metavar="YYYY-MM-DD", help="latest mail received date")
    mail.add_argument("--event-until", type=_day, metavar="YYYY-MM-DD", help="upper bound for the event date in the report")
    mail.add_argument("--read-state", choices=["all", "read", "unread"], default="all",
                      help="default all; mails whose export carries no read flag are always included")
    mail.add_argument("--max-mails", type=int, default=500, help="safety limit on messages scanned (default 500)")
    mail.add_argument("--max-ai-candidates", type=int, default=50,
                      help="stop before calling the model more than this many times (default 50)")
    mail.add_argument("--force", action="store_true", help="proceed past --max-ai-candidates")
    mail.add_argument("--no-ai", action="store_true", help="count candidates only; never call the model")
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
    if args.backfill_mail_archive:
        return backfill_mail_archive(settings, repo, args)

    started = datetime.now(KST)
    if not args.export_only:
        extractor = build_extractor(settings, args.dry_run)
        pipeline = Pipeline(settings, repo, extractor, build_collectors(settings, repo, args.only))
        stats = pipeline.run()
        print(stats.summary())
        for line in stats.stop_lines():
            print(line)
        for line in ai_errors.summary_lines(stats.ai_error_categories):
            print(line)
        for line in usage_lines(stats.model_usage):
            print(line)
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
