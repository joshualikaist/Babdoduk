# -*- coding: utf-8 -*-
"""Worker actions of the Instagram radar (scripts/windows/ggongbab_workers.py; ops.sh ig-*).

  ig-check              configuration, token scopes and expiry, models, accounts, Telegram (no values)
  ig-radar-once         one cycle; --dry-run collects and analyzes but sends nothing and writes no task
  ig-radar              the resident loop: a cycle every LOOP_SECONDS, Telegram answers in between
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
        writer = TaskWriter(load_settings())
        writer.verify_project()
    radar = Radar(root, config=config, graph=graph, judge=an.Judge(_openai()), bot=Bot(token, chat) if token and chat else None,
                  writer=writer, log=SafeLog(local / LOG), dry_run=dry_run)
    radar.store.sync_accounts(load_accounts(root))
    return radar


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
