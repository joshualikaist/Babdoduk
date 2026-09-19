# -*- coding: utf-8 -*-
"""Unattended Dooray mailbox agent: scan -> filter -> register as project task.

One manual SSO login, then no human input:

    python scripts/dooray_web_agent.py --setup --url https://<your-dooray-host>/
    python scripts/dooray_web_agent.py --discover
    python scripts/dooray_web_agent.py --run --run-pipeline

The agent does no event analysis. It moves candidate mails into the collection
project; refresh_ggongbab.py does the rest (OpenAI -> Supabase -> latest.json).

Passwords are never read, stored or typed. When the SSO session expires the run
stops with AUTH_REQUIRED (10) and asks for one manual login.

Exit codes: 0 success · 10 auth required · 20 UI changed · 30 project not found
            · 40 pipeline failed
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ggongbab.config import KST, load_settings  # noqa: E402
from ggongbab.prefilter import classify  # noqa: E402
from ggongbab.web import browser as browser_mod  # noqa: E402
from ggongbab.web.browser import browser_session, run_setup  # noqa: E402
from ggongbab.web.exit_codes import (NAMES, SUCCESS, AgentError, AuthRequired,  # noqa: E402
                                     PipelineFailed, UiContractError)
from ggongbab.web.mail_reader import discover, list_mails, open_body  # noqa: E402
from ggongbab.web.state import AgentState  # noqa: E402
from ggongbab.web.task_writer import DEFAULT_PROJECT_NAME, MailPayload, TaskWriter  # noqa: E402
from ggongbab.web.ui_contract import load_contract  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / ".local"
PROFILE_DIR = LOCAL_DIR / browser_mod.PROFILE_DIRNAME
STATE_FILE = LOCAL_DIR / "ggongbab-mail-state.json"
CONTRACT_FILE = LOCAL_DIR / "dooray-ui.json"
DISCOVERY_FILE = LOCAL_DIR / "dooray-discovery.json"


def stamp() -> str:
    return datetime.now(KST).strftime("[%H:%M]")


def log(message: str) -> None:
    print(message, flush=True)


# ---------------------------------------------------------------------------
def cmd_setup(args) -> int:
    contract = load_contract(CONTRACT_FILE)
    start = args.url or contract.mail_url
    if not start:
        log("[error] first setup needs the Dooray address")
        log("        python scripts/dooray_web_agent.py --setup --url https://<your-dooray-host>/")
        return 1
    settled = run_setup(PROFILE_DIR, contract, start, CONTRACT_FILE, log=log)
    log(f"mail_url recorded: {settled.split('?')[0]}")
    log("")
    log("Next: python scripts/dooray_web_agent.py --discover")
    log("      That records how the mail page loads, so --run never has to guess.")
    return SUCCESS


def cmd_discover(args) -> int:
    contract = load_contract(CONTRACT_FILE)
    if not contract.mail_url:
        raise UiContractError("no mailbox URL recorded yet", hint="run --setup first")
    with browser_session(PROFILE_DIR, contract, headless=False) as session:
        session.assert_authenticated()
        report = discover(session, DISCOVERY_FILE)
    json_calls = report.get("jsonCalls") or []
    log(f"recorded {len(json_calls)} JSON call shape(s) -> {DISCOVERY_FILE}")
    for call in json_calls[:15]:
        log(f"  {call['method']:4} {call['status']}  {call['url']}")
    landmarks = (report.get("domLandmarks") or {}).get("repeated") or []
    if landmarks:
        log("repeated DOM containers (mail rows are usually among these):")
        for row in landmarks[:10]:
            log(f"  {row['count']:>4}x  {row['selector']}")
    log("")
    log(f"Fill {CONTRACT_FILE.name} using this report, then set \"verified\": true.")
    log("Until it is verified, --run exits 20 without touching anything.")
    return SUCCESS


# ---------------------------------------------------------------------------
def _window(args, state: AgentState) -> tuple[date, date]:
    today = datetime.now(KST).date()
    if args.since_last_run:
        return state.since_last_run(args.days), today
    start = args.date_from or (today - timedelta(days=args.days - 1))
    end = args.date_to or today
    return start, end


def cmd_run(args) -> int:
    settings = load_settings()
    state = AgentState.load(STATE_FILE)
    contract = load_contract(CONTRACT_FILE)
    contract.require_ready()

    start, end = _window(args, state)
    log(f"{stamp()}")
    log(f"window: {start.isoformat()} .. {end.isoformat()}")

    writer = TaskWriter(settings, project_name=args.project_name)
    writer.verify_project()          # fail closed before a browser even opens
    log(f"project: verified ({args.project_name})")

    scanned = already = candidates = registered = 0
    opened = 0
    with browser_session(PROFILE_DIR, contract, headless=not args.headed) as session:
        session.assert_authenticated()
        log("session: ok")
        headers = list_mails(session, limit=args.max_mails)
        for header in headers:
            if header.received and not (start <= header.received <= end):
                continue
            scanned += 1
            if state.seen(header.mail_id):
                already += 1
                continue
            decision = classify(header.subject, header.preview)
            if not decision.candidate and args.open_body and not args.subject_only:
                # The preview is short; a mail that looks plausible from its
                # subject gets its body read before being dismissed.
                if decision.has_event_word or decision.has_meal_time:
                    open_body(session, header)
                    opened += 1
                    decision = classify(header.subject, header.text_for_filter)
            elif decision.candidate and args.open_body:
                open_body(session, header)
                opened += 1
            if not decision.candidate:
                state.record(header.mail_id, header.subject, header.received,
                             registered=False, outcome="filtered")
                continue
            candidates += 1
            payload = MailPayload(mail_id=header.mail_id, subject=header.subject,
                                  body=header.body or header.preview, received=header.received,
                                  preview_only=not header.body_opened)
            try:
                post_id = writer.create_task(payload, dry_run=args.dry_run)
            except AgentError:
                state.record(header.mail_id, header.subject, header.received,
                             registered=False, outcome="write-failed")
                state.save()
                raise
            if not args.dry_run:
                registered += 1
            state.record(header.mail_id, header.subject, header.received,
                         registered=bool(post_id), outcome="candidate")

    state.mark_run(end)
    state.prune()
    if not args.dry_run:
        state.save()

    log(f"mail scanned: {scanned}")
    log(f"already processed: {already}")
    log(f"new: {scanned - already}")
    log(f"bodies opened: {opened}")
    log(f"candidates: {candidates}")
    log(f"registered: {registered}{' (dry run)' if args.dry_run else ''}")

    if args.run_pipeline and registered:
        return _run_pipeline()
    if args.run_pipeline:
        log("pipeline: skipped (nothing new registered)")
    return SUCCESS


def _run_pipeline() -> int:
    log("pipeline: running refresh_ggongbab.py --only dooray")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "refresh_ggongbab.py"), "--only", "dooray"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (result.stdout or "").splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        for line in (result.stderr or "").splitlines()[-5:]:
            log(f"  {line}")
        raise PipelineFailed(f"refresh_ggongbab.py exited {result.returncode}")
    log("pipeline: success")
    return SUCCESS


def cmd_selftest(args) -> int:
    settings = load_settings()
    writer = TaskWriter(settings, project_name=args.project_name)
    post_id = writer.selftest()
    log(f"write contract ok; created post {post_id}")
    log("Delete that task in Dooray when you are done.")
    return SUCCESS


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--setup", action="store_true", help="open a browser once for the manual SSO login")
    mode.add_argument("--discover", action="store_true", help="record how the mail page loads")
    mode.add_argument("--run", action="store_true", help="unattended scan and register")
    mode.add_argument("--selftest", action="store_true", help="create one harmless task to verify write access")

    parser.add_argument("--url", help="Dooray address, needed on the first --setup")
    parser.add_argument("--from", dest="date_from", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        metavar="YYYY-MM-DD", help="earliest received date to scan")
    parser.add_argument("--to", dest="date_to", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        metavar="YYYY-MM-DD", help="latest received date to scan")
    parser.add_argument("--since-last-run", action="store_true", help="scan from the previous run (with a day of overlap)")
    parser.add_argument("--days", type=int, default=3, help="default window when no dates are given (default 3)")
    parser.add_argument("--max-mails", type=int, default=200, help="safety limit on rows read (default 200)")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME,
                        help="exact project name that must match, or nothing is written")
    parser.add_argument("--run-pipeline", action="store_true", help="run refresh_ggongbab.py --only dooray afterwards")
    parser.add_argument("--dry-run", action="store_true", help="scan and filter but create no task and keep state unchanged")
    parser.add_argument("--headed", action="store_true", help="show the browser during --run (debugging)")
    parser.add_argument("--subject-only", action="store_true",
                        help="never open a mail body, so no mail is marked read (tasks carry subject + preview only)")
    parser.add_argument("--no-open-body", dest="open_body", action="store_false",
                        help="alias of --subject-only")
    parser.set_defaults(open_body=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.subject_only:
        args.open_body = False
    try:
        if args.setup:
            return cmd_setup(args)
        if args.discover:
            return cmd_discover(args)
        if args.selftest:
            return cmd_selftest(args)
        return cmd_run(args)
    except AgentError as exc:
        name = NAMES.get(exc.code, "ERROR")
        log(f"[{name}] {exc}")
        if exc.hint:
            log(f"          {exc.hint}")
        return exc.code
    except KeyboardInterrupt:
        log("[interrupted]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
