"""Replayable, observation-only Portal contract; no credentials or notice values."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

TITLE_KEYS = {"title", "subject", "noticetitle", "bbsstit", "ntttitle"}
ID_KEYS = {"id", "noticeid", "bbsid", "nttid", "seq", "uid", "articleid"}
DATE_KEYS = {"createdat", "createddate", "regdate", "regdt", "date", "writedate", "updatedat"}
BODY_KEYS = {"body", "content", "contents", "html", "text", "nttcont"}


def pick_key(keys, candidates):
    matches = [k for k in keys if k.lower() in candidates]
    return matches[0] if len(matches) == 1 else ""


@dataclass
class PortalContract:
    version: int = 2
    verified: bool = False
    start_url: str = "https://portal.kaist.ac.kr/"
    list_method: str = ""
    list_host: str = ""
    list_path: str = ""
    list_query: dict = field(default_factory=dict)
    list_array_path: str = ""
    list_id_key: str = ""
    list_title_key: str = ""
    list_date_key: str = ""
    list_date_descending: bool = False
    list_page_param: str = ""
    pagination: str = "none"
    page_step: int = 0
    cursor_path: str = ""
    detail_method: str = ""
    detail_host: str = ""
    detail_path: str = ""
    detail_query: dict = field(default_factory=dict)
    detail_body_path: str = ""
    detail_id_path: str = ""
    detail_verified_count: int = 0
    detail_id_hashes: list[str] = field(default_factory=list)
    detail_state: str = ""

    def list_ready(self):
        page_ok = self.pagination == "none" or (
            self.pagination in ("page", "offset") and self.list_page_param in self.list_query
            and isinstance(self.page_step, int) and self.page_step > 0
            and str(self.list_query[self.list_page_param]).isdigit()
        ) or (self.pagination == "cursor" and bool(self.list_page_param and self.cursor_path))
        return bool(self.version == 2 and self.list_method == "GET" and self.list_host
                    and self.list_path and self.list_array_path and self.list_id_key
                    and self.list_title_key and page_ok)

    def detail_ready(self):
        return bool(self.detail_method == "GET" and self.detail_host and self.detail_body_path
                    and self.detail_id_path and self.detail_verified_count >= 2
                    and len(set(self.detail_id_hashes)) >= 2
                    and self.detail_state == "no-read-state-observed"
                    and ("{id}" in self.detail_path or "{id}" in self.detail_query.values()))

    @classmethod
    def load(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 2:
                return cls()
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def contract_from_discovery(discovery):
    # A schema summary or two arbitrary detail calls cannot authorize replay.
    data = discovery.get("contract")
    if discovery.get("version") != 2 or not isinstance(data, dict):
        return None
    contract = PortalContract(**{k: v for k, v in data.items() if k in PortalContract.__dataclass_fields__})
    contract.verified = False
    return contract if contract.list_ready() else None
