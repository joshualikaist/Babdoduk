# -*- coding: utf-8 -*-
"""Sign-up links opened before listing, and QR links read from mail posters (owner 2026-11-26).
Fake pages behind an injected opener only: no network."""
from __future__ import annotations

import io
import urllib.error
from datetime import datetime

import pytest

from ggongbab import link_check as lc
from ggongbab.config import KST
from ggongbab.db.repository import MemoryRepository
from ggongbab.models import EventCandidate, RawAttachment, RawItem
from ggongbab.parsers.ai_parser import AIResult
from ggongbab.pipeline import QR_HEADING, Pipeline

from .conftest import POSITIVE_TEXT, make_extraction

FORM = "https://docs.google.com/forms/d/e/1FAIpQLSfSyntheticFormId/viewform"


class Page:
    def __init__(self, body="<title>신청</title>", status=200, final=None):
        self.body, self.status, self.final = body.encode("utf-8"), status, final

    def __call__(self, url):
        self.url = url
        self.opened = getattr(self, "opened", 0) + 1
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return self.final or self.url

    def read(self, limit):
        assert limit == lc.MAX_BYTES
        return self.body[:limit]


def gone(code):
    def opener(url):
        raise urllib.error.HTTPError(url, code, "x", {}, None)
    return opener


def unreachable(url):
    raise TimeoutError("slow site")


# --- one link --------------------------------------------------------------------------------------
def test_a_working_page_is_ok():
    assert lc.check(FORM, opener=Page()).state == lc.OK


@pytest.mark.parametrize("code, state", [(404, lc.DEAD), (410, lc.DEAD), (403, lc.UNKNOWN), (500, lc.UNKNOWN)])
def test_only_a_missing_page_counts_as_dead(code, state):
    assert lc.check(FORM, opener=gone(code)) == lc.LinkCheck(state, code)


def test_a_slow_or_unreachable_site_is_not_evidence():
    assert lc.check(FORM, opener=unreachable).state == lc.UNKNOWN


@pytest.mark.parametrize("page", [
    Page(final="https://docs.google.com/forms/d/e/1FAIpQLSfSyntheticFormId/closedform"),
    Page(body="<div>이 양식은 더 이상 응답을 받지 않습니다.</div>"),
    Page(body="<div>The form is no longer accepting responses.</div>"),
])
def test_a_google_form_that_takes_no_answers_is_closed(page):
    assert lc.check(FORM, opener=page).state == lc.CLOSED


def test_closing_words_on_another_site_are_not_a_closed_form():
    page = Page(body="지난 행사는 더 이상 응답을 받지 않습니다")
    assert lc.check("https://club.example.com/apply", opener=page).state == lc.OK


@pytest.mark.parametrize("url", [
    # A mailing tool's per-recipient click link: opening it tells the sender this mailbox clicked.
    "https://www.matlabexpo.com/kr/poster.html?s_v1=1&elqTrackId=ab12&elq=cd34&rec_id=ef56",
    "https://app.go.example.com/e/er?s_v1=1&lid=2",
    "https://click.example.com/?u=abc",
    "https://club.example.com/apply?mkt_tok=xyz",
    "mailto:office@example.com",
    "ftp://files.example.com/form",
])
def test_links_that_track_the_reader_are_never_opened(url):
    page = Page()
    assert lc.check(url, opener=page).state == lc.SKIPPED
    assert not getattr(page, "opened", 0)


def test_a_campaign_tag_alone_is_not_a_reader_id():
    assert lc.may_open("https://luma.com/event?utm_source=mail&utm_campaign=expo")


# --- what it does to a candidate --------------------------------------------------------------------
def cand(url=FORM):
    return EventCandidate(title="학과 간담회", is_event=True, registration_url=url)


def test_a_dead_link_is_dropped_and_the_event_held():
    c = cand()
    lc.apply(c, opener=gone(404))
    assert c.registration_url is None and c.needs_review
    assert c.review_reasons == ["신청 링크가 열리지 않음 (404), 링크를 뺐음"]


def test_a_closed_form_holds_the_event_as_closed():
    c = cand()
    lc.apply(c, opener=Page(final=FORM.replace("viewform", "closedform")))
    assert c.registration_url == FORM and c.needs_review and "신청 마감" in c.review_reasons[0]


@pytest.mark.parametrize("opener", [Page(), gone(403), unreachable])
def test_anything_else_changes_nothing(opener):
    c = cand()
    lc.apply(c, opener=opener)
    assert c.registration_url == FORM and not c.needs_review and c.review_reasons == []


def test_no_link_or_no_event_opens_nothing():
    page = Page()
    lc.apply(cand(url=None), opener=page)
    lc.apply(EventCandidate(title="x", is_event=False, registration_url=FORM), opener=page)
    assert not getattr(page, "opened", 0)


# --- the pipeline --------------------------------------------------------------------------------
class SeesText:
    """An AI that names as sign-up link the first link it finds after the QR heading."""

    def __init__(self):
        self.texts = []

    def extract(self, text, images, model):
        self.texts.append(text)
        url = None
        if QR_HEADING in text:
            url = text.split(QR_HEADING, 1)[1].split()[0]
        return AIResult(extraction=make_extraction(registration_url=url), model=model)


def mail(*images):
    item = RawItem(source_type="dooray", external_id="mail-1", subject="학과 간담회 안내", raw_text=POSITIVE_TEXT,
                   source_created_at=datetime(2026, 9, 20, 9, 0, tzinfo=KST))
    item.attachments = [RawAttachment(external_file_id=f"f{i}", filename=f"poster{i}.jpg", mime_type="image/jpeg",
                                      size=len(data), data=data, parse_status="downloaded")
                        for i, data in enumerate(images)]
    return item


def big_poster(link):
    zxingcpp = pytest.importorskip("zxingcpp")
    from PIL import Image, ImageDraw

    code = zxingcpp.create_barcode(link, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6)
    height, width = code.shape[:2]
    sheet = Image.frombytes("L", (width, height), bytes(memoryview(code))).convert("RGB")
    canvas = Image.new("RGB", (sheet.width + 600, sheet.height + 600), "white")
    draw = ImageDraw.Draw(canvas)
    for y in range(0, canvas.height, 7):         # some poster texture, so the photo is not a tiny icon
        draw.line([(0, y), (canvas.width, (y * 13) % canvas.height)], fill=(200, (y * 5) % 255, 120))
    canvas.paste(sheet, (300, 300))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=92)
    assert len(out.getvalue()) >= 8 * 1024
    return out.getvalue()


def test_a_qr_link_on_the_poster_becomes_the_sign_up_link(settings):
    """2026-11-26: "포스터를 안봐서 그래. 거기 qr코드 있잖아"."""
    ai, checked = SeesText(), []
    pipe = Pipeline(settings, MemoryRepository(), ai, [], link_checker=checked.append)
    outcome = pipe.process_item(mail(big_poster(FORM)))
    assert QR_HEADING in ai.texts[0] and FORM in ai.texts[0]
    assert outcome.candidate.registration_url == FORM
    assert "신청 URL이 본문에 없음" not in outcome.candidate.review_reasons
    assert checked == [outcome.candidate]


def test_without_a_qr_code_the_text_is_unchanged(settings):
    ai = SeesText()
    Pipeline(settings, MemoryRepository(), ai, []).process_item(mail())
    assert QR_HEADING not in ai.texts[0]


def test_only_the_real_refresh_opens_links():
    import inspect

    from ggongbab import pipeline
    assert inspect.signature(pipeline.Pipeline).parameters["link_checker"].default is None
    source = open(pipeline.__file__.replace("ggongbab/pipeline.py", "refresh_ggongbab.py"), encoding="utf-8").read()
    assert "link_checker=None if args.dry_run else link_check.apply" in source
