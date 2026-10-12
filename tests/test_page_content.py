"""The page content of data/content/ (data plan phase 4): event.html and history.html show
events.json and history.json as scripts/sync_site_chrome.py writes them. No network; the pages'
translation tables are evaluated in Node."""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import page_content
import sync_site_chrome as chrome
from validate_content import validate_authored

ROOT = Path(__file__).resolve().parents[1]
EVENTS = json.loads((ROOT / "data/content/events.json").read_text(encoding="utf-8"))
HISTORY = json.loads((ROOT / "data/content/history.json").read_text(encoding="utf-8"))


def tables(html: str) -> dict:
    """The page's ko and en translation tables, as the browser evaluates them."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    start = html.index("window.BABDODUK_STR = ") + len("window.BABDODUK_STR = ")
    end = html.index("\n    };\n", start) + len("\n    }")
    result = subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(" + html[start:end] + "))"],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def activity(start, end, title, confirmation="announced"):
    return {"start": start, "end": end, "confirmation": confirmation, "link": "https://www.instagram.com/babdodukms/",
            "title": {"ko": title, "en": title.upper()}, "details": {"summary": {"ko": "내용", "en": "Summary"}}}


def test_the_pages_carry_the_content_in_both_languages():
    assert chrome.main(["--check"]) == 0   # the committed pages are what the sync writes
    html = (ROOT / "event.html").read_text(encoding="utf-8")
    strings = tables(html)
    ordered = sorted(EVENTS["activities"], key=lambda item: (item["start"], item["end"]))
    rows = re.findall(r'<li class="event-item" data-start="([\d-]+)" data-end="([\d-]+)" data-confirmation="(\w+)">', html)
    assert rows == [(item["start"], item["end"], item["confirmation"]) for item in ordered]
    for index, item in enumerate(ordered):
        for lang in ("ko", "en"):
            assert strings[lang][f"event.e{index}.summary"] == item["title"][lang]
            sheet = strings[lang][f"event.e{index}.detail"]
            for field, pair in item["details"].items():
                assert pair[lang] in sheet, (index, field, lang)
            if "place" in item:
                assert strings[lang][f"event.e{index}.place"] == item["place"][lang]
        # Korean is in the markup itself, so the page reads without JavaScript.
        assert f'data-i18n="event.e{index}.summary">{item["title"]["ko"]}</h3>' in html
    history = (ROOT / "history.html").read_text(encoding="utf-8")
    strings = tables(history)
    for index, item in enumerate(sorted(HISTORY["milestones"], key=lambda m: m["date"]), 1):
        assert strings["ko"][f"history.t{index}.label"] == item["title"]["ko"]
        assert strings["en"][f"history.t{index}.desc"] == item["text"]["en"]
        assert f'datetime="{item["date"]}" data-i18n="history.t{index}.year"' in history
    assert strings["en"]["history.roadmap.label"] == HISTORY["roadmap"]["title"]["en"]
    assert history.index("history.t1.label") < history.index("history.roadmap.label")


def test_order_and_dates_are_computed_not_authored():
    data = {"schemaVersion": 1, "notices": [
        {"date": "2026-10-01", "title": {"ko": "먼저", "en": "Older"}, "text": {"ko": "가", "en": "a"}},
        {"date": "2026-10-11", "title": {"ko": "나중", "en": "Newer"}, "text": {"ko": "나", "en": "b"}}],
        "activities": [activity("2026-12-30", "2027-01-02", "연말"), activity("2026-05-19", "2026-05-19", "하루"),
                       activity("2026-05-19", "2026-05-18", "앞")]}
    blocks = page_content.event_blocks(data)
    rows = "\n".join(blocks["events"])
    assert rows.index("앞") < rows.index("하루") < rows.index("연말")      # start, then end date
    assert '<time datetime="2026-05-19">2026.05.19</time></p>' in rows         # one day, one date
    assert "2026.12.30</time> — <time datetime=\"2027-01-02\">2027.01.02</time>" in rows  # the year changes
    assert blocks["notices"][0].count("나중") == 1 and "먼저" in blocks["notices"][1]   # newest first
    strings = page_content.event_strings(data)
    assert strings["en"]["event.n0.title"] == "Newer" and strings["ko"]["event.e2.summary"] == "연말"
    history = page_content.history_blocks({"schemaVersion": 1, "roadmap": HISTORY["roadmap"],
                                           "milestones": list(reversed(HISTORY["milestones"]))})
    assert history == page_content.history_blocks(HISTORY)
    assert page_content.milestone_date("2026-09-30", "ko") == "2026.9.30"
    assert page_content.milestone_date("2026-09-30", "en") == "Sep 30, 2026"


def test_a_note_replaces_the_labelled_rows():
    item = activity("2026-11-02", "2026-11-03", "미정")
    item["details"] = {"note": {"ko": "<strong>일정 미정</strong>", "en": "<strong>TBA</strong>"}}
    sheet = "".join(page_content.detail_sheet(item["details"], "en"))
    assert sheet == ('<div class="event-detail-sheet"><div class="event-detail-row event-detail-row--solo">'
                     '<div class="event-detail-value"><strong>TBA</strong></div></div></div>')


def test_an_edit_reaches_the_page_in_both_languages(tmp_path, monkeypatch):
    content = tmp_path / "data/content"
    shutil.copytree(ROOT / "data/content", content)
    data = copy.deepcopy(EVENTS)
    data["activities"].append(activity("2026-11-20", "2026-11-21", "밥도둑 시식회"))
    data["notices"].append({"date": "2026-11-01", "title": {"ko": "시식회 안내", "en": "Tasting"},
                            "text": {"ko": "11월에 열려요.", "en": "It's in November."}})
    (content / "events.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(page_content, "CONTENT", content)
    page = chrome.synced("event.html")
    assert page != (ROOT / "event.html").read_text(encoding="utf-8")   # the committed page is now stale
    strings = tables(page)
    assert strings["ko"]["event.e3.summary"] == "밥도둑 시식회" and strings["en"]["event.e3.summary"] == "밥도둑 시식회".upper()
    assert strings["en"]["event.n0.text"] == "It's in November."
    assert '<strong data-i18n="event.n0.title">시식회 안내</strong>' in page
    assert page.count('<li class="event-item"') == len(EVENTS["activities"]) + 1


def test_content_the_contracts_cannot_judge_is_refused(tmp_path):
    content = tmp_path / "data/content"
    shutil.copytree(ROOT / "data/content", content)
    data = copy.deepcopy(EVENTS)
    data["activities"][0]["end"] = "2026-05-01"                                        # before its start
    data["activities"][1]["details"]["prizes"]["en"] = 'Prizes <a href="https://x.example">here</a>'
    data["activities"][1]["details"]["summary"]["ko"] = "<strong>열린 채로"
    (content / "events.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    history = copy.deepcopy(HISTORY)
    history["milestones"][1]["date"] = history["milestones"][0]["date"]
    history["milestones"][0]["picture"]["image"] = "images/history-missing.png"
    (content / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    errors = page_content.content_errors(tmp_path)
    assert any("ends before it starts" in e for e in errors)
    assert any("prizes.en has markup other than <strong>" in e for e in errors)
    assert any("summary.ko leaves a <strong> open" in e for e in errors)
    assert any("share a date" in e for e in errors) and any("does not exist" in e for e in errors)
    assert page_content.content_errors(ROOT) == []
    assert not [e for e in validate_authored(ROOT) if "events.json" in e or "history.json" in e]


def test_a_page_without_its_markers_fails_loudly():
    with pytest.raises(SystemExit, match="@content:events"):
        chrome.fill_blocks("event.html", "<ol></ol>", "content", {"events": []})
    with pytest.raises(SystemExit, match="has no"):
        chrome.fill_blocks("event.html", "<!-- @content:events -->\n<li>", "content", {"events": []})
