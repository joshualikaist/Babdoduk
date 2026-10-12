"""The page-text comparison (scripts/check_page_text.py) that phases 4 and 5 of the data plan rely
on: it must report every change a reader would see or hear, and nothing else. No browser here; the
snapshots are written by hand."""
import json

import check_page_text as page_text

VIEW = {"title": "밥도둑", "lang": "ko", "description": "KAIST 밥 정보",
        "text": ["밥도둑", "오늘의 메뉴", "문의"], "names": ["a[aria-label]=홈", "img[alt]=로고"]}


def changed(**fields):
    return {"index.html|ko": dict(VIEW, **fields)}


def test_the_same_pages_compare_equal(tmp_path, capsys):
    before = {"index.html|ko": VIEW, "index.html|en": dict(VIEW, lang="en")}
    assert page_text.compare(before, json.loads(json.dumps(before))) == []
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(before), encoding="utf-8")
    b.write_text(json.dumps(before), encoding="utf-8")
    assert page_text.main(["--compare", str(a), str(b)]) == 0
    assert "no change in 2 page views" in capsys.readouterr().out


def test_every_kind_of_change_is_reported():
    before = {"index.html|ko": VIEW}
    report = page_text.compare(before, changed(text=["밥도둑", "오늘 메뉴", "문의"]))
    assert "-오늘의 메뉴" in report and "+오늘 메뉴" in report
    assert page_text.compare(before, changed(title="밥도둑 홈")) == ["== index.html|ko title: '밥도둑' -> '밥도둑 홈'"]
    assert page_text.compare(before, changed(lang="en")) != []
    assert page_text.compare(before, changed(description="")) != []
    names = page_text.compare(before, changed(names=["a[aria-label]=처음으로", "img[alt]=로고"]))
    assert names == ["== index.html|ko accessible names", "-a[aria-label]=홈", "+a[aria-label]=처음으로"]
    # A page that appears or disappears is a change too.
    assert page_text.compare(before, {}) == ["== index.html|ko: only in before"]
    assert page_text.compare({}, before) == ["== index.html|ko: only in after"]


def test_a_change_fails_the_comparison(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"index.html|ko": VIEW}), encoding="utf-8")
    b.write_text(json.dumps(changed(text=["밥도둑"])), encoding="utf-8")
    assert page_text.main(["--compare", str(a), str(b)]) == 1
    assert "== index.html|ko text" in capsys.readouterr().out


def test_every_page_is_taken_and_the_hub_on_both_tabs():
    views = page_text.pages()
    assert "index.html" in views and "mukbang.html" in views and "event.html" in views
    assert "ggongbab.html" not in views
    assert "ggongbab.html#free" in views and "ggongbab.html#menu" in views
