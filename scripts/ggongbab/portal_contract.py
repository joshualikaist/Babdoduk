# -*- coding: utf-8 -*-
"""Observed Portal HTTP contract. Empty until --discover/--calibrate succeed."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

TITLE_KEYS = {"title", "subject", "noticetitle", "bbsstit", "ntttitle"}
ID_KEYS = {"id", "noticeid", "bbsid", "nttid", "seq", "uid", "articleid"}
DATE_KEYS = {"createdat", "createddate", "regdate", "regdt", "date", "writedate", "updatedat"}
BODY_KEYS = {"body", "content", "contents", "html", "text", "nttcont"}


@dataclass
class PortalContract:
    verified: bool = False
    start_url: str = "https://portal.kaist.ac.kr/"
    list_method: str = ""
    list_host: str = ""
    list_path: str = ""
    list_id_key: str = ""
    list_title_key: str = ""
    list_date_key: str = ""
    list_page_param: str = ""
    detail_method: str = ""
    detail_host: str = ""
    detail_path: str = ""
    detail_body_key: str = ""
    detail_verified_count: int = 0
    notes: str = ""

    def list_ready(self) -> bool:
        return bool(self.list_path and self.list_id_key and self.list_title_key)

    def detail_ready(self) -> bool:
        return bool(self.detail_path and self.detail_body_key and self.detail_verified_count >= 2)

    @classmethod
    def load(cls, path: Path) -> "PortalContract":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick_key(keys: list[str], candidates: set[str]) -> str:
    lower = {k.lower(): k for k in keys}
    for name in candidates:
        if name in lower:
            return lower[name]
    return ""


def contract_from_discovery(discovery: dict[str, Any]) -> Optional[PortalContract]:
    """Fill a contract only from observed discovery rows. Never invents a path."""
    lists = discovery.get("listCandidates") or []
    details = discovery.get("detailCandidates") or []
    if not lists:
        return None
    best = lists[0]
    row_keys = [str(k) for k in (best.get("rowKeys") or [])]
    contract = PortalContract(
        verified=False,
        list_method=str(best.get("method") or "GET"),
        list_host=str(best.get("host") or ""),
        list_path=str(best.get("path") or ""),
        list_id_key=pick_key(row_keys, ID_KEYS),
        list_title_key=pick_key(row_keys, TITLE_KEYS),
        list_date_key=pick_key(row_keys, DATE_KEYS),
        list_page_param=str(best.get("pageParam") or ""),
    )
    if details:
        detail = details[0]
        contract.detail_method = str(detail.get("method") or "GET")
        contract.detail_host = str(detail.get("host") or "")
        contract.detail_path = str(detail.get("path") or "")
        contract.detail_body_key = str(detail.get("bodyKey") or pick_key(detail.get("topKeys") or [], BODY_KEYS))
        contract.detail_verified_count = int(detail.get("verifiedCount") or 0)
    if not contract.list_ready():
        return None
    return contract
