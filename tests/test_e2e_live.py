"""Pure helpers of scripts/e2e_live.py: the world cup phase and the link de-duplication."""
import datetime as dt

import e2e_live as e2e

WINDOW = {"start": "2026-10-16", "end": "2026-10-23", "previewFrom": "2026-10-13"}


def utc(*args):
    return dt.datetime(*args, tzinfo=dt.timezone.utc)


def test_phase_boundaries_are_read_in_korea_time():
    # 2026-10-15 15:00 UTC is already 10/16 00:00 in Korea.
    assert e2e.wc_phase(utc(2026, 10, 15, 14, 59), WINDOW) == "soon"
    assert e2e.wc_phase(utc(2026, 10, 15, 15, 0), WINDOW) == "live"
    # The last day runs to 23:59 KST = 14:59 UTC.
    assert e2e.wc_phase(utc(2026, 10, 23, 14, 59), WINDOW) == "live"
    assert e2e.wc_phase(utc(2026, 10, 23, 15, 0), WINDOW) == "ended"


def test_lab_honours_preview_from_but_production_does_not():
    now = utc(2026, 10, 14, 3, 0)
    assert e2e.wc_phase(now, WINDOW, is_lab=False) == "soon"
    assert e2e.wc_phase(now, WINDOW, is_lab=True) == "live"
    assert e2e.wc_phase(utc(2026, 10, 12, 3, 0), WINDOW, is_lab=True) == "soon"


def test_missing_window_is_live_and_gate_file_parses():
    assert e2e.wc_phase(utc(2026, 1, 1), {}) == "live"
    window = e2e.read_wc_window()
    assert window["start"] <= window["end"]


def test_dedupe_links_keeps_same_origin_unique_and_capped():
    base = "https://babdoduk.vercel.app"
    hrefs = ["index.html", "/index.html#top", "https://babdoduk.vercel.app/index.html", "mailto:a@b.c",
             "https://example.com/x", "", None, "ggongbab.html?x=1", "ggongbab.html?x=1#y", "javascript:void(0)"]
    assert e2e.dedupe_links(hrefs, base) == [
        "https://babdoduk.vercel.app/index.html", "https://babdoduk.vercel.app/ggongbab.html?x=1"]
    many = [f"p{i}.html" for i in range(100)]
    assert len(e2e.dedupe_links(many, base, cap=7)) == 7


def test_post_violations_production_vs_lab():
    rpc = {"host": "x.supabase.co", "path": "/rest/v1/rpc/worldcup_record_game"}
    other = {"host": "x.supabase.co", "path": "/rest/v1/something"}
    assert e2e.post_violations([rpc], is_lab=False) == [rpc]
    assert e2e.post_violations([rpc, other], is_lab=True) == [other]
