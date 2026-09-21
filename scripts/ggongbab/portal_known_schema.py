"""KAIST recents shape supplied by the operator from DevTools; no identity values.

Calibration actively requests only list pages 1 and 2. Details are observed from
manual clicks. A schema match is not evidence that replay leaves view counts alone.
"""
import time
from urllib.parse import parse_qsl, unquote, urlparse

from .portal_contract import PortalContract
from .portal_discovery import notice_timestamp
from .ingest_marker import portal_external_key
from .web.exit_codes import AuthRequired, UiContractError

SCHEMA_KIND = "kaist-recents-v1"
KNOWN_HOST = "portal.kaist.ac.kr"
KNOWN_LIST_PATH = "/wz/api/board/recents"
KNOWN_DETAIL_PATH = KNOWN_LIST_PATH + "/{id}"
LIST_ARRAY_PATH, LIST_ID_KEY, LIST_TITLE_KEY = "data", "pstNo", "pstTtl"
LIST_DATE_KEY, LIST_BOARD_KEY, LIST_PUBLIC_KEY = "regDt", "boardNo", "publicYn"
DETAIL_ID_PATH, DETAIL_BODY_PATH = "pstNo", "pstCn"
LIST_QUERY = {
    "boardNo": "", "menuNo": "21", "boardNos": "", "pstNo": "", "pageIndex": "1", "pstCtgryNo": "",
    "boardVO.fnctnStng.secretUseYn": "N", "boardVO.fnctnStng.anonUseYn": "N",
    "boardVO.fnctnStng.cmntAnonUseYn": "N", "boardVO.fnctnStng.multiLangYn": "N",
    "boardVO.sknStng.listPostCnYn": "N", "boardVO.sknStng.listPostCnTextYn": "N",
    "cmntPageIndex": "", "recordCountPerPage": "10", "searchType": "searchTtl",
    "searchValue": "", "searchAll": "true", "selectTagYn": "false",
}
DETAIL_QUERY = {"boardNos": "", "menuNo": "21"}
ROW_QUERY = {"boardNo": "boardNo"}
VIEW_KEYS = {"inqcnt", "viewcount", "readcount", "hitcount", "viewcnt", "hitcnt"}
VIEW_BLOCKED = "CALIBRATION BLOCKED: potential detail view-count side effect requires review"
# Reported in this order, so the answer names one field rather than "the query".
DETAIL_QUERY_CHECKS = ("boardNo matches row", "boardNos empty", "menuNo expected")


class DetailQueryMismatch(UiContractError):
    """One named field of the detail query differed from what the row implies.

    Carries booleans only. A boardNo or pstNo value identifies a board someone
    reads and a notice they opened, so the values stay in memory.
    """

    def __init__(self, reason, checks):
        super().__init__(reason)
        self.checks = dict(checks)


def detail_query_lines(checks):
    """The privacy-safe mismatch report: field names and yes/no, never values."""
    lines = ["detail query check:"]
    for name in DETAIL_QUERY_CHECKS:
        state = checks.get(name)
        lines.append(f"  {name}: " + ("unknown" if state is None else "yes" if state else "no"))
    return lines


def known_contract():
    return PortalContract(
        schema_kind=SCHEMA_KIND, list_method="GET", list_host=KNOWN_HOST, list_path=KNOWN_LIST_PATH,
        list_query=dict(LIST_QUERY), list_array_path=LIST_ARRAY_PATH, list_id_key=LIST_ID_KEY,
        list_title_key=LIST_TITLE_KEY, list_date_key=LIST_DATE_KEY, list_public_key=LIST_PUBLIC_KEY,
        list_page_param="pageIndex", pagination="page", pagination_location="query", page_step=1,
        detail_method="GET", detail_host=KNOWN_HOST, detail_path=KNOWN_DETAIL_PATH,
        detail_query=dict(DETAIL_QUERY), detail_query_from_row=dict(ROW_QUERY),
        detail_id_path=DETAIL_ID_PATH, detail_body_path=DETAIL_BODY_PATH,
        # Operator reports inqCnt in real responses. Absence in a later response
        # cannot resolve that risk; this version intentionally has no override.
        potential_view_side_effect=True,
    )


def pinned_shape_valid(c):
    expected = known_contract()
    fields = ("schema_kind", "list_method", "list_host", "list_path", "list_query", "list_array_path",
              "list_id_key", "list_title_key", "list_date_key", "list_public_key", "list_page_param",
              "pagination", "pagination_location", "page_step", "detail_method", "detail_host", "detail_path",
              "detail_query", "detail_query_from_row", "detail_id_path", "detail_body_path",
              "list_body", "detail_body", "list_body_type", "detail_body_type")
    return all(getattr(c, k) == getattr(expected, k) for k in fields)


def scalar(value):
    return str(value) if type(value) in (str, int) and str(value).strip() else ""


def validate_list(payload, page_index):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not isinstance(payload.get("page"), dict):
        raise UiContractError("KNOWN_LIST_SCHEMA_CHANGED")
    page = payload["page"]
    for field in ("pageIndex", "recordCountPerPage", "totalPage", "totalRecord"):
        if type(page.get(field)) is not int or page[field] < 0:
            raise UiContractError("KNOWN_PAGE_SCHEMA_CHANGED")
    if page["pageIndex"] != page_index or page["recordCountPerPage"] != 10:
        raise UiContractError("KNOWN_PAGE_INDEX_OR_SIZE_MISMATCH")
    seen = set()
    for row in payload["data"]:
        if (not isinstance(row, dict) or not scalar(row.get("pstNo")) or not scalar(row.get("boardNo"))
                or not isinstance(row.get("pstTtl"), str) or not row["pstTtl"].strip()
                or not notice_timestamp(row.get("regDt")) or not isinstance(row.get("publicYn"), str)):
            raise UiContractError("KNOWN_LIST_ROW_SCHEMA_CHANGED")
        identifier = scalar(row["pstNo"])
        if identifier in seen:
            raise UiContractError("KNOWN_LIST_DUPLICATE_ID")
        seen.add(identifier)
    return payload["data"]


def public_row(row):
    if not isinstance(row, dict) or not isinstance(row.get("publicYn"), str):
        raise UiContractError("KNOWN_PUBLIC_FIELD_CHANGED")
    return row["publicYn"] == "Y"


def bound_query(c, identifier, row):
    if not pinned_shape_valid(c) or not isinstance(row, dict):
        raise UiContractError("KNOWN_ROW_QUERY_MAPPING_CHANGED")
    if scalar(row.get("pstNo")) != identifier or not scalar(row.get("boardNo")):
        raise UiContractError("KNOWN_ROW_ID_OR_BOARD_MISSING")
    if not public_row(row):
        raise UiContractError("KNOWN_NOTICE_NOT_PUBLIC")
    return {**DETAIL_QUERY, "boardNo": scalar(row["boardNo"])}


def has_view_counter(payload):
    if isinstance(payload, dict):
        return any(str(k).replace("_", "").lower() in VIEW_KEYS or has_view_counter(v) for k, v in payload.items())
    if isinstance(payload, list):
        return any(has_view_counter(v) for v in payload)
    return False


def validate_detail(payload, identifier, board):
    if (not isinstance(payload, dict) or scalar(payload.get("pstNo")) != identifier
            or scalar(payload.get("boardNo")) != board):
        raise UiContractError("KNOWN_DETAIL_ID_OR_BOARD_MISMATCH")
    if not isinstance(payload.get("pstCn"), str) or not payload["pstCn"].strip():
        raise UiContractError("KNOWN_DETAIL_BODY_CHANGED")
    if "publicYn" in payload and payload["publicYn"] != "Y":
        raise UiContractError("KNOWN_DETAIL_NOT_PUBLIC")
    return payload["pstCn"]


def observe_detail(response, row_index, c):
    parsed = urlparse(response.url)
    prefix = KNOWN_LIST_PATH + "/"
    if (response.request.method != "GET" or parsed.scheme != "https" or parsed.netloc != KNOWN_HOST
            or not parsed.path.startswith(prefix) or "/" in parsed.path[len(prefix):]):
        return False
    identifier = unquote(parsed.path[len(prefix):])
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(pairs)
    if len(pairs) != 3 or set(query) != {"boardNo", "boardNos", "menuNo"}:
        raise UiContractError("KNOWN_DETAIL_QUERY_CHANGED")
    # Each field is compared on its own. Comparing the whole query at once said
    # only that something differed, which is not enough to act on. The
    # expectations below are unchanged; only the reporting is finer.
    checks = {"boardNo matches row": None,
              "boardNos empty": query["boardNos"] == "",
              "menuNo expected": query["menuNo"] == DETAIL_QUERY["menuNo"]}
    if not checks["boardNos empty"]:
        raise DetailQueryMismatch("KNOWN_DETAIL_BOARDNOS_MISMATCH", checks)
    if not checks["menuNo expected"]:
        raise DetailQueryMismatch("KNOWN_DETAIL_MENUNO_MISMATCH", checks)
    row = row_index.get(identifier)
    if row is None:
        return False  # Open a public notice from the two verified list pages.
    expected = bound_query(c, identifier, row)
    checks["boardNo matches row"] = query["boardNo"] == expected["boardNo"]
    if not checks["boardNo matches row"]:
        raise DetailQueryMismatch("KNOWN_DETAIL_BOARDNO_MISMATCH", checks)
    if not 200 <= response.status < 300 or "json" not in response.headers.get("content-type", "").lower():
        raise UiContractError("KNOWN_DETAIL_RESPONSE_CHANGED")
    try:
        payload = response.json()
    except Exception:
        raise UiContractError("KNOWN_DETAIL_JSON_INVALID") from None
    c.view_counter_observed |= has_view_counter(payload)
    validate_detail(payload, identifier, query["boardNo"])
    digest = portal_external_key(identifier)
    if digest not in c.detail_id_hashes:
        c.detail_id_hashes.append(digest)
    c.detail_verified_count = len(c.detail_id_hashes)
    return True


def calibrate(session, c, log, seconds=120):
    from .portal_fetch import request_json
    # Probe exact-origin contexts without extracting any account-specific data.
    request, first_rows = None, None
    tried = set()
    for page in session.context.pages:
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or parsed.netloc != KNOWN_HOST or id(page.context) in tried:
            continue
        tried.add(id(page.context))
        try:
            candidate = page.context.request
            first = request_json(candidate, KNOWN_HOST, KNOWN_LIST_PATH, dict(LIST_QUERY))
            first_rows = validate_list(first, 1)
            request = candidate
            break
        except (UiContractError, AuthRequired):
            continue
    if request is None:
        raise UiContractError("LOGIN_ID_RUNTIME_REQUIRED")
    try:
        second = request_json(request, KNOWN_HOST, KNOWN_LIST_PATH, {**LIST_QUERY, "pageIndex": "2"})
        second_rows = validate_list(second, 2)
    except (UiContractError, AuthRequired):
        raise UiContractError("LOGIN_ID_RUNTIME_REQUIRED") from None
    stamps = [notice_timestamp(r["regDt"]) for r in first_rows + second_rows]
    c.list_date_descending = bool(first_rows and second_rows and all(a >= b for a, b in zip(stamps, stamps[1:])))
    c.view_counter_observed = has_view_counter(first) or has_view_counter(second)
    row_index = {}
    for row in first_rows + second_rows:
        identifier = scalar(row["pstNo"])
        if identifier in row_index and scalar(row_index[identifier]["boardNo"]) != scalar(row["boardNo"]):
            raise UiContractError("KNOWN_LIST_BOARD_CHANGED")
        row_index[identifier] = row
    log("Known list pages 1 and 2 verified; open two distinct public notices from those pages (manual clicks only)")
    errors, query_checks = [], []
    def on_response(response):
        try:
            observe_detail(response, row_index, c)
        except DetailQueryMismatch as exc:
            errors.append(str(exc))
            query_checks.append(exc.checks)
        except UiContractError as exc:
            errors.append(str(exc))
        except Exception:
            errors.append("KNOWN_DETAIL_OBSERVATION_FAILED")
    session.context.on("response", on_response)
    deadline = time.monotonic() + seconds
    next_progress = time.monotonic() + 30
    try:
        while c.detail_verified_count < 2 and not errors and time.monotonic() < deadline:
            pages = session.context.pages
            if not pages:
                raise AuthRequired("Portal browser has no open pages")
            pages[-1].wait_for_timeout(250)
            if time.monotonic() >= next_progress:
                log(f"Known detail observations: {c.detail_verified_count}/2 distinct notices")
                next_progress = time.monotonic() + 30
    finally:
        session.context.remove_listener("response", on_response)
    if errors:
        for line in query_checks[:1] and detail_query_lines(query_checks[0]) or []:
            log(line)
        raise UiContractError(errors[0])
    if c.detail_verified_count < 2:
        raise UiContractError("KNOWN_CALIBRATION_NEEDS_TWO_DISTINCT_DETAILS")
    c.known_schema_verified = True
    # No repeated detail GET experiments and no inference from absent counters.
    c.verified = c.detail_ready()
    return c
