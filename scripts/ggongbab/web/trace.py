# -*- coding: utf-8 -*-
"""Browser lifecycle tracing for setup.

Built to answer one question with evidence instead of guesses: when KAIST SSO
finishes, does the mailbox come back into *this* automation context, or does it
end up in a browser we are not driving?

The live trace showed setup stopping at `/idp/multi` and then an `other-host`
login page, with no `/mail/...` navigation ever arriving. Recording page and
frame lifecycle events makes that visible rather than inferred.

Logs carry origin and path only. Query strings, cookies, headers, addresses and
mail content never appear.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse


def origin_and_path(url: str) -> tuple[str, str]:
    parsed = urlparse(url or "")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""
    return origin, (parsed.path or "/")


@dataclass
class LifecycleTracer:
    """Records pages opening, navigating, popping up and closing."""

    context: Any
    log: Any = print
    verbose: bool = True
    _numbers: dict[int, int] = field(default_factory=dict)
    _last: dict[str, str] = field(default_factory=dict)
    _attached: bool = False
    _page_handler: Any = None
    pages_created: int = 0
    paths_seen: list[str] = field(default_factory=list)
    origins_seen: list[str] = field(default_factory=list)

    # -- helpers -------------------------------------------------------
    def number(self, page) -> int:  # noqa: ANN001
        key = id(page)
        if key not in self._numbers:
            self._numbers[key] = len(self._numbers) + 1
        return self._numbers[key]

    def _note(self, url: str) -> tuple[str, str]:
        origin, path = origin_and_path(url)
        if path and path not in self.paths_seen:
            self.paths_seen.append(path)
        if origin and origin not in self.origins_seen:
            self.origins_seen.append(origin)
        return origin, path

    def _say(self, key: str, lines: list[str]) -> None:
        text = "\n".join(lines)
        if self._last.get(key) == text:
            return          # the same event repeated; say it once
        self._last[key] = text
        if self.verbose:
            self.log(text)

    # -- handlers ------------------------------------------------------
    def _on_page(self, page) -> None:  # noqa: ANN001
        self.pages_created += 1
        try:
            url = page.url or ""
        except Exception:  # noqa: BLE001
            url = ""
        origin, path = self._note(url)
        self._say(f"page-open-{self.number(page)}", [
            "[trace] new page",
            f"  page #{self.number(page)}",
            f"  origin: {origin or '(blank)'}",
            f"  path: {path}",
        ])
        self.watch(page)

    def _on_navigated(self, page, frame) -> None:  # noqa: ANN001
        try:
            url = frame.url or ""
            is_main = frame == page.main_frame
        except Exception:  # noqa: BLE001
            return
        if not url or url.startswith("about:"):
            return
        origin, path = self._note(url)
        self._say(f"nav-{self.number(page)}-{'main' if is_main else id(frame)}", [
            "[trace] navigation",
            f"  page #{self.number(page)}",
            f"  frame: {'main' if is_main else 'child'}",
            f"  origin: {origin}",
            f"  path: {path}",
        ])

    def _on_popup(self, popup) -> None:  # noqa: ANN001
        self._say(f"popup-{self.number(popup)}", [
            "[trace] popup", f"  page #{self.number(popup)}"])
        self.watch(popup)

    def _on_close(self, page) -> None:  # noqa: ANN001
        self._say(f"close-{self.number(page)}", [
            "[trace] page closed", f"  page #{self.number(page)}"])

    # -- wiring --------------------------------------------------------
    def watch(self, page) -> None:  # noqa: ANN001
        try:
            page.on("framenavigated", lambda frame, p=page: self._on_navigated(p, frame))
            page.on("popup", self._on_popup)
            page.on("close", self._on_close)
        except Exception:  # noqa: BLE001 - tracing must never break setup
            pass

    def start(self) -> None:
        if self._attached:
            return
        self._attached = True
        # Bound once: `self._on_page` builds a new object on every access, so
        # registering and removing would otherwise use two different callables.
        self._page_handler = self._on_page
        try:
            self.context.on("page", self._page_handler)
        except Exception:  # noqa: BLE001
            pass
        for page in list(getattr(self.context, "pages", []) or []):
            self.number(page)
            self.watch(page)

    def stop(self) -> None:
        if not self._attached:
            return
        self._attached = False
        handler = getattr(self, "_page_handler", None)
        if handler is None:
            return
        try:
            self.context.remove_listener("page", handler)
        except Exception:  # noqa: BLE001
            pass

    # -- summary -------------------------------------------------------
    def saw_path(self, prefix: str) -> bool:
        return any(p.startswith(prefix) for p in self.paths_seen)

    def summary(self) -> list[str]:
        return [
            f"pages tracked: {len(self._numbers)} (opened during the run: {self.pages_created})",
            f"origins seen: {', '.join(self.origins_seen) or '(none)'}",
            f"paths seen: {', '.join(self.paths_seen[:12]) or '(none)'}",
        ]
