# -*- coding: utf-8 -*-
"""Trend and habit lanes, audience relevance, the hero rule, the keyless Exa MCP route and the
local discovery sidecar (owner release blocker, 2026-09-29). Synthetic data only - no network."""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from discovery import adapters, common, evaluate, evidence, hosts, pipeline, process, select, sidecar, store
from discovery.adapters import exa_mcp, inbox, web

NOW = evaluate.NOW                               # 2026-09-29 10:30 KST
ROOT = Path(__file__).resolve().parents[1]


def day(n: int) -> str:
    return (NOW - timedelta(days=n)).isoformat()


NEWS = {"id": "t-news", "name": "뉴스", "type": "rss", "trustTier": "B", "categories": ["trend", "habit"],
        "kind": "news", "requireFood": True}
SEARCH = {"id": "t-search", "name": "Web search", "type": "web_search", "trustTier": "C", "categories": ["trend"],
          "lane": "trend", "requireFood": True, "kind": "mixed"}
RECIPES = {"id": "t-recipes", "name": "Recipe Blog", "type": "rss", "trustTier": "B", "categories": ["tips"],
           "kind": "recipe"}
NEUTRAL = ("세븐일레븐이 매일유업과 손잡고 우유생크림빵과 초코생크림빵을 내놓았다. 동물성 생크림 비중을 높이고 "
           "크림 비율을 45%까지 채웠다고 회사는 설명했다. 가격은 2900원이며 전국 매장에서 살 수 있다. " * 2)


def raw(title, text, published, url, **kw):
    return dict({"title": title, "text": text, "publishedAt": published, "sourceUrl": url, "medium": "news"}, **kw)


def run(*pairs):
    rows = []
    for n, (item, source) in enumerate(pairs, 1):
        row = process.normalize(item, source, NOW)
        row.update(candidateId=f"c_{n}", discoveredSeq=n, discoveredAt=NOW.isoformat())
        rows.append(row)
    process.process(rows, NOW)
    return rows


def with_image(row):
    row.update(imageUrl=row["sourceUrl"] + ".jpg", imageValidated=True, imageSource="source_page_og")
    process.score(row, NOW)
    return row


# --- owner test list (item 20) ------------------------------------------------------------
def test_trend_item_requires_trend_evidence():
    noodle = "농심이 매운맛을 줄인 컵라면을 내놓았다. 면은 더 굵게 바꿨고 국물은 사골 맛이다. 전국 매장에서 살 수 있다. " * 3
    lunch = "이마트24가 제육 도시락을 내놓았다. 밥 양을 늘리고 반찬을 네 가지로 구성했다. 전국 매장에서 살 수 있다. " * 3
    plain, claimed, title_only = run(
        (raw("농심 사골 컵라면 출시", noodle, day(2), "https://www.hankyung.com/a/1"), NEWS),
        (raw("세븐일레븐 크림빵", NEUTRAL + " 출시 직후 SNS에서 화제가 되며 매장마다 품절이 이어졌다.", day(2),
             "https://www.mk.co.kr/a/2"), NEWS),
        (raw("SNS서 난리 난 편의점 도시락 유행", lunch, day(2), "https://www.sedaily.com/a/3"), NEWS))
    assert plain["assignedCategory"] != "trend" and plain["laneDecisions"]["trend"] == "NO_TREND_EVIDENCE"
    assert claimed["assignedCategory"] == "trend" and "explicit_source_claim" in claimed["trendEvidence"]
    detail = claimed["trendEvidenceDetail"]["explicit_source_claim"]
    assert detail and detail in common.clean_text(NEUTRAL + " 출시 직후 SNS에서 화제가 되며 매장마다 품절이 이어졌다.")
    # A trend word in the title alone is not evidence: nothing is scored from title keywords.
    assert title_only["laneDecisions"]["trend"] == "NO_TREND_EVIDENCE"


def test_a_recent_recipe_alone_is_not_a_trend():
    text = ("This popular Korean side dish takes ten minutes. Ingredients: 2 tbsp soy sauce, 1 tsp sugar, "
            "1 cup spinach. Blanch the spinach and toss with the sauce. " * 3)
    [recipe] = run((raw("Sigeumchi Namul Recipe", text, day(1), "https://recipes.example.org/namul",
                        medium="blog"), RECIPES))
    assert recipe["contentKind"] == "recipe" and recipe["assignedCategory"] == "tips"
    assert recipe["laneDecisions"]["trend"] == "RECIPE_WITHOUT_TREND_EVIDENCE" and recipe["trendEvidence"] == []
    edition, _ = select.build([with_image(recipe)], date="2026-09-29", generated_at=NOW.isoformat(), recent=set())
    assert edition["featured"]["heroKind"] == "pick" and "trendEvidence" not in edition["featured"]


def test_a_corroborated_trend_is_accepted():
    a, b, same_host, other = run(
        (raw("세븐일레븐 우유생크림빵 출시", NEUTRAL, day(3), "https://www.hankyung.com/a/1"), NEWS),
        (raw("매일유업 손잡은 세븐일레븐 생크림빵", NEUTRAL.replace("회사는", "업체는"), day(2),
             "https://www.mk.co.kr/a/2"), NEWS),
        (raw("세븐일레븐 우유생크림빵 가격", NEUTRAL.replace("가격은", "값은"), day(2), "https://www.hankyung.com/a/9"),
         NEWS),
        (raw("농심 새 컵라면 판매 시작", "농심이 새 컵라면을 내놓았다. 매운맛을 줄였다. " * 8, day(2),
             "https://www.sedaily.com/a/4"), NEWS))
    assert a["assignedCategory"] == "trend" and a["trendEvidence"] == ["corroborated"]
    assert b["assignedCategory"] == "trend" and "c_1" in b["trendEvidenceDetail"]["corroborated"]
    assert "c_3" not in a["corroboratedBy"]                   # the same host is not independent
    assert other["corroboratedBy"] == [] and other["laneDecisions"]["trend"] == "NO_TREND_EVIDENCE"


def test_sales_and_adoption_evidence_is_accepted():
    [row] = run((raw("편의점 도시락 매출 늘어", "직장인 점심 수요가 몰리면서 편의점 도시락 매출이 전년 대비 32% 증가했다. "
                     "업계는 가격 부담을 이유로 꼽는다. " * 3, day(4), "https://www.yna.co.kr/view/A1"), NEWS))
    assert row["assignedCategory"] in ("trend", "habit")
    assert "sales_data" in row["trendEvidence"] and "32%" in row["trendEvidenceDetail"]["sales_data"]


def test_habit_accepts_credible_behavior_and_research_sources():
    behavior = ("1인 가구 식생활 조사에서 응답자의 45%가 아침 식사를 거른다고 답했다. 점심은 편의점 도시락과 간편식으로 "
                "해결하는 비율이 늘었다. " * 3)
    news, study, blog, old = run(
        (raw("1인 가구 식습관 조사", behavior, day(20), "https://www.yna.co.kr/view/H1"), NEWS),
        (raw("Dietary habits of university students", "This study of 327 college students examined eating "
             "habits, meal skipping and convenience food consumption after the return to in-person classes. " * 2,
             day(400), "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/", medium="research", trustTier="A"), SEARCH),
        (raw("나의 혼밥 식습관 이야기", behavior, day(5), "https://blog.naver.com/x/1", medium="blog", trustTier="C"),
         SEARCH),
        (raw("대학생 식습관 설문", "대학생 식습관 설문에서 응답자의 38%가 저녁 끼니를 배달 음식으로 해결한다고 답했다. "
             "아침 식사를 거르는 비율도 높았다. " * 3, day(120), "https://www.hani.co.kr/a/H2"), NEWS))
    assert news["assignedCategory"] == "habit"
    assert study["assignedCategory"] == "habit" and study["sourceTrust"] == "A"       # research: up to 2 years
    assert blog["laneDecisions"]["habit"] == "NOT_BEHAVIOR_SOURCE"                    # blogger opinion
    assert old["laneDecisions"]["habit"] == "TOO_OLD_FOR_HABIT"                       # news: 90 days


def test_stale_research_is_never_presented_as_a_current_trend():
    [study] = run((raw("Snacking trend among young adults", "A cohort study reports the trend toward snacking and "
                       "meal skipping in young adults; eating habits changed over five years. " * 2, day(400),
                       "https://pmc.ncbi.nlm.nih.gov/articles/PMC2/", medium="research", trustTier="A"), SEARCH))
    assert "explicit_source_claim" in study["trendSignals"]                   # it says "trend" ...
    assert study["laneDecisions"]["trend"] == "TOO_OLD_FOR_TREND"             # ... but it is not recent
    assert study["assignedCategory"] == "habit"
    edition, _ = select.build([with_image(study)], date="2026-09-29", generated_at=NOW.isoformat(), recent=set())
    assert edition["featured"]["heroKind"] == "pick" and edition["featured"]["publishedAt"][:4] == "2025"


def test_audience_relevance_influences_rank_and_hero():
    korean, generic = run(
        (raw("자취생 편의점 재료로 만드는 초간단 도시락 레시피", "편의점 삼각김밥과 컵라면 대신 10분이면 되는 자취 도시락 "
             "레시피입니다. 재료는 달걀 두 개와 밥 한 공기, 간장 한 큰술입니다. " * 3, day(3),
             "https://irisblossomlife.tistory.com/1", medium="blog"), RECIPES),
        (raw("Lemon Herb Roast Chicken Recipe", "A classic roast chicken recipe with lemon and herbs. Ingredients: "
             "one whole chicken, 2 tbsp butter, 1 lemon. Roast until golden and juicy. " * 3, day(3),
             "https://recipes.example.org/chicken", medium="blog"), RECIPES))
    assert korean["audienceRelevance"]["score"] > generic["audienceRelevance"]["score"]
    assert {"korea", "convenience_store", "quick_meal"} <= set(korean["audienceRelevance"]["signals"])
    assert korean["score"] > generic["score"]
    edition, _ = select.build([with_image(generic), with_image(korean)], date="2026-09-29",
                              generated_at=NOW.isoformat(), recent=set())
    assert edition["featured"]["url"] == korean["sourceUrl"]


def test_the_hero_prefers_a_qualified_current_trend():
    trend, recipe, naver = run(
        (raw("편의점 우유생크림빵 품절 대란", NEUTRAL + " 출시 직후 SNS에서 화제가 되며 편의점마다 품절이 이어졌다.", day(2),
             "https://www.hankyung.com/a/1"), NEWS),
        (raw("Crispy Tofu Recipe", "Crispy tofu recipe. Ingredients: 1 block tofu, 2 tbsp starch, 1 tsp salt. "
             "Press and fry the tofu until crisp. " * 3, day(0), "https://recipes.example.org/tofu", medium="blog"),
         RECIPES),
        (raw("편의점 신상 과자 후기", "CU편의점 신상 코너에서 산 과자 후기예요. 맛은 짭짤하고 가격은 1,700원이에요. "
             "타코 맛 시즈닝이 진하게 느껴졌어요. " * 3, day(1), "https://blog.naver.com/y/2", medium="blog",
             trustTier="C"), SEARCH))
    assert trend["assignedCategory"] == "trend" and naver["assignedCategory"] == "trend"
    rows = [with_image(r) for r in (trend, recipe, naver)]
    edition, _ = select.build(rows, date="2026-09-29", generated_at=NOW.isoformat(), recent=set())
    assert edition["featured"]["url"] == trend["sourceUrl"] and edition["featured"]["heroKind"] == "trend"
    assert edition["featured"]["trendEvidence"] == ["explicit_source_claim"]
    # A Tier C blog with one weak claim ("신상") may sit in the lane but never leads the page.
    edition, _ = select.build([with_image(naver), with_image(recipe)], date="2026-09-29",
                              generated_at=NOW.isoformat(), recent=set())
    assert edition["featured"]["heroKind"] == "pick"


def test_the_hero_falls_back_to_todays_pick_label_when_no_trend_qualifies():
    [recipe] = run((raw("Miso Soup Recipe", "Miso soup recipe. Ingredients: 2 tbsp miso, tofu, 1 cup dashi. "
                        "Warm the dashi and whisk in the miso. " * 3, day(1), "https://recipes.example.org/miso",
                        medium="blog"), RECIPES))
    edition, _ = select.build([with_image(recipe)], date="2026-09-29", generated_at=NOW.isoformat(), recent=set())
    assert edition["featured"]["heroKind"] == "pick" and edition["featured"]["category"] == "tips"
    page = (ROOT / "mukbang.html").read_text(encoding="utf-8")
    assert "'mg.hero.pick': '오늘의 추천 글'" in page and "'mg.hero.pick': \"Today's pick\"" in page
    assert 'id="mgHeroLabel" data-i18n="mg.hero.pick">오늘의 추천 글<' in page        # the default label
    assert "featured.heroKind === 'trend' && (featured.trendEvidence || []).length" in page
    assert "오늘의 대표 이야기" not in page


def test_query_provenance_is_persisted(tmp_path):
    class FakeMCP:
        def start(self):
            return {"name": "exa"}

        def search(self, query, objective, num):
            return [{"title": "혼밥 식습관 조사 | 연합뉴스", "url": "https://www.yna.co.kr/view/Q1", "published": day(5),
                     "highlights": "혼밥 식습관 조사 결과 응답자의 40%가 끼니를 거른다고 답했다."}]

        def fetch(self, urls, chars):
            return [{"url": "https://www.yna.co.kr/view/Q1", "title": "혼밥 식습관 조사", "body":
                     "1인 가구의 혼밥 식습관 조사 결과 응답자의 40%가 하루 한 끼 이상 끼니를 거른다고 답했다. " * 3}]

    source = dict(SEARCH, id="web-habit", lane="habit", queries=["{year} 혼밥 식습관"], categories=["habit"])
    result = web.discover(source, fetcher=None, env={}, client=FakeMCP(), now=NOW)
    assert result.status == adapters.OK and result.queries == ["2026 혼밥 식습관"]
    [item] = result.items
    assert item["siteName"] == "연합뉴스" and item["trustTier"] == "B" and item["title"] == "혼밥 식습관 조사"
    FakeMCP.search = lambda self, q, o, n: [{"title": "혼밥 식습관 ...", "url": "https://www.yna.co.kr/view/Q1",
                                             "published": day(5), "highlights": ""}]
    whole = web.discover(source, fetcher=None, env={}, client=FakeMCP(), now=NOW).items[0]
    assert whole["title"] == "혼밥 식습관 조사"                   # the page's whole title, not the cut one
    s = store.CandidateStore(tmp_path / "c.jsonl")
    row = s.upsert(process.normalize(item, source, NOW), NOW)
    process.process(s.all(), NOW)
    s.mark_selected([row["candidateId"]], NOW, "2026-09-29")
    s.save()
    [saved] = store.CandidateStore(tmp_path / "c.jsonl").all()
    assert saved["discoveryMethod"] == "exa_mcp" and saved["discoveryQuery"] == "2026 혼밥 식습관"
    assert saved["discoveryLane"] == "habit" and saved["seenQueries"] == ["2026 혼밥 식습관"]
    assert saved["assignedCategory"] == "habit" and saved["sourceTrust"] == "B" and saved["selectedFor"] == "2026-09-29"
    for key in ("trendEvidence", "trendEvidenceDetail", "audienceRelevance", "duplicateOf", "rejectionReason"):
        assert key in saved, key


def test_local_discovery_cannot_directly_publish(tmp_path):
    registry_path = tmp_path / "sources.json"
    registry_path.write_text(common.dump_json({"version": 1, "sources": [
        {"id": "yt-local", "name": "YouTube search", "type": "youtube_search", "enabled": True, "trustTier": "C",
         "categories": ["trend"], "lane": "trend", "localOnly": True, "requireFood": True, "kind": "video",
         "queries": ["{month}월 편의점 신상"]}]}), encoding="utf-8")
    paths = pipeline.Paths(tmp_path, registry_path=registry_path)
    calls = []

    def runner(argv, **_):
        calls.append(argv)
        line = json.dumps({"id": "abcdefghijk", "title": "편의점 신상 먹방 리뷰", "channel": "먹방채널",
                           "upload_date": "20260927", "view_count": 120000, "like_count": 3000,
                           "description": "요즘 SNS에서 화제인 편의점 신상 디저트를 먹어 봤어요. 크림빵과 푸딩 맛 비교 리뷰입니다."})
        return subprocess.CompletedProcess(argv, 0, stdout=line + "\n", stderr="")

    report = sidecar.run(paths, NOW, runner=runner, env={}, which=lambda _: "yt-dlp", log=lambda _: None)
    assert report["yt-local"]["items"] == 1 and "--skip-download" in calls[0] and calls[0][-1] == "ytsearch5:9월 편의점 신상"
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["research/magazine/inbox/yt-local.json", "sources.json"]      # the inbox and nothing else
    code = Path(sidecar.__file__).read_text(encoding="utf-8").split('"""', 2)[2]     # the code, not the docstring
    for forbidden in ("select", "data/magazine", "atomic_write", "git", "CandidateStore", "save_health"):
        assert forbidden not in code, forbidden
    # The normal pipeline reads the inbox as one more source; only it builds an edition.
    run_ = pipeline.discover(paths, NOW, fetcher=lambda *a, **k: b"", env={}, validate=lambda u: True, log=lambda _: None)
    [row] = run_["store"].all()
    assert row["discoveryMethod"] == "yt-dlp" and row["assignedCategory"] == "trend"
    assert set(row["trendEvidence"]) == {"explicit_source_claim", "engagement"}
    # The cloud never runs yt-dlp: a local-only source only ever reads its inbox.
    assert adapters.run({"id": "yt-local", "localOnly": True, "type": "youtube_search"}, fetcher=None, env={}).code \
        == "LOCAL_INBOX_MISSING"
    stale = inbox.read({"id": "yt-local"}, paths.inbox, NOW + timedelta(days=inbox.INBOX_MAX_DAYS + 1))
    assert stale.status == adapters.FETCH_FAILED and stale.code == "LOCAL_INBOX_STALE"


def test_an_empty_lane_is_valid_when_search_is_genuinely_exhausted(tmp_path, monkeypatch):
    class Exhausted:
        def __init__(self, **_):
            pass

        def start(self):
            return {}

        def search(self, query, objective, num):
            return [{"title": "편의점 도시락 할인 쿠폰 모음", "url": "https://www.coupang.com/np/1",
                     "highlights": "편의점 도시락 할인 쿠폰을 모았습니다. " * 10}]

        def fetch(self, urls, chars):
            return []

    monkeypatch.setattr(web, "ExaMCP", Exhausted)
    registry_path = tmp_path / "sources.json"
    registry_path.write_text(common.dump_json({"version": 1, "sources": [dict(
        SEARCH, id="web-trend", enabled=True, queries=["편의점 도시락 유행"])]}), encoding="utf-8")
    paths = pipeline.Paths(tmp_path, registry_path=registry_path)
    run_ = pipeline.discover(paths, NOW, fetcher=lambda *a, **k: b"", env={}, validate=lambda u: True,
                             log=lambda _: None)
    edition, chosen = select.build(run_["store"].all(), date="2026-09-29", generated_at=NOW.isoformat(), recent=set())
    report = pipeline.finish(paths, run_, edition, chosen, NOW)
    assert edition["lanes"]["trend"]["items"] == [] and edition["featured"] is None
    assert report["lanes"]["trend"] == {"qualifying": 0, "discoveredForLane": 1,
                                        "notQualifying": {"COMMERCE_PAGE": 1}}
    assert run_["queries"] == [{"sourceId": "web-trend", "query": "편의점 도시락 유행"}]
    import validate_content
    path = tmp_path / "2026-09-29.json"
    path.write_text(json.dumps(edition, ensure_ascii=False), encoding="utf-8")
    assert validate_content.validate_magazine(path) == []


# --- Exa hosted MCP route (no key) --------------------------------------------------------
SEARCH_TEXT = """Title: 딱 하나 남아 간신히 샀다…SNS서 난리 난 편의점 신상 | 한국경제
URL: https://www.hankyung.com/article/1
Published: 2026-09-16T06:32:23.000Z
Author: N/A
Highlights:
최근 출시된 편의점 신상 우유 생크림빵이 사회관계망서비스(SNS)를 달구고 있다.
...
"편의점 네 곳을 돌아다녀 간신히 샀다"는 후기가 보인다.

Title: 편의점 신상 과자 후기 : 네이버 블로그
URL: https://m.blog.naver.com/a/2
Published: N/A
Author: N/A
Highlights:
CU편의점 신상 코너를 둘러보다가 눈에 띄는 제품을 발견했어요."""
FETCH_TEXT = """# 편의점 신상 과자 후기 : 네이버 블로그
URL: https://m.blog.naver.com/a/2

편의점 신상 과자 후기 : 네이버 블로그

편의점 신상 과자 후기

 다먹어 라이언
 2026. 9. 6. 18:32

![사진](https://blogthumb.pstatic.net/x.jpg)
CU편의점 신상 코너를 둘러보다가 눈에 띄는 제품을 발견했어요. 바로 [도리토스](https://example.org) 타코맛이에요.
사진=인스타그램 갈무리
가격은 1,700원이고 짭짤한 맛이 진해서 맥주 안주로도 좋을 것 같아요."""


def test_mcp_output_blocks_are_parsed_for_search_and_fetch():
    first, second = exa_mcp.parse_blocks(SEARCH_TEXT)
    assert first["url"] == "https://www.hankyung.com/article/1" and first["published"].startswith("2026-09-16")
    assert first["highlights"].count("\n") == 1 and "SNS" in first["highlights"]
    assert second["published"] is None and second["title"].startswith("편의점 신상 과자 후기")
    [page] = exa_mcp.parse_blocks(FETCH_TEXT)
    body, lead = web.clean_page(page["body"], "편의점 신상 과자 후기")
    assert "pstatic" not in body and "example.org" not in body and "갈무리" not in body and "도리토스 타코맛" in body
    assert lead.startswith("CU편의점 신상 코너를")
    assert web.page_date(page["body"], NOW).date().isoformat() == "2026-09-06"


def test_the_mcp_client_sends_no_credential_and_keeps_the_session():
    sent = []

    class Response:
        def __init__(self, body, session=None):
            self.body, self.headers = body.encode("utf-8"), {"Mcp-Session-Id": session} if session else {}

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(request, timeout):
        payload = json.loads(request.data)
        sent.append((dict(request.header_items()), payload))
        if payload.get("method") == "initialize":
            return Response('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"exa"}}}',
                            session="s-123")
        if payload.get("method") == "tools/call":
            text = json.dumps(SEARCH_TEXT)
            return Response('data: {"jsonrpc":"2.0","id":%d,"result":{"content":[{"type":"text","text":%s}]}}'
                            % (payload["id"], text))
        return Response("")

    client = exa_mcp.ExaMCP(opener=opener, pause=0)
    assert client.start() == {"name": "exa"}
    hits = client.search("편의점 신상", "objective", 5)
    assert [h["url"] for h in hits] == ["https://www.hankyung.com/article/1", "https://m.blog.naver.com/a/2"]
    headers = [{k.lower(): v for k, v in h.items()} for h, _ in sent]
    assert all("x-api-key" not in h and "authorization" not in h for h in headers)
    assert headers[-1]["mcp-session-id"] == "s-123"
    call = sent[-1][1]["params"]
    assert call["name"] == "web_search_exa" and call["arguments"] == {"query": "편의점 신상", "numResults": 5,
                                                                      "objective": "objective"}


def test_result_trust_and_medium_come_from_the_host():
    assert hosts.classify_host("https://m.blog.naver.com/a/1")["tier"] == "C"
    news = hosts.classify_host("https://www.hankyung.com/article/1")
    assert (news["tier"], news["medium"], news["name"]) == ("B", "news", "한국경제")
    assert hosts.classify_host("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/")["tier"] == "A"
    assert hosts.classify_host("https://www.kdca.go.kr/x")["medium"] == "research"
    assert hosts.classify_host("https://www.coupang.com/vp/1")["commerce"] is True
    assert hosts.split_title("딱 하나 남아 간신히 샀다 | 한국경제") == ("딱 하나 남아 간신히 샀다", "한국경제")
    assert hosts.split_title("Miso Eggplant Stir-Fry") == ("Miso Eggplant Stir-Fry", "")


def test_query_templates_never_go_stale():
    assert web.expand("{year} {month}월 편의점 신상", NOW) == "2026 9월 편의점 신상"
    assert web.expand("{year} {month}월 편의점 신상", NOW + timedelta(days=40)) == "2026 11월 편의점 신상"


# --- publication rules --------------------------------------------------------------------
def test_the_validator_enforces_trend_evidence_dates_and_hero_kind(tmp_path):
    import validate_content
    lanes = {lane: {"items": []} for lane in ("tips", "trend", "health", "habit")}
    story = {"title": "t", "source": "한국경제", "url": "https://www.hankyung.com/a/1", "medium": "news",
             "publishedAt": "2026-09-27T09:00:00+09:00"}
    lanes["trend"]["items"] = [dict(story)]
    lanes["habit"]["items"] = [dict(story, url="https://www.yna.co.kr/a/2", title="h", publishedAt=None)]
    featured = dict(story, url="https://www.mk.co.kr/a/3", title="f", category="trend", heroKind="trend")
    path = tmp_path / "2026-09-29.json"
    path.write_text(json.dumps({"date": "2026-09-29", "rules": "lanes-v1", "featured": featured, "lanes": lanes}),
                    encoding="utf-8")
    errors = validate_content.validate_magazine(path)
    assert any("trend story without trendEvidence" in e for e in errors)
    assert any("habit story without a publication date" in e for e in errors)
    assert any("trend hero needs" in e for e in errors)
    lanes["trend"]["items"] = [dict(story, trendEvidence=["corroborated"])]
    lanes["habit"]["items"] = [dict(story, url="https://www.yna.co.kr/a/2", title="h")]
    featured.update(heroKind="pick", category="tips")
    path.write_text(json.dumps({"date": "2026-09-29", "rules": "lanes-v1", "featured": featured, "lanes": lanes}),
                    encoding="utf-8")
    assert validate_content.validate_magazine(path) == []
    lanes["trend"]["items"] = [dict(story, trendEvidence=["corroborated"], publishedAt="2026-08-01T09:00:00+09:00")]
    path.write_text(json.dumps({"date": "2026-09-29", "rules": "lanes-v1", "featured": featured, "lanes": lanes}),
                    encoding="utf-8")
    assert any("older than 30 days" in e for e in validate_content.validate_magazine(path))


def test_legacy_editions_keep_no_evidence_free_trends_or_keyword_habits():
    old = {"date": "2026-09-20", "featured": {"title": "f", "source": "S", "url": "https://a.example/f",
                                               "medium": "blog", "category": "trend"},
           "lanes": {"trend": {"items": [{"title": "t", "source": "S", "url": "https://a.example/t", "medium": "blog"}]},
                     "habit": {"items": [{"title": "h", "source": "S", "url": "https://a.example/h", "medium": "blog"}]},
                     "tips": {"items": [{"title": "k", "source": "S", "url": "https://a.example/k", "medium": "blog"}]}}}
    cleaned, removed = select.sanitize(old)
    assert removed == 3 and cleaned["featured"] is None
    assert cleaned["lanes"]["trend"]["items"] == [] and cleaned["lanes"]["habit"]["items"] == []
    assert len(cleaned["lanes"]["tips"]["items"]) == 1


def test_the_published_magazine_editions_satisfy_the_lane_rules():
    import validate_content
    folder = ROOT / "data" / "magazine"
    assert validate_content.validate_magazine_archive(folder) == []
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    assert validate_content.validate_magazine(folder / f"{index['latest']}.json") == []


# --- defects found in the first live run (2026-09-29) --------------------------------------
def test_live_run_defects_stay_fixed():
    # A non-food story is never a food trend, whatever it claims ("국" in 한국, "rice" in price).
    school = run((raw("역시 의대 vs 반도체 열풍… 고교 1등의 선택은?", "반도체 열풍과 맞물려 이공계 인기가 살아날 조짐이 보인다. "
                      "한국 미국 입시 측면에서 price 경쟁도 3분기 판매 기준 3위로 올라섰다. " * 3, day(0),
                      "https://kormedi.com/1"), NEWS))[0]
    assert school["rejectionReason"] == "NOT_FOOD" and school["trendSignals"] == {}
    assert not evidence.is_food("한국 미국 측면", "the price of chips")
    # A contest press release is a promotion, not a trend.
    contest = run((raw("간단요리사 미식대전 개최…숏폼 영상 공모에 총상금 1000만 원", "요리 영상 공모전을 연다. " * 10, day(0),
                       "https://www.thinkfood.co.kr/news/1"), NEWS))[0]
    assert contest["rejectionReason"] == "PROMOTION"
    # An undated search result is not published at all.
    undated = run((raw("식생활 지침 영양교육 개발도서", "건강한 식생활 지침과 영양교육 자료를 제공합니다. " * 10, None,
                       "https://www.nise.go.kr/x", medium="research", trustTier="A"), SEARCH))[0]
    assert undated["rejectionReason"] == "NO_DATE"
    # A news story that mentions a recipe is news, not a how-to.
    sauce = run((raw("K-소스, 중국 명인 셰프 레시피로 대륙 입맛 공략", "국내 소스 업체가 중국 셰프와 손잡고 현지 시장에 나섰다. " * 6,
                     day(10), "https://www.foodbank.co.kr/news/2"), NEWS))[0]
    assert sauce["contentKind"] == "news" and sauce["laneDecisions"]["tips"] == "NOT_A_HOW_TO"


def test_generic_trade_words_do_not_corroborate():
    stories = [(raw(f"식품 업계 건강 시장 동향 {n}", f"식품 업계의 건강 시장 동향 보고 {n}. 제품과 소비 흐름을 정리했다. " * 4,
                    day(1), f"https://www.site{n}.co.kr/news/{n}"), NEWS) for n in range(6)]
    rows = run(*stories)
    assert all(not r.get("corroboratedBy") for r in rows)


def test_sponsored_notices_events_and_business_news_are_not_lane_stories():
    video = {"id": "t-yt", "name": "YouTube search", "type": "youtube_search", "trustTier": "C", "categories": ["trend"],
             "lane": "trend", "requireFood": True, "kind": "video"}
    ppl = run((raw("편의점 신상 디저트 먹방", "요즘 인기 디저트를 먹어 봤어요. 구매 링크 shop.example.co.kr/main?"
                   "utm_medium=viral&utm_campaign=yt_ppl " * 3, day(3), "https://www.youtube.com/watch?v=abcdefghijk",
                   medium="youtube", viewCount=900000), video))[0]
    assert ppl["rejectionReason"] == "AD_OR_SPONSORED"
    assert "viral" not in str(evidence.trend_signals("링크 shop.example.co.kr/x?utm_medium=viral 입니다. 떡볶이가 맛있다."))
    honest = run((raw("편의점 신상 디저트 먹방 후기", "협찬 없이 내돈내산으로 산 편의점 신상 디저트 후기예요. " * 8, day(3),
                      "https://blog.naver.com/z/9", medium="blog", trustTier="C"), SEARCH))[0]
    assert honest["rejectionReason"] is None
    notice, event = run(
        (raw("[게시판] 식품업체, 병원에 1억원 기부", "식품업체가 병원에 1억원을 기부했다. 건강한 식생활 지원에 쓰인다. " * 4, day(0),
             "https://www.yna.co.kr/view/G1"), NEWS),
        (raw("한돈으로 에너지 충전, '2026 한돈런' 성료", "도시락과 식생활 캠페인에 참가자 3천명이 몰려 20% 늘었다. " * 4, day(5),
             "https://www.foodbank.co.kr/news/3"), NEWS))
    assert notice["rejectionReason"] == event["rejectionReason"] == "NOTICE_OR_EVENT"
    assert process.NOTICE_TAG.search("[신간] 천천히 나이 드는 식사법") and not process.NOTICE_TAG.search("[신상품] 삼립 동그랑땡")
    [franchise] = run((raw("메가커피 본사 매출 464% 늘 때 점주 매출은 11% 증가", "커피 프랜차이즈 본사 매출이 크게 늘었다. 커피 음료 판매도 "
                           "20% 증가했다. " * 4, day(1), "https://www.foodbank.co.kr/news/4"), NEWS))
    assert franchise["laneDecisions"]["trend"] == "BUSINESS_NEWS" and franchise["assignedCategory"] is None


def test_a_news_feed_category_alone_does_not_make_health_advice():
    [market] = run((raw("싱가포르 건강기능식품 규모 커져", "싱가포르 건강기능식품 시장 규모가 커지고 있다. " * 6, day(0),
                        "https://www.foodnews.co.kr/news/5"), dict(NEWS, categories=["health"])))
    [advice] = run((raw("저염 식단, 채소부터 먼저 먹으면 좋은 이유", "저염 식단과 채소 위주의 균형 잡힌 식사가 혈압 관리에 도움이 된다. " * 4,
                        day(0), "https://kormedi.com/2"), dict(NEWS, categories=["health"])))
    assert market["laneDecisions"]["health"] == "NOT_HEALTH_TOPIC"
    assert advice["assignedCategory"] == "health"


def test_news_breadcrumb_titles_are_cleaned():
    assert hosts.split_title("혼밥 트렌드 공개 < 유통일반 < 생활유통 < 기사본문 - 신아일보") == ("혼밥 트렌드 공개", "신아일보")
    assert hosts.split_title("추석 간편식 인기｜동아일보") == ("추석 간편식 인기", "동아일보")


def test_card_excerpts_drop_datelines_bylines_and_photo_captions():
    assert select.card_summary("[서울=뉴시스] 김상윤 기자 = MZ세대를 중심으로 헬시 플레저 소비 트렌드가 확산되고 있다.") \
        .startswith("MZ세대를 중심으로")
    assert select.card_summary("【 청년일보 】 편의점 업계가 간편식 경쟁력을 높이고 있다. 이어지는 설명입니다.") \
        .startswith("편의점 업계가")
    text = "배우가 요요를 고백했다. 사진=유튜브 채널 '레몬' 캡처 배우는 식사 습관을 바꿨다고 밝혔다."
    assert "캡처" not in select.card_summary(text) and "사진=" not in select.card_summary(text)
    assert evidence.business_title("[동향] 싱가포르 건강기능식품 시장") and evidence.business_title("동원그룹 새 CF 선보여")
    assert not evidence.business_title("편의점 신상 크림빵 품절")
    assert hosts.split_title("저당 트렌드 바람 :: 공감언론 뉴시스 ::") == ("저당 트렌드 바람", "공감언론 뉴시스")


def test_the_free_search_server_is_used_sparingly(tmp_path, monkeypatch):
    import urllib.error
    calls = []

    class Counting:
        def __init__(self, **_):
            pass

        def start(self):
            calls.append("start")

        def search(self, query, objective, num):
            calls.append("search")
            return [{"title": f"편의점 신상 {query} {n}", "url": f"https://www.hankyung.com/a/{query}{n}", "published": day(1),
                     "highlights": "편의점 신상 디저트가 SNS에서 화제다. " * 5} for n in range(6)]

        def fetch(self, urls, chars):
            calls.append(("fetch", len(urls)))
            return []

    source = dict(SEARCH, queries=["a", "b", "c"])
    result = web.discover(source, fetcher=lambda *a, **k: b"", env={}, client=Counting(), now=NOW)
    assert len(result.items) == 18 and calls.count("search") == 3
    assert [c for c in calls if isinstance(c, tuple)] == [("fetch", 10), ("fetch", 8)]    # batched after searching

    class Throttled(Counting):
        def search(self, query, objective, num):
            calls.append("search")
            raise urllib.error.HTTPError("https://mcp.exa.ai/mcp", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(web, "ExaMCP", Throttled)
    registry_path = tmp_path / "sources.json"
    registry_path.write_text(common.dump_json({"version": 1, "sources": [
        dict(SEARCH, id="web-a", enabled=True, queries=["q1", "q2"]),
        dict(SEARCH, id="web-b", enabled=True, queries=["q3"])]}), encoding="utf-8")
    calls.clear()
    run_ = pipeline.discover(pipeline.Paths(tmp_path, registry_path=registry_path), NOW, fetcher=lambda *a, **k: b"",
                             env={}, validate=lambda u: True, log=lambda _: None)
    assert run_["health"]["web-a"]["code"] == "HTTP_429" and run_["health"]["web-b"]["code"] == "RATE_LIMITED_SKIPPED"
    assert calls.count("search") == 1 and run_["health"]["web-b"]["status"] == "DEGRADED"


def test_a_weak_claim_echoed_by_trade_outlets_never_leads_the_page():
    launch = "CJ제일제당이 저당 도시락 신제품을 내놓았다. 닭가슴살과 현미밥으로 구성했다. 전국 편의점에서 판다. " * 3
    a, b = run(
        (raw("CJ제일제당, 밸런스밀 저당 도시락 출시", launch, day(0), "https://newsis.com/view/1"), NEWS),
        (raw("CJ 밸런스밀 저당 도시락 앞세워 영양 도우미", launch.replace("판다", "살 수 있다"), day(0),
             "https://www.thinkfood.co.kr/news/2"), NEWS))
    assert a["assignedCategory"] == "trend" and set(a["trendEvidence"]) == {"explicit_source_claim", "corroborated"}
    assert not select.strong_evidence(a)                                   # "신제품" + an echo is weak
    edition, _ = select.build([with_image(a), with_image(b)], date="2026-09-29", generated_at=NOW.isoformat(),
                              recent=set())
    assert edition["featured"]["heroKind"] == "pick"                       # in the lane, not the lead


def test_rebuilding_an_edition_releases_what_it_no_longer_runs(tmp_path):
    s = store.CandidateStore(tmp_path / "c.jsonl")
    one = s.upsert({"sourceUrl": "https://a.example/1", "title": "one"}, NOW)
    two = s.upsert({"sourceUrl": "https://a.example/2", "title": "two"}, NOW)
    s.mark_selected([one["candidateId"], two["candidateId"]], NOW, "2026-09-29")
    s.mark_selected([two["candidateId"]], NOW, "2026-09-29")               # same date, rebuilt
    assert one["selectedFor"] is None and one["selected"] is False and two["selectedFor"] == "2026-09-29"
