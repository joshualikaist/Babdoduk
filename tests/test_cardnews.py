"""The weekly 꽁밥 card news (scripts/render_cardnews.py, docs/CARDNEWS.md): which events go on which
card and how. Pure HTML building only; drawing the PNGs needs Chrome and is not run here."""
import json
import re
from datetime import date, datetime

import pytest

import render_cardnews as rc

MONDAY = date(2026, 11, 2)
NAMES = {"meal": "식사", "refreshment": "다과", "lunchbox": "도시락", "coupon": "식권", "unknown": ""}


def event(start, title="행사", end=None, food="meal", provided="true", building="E9", room="1층", name="",
          audience=None, sources=("dooray",)):
    return {"title": title, "startAt": start, "endAt": end, "sources": [{"type": s} for s in sources],
            "location": {"name": name, "building": building, "room": room},
            "food": {"provided": provided, "type": food},
            "audience": {"text": audience, "basis": "stated"} if audience else None}


def cards(events, tpl=None):
    document = rc.build({"events": events}, MONDAY, NAMES, tpl)
    return re.findall(r'<section class="card[^"]*">.*?</section>', document, re.S)


def test_a_cover_and_a_card_only_for_each_weekday_with_events_by_korean_day():
    """Owner 2026-11-02: a weekday without events gets no card."""
    events = [event("2026-11-02T12:00:00+09:00", "월요일 점심"), event("2026-11-06T15:00:00+09:00", "금요일 오후"),
              event("2026-11-01T23:30:00+09:00", "일요일 밤"), event("2026-11-07T10:00:00+09:00", "토요일"),
              event("2026-11-03T15:30:00+00:00", "UTC로 적힌 수요일 새벽")]   # 11-04 00:30 KST
    found = cards(events)
    assert len(found) == 4 and 'class="card cover"' in found[0]
    assert "월요일 점심" in found[1] and "UTC로 적힌 수요일 새벽" in found[2] and "금요일 오후" in found[3]
    joined = "".join(found)
    assert "일요일 밤" not in joined and "토요일" not in joined            # the weekend is not this card news
    assert "아직 알려진 꽁밥이 없어요" not in joined
    assert [b for b in re.findall(r'<div class="n">([^<]+)</div>', found[0])] == ["1", "–", "1", "–", "1"]
    assert "이번 주 꽁밥 <em>3개</em>" in found[0] and "11월 2일(월) – 11월 6일(금)" in found[0]
    assert [re.search(r'class="page">(\d) / (\d)<', c).groups() for c in found] == [(str(n), "4") for n in range(1, 5)]


def test_an_event_held_on_several_days_is_on_each_of_those_days():
    """Owner 2026-11-03: the 자연과학 토크 콘서트 ran every weekday but was only on Monday's card."""
    series = event("2026-11-02T12:00:00+09:00", "자연과학과 함께하는 토크 콘서트", end="2026-11-06T19:30:00+09:00")
    series["id"] = "talk"
    series["sessions"] = [{"startAt": f"2026-11-0{d}T12:00:00+09:00", "endAt": f"2026-11-0{d}T12:50:00+09:00"} for d in (2, 3, 4, 5)]
    series["sessions"].append({"startAt": "2026-11-06T16:00:00+09:00", "endAt": "2026-11-06T19:30:00+09:00"})
    other = event("2026-11-04T09:00:00+09:00", "수요일 아침")
    found = cards([series, other])
    assert len(found) == 6
    for day in found[1:]:
        assert "토크 콘서트" in day
    assert ">12:00<small>~ 12:50</small>" in found[2] and ">16:00<small>~ 19:30</small>" in found[5]
    assert found[3].index("수요일 아침") < found[3].index("토크 콘서트")          # each day by that day's time
    assert re.findall(r'<div class="n">([^<]+)</div>', found[0]) == ["1", "1", "2", "1", "1"]
    assert "이번 주 꽁밥 <em>2개</em>" in found[0]                                  # an event counts once
    item = rc.entry({"events": [series, other]}, MONDAY, datetime(2026, 11, 1, 18, 0, tzinfo=rc.KST))
    assert item["counts"] == [1, 1, 2, 1, 1] and item["total"] == 2 and item["days"] == [0, 1, 2, 3, 4]


def test_sessions_outside_the_week_and_an_event_without_sessions():
    started_last_week = event("2026-10-30T12:00:00+09:00", "지난주부터", end="2026-11-03T13:00:00+09:00")
    started_last_week["sessions"] = [{"startAt": "2026-10-30T12:00:00+09:00"}, {"startAt": "2026-11-03T12:00:00+09:00"}]
    long_span = event("2026-11-02T16:00:00+09:00", "설명회 일정", end="2026-11-25T20:00:00+09:00")
    found = cards([started_last_week, long_span])
    assert len(found) == 3 and "설명회 일정" in found[1] and "지난주부터" in found[2]
    assert "지난주부터" not in found[1] and "설명회 일정" not in found[2]   # no sessions: the day it starts


def test_the_cards_are_drawn_from_the_live_list_and_never_from_a_stale_copy(tmp_path):
    now = datetime(2026, 11, 8, 18, 0, tzinfo=rc.KST)
    assert rc.LIVE_FEED.startswith("https://") and rc.LIVE_FEED.endswith("/data/ggongbab/latest.json")
    assert not rc.stale({"generatedAt": "2026-11-08T09:00:00+09:00"}, now)
    assert rc.stale({"generatedAt": "2026-10-31T20:21:46+09:00"}, now)          # the copy behind the 11-02 cards
    assert rc.stale({}, now) and rc.stale({"generatedAt": "어제"}, now)
    copy = tmp_path / "latest.json"
    copy.write_text(json.dumps({"generatedAt": "2026-11-08T09:00:00+09:00", "events": []}), encoding="utf-8")
    assert rc.load_feed(str(copy))["events"] == []
    asked = []

    class Live:
        def __init__(self, request, timeout):
            asked.append((request.full_url, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"generatedAt": "2026-11-08T09:00:00+09:00", "events": [1]}'

    assert rc.load_feed(rc.LIVE_FEED, opener=Live)["events"] == [1] and asked == [(rc.LIVE_FEED, 30)]


def test_a_day_card_shows_time_title_food_place_and_a_stated_audience():
    (_, monday, *_) = cards([event("2026-11-02T12:00:00+09:00", "토크 콘서트", end="2026-11-02T13:30:00+09:00",
                                   building="E6-1", room="1501호", audience="학사과정 학생")])
    assert ">12:00<small>~ 13:30</small>" in monday and "<h2>토크 콘서트</h2>" in monday
    assert '<span class="pill">식사</span>' in monday and "📍 E6-1 1501호" in monday and "대상 · 학사과정 학생" in monday
    assert "꽁밥 1개" in monday and "dense" not in monday.split(">")[0]


def test_what_the_list_does_not_have_is_left_out():
    (_, monday, *_) = cards([event("2026-11-02T12:00:00+09:00", food="unknown", provided="unknown", building="", room="",
                                   end="2026-11-03T01:00:00+09:00")])
    assert 'class="pill"' not in monday and "📍" not in monday and "대상" not in monday
    assert '<div class="t">12:00</div>' in monday      # an end on another day is not shown as a time


def test_without_splitting_a_busy_day_is_dense_shows_four_and_says_how_many_more():
    busy = [event(f"2026-11-06T{9 + i:02d}:00:00+09:00", f"행사 {i}", audience="누구나") for i in range(6)]
    tpl = rc.template()
    tpl["rules"]["splitBusyDays"] = False
    friday = cards(busy, tpl)[-1]
    assert friday.startswith('<section class="card dense">') and friday.count('<article class="ev">') == 4
    assert "외 2개 더 · 사이트에서 확인하세요" in friday and "대상 ·" not in friday    # no room for the audience line
    three = cards(busy[:3])[-1]
    assert three.startswith('<section class="card dense">') and "외" not in three and "대상 · 누구나" in three


def test_a_day_with_more_than_a_card_holds_goes_on_to_a_second_card():
    """Owner 2026-11-03: no event is left off the card news. Friday 11-06 had five; the fifth, the
    talk concert's Shake Shack evening, was hidden behind "외 1개 더"."""
    busy = [event(f"2026-11-06T{9 + i:02d}:00:00+09:00", f"행사 {i}", audience="누구나") for i in range(6)]
    found = cards(busy)
    assert len(found) == 3
    first, second = found[1], found[2]
    assert first.count('<article class="ev">') == 4 and second.count('<article class="ev">') == 2
    assert "외 " not in first + second and "행사 5" in second
    assert "이번 주 꽁밥 · 금 · 1/2" in first and "이번 주 꽁밥 · 금 · 2/2" in second
    assert "꽁밥 6개" in first and "꽁밥 6개" in second                     # the day's count on both
    assert re.findall(r'<div class="n">([^<]+)</div>', found[0])[4] == "6"
    assert [re.search(r'class="page">(\d) / (\d)<', c).groups() for c in found] == [(str(n), "3") for n in range(1, 4)]
    item = rc.entry({"events": busy}, MONDAY, datetime(2026, 11, 1, 18, 0, tzinfo=rc.KST))
    assert item["days"] == [4, 4] and len(item["images"]) == 3 and item["counts"][4] == 6


def test_a_week_without_events_is_the_cover_alone_unless_the_template_keeps_empty_days():
    assert len(cards([])) == 1
    tpl = rc.template()
    tpl["rules"]["skipEmptyDays"] = False
    found = cards([], tpl)
    assert len(found) == 6 and "아직 알려진 꽁밥이 없어요" in found[2] and "꽁밥을 봤다면 제보해 주세요" in found[2]


def test_an_event_known_only_from_a_reader_tip_stays_on_the_site():
    """Owner 2026-11-02: tips are not made into cards; one also known from a mail is."""
    found = cards([event("2026-11-02T12:00:00+09:00", "제보로만 안 행사", sources=("tip",)),
                   event("2026-11-02T13:00:00+09:00", "메일로도 온 행사", sources=("dooray", "tip"))])
    assert len(found) == 2 and "메일로도 온 행사" in found[1] and "제보로만 안 행사" not in "".join(found)
    assert "이번 주 꽁밥 <em>1개</em>" in found[0]


def test_the_wording_and_colors_come_from_the_template():
    tpl = rc.template()
    tpl["cover"]["headline"], tpl["day"]["count"], tpl["footer"]["note"] = "다음 주", "{n}건", "바뀔 수 있음"
    tpl["colors"]["accent"] = "#123456"
    document = rc.build({"events": [event("2026-11-02T12:00:00+09:00")]}, MONDAY, NAMES, tpl)
    assert "<h1>다음 주<br />" in document and '<span class="count">1건</span>' in document and "바뀔 수 있음" in document
    assert "--accent: #123456;" in document and "var(--accent)" in document
    assert set(tpl["rules"]) == {"perCard", "denseFrom", "skipEmptyDays", "skipTipOnly", "splitBusyDays"}


def test_events_away_from_daejeon_carry_a_seoul_mark():
    (_, monday, *_) = cards([event("2026-11-02T16:00:00+09:00", name="KAIST 경영대학 서울캠퍼스", building="수펙스홀", room="")])
    assert '<span class="pill away">서울</span>' in monday


def test_text_from_the_list_stays_text():
    (_, monday, *_) = cards([event("2026-11-02T12:00:00+09:00", "<img src=x onerror=alert(1)>", room="<b>")])
    assert "<img" not in monday and "&lt;img src=x onerror=alert(1)&gt;" in monday and "&lt;b&gt;" in monday


@pytest.mark.parametrize("today, monday", [("2026-11-02", "2026-11-02"), ("2026-11-06", "2026-11-02"),
                                           ("2026-11-07", "2026-11-09"), ("2026-11-08", "2026-11-09")])
def test_a_run_is_for_this_week_until_friday_and_the_next_from_saturday(today, monday):
    assert rc.monday_of(date.fromisoformat(today)).isoformat() == monday


def test_the_index_keeps_the_newest_week_first_and_replaces_a_rerun(tmp_path):
    feed = {"generatedAt": "2026-10-31T20:21:46+09:00", "events": [event("2026-11-02T12:00:00+09:00")]}
    now = datetime(2026, 11, 2, 14, 0)
    rc.write_index(tmp_path, rc.entry(feed, date(2026, 10, 26), now))
    rc.write_index(tmp_path, rc.entry(feed, MONDAY, now))
    index = rc.write_index(tmp_path, rc.entry(feed, MONDAY, now))
    assert [w["week"] for w in index["weeks"]] == ["2026-11-02", "2026-10-26"]
    newest = index["weeks"][0]
    assert newest["counts"] == [1, 0, 0, 0, 0] and newest["total"] == 1 and newest["days"] == [0]
    assert newest["images"] == ["data/cardnews/2026-11-02/1.png", "data/cardnews/2026-11-02/2.png"]
    assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8")) == index


def test_the_published_week_matches_its_images():
    from pathlib import Path
    root = Path(rc.ROOT)
    index = json.loads((root / "data/cardnews/index.json").read_text(encoding="utf-8"))
    for week in index["weeks"]:
        assert len(week["counts"]) == 5 and max(week["counts"]) <= week["total"] <= sum(week["counts"])
        assert sorted(set(week["days"])) == [i for i in range(5) if week["counts"][i]] and week["days"] == sorted(week["days"])
        assert len(week["images"]) == len(week["days"]) + 1
        folder = sorted((root / "data/cardnews" / week["week"]).glob("*.png"))
        assert [f"data/cardnews/{week['week']}/{p.name}" for p in folder] == week["images"]     # no stale card left
        for src in week["images"]:
            data = (root / src).read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[16:24] == (1080).to_bytes(4, "big") + (1350).to_bytes(4, "big")


class Opener:
    def __init__(self, ok=True, error=None):
        self.ok, self.error, self.requests = ok, error, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"ok": self.ok}).encode()


def test_the_cards_go_to_telegram_as_one_album_with_the_caption_on_the_first(tmp_path):
    paths = []
    for n in range(1, 4):
        path = tmp_path / f"{n}.png"
        path.write_bytes(b"\x89PNG fake " + bytes([n]))
        paths.append(path)
    opener = Opener()
    assert rc.send(paths, "📅 이번 주 꽁밥", "123:SECRET", "42", opener) == "PUSH_SENT"
    (request,) = opener.requests
    assert request.full_url == "https://api.telegram.org/bot123:SECRET/sendMediaGroup"
    body = request.data.decode("utf-8", "replace")
    media = json.loads(re.search(r'name="media"\r\n\r\n(.*?)\r\n--', body, re.S).group(1))
    assert [m["media"] for m in media] == ["attach://card1", "attach://card2", "attach://card3"]
    assert media[0]["caption"] == "📅 이번 주 꽁밥" and all("caption" not in m for m in media[1:])
    assert body.count('filename="') == 3 and 'name="chat_id"\r\n\r\n42' in body
    single = Opener()
    assert rc.send(paths[:1], "표지만", "123:SECRET", "42", single) == "PUSH_SENT"
    assert single.requests[0].full_url.endswith("/sendPhoto")
    many = []
    for n in range(1, 12):
        path = tmp_path / f"m{n}.png"
        path.write_bytes(b"\x89PNG fake " + bytes([n]))
        many.append(path)
    batched = Opener()
    assert rc.send(many, "📅 이번 주 꽁밥", "123:SECRET", "42", batched) == "PUSH_SENT"
    assert [r.full_url.rsplit("/", 1)[1] for r in batched.requests] == ["sendMediaGroup", "sendPhoto"]   # 10 + 1
    first = batched.requests[0].data.decode("utf-8", "replace")
    assert first.count('filename="') == 10 and "📅 이번 주 꽁밥" in first
    assert 'name="caption"' not in batched.requests[1].data.decode("utf-8", "replace")


def test_a_failed_send_returns_a_fixed_code_without_the_token(tmp_path):
    import urllib.error
    path = tmp_path / "1.png"
    path.write_bytes(b"x")
    for opener, code in ((Opener(ok=False), "PUSH_REJECTED"), (Opener(error=urllib.error.URLError("down")), "PUSH_TRANSPORT_FAILED")):
        result = rc.send([path, path], "c", "123:SECRET", "42", opener)
        assert result == code and "SECRET" not in result


def test_cards_are_kept_a_month_then_their_files_are_deleted(tmp_path):
    """Owner 2026-11-02: keep the card news a month."""
    feed = {"generatedAt": "2026-11-01T00:00:00+09:00", "events": []}
    now = datetime(2026, 11, 2, 14, 0)
    weeks = [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26), MONDAY]
    for monday in weeks:
        (tmp_path / monday.isoformat()).mkdir()
        (tmp_path / monday.isoformat() / "1.png").write_bytes(b"x")
        index = rc.write_index(tmp_path, rc.entry(feed, monday, now))
    assert [w["week"] for w in index["weeks"]] == ["2026-11-02", "2026-10-26", "2026-10-19", "2026-10-12", "2026-10-05"]
    assert not (tmp_path / "2026-09-28").exists() and (tmp_path / "2026-10-05" / "1.png").exists()
    (tmp_path / "notes").mkdir()                                  # only week folders are ever removed
    rc.write_index(tmp_path, rc.entry(feed, date(2026, 11, 9), now))
    assert not (tmp_path / "2026-10-05").exists() and (tmp_path / "notes").exists()
