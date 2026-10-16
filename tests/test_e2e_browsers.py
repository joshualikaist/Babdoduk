"""Pure helpers of scripts/e2e_browsers.py."""
import pytest

import e2e_browsers as eb


def test_horizontal_overflow_allows_one_pixel():
    assert not eb.horizontal_overflow(390, 390)
    assert not eb.horizontal_overflow(391, 390)
    assert eb.horizontal_overflow(392, 390)


def test_small_targets_flags_below_44():
    boxes = [{"sel": "a", "w": 44, "h": 44}, {"sel": "b", "w": 100, "h": 40}, {"sel": "c", "w": 43.6, "h": 50}]
    assert [b["sel"] for b in eb.small_targets(boxes)] == ["b"]


def test_parse_engines():
    assert eb.parse_engines(None) == list(eb.ENGINES)
    assert eb.parse_engines("firefox-desktop") == ["firefox-desktop"]
    with pytest.raises(ValueError):
        eb.parse_engines("opera")


def test_audio_ok_needs_exactly_one_context_and_no_errors():
    assert eb.audio_ok(1, [])[0]
    assert not eb.audio_ok(0, [])[0]
    assert not eb.audio_ok(2, [])[0]
    assert not eb.audio_ok(1, ["boom"])[0]


def test_known_noise_is_narrow():
    assert eb.is_known_noise('Cookie "__cf_bm" has been rejected for invalid domain.')
    assert eb.is_known_noise("Cross-Origin Request Blocked: https://x.supabase.co/rest/v1/rpc/worldcup_record_game")
    assert not eb.is_known_noise("Cross-Origin Request Blocked: https://x.supabase.co/rest/v1/other")
    assert not eb.is_known_noise("TypeError: x is undefined")
    assert eb.is_known_noise('JavaScript Error: "InvalidStateError: Navigated away from page"')
