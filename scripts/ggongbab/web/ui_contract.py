# -*- coding: utf-8 -*-
"""The recorded contract for Dooray's mail web UI.

Nothing in here is guessed. The file ships with `verified: false` and empty
selectors, and `--run` refuses to act until `--discover` has filled it in from a
real authenticated session. That is the same rule the API work followed: do not
invent an interface you have not seen.

`.local/dooray-ui.json` overrides this file, so a re-discovery never needs a
code change or a commit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .exit_codes import UiContractError

# URL fragments that mean "you are looking at a login screen, not the mailbox".
LOGIN_URL_HINTS = ("login", "signin", "sign-in", "sso", "auth", "idp", "nid", "account")


@dataclass
class UiContract:
    """Where the mail list lives and how to read one row."""

    verified: bool = False
    discovered_at: Optional[str] = None
    mail_url: str = ""                    # the mailbox page to open
    login_url_hints: tuple[str, ...] = LOGIN_URL_HINTS
    logged_in_marker: str = ""            # selector that only exists when logged in
    list_container: str = ""              # selector wrapping the mail rows
    row: str = ""                         # one mail row
    row_id_attr: str = ""                 # attribute on the row holding a stable mail id
    row_subject: str = ""                 # subject within a row
    row_preview: str = ""                 # snippet within a row (optional)
    row_date: str = ""                    # received date within a row
    row_unread_marker: str = ""           # class/selector marking an unread row (optional)
    body_container: str = ""              # mail body once opened
    next_page: str = ""                   # pagination control (optional)
    # Internal JSON endpoints the web app itself calls, if discovery found them.
    # Preferred over DOM scraping: stabler, and a list call does not open a mail.
    list_api: str = ""
    detail_api: str = ""
    # Filled by --calibrate from the live endpoint, never guessed.
    list_page_param: str = ""     # query parameter used to page (e.g. "page")
    list_size_param: str = ""     # query parameter used for page size
    read_state_key: str = ""      # row field holding read/unread, "" when none exists
    notes: str = ""

    REQUIRED_DOM = ("mail_url", "logged_in_marker", "row", "row_subject")

    @classmethod
    def load(cls, *paths: Path) -> "UiContract":
        data: dict[str, Any] = {}
        for path in paths:
            if path and path.exists():
                try:
                    data.update(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError) as exc:
                    raise UiContractError(f"cannot read UI contract {path.name}: {exc.__class__.__name__}") from exc
        known = {f for f in cls.__dataclass_fields__ if f != "login_url_hints"}
        kwargs = {k: v for k, v in data.items() if k in known}
        hints = data.get("login_url_hints")
        if isinstance(hints, list) and hints:
            kwargs["login_url_hints"] = tuple(str(h).lower() for h in hints)
        return cls(**kwargs)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: (list(v) if isinstance(v, tuple) else v)
                   for k, v in self.__dict__.items()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def require_ready(self) -> None:
        """Fail closed unless the contract was actually recorded from a real session."""
        if not self.verified:
            raise UiContractError(
                "the Dooray mail UI contract has not been recorded yet",
                hint="run: python scripts/dooray_web_agent.py --setup   then   --discover")
        if self.list_api:
            return  # an internal JSON endpoint needs no DOM selectors
        missing = [f for f in self.REQUIRED_DOM if not getattr(self, f)]
        if missing:
            raise UiContractError(
                f"UI contract is incomplete: {', '.join(missing)}",
                hint="re-run --discover; the mail UI may have changed")

    def looks_like_login(self, url: str) -> bool:
        low = (url or "").lower()
        return any(hint in low for hint in self.login_url_hints)


DEFAULT_CONTRACT_FILE = Path(__file__).with_name("dooray_ui.json")


def load_contract(local_override: Optional[Path] = None) -> UiContract:
    paths = [DEFAULT_CONTRACT_FILE]
    if local_override:
        paths.append(local_override)
    return UiContract.load(*[p for p in paths if p])
