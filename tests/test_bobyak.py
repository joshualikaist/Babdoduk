"""밥약 메이커 (bobyak.html, lab only; docs/BOBYAK.md): the bill split's arithmetic, the roulette's rules (verified
first, candidates only with consent, filters, saved-only), the place card and its links, the 먹킷리스트 in this
browser (damaged and newer data), shared links without the private memo, English, and phone to desktop
widths. Synthetic places are served to the test browser only; the published file is not read or changed."""
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HOST = "bobyak.invalid"
SAVED_KEY = "babdoduk-places-saved"


def place(pid, name, area, cuisine, status, facts=(), **extra):
    data = {"id": pid, "name": name, "area": area, "address": f"대전 유성구 시험로 {pid[-1]}", "cuisine": cuisine,
            "status": status, "verifiedAt": "2026-11-07" if status == "verified" else None, "facts": list(facts),
            "sources": [{"kind": "semas", "ref": "MA" + pid[-4:], "checkedAt": "2026-11-08"}], "updatedAt": "2026-11-08"}
    data.update(extra)
    return data


CHEAP = {"kind": "budget", "band": "under10k", "text": "국밥 9,000원", "source": "operator", "checkedAt": "2026-11-07"}
HOURS = {"kind": "hours", "text": "11:00–21:00", "textEn": "11:00–21:00", "source": "official", "checkedAt": "2026-11-07"}
PLACES = [
    place("p-0001", "어은 국밥", "eoeun", "korean", "verified", [CHEAP, HOURS]),
    place("p-0002", "어은 파스타", "eoeun", "western", "verified"),
    place("p-0003", "궁동 떡볶이", "gung", "snack", "candidate"),
    place("p-0004", "궁동 옛날집", "gung", "korean", "stale"),
    place("p-0005", "문 닫은 집", "kaist", "korean", "closed"),
]
FEED = {"schemaVersion": 1, "updatedAt": "2026-11-08",
        "source": {"name": "소상공인시장진흥공단 상가(상권)정보", "url": "https://www.data.go.kr/data/15012005/openapi.do", "terms": "t"},
        "places": PLACES}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        # Real classic scrollbars, as the site checker runs: a 360px window leaves 344px for the page.
        chrome = pw.chromium.launch(channel="chrome", headless=True, ignore_default_args=["--hide-scrollbars"],
                                    args=["--disable-features=OverlayScrollbar,FluentOverlayScrollbar"])
        yield chrome
        chrome.close()


def open_page(browser, query="", feed=FEED, storage=None, lang="ko", size=(390, 844), share=None, status=200):
    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, service_workers="block")
    init = [f"localStorage.setItem('babdoduk-lang', '{lang}');", "window.__shared = []; window.__copied = [];"]
    for key, value in (storage or {}).items():
        init.append(f"localStorage.setItem({json.dumps(key)}, {json.dumps(value)});")
    if share == "native":
        init.append("navigator.share = (data) => { window.__shared.push(data); return Promise.resolve(); };")
    else:
        init.append("try { delete Navigator.prototype.share; } catch (e) {} navigator.share = undefined;")
    init.append("Object.defineProperty(navigator, 'clipboard', {value: {writeText: (t) => { window.__copied.push(t); return Promise.resolve(); }}});")
    context.add_init_script(" ".join(init))
    requests = []

    def handle(route):
        url = urlparse(route.request.url)
        requests.append(route.request.url)
        if url.hostname != HOST:
            return route.abort()
        path = unquote(url.path).lstrip("/")
        if path == "data/places/latest.json":
            return route.fulfill(json=feed) if status == 200 else route.fulfill(status=status, body="")
        file = (ROOT / path).resolve()
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"https://{HOST}/bobyak.html{query}", wait_until="networkidle")
    return context, page, errors, requests


def stored(page):
    return page.evaluate(f"JSON.parse(localStorage.getItem('{SAVED_KEY}') || 'null')")


# ---------- 정산 ----------
def test_settlement_arithmetic_always_adds_up(browser):
    context, page, errors, _ = open_page(browser)
    run = "input => BabdodukSettle.settle(input)"
    amounts = lambda r: [s["amount"] for s in r["shares"]]
    people = lambda n, **kw: [dict({"name": f"p{i}"}, **kw) for i in range(n)]
    r = page.evaluate(run, {"total": 10000, "people": people(3)})
    assert r["ok"] and amounts(r) == [3334, 3333, 3333]                         # the extra won goes to the top
    r = page.evaluate(run, {"total": 10000, "people": people(3), "unit": 100})
    assert amounts(r) == [3400, 3300, 3300]
    r = page.evaluate(run, {"total": 10005, "people": people(3), "unit": 10})
    assert amounts(r) == [3345, 3330, 3330] and sum(amounts(r)) == 10005        # below one unit: the first person
    r = page.evaluate(run, {"total": 45000, "mode": "treat", "payer": 1, "people": people(3)})
    assert amounts(r) == [0, 45000, 0]
    r = page.evaluate(run, {"total": 30000, "people": [{"name": "a"}, {"name": "b", "excluded": True}, {"name": "c"}]})
    assert amounts(r) == [15000, 0, 15000]
    r = page.evaluate(run, {"total": 30000, "people": [{"name": "a", "fixed": 12000}, {"name": "b"}, {"name": "c"}]})
    assert amounts(r) == [12000, 9000, 9000]
    r = page.evaluate(run, {"total": 0, "people": people(2)})
    assert r["ok"] and amounts(r) == [0, 0]
    r = page.evaluate(run, {"total": 20000, "people": [{"fixed": 5000}, {"fixed": 15000}]})
    assert r["ok"] and amounts(r) == [5000, 15000]
    for case, error in [({"total": 1000, "people": []}, "nobody"),
                        ({"total": 1000, "people": [{"excluded": True}]}, "nobody"),
                        ({"total": -1, "people": people(2)}, "total"),
                        ({"total": 10.5, "people": people(2)}, "total"),
                        ({"total": 100000001, "people": people(2)}, "total"),
                        ({"total": 1000, "people": people(31)}, "tooMany"),
                        ({"total": 1000, "people": people(2), "unit": 7}, "unit"),
                        ({"total": 1000, "mode": "treat", "payer": 5, "people": people(2)}, "payer"),
                        ({"total": 1000, "mode": "treat", "payer": 0, "people": [{"excluded": True}, {}]}, "payer"),
                        ({"total": 1000, "people": [{"fixed": 1500}, {}]}, "fixedOver"),
                        ({"total": 1000, "people": [{"fixed": -5}, {}]}, "fixedInvalid"),
                        ({"total": 1000, "people": [{"fixed": 300}, {"fixed": 300}]}, "fixedShort")]:
        assert page.evaluate(run, case) == {"ok": False, "error": error}, case
    # Invariant over many shapes: every share is a whole, non-negative amount and they add up to the total.
    bad = page.evaluate("""() => {
      const bad = []; let seed = 7;
      const rnd = n => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
      for (let i = 0; i < 3000; i++) {
        const n = 1 + rnd(12), total = rnd(500000), unit = [1, 10, 100, 1000][rnd(4)];
        const people = Array.from({length: n}, () => ({excluded: rnd(5) === 0, fixed: rnd(6) === 0 ? rnd(20000) : null}));
        const r = BabdodukSettle.settle({total, unit, people});
        if (!r.ok) continue;
        const sum = r.shares.reduce((a, s) => a + s.amount, 0);
        if (sum !== total || r.shares.some(s => s.amount < 0 || !Number.isInteger(s.amount) || (s.excluded && s.amount)))
          bad.push({total, unit, people});
      }
      return bad.slice(0, 3);
    }""")
    assert bad == []
    assert page.evaluate("BabdodukSettle.parseWon('45,000원')") == 45000
    assert page.evaluate("Number.isNaN(BabdodukSettle.parseWon('4.5'))")
    assert not errors
    context.close()


def test_settlement_form_splits_shares_and_never_sends_amounts(browser):
    context, page, errors, requests = open_page(browser, share="native")
    before = len(requests)
    page.fill("#bobTotal", "45,000")
    assert page.locator(".bob-share-amount").evaluate_all("els => els.map(e => e.dataset.amount)") == ["22500", "22500"]
    page.locator('[data-bob="add-person"]').click()
    page.locator('.bob-person-name[data-index="0"]').fill("민수")
    page.locator('.bob-person-name[data-index="1"]').fill("지아")
    page.locator('.bob-person-name[data-index="2"]').fill("현우")
    page.fill("#bobTotal", "10000")
    assert page.locator(".bob-share-amount").evaluate_all("els => els.map(e => e.dataset.amount)") == ["3334", "3333", "3333"]
    page.locator('[data-bob="exclude"][data-index="2"]').click()
    assert page.locator(".bob-share-amount").evaluate_all("els => els.map(e => e.dataset.amount)") == ["5000", "5000", "0"]
    page.locator('.bob-person-fixed[data-index="0"]').fill("12000")
    assert page.locator(".bob-error").get_attribute("data-error") == "fixedOver"
    assert "12,000원" in page.locator(".bob-error").inner_text()
    page.locator('.bob-person-fixed[data-index="0"]').fill("7000")
    assert page.locator(".bob-share-amount").evaluate_all("els => els.map(e => e.dataset.amount)") == ["7000", "3000", "0"]
    assert "합계 10,000원" in page.locator(".bob-sum").inner_text()
    page.locator('[data-bob="mode"][data-value="treat"]').click()
    page.locator('[data-bob="payer"][data-index="1"]').click()
    assert page.locator(".bob-share-amount").evaluate_all("els => els.map(e => e.dataset.amount)") == ["0", "10000", "0"]
    page.locator('[data-bob="share-settle"]').click()
    page.wait_for_function("window.__shared.length === 1")
    shared = page.evaluate("window.__shared[0]")
    assert "지아 10,000원" in shared["text"] and "총 10,000원" in shared["text"]
    assert shared["url"].endswith("/bobyak.html") and "10000" not in shared["url"]
    page.locator('[data-bob="remove-person"][data-index="0"]').click()
    assert page.locator(".bob-person").count() == 2
    # Typing and splitting asked nothing of any server.
    assert [u for u in requests[before:] if "/data/" in u or HOST not in u] == []
    assert not errors
    context.close()


# ---------- Roulette ----------
def test_roulette_rules(browser):
    context, page, errors, _ = open_page(browser)
    pick = "opts => BabdodukPlaces.pick(window.__feed, Object.assign({random: () => 0.99}, opts))"
    page.evaluate("feed => { window.__feed = feed; }", PLACES)
    r = page.evaluate(pick, {})
    assert r["status"] == "ok" and r["pool"] == "verified" and r["place"]["id"] in ("p-0001", "p-0002") and r["size"] == 2
    assert page.evaluate(pick, {"avoid": "p-0002"})["place"]["id"] == "p-0001"
    assert page.evaluate(pick, {"area": "gung"}) == {"status": "consent", "count": 1}       # never mixed in silently
    r = page.evaluate(pick, {"area": "gung", "consent": True})
    assert r["status"] == "ok" and r["pool"] == "candidate" and r["place"]["id"] == "p-0003"
    # Consent does not push candidates ahead of verified places.
    assert page.evaluate(pick, {"consent": True})["pool"] == "verified"
    assert page.evaluate(pick, {"budget": "under10k"})["place"]["id"] == "p-0001"            # the one with a checked price
    assert page.evaluate(pick, {"budget": "over15k", "consent": True}) == {"status": "empty", "reason": "filters"}
    assert page.evaluate(pick, {"area": "kaist", "consent": True}) == {"status": "empty", "reason": "filters"}  # closed never
    assert page.evaluate(pick, {"savedIds": []}) == {"status": "empty", "reason": "saved"}
    assert page.evaluate(pick, {"savedIds": ["p-0004", "p-0005"]}) == {"status": "empty", "reason": "saved"}
    assert page.evaluate(pick, {"savedIds": ["p-0002"]})["place"]["id"] == "p-0002"
    assert page.evaluate("BabdodukPlaces.pick([], {})") == {"status": "empty", "reason": "data"}
    links = page.evaluate("p => BabdodukPlaces.mapLinks(p)", PLACES[0])
    assert links["naver"] == "https://map.naver.com/p/search/%EC%96%B4%EC%9D%80%20%EA%B5%AD%EB%B0%A5%20%EB%8C%80%EC%A0%84%20%EC%9C%A0%EC%84%B1%EA%B5%AC%20%EC%8B%9C%ED%97%98%EB%A1%9C%201"
    assert links["kakao"].startswith("https://map.kakao.com/?q=") and "%EC%8B%9C%ED%97%98%EB%A1%9C" in links["kakao"]
    assert page.evaluate("BabdodukPlaces.idFromQuery('?p=p-0003&x=1')") == "p-0003"
    assert page.evaluate("BabdodukPlaces.idFromQuery('?p=%3Cscript%3E')") is None
    assert not errors
    context.close()


def test_one_tap_pick_then_consent_for_candidates(browser):
    context, page, errors, _ = open_page(browser)
    assert "확인된 식당 2곳 · 확인 안 된 후보 1곳 · 2026-11-08 기준" in page.locator("#bobDataNote").inner_text()
    page.locator("#bobSpin").click()
    card = page.locator(".bob-card")
    assert card.count() == 1 and card.locator(".bob-badge").inner_text() == "밥도둑 확인"
    assert page.evaluate("document.activeElement.classList.contains('bob-card')")
    # Optional filters: the area with only a candidate asks first.
    page.locator("#bobFiltersToggle").click()
    assert page.locator("#bobFilters").is_visible()
    page.locator('[data-bob="filter"][data-group="area"][data-value="gung"]').click()
    assert "1개" in page.locator("#bobFiltersToggle").inner_text()
    page.locator("#bobSpin").click()
    assert page.locator(".bob-consent").count() == 1 and page.locator(".bob-card").count() == 0
    assert "후보 1곳" in page.locator(".bob-consent").inner_text()
    page.locator('[data-bob="consent"]').click()
    card = page.locator(".bob-card")
    assert card.locator(".bob-card-name").inner_text() == "궁동 떡볶이"
    assert card.locator(".bob-badge").inner_text() == "확인 안 된 후보"
    assert "확인 안 된 후보 중에서 뽑았어요" in card.inner_text()
    assert "확인 안 됨" in card.inner_text()                                   # menu, price, hours are not invented
    assert page.locator(".bob-consent-on").count() == 1
    page.locator('[data-bob="consent-off"]').click()
    page.locator("#bobSpin").click()
    assert page.locator(".bob-consent").count() == 1
    # A budget only matches checked prices; nothing matches -> say so and offer a reset.
    page.locator('[data-bob="filter"][data-group="area"][data-value="all"]').click()
    page.locator('[data-bob="filter"][data-group="budget"][data-value="over15k"]').click()
    page.locator("#bobSpin").click()
    assert "이 조건에 맞는 식당이 없어요" in page.locator("#bobResult").inner_text()
    page.locator('#bobResult [data-bob="reset"]').click()
    assert page.locator("#bobFiltersToggle").inner_text() == "조건 고르기"
    # Only cuisines that exist are offered.
    cuisines = page.locator('[data-group="cuisine"]').evaluate_all("els => els.map(e => e.dataset.value)")
    assert cuisines == ["all", "korean", "western", "snack"]
    assert not errors
    context.close()


def test_card_shows_only_confirmed_facts_with_their_source(browser):
    context, page, errors, _ = open_page(browser, "?p=p-0001")
    card = page.locator(".bob-card")
    assert card.locator(".bob-card-name").inner_text() == "어은 국밥"
    text = card.inner_text()
    assert "1만 원 이하 · 국밥 9,000원" in text and "밥도둑 확인 · 2026-11-07" in text
    assert "가게 공식 안내 · 2026-11-07" in text
    assert "메뉴\n확인 안 됨" in text or "메뉴 확인 안 됨" in text.replace("\n", " ")
    assert "소상공인시장진흥공단" in text
    assert card.locator('a[href^="https://map.naver.com/p/search/"]').get_attribute("rel") == "noopener"
    assert card.locator('a[href^="https://map.kakao.com/?q="]').get_attribute("target") == "_blank"
    assert card.locator('[data-bob="spin"]').count() == 0                       # a shared link is not a pick
    context.close()
    context, page, errors2, _ = open_page(browser, "?p=p-0004")
    assert page.locator(".bob-badge").first.inner_text() == "정보 확인 필요"
    assert "폐업했거나" in page.locator(".bob-card").inner_text()
    context.close()
    context, page, errors3, _ = open_page(browser, "?p=p-9999")
    assert "이 식당을 찾지 못했어요" in page.locator("#bobResult").inner_text()
    context.close()
    assert not errors + errors2 + errors3


def test_empty_data_and_failed_load_are_told_apart(browser):
    empty = dict(FEED, places=[], updatedAt=None)
    context, page, errors, _ = open_page(browser, feed=empty)
    assert "아직 올라온 식당이 없어요" in page.locator("#bobResult").inner_text()
    assert page.locator("#bobDataNote").inner_text() == "확인된 식당 0곳 · 확인 안 된 후보 0곳"
    page.locator("#bobSpin").click()
    assert "아직 올라온 식당이 없어요" in page.locator("#bobResult").inner_text()
    context.close()
    context, page, errors2, _ = open_page(browser, status=503)
    assert "불러오지 못했어요" in page.locator("#bobResult").inner_text()
    assert "없어요" not in page.locator("#bobResult").inner_text()
    assert page.locator("#bobSpin").is_disabled()
    assert page.locator('[data-bob="retry"]').count() == 1
    assert not errors + errors2
    context.close()


# ---------- 먹킷리스트 ----------
def test_food_list_saves_moves_removes_and_feeds_the_roulette(browser):
    context, page, errors, _ = open_page(browser, share="native")
    page.locator("#bobFiltersToggle").click()
    page.locator('[data-bob="saved-only"]').click()
    page.locator("#bobSpin").click()
    assert "먹킷리스트에서 뽑을 수 있는 식당이 없어요" in page.locator("#bobResult").inner_text()
    page.goto(f"https://{HOST}/bobyak.html?p=p-0002", wait_until="networkidle")
    page.locator('[data-bob="list-set"][data-status="want"]').click()
    data = stored(page)
    assert data["v"] == 1 and [(i["id"], i["status"], i["memo"]) for i in data["items"]] == [("p-0002", "want", "")]
    assert data["items"][0]["savedAt"] and data["items"][0]["updatedAt"]
    assert page.locator('[data-bob="list-set"][data-status="want"]').get_attribute("aria-pressed") == "true"
    page.locator('[data-bob="list-set"][data-status="again"]').click()
    assert stored(page)["items"][0]["status"] == "again" and len(stored(page)["items"]) == 1
    page.locator(".bob-card textarea").fill("창가 자리, 민수 생일")
    page.locator('.bob-card [data-bob="memo-save"]').click()
    assert stored(page)["items"][0]["memo"] == "창가 자리, 민수 생일"
    assert "또 갈래" in page.locator("#bobListBody").inner_text() and "창가 자리" in page.locator("#bobListBody").inner_text()
    # The memo stays out of what is shared.
    page.locator('.bob-card [data-bob="share-place"]').click()
    page.wait_for_function("window.__shared.length === 1")
    shared = page.evaluate("window.__shared[0]")
    assert shared["url"].endswith("/bobyak.html?p=p-0002")
    assert "창가" not in json.dumps(shared, ensure_ascii=False) and "또 갈래" not in json.dumps(shared, ensure_ascii=False)
    # Saved-only roulette now picks it.
    page.locator("#bobFiltersToggle").click()
    page.locator('[data-bob="saved-only"]').click()
    page.locator("#bobSpin").click()
    assert page.locator(".bob-card-name").inner_text() == "어은 파스타"
    page.reload(wait_until="networkidle")
    assert "어은 파스타" in page.locator("#bobListBody").inner_text()
    page.locator('#bobListBody [data-bob="open"]').click()
    assert page.locator(".bob-card-name").inner_text() == "어은 파스타"
    page.locator('.bob-card [data-bob="list-remove"]').click()
    assert stored(page)["items"] == [] and "아직 담은 식당이 없어요" in page.locator("#bobListBody").inner_text()
    assert not errors
    context.close()


def test_a_saved_place_that_left_the_list_is_named_as_such(browser):
    item = {"id": "p-0999", "status": "want", "memo": "", "savedAt": "2026-11-01T00:00:00Z", "updatedAt": "2026-11-01T00:00:00Z"}
    context, page, errors, _ = open_page(browser, storage={SAVED_KEY: json.dumps({"v": 1, "items": [item]})})
    body = page.locator("#bobListBody").inner_text()
    assert "목록에서 빠진 식당" in body and "폐업했거나" in body
    page.locator('#bobListBody [data-bob="list-remove"]').click()
    assert stored(page)["items"] == []
    assert not errors
    context.close()


def test_damaged_and_newer_saved_data(browser):
    context, page, errors, _ = open_page(browser, storage={SAVED_KEY: "{not json"})
    assert "새로 시작했어요" in page.locator("#bobListBody").inner_text()
    assert page.evaluate("localStorage.getItem('babdoduk-places-saved-unreadable')") == "{not json"
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") is None
    context.close()
    newer = json.dumps({"v": 2, "items": [{"id": "p-0001", "status": "been", "memo": "m", "savedAt": "x", "updatedAt": "x"}],
                        "extra": True})
    context, page, errors2, _ = open_page(browser, storage={SAVED_KEY: newer})
    assert "보기만 할 수 있어요" in page.locator("#bobListBody").inner_text()
    assert "어은 국밥" in page.locator("#bobListBody").inner_text()
    page.locator('#bobListBody [data-bob="open"]').click()
    page.locator('[data-bob="list-set"][data-status="want"]').click()
    assert page.evaluate(f"localStorage.getItem('{SAVED_KEY}')") == newer           # never rewritten
    assert page.locator(".bob-card textarea").count() == 0
    assert not errors + errors2
    context.close()


# ---------- Language and widths ----------
def test_english_keeps_korean_names(browser):
    context, page, errors, _ = open_page(browser, "?p=p-0001", lang="en")
    card = page.locator(".bob-card")
    assert card.locator(".bob-card-name").inner_text() == "어은 국밥"                # no invented English name
    text = card.inner_text()
    assert "Checked by Babdoduk" in text and "Up to ₩10,000" in text and "Not checked" in text
    assert page.locator("h1").inner_text() == "Meal plan maker"
    page.fill("#bobTotal", "10000")
    assert page.locator(".bob-share-amount").first.inner_text() == "₩5,000"
    page.locator("#langToggle").click()
    assert page.locator(".bob-card .bob-badge").inner_text() == "밥도둑 확인"
    assert page.locator(".bob-share-amount").first.inner_text() == "5,000원"
    assert not errors
    context.close()


@pytest.mark.parametrize("size", [(360, 800), (390, 844), (768, 1024), (1024, 768), (1440, 900)])
def test_widths_fit_and_targets_are_44px(browser, size):
    context, page, errors, _ = open_page(browser, "?p=p-0001", size=size)
    page.locator('[data-bob="list-set"][data-status="want"]').click()
    page.locator("#bobFiltersToggle").click()
    page.locator('[data-bob="add-person"]').click()
    page.locator('.bob-person-name[data-index="0"]').fill("아주아주긴이름을가진참가자입니다정말로길어요")
    page.fill("#bobTotal", "123456789")
    page.fill("#bobTotal", "99999999")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, (size, overflow)
    small = page.locator("#bobApp button, #bobApp a, #bobApp input, #bobApp select").evaluate_all("""els => els.filter(el => {
      const r = el.getBoundingClientRect(); if (!r.width) return false;
      return r.height < 44 || r.width < 44; }).map(el => el.outerHTML.slice(0, 80))""")
    assert small == [], (size, small)
    assert not errors
    context.close()
