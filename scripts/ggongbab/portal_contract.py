"""Replayable, observation-only Portal contract; no credentials or notice values."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

TITLE_KEYS = {"title", "subject", "noticetitle", "bbsstit", "ntttitle", "pstttl"}
ID_KEYS = {"id", "noticeid", "bbsid", "nttid", "seq", "uid", "articleid", "pstno"}
DATE_KEYS = {"createdat", "createddate", "regdate", "regdt", "date", "writedate", "updatedat"}
BODY_KEYS = {"body", "content", "contents", "html", "text", "nttcont", "pstcn"}


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
    list_body_type: str = ""
    list_body: dict = field(default_factory=dict)
    list_post_evidence: list[str] = field(default_factory=list)
    detail_body_type: str = ""
    detail_body: dict = field(default_factory=dict)
    detail_post_evidence: list[str] = field(default_factory=list)
    detail_request_id_path: str = ""
    detail_request_id_type: str = "string"
    pagination_location: str = "query"
    schema_kind: str = "generic"
    detail_query_from_row: dict = field(default_factory=dict)
    list_public_key: str = ""
    known_schema_verified: bool = False
    potential_view_side_effect: bool = False
    view_counter_observed: bool = False
    detail_side_effect_reviewed: bool = False

    def post_ready(self, endpoint):
        from .portal_post import leaves
        try:
            body_type = getattr(self, endpoint + "_body_type")
            evidence = getattr(self, endpoint + "_post_evidence")
            body = getattr(self, endpoint + "_body")
            fields = dict(leaves(body))
            if body_type not in ("json", "form") or len(set(evidence)) < 2:
                return False
            if body_type == "form" and any("." in p for p in fields):
                return False
            placeholders = [p for p, v in fields.items() if v == "{id}"]
            if endpoint == "detail":
                return (placeholders == ([self.detail_request_id_path] if self.detail_request_id_path else [])
                        and self.detail_request_id_type in ("int", "string"))
            return not placeholders
        except (ValueError, TypeError, AttributeError):
            return False

    def list_ready(self):
        if self.schema_kind != "generic":
            from .portal_known_schema import pinned_shape_valid
            return pinned_shape_valid(self)
        from .portal_post import leaves
        try:
            params = dict(leaves(self.list_body)) if self.pagination_location == "body" else self.list_query
        except (ValueError, TypeError):
            return False
        page_ok = self.pagination == "none" or (
            self.pagination in ("page", "offset") and self.list_page_param in params
            and isinstance(self.page_step, int) and self.page_step > 0
            and str(params[self.list_page_param]).isdigit()
        ) or (self.pagination == "cursor" and bool(self.list_page_param and self.cursor_path))
        method_ok = self.list_method == "GET" or (self.list_method == "POST" and self.post_ready("list"))
        return bool(self.version == 2 and method_ok and self.list_host
                    and self.pagination_location in ("query", "body")
                    and (self.pagination_location != "body" or self.list_method == "POST")
                    and self.list_path and self.list_array_path and self.list_id_key
                    and self.list_title_key and page_ok)

    def detail_ready(self):
        if self.schema_kind != "generic":
            from .portal_known_schema import pinned_shape_valid
            return bool(pinned_shape_valid(self) and self.known_schema_verified
                        and self.detail_verified_count >= 2 and len(set(self.detail_id_hashes)) >= 2
                        and self.detail_side_effect_reviewed and not self.potential_view_side_effect)
        method_ok = self.detail_method == "GET" or (self.detail_method == "POST" and self.post_ready("detail"))
        return bool(method_ok and self.detail_host and self.detail_body_path
                    and self.detail_id_path and self.detail_verified_count >= 2
                    and len(set(self.detail_id_hashes)) >= 2
                    and self.detail_state == "no-read-state-observed"
                    and ("{id}" in self.detail_path or "{id}" in self.detail_query.values()
                         or (self.detail_method == "POST" and self.detail_request_id_path)))

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
