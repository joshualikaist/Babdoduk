"""방문 수와 이용 통계 (owner 2026-11-20; docs/USAGE_STATS.md): supabase/migrations/018_visit_counts.sql,
api/visit.js, the counter in js/site.js and scripts/usage_stats.py.

Nothing leaves this machine: the function runs under Node with fetch replaced, the pages are served to a
headless Chrome from this checkout under our own host names, and the report reads a stand-in database."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

import usage_stats

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase/migrations/018_visit_counts.sql").read_text(encoding="utf-8")
API = (ROOT / "api/visit.js").read_text(encoding="utf-8")
SITE_JS = (ROOT / "js/site.js").read_text(encoding="utf-8")
OUR_SITES = {"www.babdodukms.com", "babdoduk.vercel.app", "babdoduk-lab.vercel.app"}
KST = timezone(timedelta(hours=9))


# --- the table and its one function ------------------------------------------------------------------
def test_the_counts_hold_no_person_and_only_count_visit_is_open():
    table = SQL.split("create table if not exists public.visit_counts (", 1)[1].split(");", 1)[0]
    columns = re.findall(r"^\s+([a-z_]+) ", table, re.M)
    assert columns == ["hour", "site", "page", "lang", "device", "views", "primary"]
    for private in ("user", "ip", "address", "agent", "cookie", "forwarded", "email"):
        assert private not in table, private
    assert "alter table public.visit_counts enable row level security;" in SQL
    assert "revoke all on table public.visit_counts from public, anon, authenticated;" in SQL
    assert re.findall(r"grant ([a-z, ]+) on table (\S+) to anon", SQL) == []
    assert re.findall(r"grant execute on function ([^;]+) to anon;", SQL) == ["public.count_visit(text, text, text, text)"]
    body = SQL.split("create or replace function public.count_visit(", 1)[1].split("$$;", 1)[0]
    assert "security definer set search_path = ''" in body and "date_trunc('hour', now())" in body
    assert "request.headers" not in SQL, "the database never looks at who called"


def test_the_sites_and_pages_agree_everywhere():
    assert set(re.findall(r"'([a-z.-]+\.(?:com|app))'", SQL)) == OUR_SITES
    assert set(re.findall(r"'([a-z.-]+\.(?:com|app))'", API.split("const SITES", 1)[1].split(";", 1)[0])) == OUR_SITES
    counter = re.search(r"/\^\((.+?)\)\$/\.test\(loc\.hostname\)", SITE_JS).group(1)
    assert {h.replace("\\.", ".") for h in counter.split("|")} == OUR_SITES
    seeded = set(re.findall(r"\('([a-z0-9-]+)'\)", SQL.split("insert into public.visit_pages", 1)[1].split(";", 1)[0]))
    assert seeded == {p.stem for p in ROOT.glob("*.html")}, "a new page needs python scripts/usage_stats.py pages"
    assert usage_stats.SITES["all"] == tuple(sorted(OUR_SITES, key=["www.babdodukms.com", "babdoduk.vercel.app",
                                                                    "babdoduk-lab.vercel.app"].index))
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))["functions"]["api/visit.js"]
    assert config["includeFiles"] == "js/ggongbab-public-config.js"


# --- the function ---------------------------------------------------------------------------------------
RUN = r"""
const visit = require(process.argv[1]);
const data = JSON.parse(process.argv[2]);
const calls = [];
global.fetch = async (url, options) => {
  calls.push([url, JSON.parse(options.body), Object.keys(options.headers).sort()]);
  if (data.fail) throw new Error('down');
  return { ok: true, status: 204 };
};
const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(body) { this.body = body; } };
const req = { method: data.method || 'POST', headers: data.headers, body: data.body };
visit(req, res).then(() => console.log(JSON.stringify({ status: res.statusCode, headers: res.headers, calls })));
"""
LAB = {"host": "babdoduk-lab.vercel.app", "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"}


def call_visit(body, headers=LAB, method="POST", fail=False):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    args = json.dumps({"body": body, "headers": headers, "method": method, "fail": fail})
    out = subprocess.run(["node", "-e", RUN, str(ROOT / "api/visit.js"), args], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_page_opened_on_our_site_adds_one_count_and_nothing_about_the_person():
    out = call_visit('{"page":"ggongbab","lang":"ko","device":"phone"}')
    assert out["status"] == 204 and out["headers"]["Cache-Control"] == "no-store"
    [(url, body, headers)] = out["calls"]
    assert url.endswith("/rest/v1/rpc/count_visit")
    assert body == {"p_site": "babdoduk-lab.vercel.app", "p_page": "ggongbab", "p_lang": "ko", "p_device": "phone"}
    assert headers == ["Authorization", "Content-Type", "apikey"], "no address or agent is passed on"
    # A parsed JSON body counts the same.
    assert call_visit({"page": "index", "lang": "en", "device": "computer"})["calls"][0][1]["p_lang"] == "en"


@pytest.mark.parametrize("body,headers", [
    ('{"page":"ggongbab","lang":"ko","device":"phone"}', {"host": "evil.example", "user-agent": "Mozilla/5.0"}),
    ('{"page":"ggongbab","lang":"ko","device":"phone"}', {"host": "babdoduk-git-x.vercel.app", "user-agent": "Mozilla/5.0"}),
    ('{"page":"ggongbab","lang":"ko","device":"phone"}', {"host": "www.babdodukms.com", "user-agent": "Googlebot/2.1"}),
    ('{"page":"ggongbab","lang":"ko","device":"phone"}', {"host": "www.babdodukms.com"}),
    ('{"page":"../x","lang":"ko","device":"phone"}', LAB),
    ('{"page":"ggongbab","lang":"fr","device":"phone"}', LAB),
    ('{"page":"ggongbab","lang":"ko","device":"watch"}', LAB),
    ('{"page":"ggongbab","lang":"ko","device":"phone","pad":"' + "x" * 600 + '"}', LAB),
    ("not json", LAB),
])
def test_anything_else_counts_nothing_and_still_answers_204(body, headers):
    out = call_visit(body, headers)
    assert out["status"] == 204 and out["calls"] == []


def test_a_read_is_refused_and_a_database_failure_is_silent():
    assert call_visit(None, method="GET")["status"] == 405
    out = call_visit('{"page":"my","lang":"ko","device":"tablet"}', fail=True)
    assert out["status"] == 204 and len(out["calls"]) == 1


# --- the counter in every page -----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(channel="chrome", headless=True)
        yield chrome
        chrome.close()


IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1"


def open_page(browser, url, *, human=True, ua=IPHONE, init=""):
    """Serve this checkout under `url`'s host; records what the page sends to /api/visit."""
    context = browser.new_context(user_agent=ua, service_workers="block")
    if human:
        context.add_init_script("Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false });")
    if init:
        context.add_init_script(init)
    beacons = []

    def handle(route):
        req = route.request
        u = urlparse(req.url)
        if u.hostname != urlparse(url).hostname:
            return route.abort()
        if u.path == "/api/visit":
            beacons.append(req.post_data)
            return route.fulfill(status=204, body="")
        file = (ROOT / unquote(u.path).lstrip("/")).resolve()
        if u.path == "/":
            file = ROOT / "index.html"
        if file.is_file() and ROOT in file.parents:
            return route.fulfill(path=str(file))
        return route.fulfill(status=404, body="")

    context.route("**/*", handle)
    page = context.new_page()
    page.goto(url, wait_until="load")
    page.wait_for_timeout(400)
    return context, page, beacons


def test_one_page_load_sends_one_count_of_page_language_and_device(browser):
    context, page, beacons = open_page(browser, "https://babdoduk-lab.vercel.app/privacy.html")
    assert [json.loads(b) for b in beacons] == [{"page": "privacy", "lang": "ko", "device": "phone"}]
    context.close()
    context, page, beacons = open_page(browser, "https://www.babdodukms.com/",
                                       ua="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36",
                                       init="localStorage.setItem('babdoduk-lang', 'en');")
    assert [json.loads(b) for b in beacons] == [{"page": "index", "lang": "en", "device": "computer"}]
    context.close()


@pytest.mark.parametrize("url,human,init", [
    ("http://127.0.0.1/privacy.html", True, ""),                                    # not our site
    ("https://babdoduk-lab.vercel.app/privacy.html", False, ""),                     # an automated browser
    ("https://babdoduk-lab.vercel.app/privacy.html", True,
     "Object.defineProperty(Navigator.prototype, 'globalPrivacyControl', { get: () => true });"),
    ("https://babdoduk-lab.vercel.app/privacy.html", True,
     "Object.defineProperty(Navigator.prototype, 'doNotTrack', { get: () => '1' });"),
    ("https://babdoduk-lab.vercel.app/privacy.html?nocount=1", True, ""),            # the owner's own phone
])
def test_nothing_is_sent_when_it_should_not_count(browser, url, human, init):
    context, page, beacons = open_page(browser, url, human=human, init=init)
    assert beacons == []
    context.close()


def test_opting_out_sticks_until_it_is_undone(browser):
    context, page, beacons = open_page(browser, "https://babdoduk-lab.vercel.app/privacy.html?nocount=1")
    page.goto("https://babdoduk-lab.vercel.app/privacy.html", wait_until="load")
    page.wait_for_timeout(300)
    assert beacons == []
    page.goto("https://babdoduk-lab.vercel.app/privacy.html?nocount=0", wait_until="load")
    page.wait_for_timeout(300)
    assert len(beacons) == 1
    info = page.evaluate("""() => BabdodukVisit.info({ hostname: 'www.babdodukms.com', search: '', pathname: '/lab-ggongbab.html' },
        { userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', maxTouchPoints: 5 })""")
    assert info == {"page": "lab-ggongbab", "lang": "ko", "device": "tablet"}   # an iPad asks for the desktop site
    context.close()


# --- the report ------------------------------------------------------------------------------------------
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=KST)


def stand_in(tmp_path):
    (tmp_path / "data/ggongbab/archive").mkdir(parents=True)
    (tmp_path / "data/content").mkdir(parents=True)
    (tmp_path / "data/foods/packs").mkdir(parents=True)
    events = [{"id": "lunch", "title": "점심 도시락 나눔", "startAt": "2026-11-18T12:00:00+09:00", "food": {"type": "lunchbox"}},
              {"id": "tea", "title": "다과회", "startAt": "2026-11-19T15:00:00+09:00", "food": {"type": "refreshment"}}]
    (tmp_path / "data/ggongbab/latest.json").write_text(json.dumps({"events": events}), encoding="utf-8")
    (tmp_path / "data/ggongbab/archive/index.json").write_text(json.dumps({"events": []}), encoding="utf-8")
    (tmp_path / "data/content/labels.json").write_text(json.dumps({
        "freeFood": {"lunchbox": {"ko": "도시락"}, "refreshment": {"ko": "다과"}},
        "restaurants": [{"id": "west", "name": "서맛골 W2"}]}), encoding="utf-8")
    (tmp_path / "data/foods/packs/k.json").write_text(json.dumps({"items": [{"id": "kr-bibimbap", "nameKo": "비빔밥"}]}),
                                                     encoding="utf-8")
    (tmp_path / "ggongbab.html").write_text("<title>밥도둑 · 꽁밥</title>", encoding="utf-8")
    hour = lambda h: (NOW - timedelta(hours=h)).astimezone(timezone.utc).isoformat()
    db = {
        "visit_counts": [
            {"hour": hour(1), "site": "www.babdodukms.com", "page": "ggongbab", "lang": "ko", "device": "phone", "views": 40},
            {"hour": hour(1), "site": "babdoduk-lab.vercel.app", "page": "ggongbab", "lang": "ko", "device": "phone", "views": 900},
            {"hour": hour(25), "site": "babdoduk.vercel.app", "page": "index", "lang": "en", "device": "computer", "views": 3}],
        "saved_events": [{"event_id": "lunch", "saved_at": hour(2)}] * 7 + [{"event_id": "tea#1", "saved_at": hour(3)}] * 2,
        "saved_places": [{"place_id": "west", "status": "again"}] * 6,
        "push_devices": [{"events": ["lunch", "tea"]}] * 5,
        "pick_dish_stats": [{"dish_id": "kr-bibimbap", "draws": 9, "likes": 4, "rerolls": 1}],
        "worldcup_dish_stats": [{"dish_id": "kr-bibimbap", "matches": 3, "wins": 2, "entries": 1, "titles": 1}],
    }
    asked = []

    def call(method, path, body=None, prefer=""):
        asked.append(path)
        table, query = path.split("?", 1)
        offset = int(re.search(r"offset=(\d+)", query).group(1))
        return db[table][offset:offset + usage_stats.PAGE_SIZE]
    return call, asked


def test_the_report_answers_when_where_and_which_stars_with_small_numbers_hidden(tmp_path):
    call, asked = stand_in(tmp_path)
    text = usage_stats.report(call, days=28, site="prod", now=NOW, root=tmp_path)
    assert "모두 43번 열렸어요." in text                       # the lab's 900 are left out of 실제 사이트
    assert "| 11시 | 43 |" in text and "| 금 | 40 |" in text and "| 밥도둑 · 꽁밥 | 40 |" in text and "- 휴대폰: 40" in text
    assert "| 1 | 점심 도시락 나눔 · 11/18 수 · 도시락 | 7 |" in text
    assert "| 2 | 다과회 · 11/19 목 · 다과 | 5 미만 |" in text   # 2 stars: hidden
    assert "| 10시 | 7 |" in text and "| 9시 | 5 미만 |" in text
    assert "알림을 켠 기기는 5대예요." in text and "| 서맛골 W2 | 6 | 5 미만 | 5 미만 | 6 |" in text
    assert "| 1 | 비빔밥 | 4 |" in text                         # already anonymous: shown as it is
    for path in asked:
        table, query = path.split("?", 1)
        columns = set(re.search(r"select=([^&]+)", query).group(1).split(","))
        assert columns <= usage_stats.READS[table], path
    assert not any(re.search(r"user_id|memo|endpoint|p256dh|seen|display_name|email", p) for p in asked)


def test_a_column_outside_the_list_is_refused_and_a_missing_table_is_reported(tmp_path):
    with pytest.raises(ValueError):
        usage_stats.rows(lambda *a, **k: [], "saved_events", "user_id,event_id")

    def refusing(method, path, body=None, prefer=""):
        raise SystemExit(f"{method} {path.split('?')[0]}: HTTP 404")
    text = usage_stats.report(refusing, now=NOW, root=stand_in(tmp_path)[0] and tmp_path)
    assert "018을 적용했는지 확인해 주세요" in text and text.count("읽지 못했어요") >= 4


def test_the_policy_says_what_the_counter_and_the_report_do():
    ko = json.loads((ROOT / "i18n/ko.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "i18n/en.json").read_text(encoding="utf-8"))
    assert "분석 도구" not in ko["privacy.s6.i3"] and "analytics tools" not in en["privacy.s6.i3"]
    for word in ("사이트 주소", "페이지", "언어", "휴대폰/태블릿/컴퓨터", "한 시간", "접속 주소(IP)", "추적 거부"):
        assert word in ko["privacy.s6.i3"], word
    assert f"{usage_stats.MIN_CELL}보다 작으면" in ko["privacy.s2.note"] and f"below {usage_stats.MIN_CELL}" in en["privacy.s2.note"]
    assert "globalPrivacyControl" in SITE_JS and "doNotTrack" in SITE_JS
    assert "date_trunc('hour'" in SQL
