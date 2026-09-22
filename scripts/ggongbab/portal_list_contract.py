"""Independent LIST-only capability. Never authorizes detail or authentication replay."""
from urllib.parse import parse_qsl, urlsplit

from .portal_known_schema import KNOWN_HOST, KNOWN_LIST_PATH, LIST_QUERY, validate_list
from .web.exit_codes import UiContractError

LIST_URL = "https://" + KNOWN_HOST + KNOWN_LIST_PATH
MAX_RESPONSE_BYTES = 2_000_000


def list_query(page_index):
    if type(page_index) is not int or not 1 <= page_index <= 10000:
        raise UiContractError("PORTAL_LIST_PAGE_INVALID")
    return {**LIST_QUERY, "pageIndex": str(page_index)}


def require_list_request(method, url):
    """Check the final prepared URL, not just the caller's intended destination."""
    try:
        parsed = urlsplit(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query = dict(pairs)
        page = int(query.get("pageIndex", ""))
        valid = (method == "GET" and parsed.scheme == "https"
                 and parsed.netloc == KNOWN_HOST and parsed.path == KNOWN_LIST_PATH
                 and not parsed.fragment and len(pairs) == len(query)
                 and query == list_query(page))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise UiContractError("PORTAL_LIST_REQUEST_BLOCKED")


def validate_page(payload, page_index):
    rows = validate_list(payload, page_index)
    page = payload["page"]
    if (len(rows) > 10 or (rows and page["totalPage"] < page_index)
            or page["totalRecord"] < len(rows)
            or (not rows and page_index < page["totalPage"])):
        raise UiContractError("PORTAL_LIST_PAGE_INCONSISTENT")
    return rows
