"""The translations (data plan phase 5): i18n/ko.json and i18n/en.json hold every page's text once,
scripts/sync_site_chrome.py writes each page's table from them, and js/site.js is the one language
switch. The tables are evaluated in Node, as the browser reads them."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import page_content
import sync_site_chrome as chrome

ROOT = Path(__file__).resolve().parents[1]
I18N = {lang: json.loads((ROOT / f"i18n/{lang}.json").read_text(encoding="utf-8")) for lang in ("ko", "en")}
MARKUP_KEY = re.compile(r'data-i18n(?:-html|-aria-key|-alt)?="([^"]+)"')


def node(script: str, stdin: str = "") -> str:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return subprocess.run(["node", "-e", script], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def table(html: str) -> dict:
    start = html.index("window.BABDODUK_STR = ") + len("window.BABDODUK_STR = ")
    end = html.index("\n    };\n", start) + len("\n    }")
    return json.loads(node("process.stdout.write(JSON.stringify(" + html[start:end] + "))"))


def test_both_languages_have_every_key():
    assert set(I18N["ko"]) == set(I18N["en"])
    for lang, strings in I18N.items():
        assert all(isinstance(value, str) and value.strip() for value in strings.values()), lang
        assert list(strings) == sorted(strings), lang          # kept sorted, so a diff shows one line


def test_every_key_has_one_source():
    """Shared labels and data/content/ entries are written from their own files, never from i18n/."""
    families = set(chrome.COMMON_STRINGS)
    for page, config in chrome.PAGES.items():
        families |= set(config.get("strings", ()))
        assert f"title.{page[:-5]}" in I18N["ko"], page
        generated = set(chrome.label_strings(page))
        if page in chrome.CONTENT_STRINGS:
            generated |= set(chrome.CONTENT_STRINGS[page]()["ko"])
        assert not generated & set(I18N["ko"]), (page, sorted(generated & set(I18N["ko"])))
    orphans = sorted(k for k in I18N["ko"] if k.split(".")[0] not in families and not k.startswith("title."))
    assert orphans == []                                      # every key reaches some page


def test_every_page_reads_its_text_in_both_languages():
    assert chrome.main(["--check"]) == 0                      # the committed tables are what the sync writes
    titles = set()
    for page in chrome.PAGES:
        html = (ROOT / page).read_text(encoding="utf-8")
        strings = table(html)
        assert set(strings["ko"]) == set(strings["en"]), page
        assert strings["ko"]["docTitle"] and strings["en"]["docTitle"], page
        titles.add(strings["ko"]["docTitle"])
        used = set(MARKUP_KEY.findall(html))
        assert used <= set(strings["ko"]), (page, sorted(used - set(strings["ko"])))
    assert len(titles) == len(chrome.PAGES)


def test_one_language_switch_for_every_page():
    for page in chrome.PAGES:
        html = (ROOT / page).read_text(encoding="utf-8")
        block = html[html.index("<!-- @i18n:strings -->"):html.index("<!-- @end i18n -->")]
        assert block.rstrip().endswith('<script src="js/site.js"></script>'), page
        # The table and site.js come before every other script of the page.
        assert html.index("<script") > html.index("<!-- @i18n:strings -->"), page
        for copy in ("function applyLang", "getElementById('scrollProgressBar')", "querySelectorAll('[data-mega]')",
                     "var STR = ", "babdoduk-langchange"):
            assert copy not in html, (page, copy)
    site = (ROOT / "js/site.js").read_text(encoding="utf-8")
    for part in ("function applyLang", "[data-i18n-alt]", "babdoduk-lang", "scrollProgressBar", "[data-mega]"):
        assert part in site, part


def test_a_table_value_reads_back_exactly():
    values = ["Couldn't", "a\\b", "line one\nline two", "x</script><script>alert(1)</script>", "<!-- no -->",
              '"quoted" and \'single\'', " sep ", "<strong>ok</strong>"]
    literal = "[" + ", ".join(page_content.js_str(value) for value in values) + "]"
    assert json.loads(node("process.stdout.write(JSON.stringify(" + literal + "))")) == values
    assert "</script" not in literal


def test_the_wordmark_says_where_it_goes():
    for page, config in chrome.PAGES.items():
        nav = (ROOT / page).read_text(encoding="utf-8")
        link = re.search(r'<a href="([^"]+)" id="navHome"[^>]*>', nav).group(0)
        if config.get("home") == "#":                          # the home page scrolls to the top
            assert 'data-i18n-aria-key="nav.topAria" aria-label="맨 위로"' in link, page
        else:
            assert 'href="index.html"' in link and 'data-i18n-aria-key="nav.homeAria" aria-label="홈으로"' in link, page
    assert I18N["en"]["nav.topAria"] == "Back to top" and I18N["en"]["nav.homeAria"] == "Home"
