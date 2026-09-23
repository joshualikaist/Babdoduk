"""Pure operational policy: fixed reasons, no content or account information."""
from .portal_session import SAFE_REASON_CODES

PORTAL_PORT = 9223
DOORAY_PORT = 9222
WARNING_SECONDS = 180
CRITICAL_SECONDS = 600
MAX_RESTARTS = 5

TRANSIENT = frozenset({
    "WORKER_EXITED", "PORTAL_LIST_CONNECT_TIMEOUT", "PORTAL_LIST_READ_TIMEOUT",
    "PORTAL_LIST_CONNECTION_ERROR", "PORTAL_LIST_TLS_ERROR", "PORTAL_LIST_CHUNK_READ_ERROR",
    "PORTAL_LIST_TRANSPORT_UNAVAILABLE", "PORTAL_HEARTBEAT_WRITE_FAILED",
})
HUMAN = frozenset({
    "PORTAL_LIST_AUTH_REQUIRED", "PORTAL_LIST_REDIRECT_REQUIRES_MANUAL_REVIEW",
    "PORTAL_SESSION_COOKIE_MISSING_OR_AMBIGUOUS", "PORTAL_SESSION_COOKIE_UNUSABLE",
    "PORTAL_CONTEXT_MISSING_OR_AMBIGUOUS", "PORTAL_SESSION_HANDOFF_FAILED",
    "PORTAL_LIST_SESSION_UNAVAILABLE", "PORTAL_UI_CHANGED", "PORTAL_RESIDENT_OWNER_UNVERIFIED",
    "PORTAL_LIST_STATE_UNAVAILABLE", "PORTAL_LIST_SCAN_INCOMPLETE", "OPS_STATE_UNAVAILABLE",
    "OPS_CONFIGURATION_REQUIRED", "OPS_RETRY_EXHAUSTED", "OPS_WORKER_UNRESPONSIVE",
})
REASONS = SAFE_REASON_CODES | TRANSIENT | HUMAN | frozenset({
    "WORKER_STARTING", "WORKER_RUNNING", "WORKER_STOPPED", "WORKER_ALREADY_RUNNING",
    "WATCHDOG_STARTING", "WATCHDOG_ALREADY_RUNNING", "PORTAL_BROWSER_STARTED",
    "PORTAL_BROWSER_RECOVERED", "PORTAL_BROWSER_ABSENT", "OPS_DISABLED",
    "PORTAL_OPERATION_STATUS", "DOORAY_RUN_OK", "DOORAY_RUN_FAILED",
})


def reason(value):
    return value if isinstance(value, str) and value in REASONS else "WORKER_EXITED"


def restart_action(code, attempts, browser_recoveries=0):
    code = reason(code)
    if code in HUMAN:
        return "manual", None
    if attempts >= MAX_RESTARTS:
        return "exhausted", None
    delay = min(60 * 2 ** attempts, 900)
    if code == "PORTAL_CDP_ATTACH_TIMEOUT":
        return ("recover", delay) if browser_recoveries < 1 else ("manual", None)
    if code in TRANSIENT:
        return "retry", delay
    return "manual", None


def alert_state(code, last_success, now):
    """Future notifier interface: stable enums + numeric age, never user content."""
    code = reason(code)
    age = max(0, int(now - last_success)) if last_success is not None else None
    if code in HUMAN or code == "PORTAL_CDP_ATTACH_TIMEOUT":
        severity, action = "critical", "operator_required"
    elif age is None or age > CRITICAL_SECONDS:
        severity, action = "critical", "collector_offline"
    elif age > WARNING_SECONDS or code in TRANSIENT or code == "PORTAL_BROWSER_ABSENT":
        severity, action = "warning", "collector_delayed"
    else:
        severity, action = "healthy", "none"
    return {"component": "portal", "severity": severity, "action": action,
            "reason": code, "last_success_age_seconds": age}
