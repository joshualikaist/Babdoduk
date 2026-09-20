"""Active GETs through the browser's current authenticated request context."""
from urllib.parse import quote, urlencode, urlparse

from .portal_discovery import at_path, has_read_state, notice_date, stable_id
from .web.exit_codes import AuthRequired, UiContractError


def request_json(request, host, path, query):
    url = "https://" + host + path
    if query:
        url += "?" + urlencode(query)
    try:
        # Never follow an API redirect into an SSO form (or another host).
        response = request.get(url, timeout=30000, max_redirects=0)
        try:
            if response.status in (301, 302, 303, 307, 308, 401, 403):
                raise AuthRequired("Portal authenticated API access required")
            if not 200 <= response.status < 300:
                raise UiContractError("Portal API request failed")
            if "json" not in response.headers.get("content-type", "").lower():
                raise AuthRequired("Portal API did not return authenticated JSON")
            return response.json()
        finally:
            response.dispose()
    except (AuthRequired, UiContractError):
        raise
    except Exception:
        # Playwright exceptions often embed full URLs containing private IDs/cursors.
        raise UiContractError("Portal API request failed; values suppressed") from None


def exact_rows(payload, c):
    rows = at_path(payload, c.list_array_path)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise UiContractError("Portal list array contract changed")
    if any(not stable_id(r.get(c.list_id_key)) or not isinstance(r.get(c.list_title_key), str) for r in rows):
        raise UiContractError("Portal list field contract changed")
    if has_read_state(payload):
        raise UiContractError("Portal read-state semantics require review before detail fetch")
    return rows


def request_context(session, c):
    # resident_session.context is a BrowserScope, not an APIRequestContext.
    # Select the actual page context by exact origin, including SSO-created contexts.
    tried = set()
    schema_failure = False
    for page in session.context.pages:
        try:
            parsed = urlparse(page.url)
            if parsed.scheme != "https" or parsed.netloc != c.list_host:
                continue
            context = page.context
            if id(context) in tried:
                continue
            tried.add(id(context))
            request = context.request
            payload = request_json(request, c.list_host, c.list_path, dict(c.list_query))
            exact_rows(payload, c)
            return request, payload
        except UiContractError:
            schema_failure = True
        except AuthRequired:
            continue
        except Exception:
            continue
    if schema_failure:
        raise UiContractError("Portal list contract could not be verified in any browser context")
    raise AuthRequired("Portal browser context unavailable; complete manual setup")


def iter_notices(request, c, *, max_pages=20, max_items=500, date_from=None, initial_payload=None):
    query = dict(c.list_query)
    seen, cursors = set(), set()
    previous_date = None
    for page_number in range(max_pages):
        payload = (initial_payload if page_number == 0 and initial_payload is not None
                   else request_json(request, c.list_host, c.list_path, query))
        rows = exact_rows(payload, c)
        fresh = [r for r in rows if stable_id(r[c.list_id_key]) not in seen]
        if not fresh:
            return
        dates = [notice_date(r.get(c.list_date_key)) for r in rows]
        ordered = c.list_date_descending and all(dates)
        if ordered:
            ordered = all(a >= b for a, b in zip(dates, dates[1:]))
            ordered = ordered and (previous_date is None or previous_date >= dates[0])
        # Fail on changed ordering before trusting a cutoff.
        if c.list_date_descending and all(dates) and not ordered:
            raise UiContractError("Portal date ordering contract changed")
        for row in fresh:
            identifier = stable_id(row[c.list_id_key])
            if identifier in seen:
                continue
            seen.add(identifier)
            yield row
            if len(seen) >= max_items:
                return
        if date_from and ordered and dates[-1] < date_from:
            return
        previous_date = dates[-1] if ordered else None
        if c.pagination in ("page", "offset"):
            query[c.list_page_param] = str(int(query[c.list_page_param]) + c.page_step)
        elif c.pagination == "cursor":
            cursor = at_path(payload, c.cursor_path)
            if cursor is None or cursor == "":
                return
            if not isinstance(cursor, (str, int)) or isinstance(cursor, bool):
                raise UiContractError("Portal cursor contract changed")
            cursor = str(cursor)
            if cursor in cursors:
                return
            cursors.add(cursor)
            query[c.list_page_param] = cursor
        else:
            return


def fetch_detail(request, c, identifier):
    # IDs in query parameters are escaped by urlencode; path IDs by quote.
    if identifier in (".", ".."):
        raise UiContractError("Portal stable id cannot be used in a request path")
    path = c.detail_path.replace("{id}", quote(identifier, safe=""))
    query = {k: identifier if v == "{id}" else v for k, v in c.detail_query.items()}
    payload = request_json(request, c.detail_host, path, query)
    if has_read_state(payload):
        raise UiContractError("Portal detail read-state semantics require review")
    if stable_id(at_path(payload, c.detail_id_path)) != identifier:
        raise UiContractError("Portal detail stable id contract changed")
    body = at_path(payload, c.detail_body_path)
    if not isinstance(body, str) or not body.strip():
        raise UiContractError("Portal detail body contract changed")
    return body
