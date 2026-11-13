"""What the two Vercel projects serve (data plan phase 2, 2026-10-12). No network.

Both projects deploy this repository: babdoduk from main, babdoduk-lab from lab. The lab-only
experiments stay in git on both branches, and vercel.json answers 404 for them on every host
but babdoduk-lab.vercel.app. .vercelignore keeps everything that is not a site resource out of
both deployments.
"""
import hashlib
import json
import re
from pathlib import Path

import sync_site_chrome as chrome
from deploy_headers import response_headers

ROOT = Path(__file__).resolve().parents[1]
LAB_HOST = "babdoduk-lab.vercel.app"
LAB_ONLY = ("food.html", "lab.html", "lab-ggongbab.html", "cardnews.html", "data/cardnews/index.json",
            "data/cardnews/2026-11-02/1.png", "bobyak.html", "data/places/latest.json", "calendar.ics",
            "data/food-log.json")
SITE = ("index.html", "ggongbab.html", "mukbang.html", "event.html", "history.html", "choose.html", "tip.html", "privacy.html", "my.html",
        "manifest.json", "css/site.css", "js/home.js", "images/og-babdoduk.png", "data/ggongbab/latest.json",
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
        if path == "calendar.ics":
            # Owner 2026-11-13: the KAIST Portal export is deleted (production served it under an encoded
            # path despite the 404 rule); the rule stays so a copy put back is still kept off production.
            assert not (ROOT / path).exists(), path
            continue
        assert (ROOT / path).exists(), path                     # kept in git: the lab still serves it
    for path in SITE + ("data/food-log.json.bak", "lab-ggongbab.html/x", "data/cardnews", "cardnews.html.bak",
                        "bobyak.html.bak", "data/places"):
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
    for route in header_routes:
        assert route.get("continue") is True
        if "has" in route:
            assert set(route) == {"src", "headers", "continue", "has"}
            assert route["has"] == [{"type": "query", "key": "v", "value": "[0-9a-f]{10}"}]
            assert route["headers"] == {"Cache-Control": "public, max-age=31536000, immutable"}
        else:
            assert set(route) == {"src", "headers", "continue"}
    data = [r for r in header_routes if "Access-Control-Allow-Origin" in r["headers"]]
    assert len(data) == 1
    assert re.fullmatch(data[0]["src"], "/data/ggongbab/latest.json")
    assert data[0]["headers"] == {"Access-Control-Allow-Origin": "https://www.babdodukms.com",
                                  "Link": '</LICENSE>; rel="license"'}
    for path in SITE:
        if not path.startswith("data/"):
            assert not re.fullmatch(data[0]["src"], "/" + path), path
    [notice] = [r for r in header_routes if "Content-Type" in r["headers"]]
    assert re.fullmatch(notice["src"], "/LICENSE")
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


# --- content stamps (docs/DEPLOYMENT_AND_BRANCHES.md) ------------------------------------------------------
def deployed_text():
    """Every page and script the site serves (vendor libraries aside)."""
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(ROOT.glob("*.html")) + sorted((ROOT / "js").glob("*.js"))}


STAMPED_REF = re.compile(r"""["']((?:\./)?(?:js|css)/[A-Za-z0-9_./-]+?\.(?:js|css))(\?v=[0-9a-f]+)?["']""")


def test_every_local_script_and_stylesheet_is_addressed_by_its_content():
    """Each local script and stylesheet reference carries ?v=<10 hex of the file's sha256>, so a changed
    file gets a new address (browsers may keep /js/ and /css/ for long)."""
    checked = 0
    for name, text in deployed_text().items():
        refs = [(m.group(1), m.group(2)) for m in STAMPED_REF.finditer(text)]
        if name.startswith("js/"):          # modules import their neighbours as ./<file>.js
            refs += [("js/" + m.group(1)[2:], m.group(2)) for m in
                     re.finditer(r"""(?:\bfrom\s*|\bimport\s*\(\s*)["'](\./[A-Za-z0-9_.-]+\.js)(\?v=[0-9a-f]+)?["']""", text)
                     if not m.group(1).startswith("./vendor/")]
        for path, version in refs:
            path = path.removeprefix("./")
            if path.startswith("js/vendor/"):
                continue                    # versioned by its folder
            file = ROOT / path
            if not file.exists() and path in chrome.LAB_ONLY_SCRIPTS:
                continue
            assert version == "?v=" + hashlib.sha256(file.read_bytes()).hexdigest()[:10], (name, path, version)
            checked += 1
    assert checked > 60
    # The calendar function reads its files from disk, by plain path; the service worker keeps its address.
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    for name in re.findall(r"js/[a-z-]+\.js", config["functions"]["api/cal.js"]["includeFiles"]):
        assert (ROOT / name).is_file(), name
    assert "register('/sw.js'" in (ROOT / "js/ggongbab-push.js").read_text(encoding="utf-8")


def test_security_headers_cover_pages_assets_functions_and_errors():
    for path in ("/", "/index.html", "/my.html", "/js/site.js", "/data/ggongbab/latest.json",
                 "/cal/" + "A" * 43 + ".ics", "/missing"):
        headers = response_headers(path)
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert headers["X-Frame-Options"] == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]
        assert headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


def test_only_stamped_assets_and_versioned_vendor_files_are_immutable():
    for path in ("/", "/ggongbab.html", "/data/ggongbab/latest.json", "/js/site.js", "/css/site.css",
                 "/js/site.js?v=wrong", "/css/site.css?v=1234"):
        headers = response_headers(path)
        assert headers["Cache-Control"] == "public, max-age=0, must-revalidate"
    for path in ("/js/site.js?v=0123456789", "/css/site.css?v=abcdef0123",
                 "/js/vendor/three-0.186.1/three.module.js"):
        assert response_headers(path)["Cache-Control"] == "public, max-age=31536000, immutable"
    assert response_headers("/sw.js")["Cache-Control"] == "no-cache"
    assert response_headers("/sw.js?v=0123456789")["Cache-Control"] == "no-cache"


def test_html_policy_keeps_the_existing_script_font_and_map_sources():
    for page in chrome.PAGES:
        policy = response_headers("/" + page)["Content-Security-Policy"]
        directives = dict((part.strip().split(None, 1) + [""])[:2] for part in policy.split(";"))
        assert directives["default-src"] == "'self'"
        assert directives["object-src"] == "'none'"
        assert directives["base-uri"] == "'self'"
        assert "'unsafe-eval'" not in policy
        assert "'wasm-unsafe-eval'" in directives["script-src"]
        for script in ("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.116.0/dist/umd/supabase.js",
                       "https://t1.kakaocdn.net/kakao_js_sdk/2.8.3/kakao.min.js"):
            assert script in directives["script-src"].split()
        assert "https://fonts.googleapis.com" in directives["style-src"].split()
        assert "https://fonts.gstatic.com" in directives["font-src"].split()
        assert "https://myjglfynhnptlclawlcc.supabase.co" in directives["connect-src"].split()
        assert "wss://myjglfynhnptlclawlcc.supabase.co" in directives["connect-src"].split()
        assert directives["worker-src"] == "'self' blob:"
        # Magazine photos come from changing article/image hosts, never executable code.
        assert "https:" in directives["img-src"].split()
