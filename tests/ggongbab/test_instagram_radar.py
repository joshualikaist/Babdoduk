# -*- coding: utf-8 -*-
"""Instagram radar (docs/INSTAGRAM_RADAR.md). Fakes only: no Graph API, OpenAI, Telegram or Dooray."""
from __future__ import annotations

import io
import json
import urllib.parse
from datetime import datetime

import pytest

from ggongbab.instagram import analyze as an
from ggongbab.instagram import meta_graph as mg
from ggongbab.instagram.radar import Config, Radar, load_accounts
from ggongbab.ops_policy import REASONS

TOKEN = "EAASYNTHETICTOKENnotreal1234567890"
SECRET = "synthetic-app-secret"
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=an.KST).timestamp()


def jpeg(color=(200, 30, 30)) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buffer, "JPEG")
    return buffer.getvalue()


def media(mid, caption, ts="2026-10-05T08:30:00+0000", kind="CAROUSEL_ALBUM", images=2, color=None):
    item = {"id": mid, "caption": caption, "media_type": kind, "permalink": f"https://www.instagram.com/p/{mid}/",
            "timestamp": ts}
    if kind == "CAROUSEL_ALBUM":
        item["children"] = {"data": [{"media_type": "IMAGE", "media_url": f"https://scontent.cdninstagram.com/{mid}-{i}.jpg?oe=1"}
                                     for i in range(images)]}
    elif kind == "VIDEO":
        item["thumbnail_url"] = f"https://scontent.cdninstagram.com/{mid}-thumb.jpg"
    else:
        item["media_url"] = f"https://scontent.cdninstagram.com/{mid}.jpg"
    return item


class Graph:
    def __init__(self, posts=None, errors=None, scopes=mg.REQUIRED_SCOPES, expires=0, usage=None):
        self.posts, self.errors, self.calls = posts or {}, errors or {}, []
        self.scopes, self.expires, self.usage = set(scopes), expires, usage or {}
        self.downloads = []

    def token_status(self):
        return {"valid": True, "scopes": set(self.scopes) | {"public_profile"}, "expires_at": self.expires}

    def discover(self, username, *, limit=10, after=""):
        self.calls.append((username, after))
        if username in self.errors:
            raise self.errors[username]
        items = self.posts.get(username, [])
        start = int(after or 0)
        page = items[start:start + limit]
        paging = {"cursors": {"after": str(start + limit)}} if start + limit < len(items) else {}
        return {"username": username, "media": {"data": page, "paging": paging}}, self.usage

    def download(self, url):
        self.downloads.append(url)
        return jpeg((10, 10, 10)) if "same" in url else jpeg((len(url) % 255, 40, 90))


def judgement(food, confidence, **extra):
    base = dict(is_free_food_event=food, confidence=confidence, event_title="중간고사 간식 이벤트" if food else "오픈랩 공지",
                food_items=["고피자 세트"] if food else [], start_at="2026-10-08T17:30+09:00" if food else None,
                end_at=None, location="스포츠 컴플렉스와 잔디구장 사이" if food else "", language="ko",
                eligibility="과비 납부한 전자과 주/복/부전공 학부생" if food else "", quantity_limit="선착순 100명" if food else None,
                requirements="학생증" if food else None, registration=None, evidence=["고피자"], reason="test")
    base.update(extra)
    return an.Judgement(**base)


class Judge:
    """Answers by a tag in the caption: {model: Judgement}."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, model, content):
        text = content[0]["text"]
        tag = next(t for t in self.answers if t in text)
        self.calls.append((model, tag, sum(1 for c in content if c["type"] == "input_image")))
        answer = self.answers[tag].get(model)
        if isinstance(answer, Exception):
            raise answer
        return answer, 9000, 300


class Bot:
    chat_id = "42"

    def __init__(self):
        self.said, self.asked, self.digests, self.pending, self.answered, self.sent = [], [], [], [], [], []

    def say(self, text):
        self.said.append(text)

    def ask(self, text, media_id, image=None):
        self.asked.append((media_id, text, image is not None))
        return 100 + len(self.asked)

    def digest(self, items):
        self.digests.append(items)

    def updates(self, offset, wait=25):
        out, self.pending = self.pending, []
        return out

    def events(self, updates):
        from ggongbab.instagram.telegram_review import Bot as Real
        return Real("x", self.chat_id).events(updates)

    def answer(self, callback, text):
        self.answered.append(text)

    def _call(self, method, payload):
        self.sent.append((method, payload))
        return {"message_id": 900}


class Writer:
    def __init__(self):
        self.tasks = []

    def create_task(self, mail):
        self.tasks.append(mail)
        return f"post-{len(self.tasks)}"


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".local").mkdir()
    return tmp_path


def radar(root, graph, judge=None, *, bot=None, writer=None, dry_run=False, clock=None):
    clock = clock or {"t": NOW}
    config = Config(version="v26.0", ig_user_id="17841440065235713", token=TOKEN, primary="gpt-6-luna", review="gpt-6.1-terra")
    r = Radar(root, config=config, graph=graph, judge=judge or Judge({}), bot=bot, writer=writer,
              now=lambda: clock["t"], sleep=lambda s: None, dry_run=dry_run)
    r.store.sync_accounts([{"username": "shoutoutto.ee", "display_name": "전자과", "interval_minutes": 120},
                           {"username": "in.cs.tagram", "display_name": "전산학부", "interval_minutes": 180}])
    return r, clock


# --- the Graph client ---------------------------------------------------------------------------
class Opener:
    def __init__(self, body=None, status=200, error=None, headers=None):
        self.body, self.status, self.error, self.requests = body or {}, status, error, []
        self.headers = headers or {"X-App-Usage": '{"call_count": 12, "total_cputime": 3, "total_time": 5}'}

    def __call__(self, request, timeout=None, context=None):
        self.requests.append(request)
        if self.status >= 400:
            import urllib.error
            raise urllib.error.HTTPError(request.full_url, self.status, "x", self.headers,
                                         io.BytesIO(json.dumps({"error": self.error or {}}).encode()))
        outer = self

        class Response(io.BytesIO):
            headers = outer.headers

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Response(json.dumps(self.body).encode())


def test_graph_sends_get_only_with_the_token_in_a_header_and_an_appsecret_proof():
    opener = Opener({"business_discovery": {"username": "shoutoutto.ee", "media": {"data": []}}})
    client = mg.GraphClient(TOKEN, ig_user_id="17841440065235713", app_secret=SECRET, opener=opener)
    found, headers = client.discover("shoutoutto.ee", limit=10, after="QVFI")
    request = opener.requests[0]
    assert request.get_method() == "GET" and request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.full_url and "appsecret_proof=" in request.full_url
    fields = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["fields"][0]
    assert "business_discovery.username(shoutoutto.ee)" in fields and "media.after(QVFI).limit(10)" in fields
    assert "children{media_type,media_url,thumbnail_url}" in fields
    assert mg.usage_percent(headers) == 12


@pytest.mark.parametrize("status, error, kind", [
    (400, {"code": 4}, "rate_limit"), (400, {"code": 80002}, "rate_limit"), (429, {}, "rate_limit"),
    (400, {"code": 190}, "auth"), (400, {"code": 110}, "unsupported"),
    (400, {"code": 100, "error_subcode": 2207013}, "unsupported"), (500, {"code": 1}, "other"),
])
def test_graph_errors_get_a_fixed_kind_and_never_the_token(status, error, kind):
    client = mg.GraphClient(TOKEN, ig_user_id="17841440065235713", opener=Opener(status=status, error=error))
    with pytest.raises(mg.GraphError) as caught:
        client.discover("shoutoutto.ee")
    assert caught.value.kind == kind and TOKEN not in str(caught.value)


def test_usage_reads_both_headers_and_masks_signed_urls():
    buc = json.dumps({"17841440065235713": [{"type": "instagram", "call_count": 85, "total_time": 10}]})
    assert mg.usage_percent({"X-Business-Use-Case-Usage": buc, "X-App-Usage": '{"call_count": 3}'}) == 85
    assert "***" in mg.mask("https://x/y?oe=ABC&access_token=EAA") and "EAA" not in mg.mask("https://x/y?access_token=EAA")


def test_images_come_only_from_instagram_cdns_and_bad_usernames_are_refused():
    client = mg.GraphClient(TOKEN, ig_user_id="17841440065235713", opener=Opener())
    with pytest.raises(mg.GraphError):
        client.download("https://evil.example/x.jpg")
    with pytest.raises(mg.GraphError):
        client.discover("bad name){x}")


# --- collect ---------------------------------------------------------------------------------------
def test_first_run_backfills_thirty_then_only_new_posts_and_images_are_stored_once(root):
    posts = [media(f"9{n:03d}", f"공지 {n}", images=2) for n in range(40)]
    posts[0]["children"]["data"][1]["media_url"] = "https://scontent.cdninstagram.com/same.jpg"
    posts[1]["children"]["data"][0]["media_url"] = "https://scontent.cdninstagram.com/same.jpg"
    graph = Graph({"shoutoutto.ee": posts})
    r, clock = radar(root, graph)
    assert r.collect() == 30                                     # first backfill stops at 30
    assert [c[1] for c in graph.calls if c[0] == "shoutoutto.ee"] == ["", "10", "20"]
    assert r.store.account("shoutoutto.ee")["last_media_id"] == "9000"
    hashes = {row["sha256"] for m in range(30) for row in r.store.images(f"9{m:03d}")}
    assert len(list((root / ".local/ig-media").iterdir())) == len(hashes) < 60   # the shared image once
    graph.posts["shoutoutto.ee"] = [media("9999", "새 글")] + posts
    clock["t"] += 3 * 3600
    assert r.collect() == 1                                      # stops at the first known post
    assert r.store.has_post("9999")


def test_posts_before_collect_since_are_never_collected_and_a_pinned_post_does_not_stop_it(root):
    """Owner decision 2026-10-29: start from that week's Monday, not 30 posts per account."""
    (root / "inputs/instagram").mkdir(parents=True)
    (root / "inputs/instagram/accounts.json").write_text(json.dumps({"collect_since": "2026-10-05", "accounts": []}))
    pinned = media("PIN", "고정 공지", ts="2026-09-01T00:00:00+0000")
    recent = [media(f"R{n}", f"글 {n}", ts=f"2026-10-0{6 - n}T03:00:00+0000") for n in range(2)]   # 10-06, 10-05 KST
    older = [media(f"O{n}", f"옛 글 {n}", ts=f"2026-10-0{4 - n}T03:00:00+0000") for n in range(3)]
    graph = Graph({"shoutoutto.ee": [pinned] + recent + older + [media(f"X{n}", "x", ts="2026-09-01T00:00:00+0000") for n in range(10)]})
    r, clock = radar(root, graph)
    assert r.collect() == 2 and [c[1] for c in graph.calls if c[0] == "shoutoutto.ee"] == [""]   # one page
    assert r.store.has_post("R0") and r.store.has_post("R1") and not r.store.has_post("PIN") and not r.store.has_post("O0")
    assert r.store.account("shoutoutto.ee")["last_media_id"] == "R0"
    graph.posts["shoutoutto.ee"] = [pinned, media("NEW", "새 글", ts="2026-10-07T00:00:00+0000")] + recent + older
    clock["t"] += 3 * 3600
    assert r.collect() == 1 and r.store.has_post("NEW")


def test_a_video_keeps_its_thumbnail_and_an_image_its_media_url(root):
    graph = Graph({"shoutoutto.ee": [media("1", "v", kind="VIDEO"), media("2", "i", kind="IMAGE")]})
    r, _ = radar(root, graph)
    r.collect()
    assert any("1-thumb" in u for u in graph.downloads) and any(u.endswith("/2.jpg") for u in graph.downloads)
    assert len(r.store.images("1")) == 1 and len(r.store.images("2")) == 1


def test_accounts_are_due_by_their_interval_and_high_usage_doubles_it(root):
    graph = Graph({"shoutoutto.ee": [media("1", "x")]}, usage={"X-App-Usage": '{"call_count": 85}'})
    bot = Bot()
    r, clock = radar(root, graph, bot=bot)
    r.collect()
    assert r.store.get("slow_factor") == 2 and any("2배" in s for s in bot.said)
    clock["t"] += 3 * 3600                                       # 3 h: past 120 min, not past 240 min
    assert [a["username"] for a in r.due()] == []
    clock["t"] += 3 * 3600
    assert {a["username"] for a in r.due()} == {"shoutoutto.ee", "in.cs.tagram"}


def test_a_rate_limit_stops_the_round_and_backs_off_exponentially(root):
    graph = Graph(errors={"in.cs.tagram": mg.GraphError("rate_limit", 4)})
    r, clock = radar(root, graph)
    r.collect()
    first = r.store.get("backoff_until") - clock["t"]
    assert first == 900 and r.backing_off()
    assert [c[0] for c in graph.calls] == ["in.cs.tagram"]       # nothing after the limit
    clock["t"] += 901
    r.store.update_account("in.cs.tagram", last_checked=None)
    r.collect()
    assert r.store.get("backoff_until") - clock["t"] == 1800


def test_an_unsupported_account_is_marked_and_announced_once(root):
    bot = Bot()
    graph = Graph(errors={"in.cs.tagram": mg.GraphError("unsupported", 110)})
    r, clock = radar(root, graph, bot=bot)
    r.collect()
    clock["t"] += 7 * 86400
    r.collect()
    assert r.store.account("in.cs.tagram")["status"] == "unsupported"
    assert sum("in.cs.tagram" in s for s in bot.said) == 1
    assert sum(c[0] == "in.cs.tagram" for c in graph.calls) == 1


def test_a_missing_scope_stops_the_cycle_with_a_telegram_notice(root):
    bot = Bot()
    r, _ = radar(root, Graph(scopes=mg.REQUIRED_SCOPES - {"instagram_manage_insights"}), bot=bot)
    assert r.cycle() == "IG_TOKEN_INVALID"
    assert any("instagram_manage_insights" in s for s in bot.said)


def test_a_token_that_expires_within_a_week_is_announced(root):
    bot = Bot()
    r, _ = radar(root, Graph(expires=NOW + 3 * 86400), bot=bot)
    assert r.check_token() and any("만료" in s for s in bot.said)


# --- analysis: the golden cases (synthetic copies of the three posts) ----------------------------------
GOLDEN = [
    media("Dd1fg2j4Nf", "[KO] 🍕 전자과 중간고사 간식 이벤트! 10/6 (화) 17:30 고피자 세트 선착순 100명", ts="2026-10-05T08:00:00+0000"),
    media("Dd1kD9Iw", "[EN] 🍕 EE midterm snack event! Oct 6 (Tue) 17:30 GOPIZZA, first 100", ts="2026-10-05T08:05:00+0000"),
    media("DeG1R4Njz4m", "[LAB] 전자과 오픈랩 참여 연구실 안내", ts="2026-10-06T01:00:00+0000", images=1),
]


def golden_judge():
    return Judge({"[KO]": {"gpt-6-luna": judgement(True, 0.93)},
                  "[EN]": {"gpt-6-luna": judgement(True, 0.9, language="en", location="between Sports Complex and the field",
                                                   food_items=["GOPIZZA set"], quantity_limit="first 100")},
                  "[LAB]": {"gpt-6-luna": judgement(False, 0.95)}})


def test_golden_food_post_is_confirmed_its_english_twin_merged_and_the_open_lab_dropped(root):
    judge = golden_judge()
    writer = Writer()
    r, _ = radar(root, Graph({"shoutoutto.ee": list(reversed(GOLDEN))}), judge, writer=writer)
    r.collect()
    r.analyze()
    ko, en, lab = (r.store.candidate(m["id"]) for m in GOLDEN)
    assert ko["status"] == en["status"] == "auto_confirmed" and en["merge_group"] == ko["merge_group"] == "Dd1fg2j4Nf"
    extraction = json.loads(ko["extraction_json"])
    assert extraction["start_at"] == "2026-10-08T17:30+09:00" and extraction["quantity_limit"] == "선착순 100명"
    assert lab["status"] == "auto_rejected" and lab["decided_by"] == "prefilter"   # no food word, one image
    assert all(call[0] == "gpt-6-luna" for call in judge.calls) and all(call[2] == 2 for call in judge.calls)
    r.bridge()
    (task,) = writer.tasks                                      # one task for the merged event
    assert task.subject.startswith("[인스타 @shoutoutto.ee] 중간고사 간식 이벤트")
    assert "https://www.instagram.com/p/Dd1fg2j4Nf/" in task.body and "https://www.instagram.com/p/Dd1kD9Iw/" in task.body
    assert len(task.images) == 2 and task.mail_id == "instagram-Dd1fg2j4Nf"
    r.bridge()
    assert len(writer.tasks) == 1 and r.store.candidate("Dd1kD9Iw")["dooray_post_id"] == "merged:post-1"


@pytest.mark.parametrize("primary, review, status, by", [
    (judgement(True, 0.6), judgement(True, 0.8), "auto_confirmed", "review"),
    (judgement(True, 0.6), judgement(False, 0.9), "auto_rejected", "review"),
    (judgement(True, 0.6), judgement(True, 0.6), "pending_human", ""),
    (judgement(False, 0.5), judgement(True, 0.7), "pending_human", ""),
])
def test_the_review_model_settles_unsure_posts_and_the_owner_the_rest(root, primary, review, status, by):
    judge = Judge({"[KO]": {"gpt-6-luna": primary, "gpt-6.1-terra": review}})
    r, _ = radar(root, Graph({"shoutoutto.ee": [GOLDEN[0]]}), judge)
    r.collect()
    r.analyze()
    row = r.store.candidate("Dd1fg2j4Nf")
    assert row["status"] == status and row["decided_by"] == by
    assert [c[0] for c in judge.calls] == ["gpt-6-luna", "gpt-6.1-terra"]


def test_a_model_error_leaves_the_post_for_the_next_cycle_and_is_recorded(root):
    judge = Judge({"[KO]": {"gpt-6-luna": RuntimeError("boom")}})
    r, _ = radar(root, Graph({"shoutoutto.ee": [GOLDEN[0]]}), judge)
    r.collect()
    r.analyze()
    assert r.store.candidate("Dd1fg2j4Nf") is None and len(r.store.unanalyzed()) == 1
    run = r.store.db.execute("SELECT error FROM analysis_runs").fetchone()
    assert run["error"] == "RuntimeError"


def test_costs_are_recorded_per_call_and_a_month_over_five_dollars_is_announced(root):
    bot = Bot()
    r, _ = radar(root, Graph({"shoutoutto.ee": [GOLDEN[0]]}), golden_judge(), bot=bot)
    r.collect()
    r.analyze()
    assert r.store.month_cost(0) == pytest.approx(an.cost("gpt-6-luna", 9000, 300))
    r.store.add_run("x", "primary", "gpt-6.1-terra", input_tokens=5_000_000, output_tokens=0, cost=5.0, now=NOW)
    r.cost_check()
    assert any("비용" in s for s in bot.said)


# --- the owner on Telegram ---------------------------------------------------------------------------
def unsure(root, n=1, **kw):
    posts = [media(f"Q{i}", f"[Q{i}] 간식 나눔?", ts=f"2026-10-05T0{i}:00:00+0000") for i in range(n)]
    judge = Judge({f"[Q{i}]": {"gpt-6-luna": judgement(True, 0.5), "gpt-6.1-terra": judgement(True, 0.5)} for i in range(n)})
    bot, writer = Bot(), Writer()
    r, clock = radar(root, Graph({"shoutoutto.ee": posts}), judge, bot=bot, writer=writer, **kw)
    r.collect()
    r.analyze()
    return r, bot, writer, clock


def button(action, media_id, chat=42, update_id=1):
    return {"update_id": update_id, "callback_query": {"id": "cb", "data": f"ig:{action}:{media_id}",
                                                       "message": {"chat": {"id": chat}}}}


def test_an_unsure_post_becomes_a_question_and_the_owners_button_decides(root):
    r, bot, writer, _ = unsure(root)
    r.review()
    (asked,) = bot.asked
    assert asked[0] == "Q0" and asked[2] is True and "1차: 꽁밥 0.50 / 2차: 꽁밥 0.50" in asked[1]
    r.bridge()
    assert writer.tasks == []                                   # never before the owner answers
    bot.pending = [button("ok", "Q0", chat=999, update_id=1)]   # someone else: ignored
    r.review()
    assert r.store.candidate("Q0")["status"] == "pending_human"
    bot.pending = [button("ok", "Q0", update_id=2)]
    r.review()
    assert r.store.candidate("Q0")["status"] == "human_confirmed" and r.store.get("telegram_offset") == 3
    r.bridge()
    assert len(writer.tasks) == 1


def test_a_rejection_is_kept_as_a_label_for_the_next_prompts(root):
    r, bot, writer, _ = unsure(root)
    r.review()
    bot.pending = [button("no", "Q0")]
    r.review()
    r.bridge()
    assert r.store.candidate("Q0")["status"] == "human_rejected" and writer.tasks == []
    assert r.store.recent_labels()[0]["action"] == "reject"
    content = an.user_content("x", "2026-10-05T08:00:00+0000", [], r.store.recent_labels())
    assert "꽁밥 아님" in content[0]["text"]


def test_an_edit_reply_updates_the_fields_and_confirms(root):
    r, bot, writer, _ = unsure(root)
    r.review()
    bot.pending = [button("edit", "Q0")]
    r.review()
    assert bot.sent and bot.sent[-1][1]["reply_markup"] == {"force_reply": True}
    bot.pending = [{"update_id": 5, "message": {"chat": {"id": 42}, "text": "시작: 2026-10-08T12:00+09:00\n음식: 샌드위치, 커피",
                                                "reply_to_message": {"message_id": 900}}}]
    r.review()
    row = r.store.candidate("Q0")
    extraction = json.loads(row["extraction_json"])
    assert row["status"] == "human_confirmed" and extraction["start_at"] == "2026-10-08T12:00+09:00"
    assert extraction["food_items"] == ["샌드위치", "커피"]


def test_more_than_five_questions_a_day_wait_for_a_digest(root):
    r, bot, _, clock = unsure(root, n=7, clock={"t": datetime(2026, 10, 7, 10, 0, tzinfo=an.KST).timestamp()})
    r.review()
    assert len(bot.asked) == 5 and len(r.store.candidates("queued_digest")) == 2
    clock["t"] = datetime(2026, 10, 7, 18, 5, tzinfo=an.KST).timestamp()
    r.review()
    (digest,) = bot.digests
    assert len(digest) == 2 and not r.store.candidates("queued_digest")
    r.review()
    assert len(bot.digests) == 1                                # once per digest slot


def test_events_that_are_over_are_neither_asked_about_nor_handed_over(root):
    """A first run backfills months of posts (2026-10-29: 31 confirmed, all past events)."""
    posts = [media("OLD", "[OLD] 간식 이벤트", ts="2026-09-01T08:00:00+0000"),
             media("ASK", "[ASK] 간식 나눔?", ts="2026-09-01T09:00:00+0000"),
             media("NEW", "[NEW] 간식 이벤트", ts="2026-10-06T08:00:00+0000")]
    judge = Judge({"[OLD]": {"gpt-6-luna": judgement(True, 0.95, start_at="2026-09-03T17:30+09:00")},
                   "[ASK]": {"gpt-6-luna": judgement(True, 0.5, start_at=None),
                             "gpt-6.1-terra": judgement(True, 0.5, start_at=None)},
                   "[NEW]": {"gpt-6-luna": judgement(True, 0.95)}})
    bot, writer = Bot(), Writer()
    r, clock = radar(root, Graph({"shoutoutto.ee": posts}), judge, bot=bot, writer=writer)
    r.collect()
    r.analyze()
    assert [r.store.candidate(m)["status"] for m in ("OLD", "ASK", "NEW")] == ["expired", "expired", "auto_confirmed"]
    r.review()
    r.bridge()
    assert bot.asked == [] and [t.mail_id for t in writer.tasks] == ["instagram-NEW"]
    r.store.update_candidate("NEW", status="auto_confirmed", dooray_post_id=None)
    clock["t"] = datetime(2026, 10, 8, 21, 0, tzinfo=an.KST).timestamp()   # confirmed, but the event passed
    r.bridge()
    assert r.store.candidate("NEW")["status"] == "expired" and len(writer.tasks) == 1


@pytest.mark.parametrize("extraction, posted, past", [
    ({"start_at": "2026-10-07T07:00+09:00"}, "2026-10-01T00:00:00+0000", False),   # started 2 h ago
    ({"start_at": "2026-10-07T05:00+09:00"}, "2026-10-01T00:00:00+0000", True),    # 4 h ago, no end
    ({"start_at": "2026-10-06T10:00+09:00", "end_at": "2026-10-09T18:00+09:00"}, "2026-10-01T00:00:00+0000", False),
    ({"start_at": None}, "2026-09-30T00:00:00+0000", False),                       # undated, 7 days old
    ({"start_at": None}, "2026-09-20T00:00:00+0000", True),                        # undated, 17 days old
    ({"start_at": "곧"}, "2026-10-06T00:00:00+0000", False),
])
def test_an_event_is_over_after_its_end_or_three_hours_after_its_start(extraction, posted, past):
    assert an.is_past(extraction, posted, datetime.fromtimestamp(NOW, an.KST)) is past


def test_mixed_language_twins_are_merged_by_their_start_time():
    ko = {"start_at": "2026-10-08T18:00+09:00", "language": "mixed", "location": "N1 로비", "food_items": ["싸이버거"],
          "quantity_limit": "사전 신청 선착순 80명"}
    en = ko | {"location": "N1 lobby", "food_items": ["Thigh burger"], "quantity_limit": "First 80 people"}
    assert an.same_event(ko, en)
    assert not an.same_event(ko, en | {"quantity_limit": "First 50 people"})
    assert not an.same_event(ko | {"language": "ko"}, en | {"language": "ko"})


def test_a_dry_run_sends_nothing_and_writes_no_task(root):
    r, bot, writer, _ = unsure(root, dry_run=True)
    r.review()
    r.bridge()
    assert bot.asked == [] and writer.tasks == [] and bot.said == []


# --- hygiene -----------------------------------------------------------------------------------------
def test_no_secret_reaches_the_database_the_state_or_the_log(root):
    from ggongbab.instagram.cli import write_state
    from ggongbab.ops_storage import SafeLog
    r, _ = radar(root, Graph({"shoutoutto.ee": GOLDEN}), golden_judge())
    r.log = SafeLog(root / ".local/ops-ig-radar.log")
    r.cycle()
    write_state(r, "IG_RADAR_CYCLE_OK")
    r.log.close()
    for path in (root / ".local").rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes() and SECRET.encode() not in path.read_bytes()


def test_the_accounts_file_lists_valid_unique_accounts_with_sane_intervals():
    from pathlib import Path
    from ggongbab.instagram.meta_graph import USERNAME
    root = Path(__file__).resolve().parents[2]
    rows = load_accounts(root)
    names = [row["username"] for row in rows]
    assert names[:3] == ["shoutoutto.ee", "in.cs.tagram", "kaistua_grit"] and len(set(names)) == len(names)
    assert all(USERNAME.fullmatch(n) and n == n.lower() for n in names)
    assert all(60 <= row["interval_minutes"] <= 360 and row["display_name"] for row in rows)
    assert sum(1440 / row["interval_minutes"] for row in rows) <= 300     # the daily call target
    graduate = {"kaist_gsa", "kaist_dhcss", "kaist_stp", "kaistbiz", "kaist_gsis", "kaist_future"}
    assert not graduate & set(names)      # undergraduate accounts only (docs/INSTAGRAM_SOURCES.md)


def test_every_logged_code_is_declared():
    import re
    from pathlib import Path
    source = "".join(p.read_text(encoding="utf-8") for p in
                     (Path(__file__).resolve().parents[2] / "scripts/ggongbab/instagram").glob("*.py"))
    assert set(re.findall(r'"(IG_[A-Z_]+)"', source)) - {"IG_RADAR_BUSY", "IG_CONFIG_REQUIRED"} <= REASONS


def test_the_prefilter_needs_a_food_word_or_a_poster():
    assert an.prefilter("간식 나눔", 1) and an.prefilter("", 3) and not an.prefilter("오픈랩 안내", 1)


def test_only_get_is_ever_used_in_the_graph_module():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "scripts/ggongbab/instagram/meta_graph.py").read_text(encoding="utf-8")
    assert 'method="GET"' in source and "POST" not in source and "DELETE" not in source
    assert "manage_comments" not in source
