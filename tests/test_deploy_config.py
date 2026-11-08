"""What the two Vercel projects serve (data plan phase 2, 2026-10-12). No network.

Both projects deploy this repository: babdoduk from main, babdoduk-lab from lab. The lab-only
experiments stay in git on both branches, and vercel.json answers 404 for them on every host
but babdoduk-lab.vercel.app. .vercelignore keeps everything that is not a site resource out of
both deployments.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB_HOST = "babdoduk-lab.vercel.app"
LAB_ONLY = ("food.html", "lab.html", "lab-ggongbab.html", "calendar.ics", "data/food-log.json")
SITE = ("index.html", "ggongbab.html", "mukbang.html", "event.html", "history.html", "choose.html", "tip.html", "privacy.html",
        "manifest.json", "css/site.css", "js/home.js", "images/kakao-loopy.jpg", "data/ggongbab/latest.json",
        "data/kaist-menu/week.json", "data/magazine/index.json")


def routes():
    return json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))["routes"]


def test_lab_only_experiments_answer_404_on_every_host_but_the_lab():
    [route] = [r for r in routes() if "status" in r]
    assert route["status"] == 404 and route["missing"] == [{"type": "host", "value": LAB_HOST}]
    assert set(route) == {"src", "missing", "status"}          # no destination: nothing else is served
    pattern = re.compile(route["src"])
    for path in LAB_ONLY:
        assert pattern.fullmatch("/" + path), path
        assert (ROOT / path).exists(), path                     # kept in git: the lab still serves it
    for path in SITE + ("data/food-log.json.bak", "lab-ggongbab.html/x"):
        assert not pattern.fullmatch("/" + path), path


def test_nothing_the_site_fetches_is_left_out_of_the_deployment():
    """.vercelignore keeps code, docs and data/content/ out of the deployment: no page or script may
    fetch a path under them (a page that did would fail only once deployed)."""
    ignored = [line.strip().rstrip("/") for line in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#") and "*" not in line]
    sources = sorted(ROOT.glob("*.html")) + sorted((ROOT / "js").glob("*.js"))
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for path in re.findall(r"""(?:fetch|getJson|getJSON)\(\s*['"]([^'"]+)['"]""", text):
            assert not any(path == p or path.startswith(p + "/") for p in ignored), (source.name, path)


def test_no_product_page_links_a_lab_only_experiment():
    lab_pages = {name for name in LAB_ONLY if name.endswith(".html")}
    for page in sorted(ROOT.glob("*.html")):
        if page.name in lab_pages:
            continue
        html = page.read_text(encoding="utf-8")
        for path in LAB_ONLY:
            assert not re.search(r'(href|src|fetch\()\s*=?\s*["\'](\./)?' + re.escape(path), html), (page.name, path)


def test_only_site_resources_are_deployed():
    entries = [line.strip() for line in (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")]
    for name in ("research", "scripts", "tests", "docs", "supabase", "inputs", "i18n", "schemas", "shared",
                 "data/content", ".claude", ".cursor", ".github", "*.md", "*.txt", "*.ini", ".env.example",
                 ".local", ".env"):
        assert name in entries, name
    # robots.txt is the one text file the site serves (docs/PUBLIC_EXPOSURE.md).
    assert entries.index("!robots.txt") > entries.index("*.txt")
    # Nothing the pages load is ignored: no entry names a site file or folder.
    for entry in entries:
        assert entry not in ("css", "js", "images", "data", "manifest.json", "*.html", "*.json", "*.css", "*.js"), entry
    for path in SITE:
        top = path.split("/")[0]
        assert top not in entries and (ROOT / path).exists(), path


def test_only_our_domain_may_read_the_data_from_another_site_and_the_rights_notice_travels_with_it():
    """docs/PUBLIC_EXPOSURE.md: Vercel's default `*` let a copy site show our feed live; the rights
    notice is linked from every data response and served as text."""
    header_routes = [r for r in routes() if "headers" in r]
    assert all(r.get("continue") is True and set(r) == {"src", "headers", "continue"} for r in header_routes)
    data = [r for r in header_routes if re.fullmatch(r["src"], "/data/ggongbab/latest.json")]
    assert len(data) == 1
    assert data[0]["headers"] == {"Access-Control-Allow-Origin": "https://www.babdodukms.com",
                                  "Link": '</LICENSE>; rel="license"'}
    for path in SITE:
        if not path.startswith("data/"):
            assert not re.fullmatch(data[0]["src"], "/" + path), path
    [notice] = [r for r in header_routes if re.fullmatch(r["src"], "/LICENSE")]
    assert notice["headers"] == {"Content-Type": "text/plain; charset=utf-8"}
    # Header routes come first: the lab-only 404 still answers after them.
    assert "status" in routes()[-1]


def test_the_license_reserves_every_right_and_robots_refuses_ai_crawlers_and_the_data():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "All rights reserved" in license_text
    assert "Permission is hereby granted" not in license_text          # no longer the MIT grant
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    groups, current = [], None
    for line in robots.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        key, _, value = (part.strip() for part in line.partition(":"))
        if key.lower() == "user-agent":
            if current is None or current["rules"]:
                current = {"agents": [], "rules": []}
                groups.append(current)
            current["agents"].append(value)
        else:
            current["rules"].append((key.lower(), value))
    rules = {agent: group["rules"] for group in groups for agent in group["agents"]}
    for bot in ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended", "PerplexityBot", "Bytespider"):
        assert rules[bot] == [("disallow", "/")], bot
    assert rules["*"] == [("disallow", "/data/")]
