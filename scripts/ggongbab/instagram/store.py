# -*- coding: utf-8 -*-
"""The Instagram radar's local state on the operations PC: one SQLite file (.local/ig-radar.sqlite3)
and the downloaded images (.local/ig-media/<sha256>.<ext>). The canonical event store stays the
existing pipeline: a confirmed post reaches it as a Dooray collection task (radar.py).

Tables follow docs/INSTAGRAM_RADAR.md: ig_accounts, ig_posts, ig_post_images, analysis_runs,
food_event_candidates, human_reviews, api_usage_log, plus a small key-value table `kv` for the
Telegram offset, the backoff and the slow-down multiplier. No secret is ever written here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS ig_accounts (
  username TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', interval_minutes INTEGER NOT NULL DEFAULT 180,
  active INTEGER NOT NULL DEFAULT 1, last_success REAL, last_checked REAL, last_media_id TEXT,
  status TEXT NOT NULL DEFAULT 'ok', status_notified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ig_posts (
  media_id TEXT PRIMARY KEY, username TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL,
  permalink TEXT NOT NULL DEFAULT '', media_type TEXT NOT NULL DEFAULT '', raw_json TEXT NOT NULL,
  fetched_at REAL NOT NULL, prefilter TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS ig_post_images (
  media_id TEXT NOT NULL, position INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
  PRIMARY KEY (media_id, position));
CREATE TABLE IF NOT EXISTS analysis_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, media_id TEXT NOT NULL, stage TEXT NOT NULL, model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0,
  result_json TEXT, error TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS food_event_candidates (
  media_id TEXT PRIMARY KEY, status TEXT NOT NULL, merge_group TEXT NOT NULL, decided_by TEXT NOT NULL DEFAULT '',
  extraction_json TEXT NOT NULL, dooray_post_id TEXT, question_sent REAL, telegram_message_id INTEGER,
  updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS human_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, media_id TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_usage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, endpoint TEXT NOT NULL, outcome TEXT NOT NULL,
  app_usage TEXT, buc_usage TEXT, max_percent REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
STATUSES = frozenset({"auto_confirmed", "auto_rejected", "pending_human", "queued_digest", "human_confirmed",
                      "human_rejected", "expired"})   # expired: the event was over (analyze.is_past)


class Store:
    def __init__(self, local: Path):
        self.local = Path(local)
        self.media = self.local / "ig-media"
        self.media.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.local / "ig-radar.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    # --- key-value -------------------------------------------------------------------------------
    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def put(self, key: str, value) -> None:
        self.db.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value)))
        self.db.commit()

    # --- accounts --------------------------------------------------------------------------------
    def sync_accounts(self, rows: Iterable[dict]) -> None:
        """Add new accounts and update names, intervals and the active flag; state is kept."""
        for row in rows:
            self.db.execute(
                "INSERT INTO ig_accounts(username, display_name, interval_minutes, active) VALUES(?,?,?,?) "
                "ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name, "
                "interval_minutes=excluded.interval_minutes, active=excluded.active",
                (row["username"], row.get("display_name", ""), int(row.get("interval_minutes", 180)),
                 1 if row.get("active", True) else 0))
        self.db.commit()

    def accounts(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM ig_accounts WHERE active=1 ORDER BY username").fetchall()

    def account(self, username: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM ig_accounts WHERE username=?", (username,)).fetchone()

    def update_account(self, username: str, **fields) -> None:
        keys = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE ig_accounts SET {keys} WHERE username=?", (*fields.values(), username))
        self.db.commit()

    # --- posts and images ------------------------------------------------------------------------
    def has_post(self, media_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM ig_posts WHERE media_id=?", (media_id,)).fetchone() is not None

    def add_post(self, username: str, media: dict, now: float) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO ig_posts(media_id, username, caption, timestamp, permalink, media_type, raw_json, fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (str(media["id"]), username, media.get("caption") or "", media.get("timestamp") or "",
             media.get("permalink") or "", media.get("media_type") or "", json.dumps(media, ensure_ascii=False), now))
        self.db.commit()

    def post(self, media_id: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM ig_posts WHERE media_id=?", (media_id,)).fetchone()

    def set_prefilter(self, media_id: str, value: str) -> None:
        self.db.execute("UPDATE ig_posts SET prefilter=? WHERE media_id=?", (value, media_id))
        self.db.commit()

    def unanalyzed(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT p.* FROM ig_posts p LEFT JOIN food_event_candidates c ON c.media_id=p.media_id "
            "WHERE c.media_id IS NULL AND p.prefilter='' ORDER BY p.timestamp").fetchall()

    def save_image(self, media_id: str, position: int, data: bytes, ext: str) -> str:
        """Content-addressed: the same image is stored once, whichever post it came from."""
        digest = hashlib.sha256(data).hexdigest()
        path = self.media / f"{digest}.{ext}"
        if not path.exists():
            path.write_bytes(data)
        self.db.execute("INSERT OR REPLACE INTO ig_post_images(media_id, position, path, sha256) VALUES(?,?,?,?)",
                        (media_id, position, str(path), digest))
        self.db.commit()
        return str(path)

    def images(self, media_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM ig_post_images WHERE media_id=? ORDER BY position", (media_id,)).fetchall()

    # --- analysis, candidates, reviews ------------------------------------------------------------
    def add_run(self, media_id: str, stage: str, model: str, *, input_tokens=0, output_tokens=0, cost=0.0,
                result: Optional[dict] = None, error: str = "", now: Optional[float] = None) -> None:
        self.db.execute(
            "INSERT INTO analysis_runs(media_id, stage, model, input_tokens, output_tokens, cost_usd, result_json, error, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (media_id, stage, model, int(input_tokens), int(output_tokens), float(cost),
             json.dumps(result, ensure_ascii=False) if result is not None else None, error, now or time.time()))
        self.db.commit()

    def month_cost(self, since: float) -> float:
        row = self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) AS c FROM analysis_runs WHERE created_at>=?", (since,)).fetchone()
        return float(row["c"])

    def upsert_candidate(self, media_id: str, status: str, merge_group: str, extraction: dict, *,
                         decided_by: str = "", now: Optional[float] = None) -> None:
        if status not in STATUSES:
            raise ValueError(status)
        self.db.execute(
            "INSERT INTO food_event_candidates(media_id, status, merge_group, decided_by, extraction_json, updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET status=excluded.status, "
            "merge_group=excluded.merge_group, decided_by=excluded.decided_by, extraction_json=excluded.extraction_json, "
            "updated_at=excluded.updated_at",
            (media_id, status, merge_group, decided_by, json.dumps(extraction, ensure_ascii=False), now or time.time()))
        self.db.commit()

    def candidate(self, media_id: str) -> Optional[sqlite3.Row]:
        return self.db.execute("SELECT * FROM food_event_candidates WHERE media_id=?", (media_id,)).fetchone()

    def candidates(self, *statuses: str) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(statuses))
        return self.db.execute(f"SELECT * FROM food_event_candidates WHERE status IN ({marks}) ORDER BY updated_at",
                               statuses).fetchall()

    def update_candidate(self, media_id: str, **fields) -> None:
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(fields["status"])
        fields["updated_at"] = fields.get("updated_at") or time.time()
        keys = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE food_event_candidates SET {keys} WHERE media_id=?", (*fields.values(), media_id))
        self.db.commit()

    def group_members(self, merge_group: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM food_event_candidates WHERE merge_group=? ORDER BY updated_at",
                               (merge_group,)).fetchall()

    def recent_confirmed(self, username: str, since_iso: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT c.media_id, c.merge_group, c.extraction_json, p.timestamp FROM food_event_candidates c "
            "JOIN ig_posts p ON p.media_id=c.media_id WHERE p.username=? AND p.timestamp>=? "
            "AND c.status IN ('auto_confirmed','human_confirmed','pending_human','queued_digest')",
            (username, since_iso)).fetchall()
        return [dict(r) | {"extraction": json.loads(r["extraction_json"])} for r in rows]

    def add_review(self, media_id: str, action: str, payload: str = "", now: Optional[float] = None) -> None:
        self.db.execute("INSERT INTO human_reviews(media_id, action, payload, created_at) VALUES(?,?,?,?)",
                        (media_id, action, payload, now or time.time()))
        self.db.commit()

    def recent_labels(self, limit: int = 4) -> list[dict[str, Any]]:
        """The owner's latest verdicts with their posts, for few-shot examples."""
        rows = self.db.execute(
            "SELECT r.action, r.media_id, p.caption, c.extraction_json FROM human_reviews r "
            "JOIN ig_posts p ON p.media_id=r.media_id JOIN food_event_candidates c ON c.media_id=r.media_id "
            "WHERE r.action IN ('confirm','reject','edit') ORDER BY r.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def log_usage(self, endpoint: str, outcome: str, headers: Optional[dict], percent: float, now: float) -> None:
        headers = headers or {}
        self.db.execute("INSERT INTO api_usage_log(at, endpoint, outcome, app_usage, buc_usage, max_percent) VALUES(?,?,?,?,?,?)",
                        (now, endpoint, outcome, headers.get("X-App-Usage"), headers.get("X-Business-Use-Case-Usage"), percent))
        self.db.commit()

    def calls_since(self, since: float) -> int:
        return int(self.db.execute("SELECT COUNT(*) AS n FROM api_usage_log WHERE at>=?", (since,)).fetchone()["n"])
