"""The real-font smoke never passes on a page that could not load its web font. Offline; no browser."""
import check_real_fonts
from check_real_fonts import EXIT, PAGES, SIZES, verdict


def capture(**over):
    return {"page": "ggongbab.html", "lang": "en", "size": "390x844", "overflow": 0, "font": True, "errors": [], **over}


def test_clean_captures_with_the_web_font_pass():
    assert verdict([capture(), capture(lang="ko")]) == "PASS"


def test_overflow_or_a_page_error_fails_even_without_the_font():
    assert verdict([capture(), capture(overflow=12)]) == "FAIL"
    assert verdict([capture(errors=["TypeError: x"])]) == "FAIL"
    assert verdict([capture(font=False, overflow=3)]) == "FAIL"


def test_a_missing_web_font_is_a_skip_never_a_pass():
    assert verdict([capture(), capture(font=False)]) == "SKIP"
    assert verdict([]) == "SKIP"


def test_exit_codes_and_coverage():
    assert EXIT == {"PASS": 0, "FAIL": 1, "SKIP": 3}
    assert PAGES == ["index.html", "ggongbab.html", "event.html", "mukbang.html", "history.html", "food.html"]
    assert {(390, 844), (360, 800), (1440, 900)} <= set(SIZES)
    assert check_real_fonts.FONT_HOSTS == {"fonts.googleapis.com", "fonts.gstatic.com"}
