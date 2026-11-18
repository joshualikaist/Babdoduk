# -*- coding: utf-8 -*-
"""Worker actions of the Instagram radar (scripts/windows/ggongbab_workers.py; ops.sh ig-*).

  ig-check              configuration, token scopes and expiry, models, accounts, Telegram (no values)
  ig-radar-once         one cycle; --dry-run collects and analyzes but sends nothing and writes no task
  ig-radar              the resident loop: a cycle every LOOP_SECONDS, Telegram answers in between
  telegram-notes        the owner's latest notes to the bot (what Claude reads; .local/telegram-inbox.jsonl)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..ops_storage import SafeLog, atomic_json
from . import analyze as an
from .meta_graph import REQUIRED_SCOPES, GraphClient, GraphError
from .radar import LOCK, LOG, LOOP_SECONDS, STATE, Config, Radar, check_models, load_accounts


def _openai():
    from openai import OpenAI
    from ..config import load_settings
    return OpenAI(api_key=load_settings().openai_api_key, timeout=120, max_retries=2)


class DeferredWriter:
    """The Dooray collection writer, verified on first use instead of at start.

    Dooray closed its API for days after the 2026-11-13 incident and then rejected the old key.
    A start that required a verified project took the whole radar down with it, and with it the
    owner's Telegram bot, the tip review and the held-event buttons. Now the radar starts anyway:
    a hand-over before the project verifies raises ProjectNotFound, which the bridge and the tips
    already treat as "retry next cycle", so nothing is lost. Re-verification is tried at most once
    per RETRY_SECONDS; once it succeeds the real writer is used unchanged, still fail-closed."""

    RETRY_SECONDS = 300

    def __init__(self, writer, *, now=time.time):
        self._writer, self._now, self._next_try = writer, now, 0.0

    @property
    def verified(self) -> bool:
        return bool(getattr(self._writer, "_verified", False))

    def verify(self) -> bool:
        if self.verified:
            return True
        if self._now() < self._next_try:
            return False
        try:
            self._writer.verify_project()
            return True
        except Exception:  # noqa: BLE001 - any failure leaves the writer unverified; retried later
            self._next_try = self._now() + self.RETRY_SECONDS
            return False

    def create_task(self, *args, **kwargs):
        from ..web.exit_codes import ProjectNotFound
        if not self.verify():
            raise ProjectNotFound("Dooray collection project not verified yet")
        return self._writer.create_task(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._writer, name)


def build(root: Path, *, dry_run: bool) -> Radar:
    from .telegram_review import Bot, credentials
    config = Config()
    if config.missing():
        raise SystemExit("IG_CONFIG_REQUIRED: " + ", ".join(config.missing()))
    local = Path(root) / ".local"
    graph = GraphClient(config.token, version=config.version, ig_user_id=config.ig_user_id, app_secret=config.app_secret)
    token, chat = credentials(local)
    writer = None
    if not dry_run:
        from ..config import load_settings
        from ..web.task_writer import TaskWriter
        writer = DeferredWriter(TaskWriter(load_settings()))
    radar = Radar(root, config=config, graph=graph, judge=an.Judge(_openai()), bot=Bot(token, chat) if token and chat else None,
                  writer=writer, log=SafeLog(local / LOG), dry_run=dry_run)
    if writer is not None and not writer.verify():
        radar.log("IG_DOORAY_UNVERIFIED")
        radar.alert("dooray:unverified", "두레이에 연결되지 않습니다. 인스타그램·제보 행사는 모아 두었다가 "
                    "연결되면 넘깁니다. 두레이 열쇠를 확인해 주세요.", every=12 * 3600)
    radar.store.sync_accounts(load_accounts(root))
    if not dry_run:
        from ..config import load_settings
        from ..tips import build as tips
        from ..tips import report_classifier
        # Reports are read by the radar's own primary model and client (docs/GGONGBAB_TIPS.md).
        classify = report_classifier(radar.judge.client, config.primary, radar.store, time.time)
        radar.tips = tips(load_settings(), radar.bot, writer, store=radar.store, now=time.time, log=radar.log,
                          classify=classify)
        radar.dispatch = dispatcher(root)
        radar.ingest = ingest_reader(load_settings())
        from ..held import build as held
        radar.held = held(load_settings(), radar.bot, store=radar.store, now=time.time, log=radar.log,
                          on_publish=lambda: radar.request_refresh(True))
    return radar


def ingest_reader(settings):
    """The newest Dooray ingest runs of the cloud refresh, for Radar.check_ingest (read only)."""
    if not getattr(settings, "has_supabase", False):
        return None
    from ..db.supabase_client import SupabaseClient
    db = SupabaseClient(settings.supabase_url, settings.supabase_secret_key)
    return lambda: db.select("ingest_runs", {"select": "status,started_at,error_message", "source_type": "eq.dooray",
                                             "order": "started_at.desc", "limit": "12"})


def dispatcher(root: Path):
    """The cloud-refresh request for what the radar and the tips hand over. It shares the Dooray Radar's
    operator switch (radar-dispatch-on / -off) and its debounce state, so the two radars together still
    send at most one request per 5 minutes and DAILY_CAP a day (docs/GGONGBAB_TRIGGER.md). Every call is
    also the keep-alive: the radar calls this every ~25 s, so a run goes out when none went for 30 minutes."""
    from ..dispatch import request_refresh
    from ..dooray_radar import RadarFiles
    files = RadarFiles(root)

    def send(new: bool) -> str:
        if not files.dispatch_enabled():
            return "DISPATCH_OFF"
        return request_refresh(files.dispatch, new_candidates=new, keepalive=True)
    return send


def notes(root: Path, limit: int = 20) -> int:
    """The owner's latest Telegram notes (telegram_review.keep_note), oldest first."""
    from .telegram_review import read_notes
    for entry in read_notes(Path(root) / ".local", limit):
        print(entry.get("at", ""), entry.get("text", ""), f"[사진 {entry['photo']}]" if entry.get("photo") else "")
    return 0


def models_ready(radar: Radar) -> bool:
    """Checked once a day: a missing model or one that refuses images stops the radar (never a swap)."""
    if time.time() - float(radar.store.get("models_checked", 0)) < 86400:
        return True
    problems = check_models(_openai(), radar.config)
    if problems:
        radar.log("IG_MODEL_UNAVAILABLE")
        radar.alert("models", "분석 모델 문제로 멈췄습니다: " + "; ".join(problems))
        print("IG_MODEL_UNAVAILABLE: " + "; ".join(problems))
        return False
    radar.store.put("models_checked", time.time())
    return True


def write_state(radar: Radar, code: str) -> None:
    atomic_json(radar.local / STATE, {"reason": code, "observed": time.time(), "counts": radar.counts,
                                       "slow_factor": radar.store.get("slow_factor", 1),
                                       "backoff_until": radar.store.get("backoff_until", 0)})


def check(root: Path) -> int:
    config = Config()
    print("config missing  :", ", ".join(config.missing()) or "-")
    from .telegram_review import credentials
    token, chat = credentials(Path(root) / ".local")
    print("telegram        :", "configured" if token and chat else "not configured")
    print("accounts        :", ", ".join(r["username"] for r in load_accounts(root)))
    print("models          :", config.primary, "/", config.review)
    problems = check_models(_openai(), config)
    print("model check     :", "; ".join(problems) or "ok (present, image input accepted)")
    if config.missing():
        return 1
    graph = GraphClient(config.token, version=config.version, ig_user_id=config.ig_user_id, app_secret=config.app_secret)
    try:
        status = graph.token_status()
    except GraphError as exc:
        print("token           : rejected (" + exc.kind + ")")
        return 1
    missing = REQUIRED_SCOPES - status["scopes"]
    print("token           :", "valid" if status["valid"] else "INVALID",
          "| expires", "never" if not status["expires_at"] else time.strftime("%Y-%m-%d", time.localtime(status["expires_at"])))
    print("required scopes :", "all 4 present" if not missing else "MISSING " + ", ".join(sorted(missing)))
    extra = sorted(status["scopes"] - REQUIRED_SCOPES - {"public_profile"})
    if extra:
        print("other scopes    :", ", ".join(extra), "(not used by this radar)")
    return 0 if status["valid"] and not missing and not problems else 1


def once(root: Path, *, dry_run: bool) -> int:
    from ..portal_list_state import ListStateError, poller_lock
    try:
        with poller_lock(Path(root) / ".local" / LOCK):
            radar = build(root, dry_run=dry_run)
            if not models_ready(radar):
                return 1
            code = radar.cycle()
            write_state(radar, code)
            print(code, json.dumps(radar.counts, ensure_ascii=False))
            return 0 if code == "IG_RADAR_CYCLE_OK" else 1
    except ListStateError:
        print("IG_RADAR_BUSY")
        return 1


def loop(root: Path) -> int:
    from ..portal_list_state import ListStateError, poller_lock
    try:
        with poller_lock(Path(root) / ".local" / LOCK):
            radar = build(root, dry_run=False)
            radar.log("IG_RADAR_RUNNING")
            while True:
                if models_ready(radar):
                    try:
                        code = radar.cycle()
                    except Exception:  # noqa: BLE001 - one bad cycle must not end the resident radar
                        code = "IG_RADAR_CYCLE_FAILED"
                        radar.log(code)
                    write_state(radar, code)
                deadline = time.time() + LOOP_SECONDS
                while time.time() < deadline:
                    radar.review(wait=25)       # long polling: answers arrive within seconds
                    if radar.bot is None:
                        time.sleep(30)
    except ListStateError:
        print("IG_RADAR_BUSY")
        return 1
