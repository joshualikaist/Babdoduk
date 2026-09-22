# -*- coding: utf-8 -*-
"""Exit-code contract for the unattended agent.

Windows Task Scheduler shows the last result code, so each failure mode gets its
own number and a watchdog can tell "log in again" apart from "the UI changed".
"""
from __future__ import annotations

SUCCESS = 0
AUTH_REQUIRED = 10      # SSO session expired; a human must run --setup
UI_CHANGED = 20         # selectors / page structure no longer match: refuse to act
PROJECT_NOT_FOUND = 30  # the collection project did not verify exactly
PIPELINE_FAILED = 40    # mails registered, but refresh_ggongbab.py failed

NAMES = {
    SUCCESS: "SUCCESS",
    AUTH_REQUIRED: "AUTH_REQUIRED",
    UI_CHANGED: "UI_CHANGED",
    PROJECT_NOT_FOUND: "PROJECT_NOT_FOUND",
    PIPELINE_FAILED: "PIPELINE_FAILED",
}


class AgentError(Exception):
    """Base class; every subclass maps to one exit code."""

    code = 1

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


class AuthRequired(AgentError):
    code = AUTH_REQUIRED


class UiContractError(AgentError):
    """The page did not look the way the recorded contract says it should.

    Raised instead of guessing. Nothing is written when this fires.
    """

    code = UI_CHANGED


class ProjectNotFound(AgentError):
    code = PROJECT_NOT_FOUND


class PipelineFailed(AgentError):
    code = PIPELINE_FAILED
