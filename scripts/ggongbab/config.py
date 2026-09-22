# -*- coding: utf-8 -*-
"""Environment-driven configuration for the ggongbab pipeline.

Secrets are read from the environment only. Nothing here is hard-coded.
A local .env file (gitignored) is loaded if present, without overriding
values that are already exported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "ggongbab"
KST = timezone(timedelta(hours=9), name="Asia/Seoul")
# Bump whenever SYSTEM_PROMPT changes meaning: cached parses are keyed on this,
# so a new version re-parses stored items instead of reusing older extractions.
# v2: explicit-evidence rules for registration_required and eligibility.
PROMPT_VERSION = "ggongbab-extract-v2"

# Supabase backend key, in priority order. SUPABASE_SECRET_KEY is the current name;
# SUPABASE_SERVICE_ROLE_KEY is the legacy name and is read only as a fallback.
SUPABASE_KEY_ENV = ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")


def _first_env(*names: str) -> tuple[str, str]:
    """Return (variable_name, value) of the first non-empty variable, or ("", "")."""
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return name, value
    return "", ""


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    # Dooray
    dooray_token: str = field(default_factory=lambda: os.environ.get("DOORAY_API_TOKEN", ""))
    dooray_project_id: str = field(default_factory=lambda: os.environ.get("DOORAY_PROJECT_ID", "4424523215847914253"))
    dooray_base: str = field(default_factory=lambda: os.environ.get("DOORAY_API_BASE", "https://api.gov-dooray.com"))
    dooray_page_size: int = field(default_factory=lambda: _int("DOORAY_PAGE_SIZE", 100))
    dooray_max_pages: int = field(default_factory=lambda: _int("DOORAY_MAX_PAGES", 5))

    # Supabase (backend only; never exposed to the browser)
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", "").rstrip("/"))
    supabase_secret_key: str = field(default_factory=lambda: _first_env(*SUPABASE_KEY_ENV)[1])
    supabase_key_env: str = field(default_factory=lambda: _first_env(*SUPABASE_KEY_ENV)[0])

    # OpenAI
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: os.environ.get("GGONGBAB_AI_MODEL", "gpt-5.6-luna"))
    # Empty by default: production runs on the primary model alone. The fallback
    # is an operator-controlled comparison tool, not part of normal extraction.
    # An ambiguous source should end up in needs_review, not be guessed at by a
    # model that costs about ten times as much per token.
    ai_fallback_model: str = field(default_factory=lambda: os.environ.get("GGONGBAB_AI_FALLBACK_MODEL", "").strip())
    ai_confidence_threshold: float = field(default_factory=lambda: _float("GGONGBAB_AI_CONFIDENCE_THRESHOLD", 0.75))
    ai_max_images: int = field(default_factory=lambda: _int("GGONGBAB_AI_MAX_IMAGES", 2))
    ai_max_image_bytes: int = field(default_factory=lambda: _int("GGONGBAB_AI_MAX_IMAGE_BYTES", 6 * 1024 * 1024))

    # Export
    publish_confidence_threshold: float = field(default_factory=lambda: _float("GGONGBAB_PUBLISH_CONFIDENCE", 0.7))
    expired_grace_hours: int = field(default_factory=lambda: _int("GGONGBAB_EXPIRED_GRACE_HOURS", 3))
    export_horizon_days: int = field(default_factory=lambda: _int("GGONGBAB_EXPORT_HORIZON_DAYS", 60))

    # Collectors
    kaist_public_enabled: bool = field(default_factory=lambda: _bool("GGONGBAB_KAIST_PUBLIC_ENABLED", True))
    kaist_public_max_items: int = field(default_factory=lambda: _int("GGONGBAB_KAIST_PUBLIC_MAX_ITEMS", 40))
    manual_path: Path = field(default_factory=lambda: Path(os.environ.get("GGONGBAB_MANUAL_PATH", str(DATA_DIR / "manual.json"))))

    # Dedup
    dedup_threshold: float = field(default_factory=lambda: _float("GGONGBAB_DEDUP_THRESHOLD", 0.72))

    @property
    def has_dooray(self) -> bool:
        return bool(self.dooray_token and self.dooray_project_id)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_secret_key)

    @property
    def supabase_key_is_legacy(self) -> bool:
        return self.supabase_key_env == "SUPABASE_SERVICE_ROLE_KEY"

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


def load_settings() -> Settings:
    return Settings()
