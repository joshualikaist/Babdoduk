"""밥약 메이커 places (docs/BOBYAK.md): the public-data candidates, the operator's review and the published file,
and the drafted place-report migration. Synthetic rows only; no network (a request would fail the test)."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from places import semas

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 8, 10, 0, tzinfo=timezone(timedelta(hours=9)))


def row(ref, name, dong="어은동", large="음식", middle="한식", small="백반/한정식", lat="36.3625", lon="127.3590", **extra):
    base = {"bizesId": ref, "bizesNm": name, "brchNm": "", "indsLclsNm": large, "indsMclsNm": middle, "indsSclsNm": small,
            "ctprvnNm": "대전광역시", "signguNm": "유성구", "ldongNm": dong, "rdnmAdr": f"대전광역시 유성구 대학로 {ref[-2:]}",
            "lnoAdr": "", "lat": lat, "lon": lon}
    base.update(extra)
    return base


ROWS = [row("MA0101", "어은 국밥"), row("MA0102", "궁동 떡볶이", dong="궁동", middle="분식", small="떡볶이"),
        row("MA0103", "카이스트 카페", dong="구성동", middle="비알코올", small="카페"),
        row("MA0104", "세탁소", large="수리·개인"),                         # not food
        row("MA0105", "봉명 고깃집", dong="봉명동"),                          # outside the three areas
        row("MA0106", "멀리 국밥", lat="36.45"),                              # outside the rectangle
        row("MA0107", "서울 국밥", ctprvnNm="서울특별시")]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test reached the network")
    monkeypatch.setattr(semas.urllib.request, "urlopen", refuse)


def test_only_food_businesses_in_kaist_eoeun_and_gung_become_candidates():
    data = semas.build_candidates(ROWS, NOW)
    assert [s["ref"] for s in data["stores"]] == ["MA0101", "MA0102", "MA0103"]
    by = {s["ref"]: s for s in data["stores"]}
    assert (by["MA0101"]["area"], by["MA0102"]["area"], by["MA0103"]["area"]) == ("eoeun", "gung", "kaist")
    assert (by["MA0101"]["cuisine"], by["MA0102"]["cuisine"], by["MA0103"]["cuisine"]) == ("korean", "snack", "cafe")
    assert data["count"] == 3 and data["fetchedAt"].startswith("2026-11-08")


@pytest.mark.parametrize("middle,small,cuisine", [("중식", "짜장/짬뽕", "chinese"), ("일식", "초밥", "japanese"),
                                                  ("서양식", "파스타", "western"), ("동남아시아", "쌀국수", "asian"),
                                                  ("주점", "요리 주점", "pub"), ("제과제빵떡케이크", "빵/도넛", "bakery"),
                                                  ("기타 간이", "햄버거", "fastfood"), ("구내식당·뷔페", "뷔페", "other")])
def test_cuisine_comes_from_the_category_names(middle, small, cuisine):
    assert semas.cuisine_of(middle, small) == cuisine


def test_the_key_is_read_from_the_environment_or_the_credentials_file_and_never_printed(tmp_path, capsys, monkeypatch):
    creds = tmp_path / "credentials"
    creds.write_text("OTHER=1\nexport DATA_GO_KR_KEY='abc+def/=='\n", encoding="utf-8")
    assert semas.read_key({}, creds) == "abc+def/=="
    assert semas.read_key({"DATA_GO_KR_KEY": "env"}, creds) == "env"
    assert semas.read_key({}, tmp_path / "missing") is None
    monkeypatch.setattr(semas, "CREDENTIALS", creds)
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    assert semas.main(["key"]) == 0
    out = capsys.readouterr()
    assert "DATA_GO_KR_KEY: set" in out.out and "abc" not in out.out + out.err


def test_fetch_without_a_key_makes_no_request(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(semas, "CREDENTIALS", tmp_path / "none")
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    assert semas.main(["fetch"]) == 1                 # the autouse fixture fails on any request
    assert "no request was made" in capsys.readouterr().err


def page_xml(rows, total, code="00"):
    items = "".join("<item>" + "".join(f"<{k}>{v}</{k}>" for k, v in r.items()) + "</item>" for r in rows)
    return (f"<response><header><resultCode>{code}</resultCode><resultMsg>NORMAL SERVICE</resultMsg></header>"
            f"<body><items>{items}</items><totalCount>{total}</totalCount></body></response>")


class Reply:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.text.encode("utf-8")


def test_fetch_pages_through_the_rectangle_and_keeps_the_key_out_of_errors():
    asked = []
    pages = [page_xml(ROWS[:4], 6), page_xml(ROWS[4:6], 6)]

    def opener(url, timeout):
        asked.append(url)
        return Reply(pages[len(asked) - 1])
    rows = semas.fetch("SECRET+KEY", opener=opener, pause=0)
    assert len(rows) == 6 and len(asked) == 2
    assert all(u.startswith(semas.API + "?") and "minx=127.338" in u and "numOfRows=1000" in u for u in asked)
    assert "pageNo=2" in asked[1]

    with pytest.raises(semas.PlacesError) as refused:
        semas.fetch("SECRET+KEY", opener=lambda url, timeout: Reply(
            "<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
            "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"), pause=0)
    assert "30" in str(refused.value) and "SECRET" not in str(refused.value)
    assert semas.fetch("k", opener=lambda url, timeout: Reply(page_xml([], 0, code="03")), pause=0) == []
    with pytest.raises(semas.PlacesError):
        semas.fetch("k", opener=lambda url, timeout: Reply(page_xml([], 0, code="99")), pause=0)


def test_nothing_is_published_until_the_operator_decides():
    candidates = semas.build_candidates(ROWS, NOW)
    report, approvals = semas.review(candidates, semas.empty_feed(), {"items": []})
    assert [r["ref"] for r in report["new"]] == ["MA0101", "MA0102", "MA0103"]
    assert all(item["decision"] == "" for item in approvals["items"])
    feed, summary = semas.publish(candidates, semas.empty_feed(), approvals, "2026-11-08")
    assert feed["places"] == [] and summary["undecided"] == 3
    # Reviewing again keeps every row once and never resets a decision.
    approvals["items"][0]["decision"] = "candidate"
    _, again = semas.review(candidates, semas.empty_feed(), approvals)
    assert len(again["items"]) == 3 and again["items"][0]["decision"] == "candidate"


def decided(approvals, **decisions):
    for item in approvals["items"]:
        if item["ref"] in decisions:
            item.update(decisions[item["ref"]])
    return approvals


def test_publish_applies_candidate_verified_and_skip_with_stable_site_ids():
    candidates = semas.build_candidates(ROWS, NOW)
    _, approvals = semas.review(candidates, semas.empty_feed(), {"items": []})
    fact = {"kind": "budget", "band": "under10k", "text": "국밥 9,000원", "source": "operator", "checkedAt": "2026-11-07"}
    decided(approvals, MA0101={"decision": "verified", "checkedAt": "2026-11-07", "facts": [fact]},
            MA0102={"decision": "candidate"}, MA0103={"decision": "skip"})
    feed, summary = semas.publish(candidates, semas.empty_feed(), approvals, "2026-11-08")
    assert semas.feed_errors(feed) == []
    assert [(p["id"], p["name"], p["status"]) for p in feed["places"]] == [("p-0001", "어은 국밥", "verified"),
                                                                          ("p-0002", "궁동 떡볶이", "candidate")]
    verified, candidate = feed["places"]
    assert verified["verifiedAt"] == "2026-11-07" and verified["facts"] == [fact]
    assert candidate["facts"] == [] and candidate["verifiedAt"] is None
    assert verified["sources"] == [{"kind": "semas", "ref": "MA0101", "checkedAt": "2026-11-08"}]
    assert summary["added"] == 2 and summary["skipped"] == 1
    # Publishing the same decisions again changes nothing.
    again, _ = semas.publish(candidates, feed, approvals, "2026-11-09")
    assert again["places"] == feed["places"]


def test_a_store_that_left_the_public_data_is_only_flagged_until_the_operator_says_closed():
    candidates = semas.build_candidates(ROWS, NOW)
    _, approvals = semas.review(candidates, semas.empty_feed(), {"items": []})
    decided(approvals, MA0101={"decision": "candidate"}, MA0102={"decision": "candidate"})
    feed, _ = semas.publish(candidates, semas.empty_feed(), approvals, "2026-11-08")
    later = semas.build_candidates([ROWS[1], dict(ROWS[0], bizesNm="어은 국밥 본점")], NOW)
    later["stores"] = [s for s in later["stores"] if s["ref"] != "MA0102"]          # MA0102 disappeared
    report, approvals2 = semas.review(later, feed, {"items": []})
    assert [r["ref"] for r in report["missing"]] == ["MA0102"]
    assert report["changed"] == [{"ref": "MA0101", "id": "p-0001", "before": {"name": "어은 국밥", "address": feed["places"][0]["address"]},
                                  "after": {"name": "어은 국밥 본점", "address": feed["places"][0]["address"]}}]
    same, _ = semas.publish(later, feed, approvals2, "2026-11-09")              # undecided: nothing moves
    assert same["places"] == feed["places"]
    decided(approvals2, MA0102={"decision": "closed"}, MA0101={"decision": "accept"})
    final, summary = semas.publish(later, feed, approvals2, "2026-11-09")
    assert [(p["name"], p["status"]) for p in final["places"]] == [("어은 국밥 본점", "candidate"), ("궁동 떡볶이", "closed")]
    assert final["places"][0]["id"] == "p-0001" and summary == dict(summary, closed=1, updated=1)


@pytest.mark.parametrize("bad,message", [
    ({"decision": "verified"}, "checkedAt"),
    ({"decision": "verified", "checkedAt": "2026-11-07", "facts": [{"kind": "budget", "text": "싸요", "source": "operator",
                                                                   "checkedAt": "2026-11-07"}]}, "band"),
    ({"decision": "verified", "checkedAt": "2026-11-07", "facts": [{"kind": "menu", "text": "국밥", "checkedAt": "2026-11-07"}]}, "source"),
    ({"decision": "closed"}, "no published place"),
    ({"decision": "accept"}, "no published place"),
])
def test_publish_refuses_a_decision_it_cannot_honour(bad, message):
    candidates = semas.build_candidates(ROWS, NOW)
    _, approvals = semas.review(candidates, semas.empty_feed(), {"items": []})
    decided(approvals, MA0101=bad)
    with pytest.raises(semas.PlacesError, match=message):
        semas.publish(candidates, semas.empty_feed(), approvals, "2026-11-08")


def test_the_feed_rules_beyond_the_schema():
    feed = json.loads((ROOT / "data/places/latest.json").read_text(encoding="utf-8"))
    assert semas.feed_errors(feed) == [] and feed["places"] == []          # shipped empty: no place is invented
    place = {"id": "p-0001", "name": "a", "area": "gung", "address": "대전 유성구 1", "cuisine": "korean", "status": "candidate",
             "verifiedAt": None, "facts": [{"kind": "menu", "text": "국밥", "source": "operator", "checkedAt": "2026-11-07"}],
             "sources": [{"kind": "semas", "ref": "MA1", "checkedAt": "2026-11-08"}], "updatedAt": "2026-11-08"}
    feed["places"] = [place, dict(place, id="p-0002", facts=[])]
    errors = " | ".join(semas.feed_rule_errors(feed))
    assert "candidate carries no facts" in errors and "published twice" in errors
    feed["places"] = [dict(place, facts=[], status="verified", verifiedAt=None)]
    assert "verifiedAt" in " | ".join(semas.feed_rule_errors(feed))


SQL = (ROOT / "supabase/migrations/012_place_reports.sql").read_text(encoding="utf-8")


def test_place_reports_are_insert_only_through_one_checking_function():
    assert "DRAFT, NOT APPLIED" in SQL
    for table in ("place_reports", "place_report_rate"):
        assert f"alter table public.{table} enable row level security;" in SQL
        assert re.search(rf"revoke all on table public\.{table} from public, anon, authenticated", SQL)
    assert not re.search(r"grant [a-z, ]+ on table public\.place_report\w* to [a-z, ]*\b(anon|authenticated)", SQL)
    assert "create policy" not in SQL                       # no public read, no board
    assert "security definer set search_path = pg_catalog, public" in SQL
    assert "grant execute on function public.place_submit_report(text, text, text, text) to anon, authenticated, service_role" in SQL
    assert "PLACE_REPORT_RATE_LIMITED" in SQL and "> 5" in SQL and ">= 100" in SQL


def test_no_page_calls_the_place_report_function_yet():
    for path in list(ROOT.glob("*.html")) + list((ROOT / "js").glob("*.js")):
        assert "place_submit_report" not in path.read_text(encoding="utf-8"), path.name
    assert "ggongbab-public-config" not in (ROOT / "bobyak.html").read_text(encoding="utf-8")
