"""Pure helpers of scripts/e2e_quality.py: link normalisation, anchor targets, axe classification,
violation grouping, the image oversize ratio and the performance warnings."""
import e2e_quality as eq

BASE = "https://babdoduk.vercel.app"


def test_normalize_internal_drops_fragment_and_resolves_relative():
    assert eq.normalize_link("ggongbab.html#menu", BASE + "/index.html", BASE) == ("internal", BASE + "/ggongbab.html", "menu")
    assert eq.normalize_link("../css/site.css", BASE + "/a/b.html", BASE) == ("internal", BASE + "/css/site.css", "")
    assert eq.normalize_link("/worldcup.html?cat=x", BASE + "/index.html", BASE) == ("internal", BASE + "/worldcup.html?cat=x", "")
    assert eq.normalize_link("#today", BASE + "/mukbang.html", BASE) == ("internal", BASE + "/mukbang.html", "today")


def test_normalize_external_and_skipped():
    assert eq.normalize_link("https://naver.me/abc", BASE + "/", BASE)[0] == "external"
    assert eq.normalize_link("//example.com/x", BASE + "/", BASE) == ("external", "https://example.com/x", "")
    for href in ("", "  ", "#", "mailto:a@b.c", "tel:123", "javascript:void(0)", "data:text/plain,x", None):
        assert eq.normalize_link(href, BASE + "/", BASE)[0] == "skip"


def test_other_subdomain_is_external():
    assert eq.normalize_link("https://babdoduk-lab.vercel.app/", BASE + "/", BASE)[0] == "external"


def test_anchor_targets():
    assert eq.anchor_target_exists("today", {"today", "x"})
    assert not eq.anchor_target_exists("nope", {"today"})
    assert eq.anchor_target_exists("top", set()) and eq.anchor_target_exists("", set())
    assert eq.anchor_target_exists("menu", set(), "/ggongbab.html")      # hash route of the page's script
    assert not eq.anchor_target_exists("menu", set(), "/mukbang.html")
    assert eq.anchor_target_exists("%EC%98%A4", {"오"})


def test_classify_axe_fails_on_critical_and_serious_only():
    res = eq.classify_axe([{"impact": "critical"}, {"impact": "serious"}, {"impact": "serious"},
                           {"impact": "moderate"}, {"impact": "minor"}, {"impact": None}])
    assert res["counts"] == {"critical": 1, "serious": 2, "moderate": 1, "minor": 2}
    assert len(res["fail"]) == 3 and len(res["warn"]) == 3


def test_classify_axe_empty():
    assert eq.classify_axe([])["fail"] == []


def test_group_violations_merges_scopes_and_orders_by_impact():
    rows = [
        {"page": "a.html", "rule": "r1", "impact": "moderate", "scope": "phone/ko", "elements": ["x"]},
        {"page": "b.html", "rule": "r2", "impact": "serious", "scope": "phone/ko", "elements": ["y"], "evidence": "e"},
        {"page": "b.html", "rule": "r2", "impact": "serious", "scope": "desktop/en", "elements": ["y", "z"]},
    ]
    groups = eq.group_violations(rows)
    assert [g["rule"] for g in groups] == ["r2", "r1"]
    assert groups[0]["scopes"] == ["phone/ko", "desktop/en"] and groups[0]["elements"] == ["y", "z"]


def test_oversize_ratio():
    assert eq.oversize_ratio(720, 540, 60, 45) == 12.0
    assert eq.oversize_ratio(720, 540, 360, 270, dpr=2) == 1.0
    assert eq.oversize_ratio(720, 540, 0, 0) == 0.0


def test_perf_warnings_thresholds():
    ok = {"lcp_ms": 2500, "cls": 0.1, "bytes": 3 * 1024 * 1024}
    assert eq.perf_warnings("p", "phone/ko", ok, True) == []
    bad = {"lcp_ms": 2600, "cls": 0.11, "bytes": 3 * 1024 * 1024 + 1}
    assert len(eq.perf_warnings("p", "phone/ko", bad, True)) == 3
    assert len(eq.perf_warnings("p", "desktop/ko", bad, False)) == 2   # weight only on the phone


def test_page_key_and_human():
    assert eq.page_key(BASE + "/worldcup.html?cat=x") == "/worldcup.html"
    assert eq.human(2048) == "2 KB" and eq.human(5 * 1048576) == "5.00 MB"
