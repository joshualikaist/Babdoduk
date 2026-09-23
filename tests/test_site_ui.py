"""UI-only regressions; no live service requests."""
from check_site_ui import ROOT, public_pages, run_checks


def test_public_page_inventory_and_shared_styles():
    pages = public_pages()
    assert set(pages) == {"index.html", "history.html", "food.html", "mukbang.html",
                          "ggongbab.html", "lab-ggongbab.html", "event.html", "lab.html"}
    for name in pages:
        assert 'href="css/site.css"' in (ROOT / name).read_text(encoding="utf-8")


def test_scrollbar_css_contract_and_no_trend_carousel():
    shared = (ROOT / "css/site.css").read_text(encoding="utf-8")
    for token in ("--scrollbar-track", "--scrollbar-thumb", "--scrollbar-thumb-hover",
                  "scrollbar-color:", "::-webkit-scrollbar-track", "::-webkit-scrollbar-thumb",
                  "::-webkit-scrollbar-thumb:hover", "::-webkit-scrollbar-corner",
                  "@media (forced-colors: none)", "html:has(body.mg-body)"):
        assert token in shared
    assert "scrollbar-width: none" not in shared and "scrollbar-width: thin" not in shared
    magazine = (ROOT / "css/magazine.css").read_text(encoding="utf-8")
    assert ".mg-lane--trend .mg-lane-items" not in magazine
    assert ".mg-lane--trend .mg-story" not in magazine
    html = (ROOT / "mukbang.html").read_text(encoding="utf-8")
    assert "MagazineRails" not in html and "magazine-rails.js" not in html


def test_all_public_pages_windows_scrollbars_and_overflow():
    report = run_checks()
    assert len(report["results"]) == 40
    assert all(result["overflow"] == 0 for result in report["results"].values())
