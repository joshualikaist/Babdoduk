# -*- coding: utf-8 -*-
"""Instagram: not configured.

Agent Reach reaches Instagram through OpenCLI driving an already logged-in local Chrome. For
Babdoduk that is local-only work with a dedicated monitoring account and profile, never in
GitHub Actions, never with copied cookies, stopping on any challenge. Until that exists and is
approved, this adapter reports NOT_CONFIGURED and contributes nothing - no placeholder links,
no invented posts. Instagram finds, once enabled, enter the candidate store as Tier-C
discovery candidates, not direct publication."""
from __future__ import annotations

from . import NOT_CONFIGURED, AdapterResult


def discover(source: dict) -> AdapterResult:
    return AdapterResult(NOT_CONFIGURED, code="OPENCLI_NOT_CONFIGURED")
