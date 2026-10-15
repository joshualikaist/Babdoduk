# -*- coding: utf-8 -*-
"""End-to-end check of the free-food (꽁밥) pipeline, from a mail to a card on the page.

No real external system is used: no Dooray, Portal, Supabase or public file. The real code runs
over in-memory and local substitutes, with a fixed clock:

  1. Radar stage   synthetic mails (tests/fixtures/e2e_ggongbab/) -> web/mail_detail.py (a fake
                   page.request serves the detail JSON, attachments and inline images),
                   parsers/attachment_text.py, prefilter.classify, dooray_radar.scan_once (fake
                   opener session and a fake task writer that captures the task payloads).
  2. Cloud stage   each captured payload becomes the task body TaskWriter.build_task writes, then a
                   RawItem exactly as collectors/dooray.py normalize_post reads it, then
                   Pipeline.process_item (sanitizer, rules, AI, validator, dedup) over a
                   MemoryRepository, then exporter.build_payload / build_archive and
                   validate_content.
  3. AI            --ai fake (default): a scripted extractor, deterministic, used by tests and CI.
                   --ai real: the real OpenAI extractor with the key from the ops .env (read, never
                   printed); a few cents.
  4. Page stage    the payload is written to a TEMP dir only and served to ggongbab.html at a fixed
                   page clock through the local-server helper of check_ggongbab_ui.py.

Prints a per-fixture trace (prefilter -> task -> AI -> validator -> published -> card) with fixture
keys only, never mail text. Exits non-zero on any mismatch.

Usage:
  python scripts/e2e_ggongbab_flow.py                 # fake AI
  python scripts/e2e_ggongbab_flow.py --ai real       # observe the real model on the fixtures
  python scripts/e2e_ggongbab_flow.py --write-fixtures  # regenerate the poster PNG and the PDF
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import socket
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab import dooray_radar as radar  # noqa: E402
from ggongbab.collectors.dooray import DoorayCollector  # noqa: E402
from ggongbab.config import KST, Settings  # noqa: E402
from ggongbab.db.repository import MemoryRepository  # noqa: E402
from ggongbab.exporter import build_archive, build_payload  # noqa: E402
from ggongbab.models import EventExtraction, Evidence  # noqa: E402
from ggongbab.parsers.ai_parser import AIResult, AIUsage  # noqa: E402
from ggongbab.pipeline import Pipeline  # noqa: E402
from ggongbab.web.mail_detail import MailOpener  # noqa: E402
from ggongbab.web.mail_reader import MailHeader  # noqa: E402
from ggongbab.web.state import AgentState, digest  # noqa: E402
from ggongbab.web.task_writer import TaskWriter  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "e2e_ggongbab"
LATEST = ROOT / "data" / "ggongbab" / "latest.json"
HOST = "mail.e2e.invalid"
DETAIL_API = f"https://{HOST}/v2/wapi/mails/{{id}}?render=html"
BODY_PATH = "result.content.body.content"
OPS_ENV = Path("C:/Users/joshu/Babdoduk-ops/.env")
POSTER_TEXT = ["진로 토크 콘서트", "9월 22일(화) 12:00~13:00", "N1 101호", "점심 도시락 제공"]


# --------------------------------------------------------------------------- fixtures
def load_fixtures() -> tuple[datetime, list[dict]]:
    spec = json.loads((FIXTURES / "mails.json").read_text(encoding="utf-8"))
    return datetime.fromisoformat(spec["reference"]), spec["mails"]


def _pdf(lines: list[str]) -> bytes:
    """A one-page text PDF (Helvetica, ASCII). Enough for pypdfium2 to extract the text."""
    rows = "".join(f"({line}) Tj 0 -28 Td " for line in lines)
    content = f"BT /F1 18 Tf 72 720 Td {rows}ET".encode("latin-1")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
               b" /Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_poster_png() -> bytes:
    """A poster image with large Korean text, drawn with Pillow. A seeded noise layer keeps it above
    the Radar's 8 KB icon threshold, as a real poster is."""
    import random

    from PIL import Image, ImageDraw, ImageFont

    font_path = next((p for p in ("C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
                                  "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc") if Path(p).exists()), None)
    if font_path is None:
        raise SystemExit("no Korean font found; the committed poster.png is used instead (do not regenerate here)")
    width, height = 900, 1200
    rng = random.Random(20260920)
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            base, noise = 235 - y // 30, (6 if y > 1100 else 0)     # noise only in the bottom strip keeps the file small
            pixels[x, y] = (base + rng.randint(-noise, noise), base - 12 + rng.randint(-noise, noise),
                            255 - y // 20 + rng.randint(-noise, noise))
    draw = ImageDraw.Draw(image)
    sizes = (84, 64, 64, 76)
    y = 260
    for line, size in zip(POSTER_TEXT, sizes):
        font = ImageFont.truetype(font_path, size)
        box = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (box[2] - box[0])) // 2, y), line, font=font, fill=(20, 24, 60))
        y += size + 90
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def write_fixtures() -> None:
    # The PDF keeps its "Date:" and "Venue:" labels: they are flyer content, not a mail header block.
    (FIXTURES / "poster.png").write_bytes(make_poster_png())
    (FIXTURES / "announcement.pdf").write_bytes(_pdf([
        "Startup Networking Day",
        "Date: September 24, 2026, 18:00-20:00",
        "Venue: Building E3, room 201",
        "Dinner provided for all attendees.",
        "Please register at https://example.org/networking-day",
    ]))
    print("wrote poster.png and announcement.pdf")


# --------------------------------------------------------------------------- expectations
@dataclass
class Expect:
    candidate: bool
    reason: str = ""            # prefilter reason (exact, fake and real alike: no AI involved)
    opened: bool = True
    images: int = 0             # poster images that go with the task
    attachment_block: bool = False
    restored: bool = False      # an unread mail marked unread again
    published: bool = False
    food: str = ""              # "text" / "poster" food source when published with food
    giveaway: bool = False
    deadline_only: bool = False


EXPECT: dict[str, Expect] = {
    "food-body": Expect(True, "food provision wording + event + date", restored=True, published=True, food="text"),
    "food-pdf": Expect(True, "food provision wording + event + date", attachment_block=True, published=True, food="text"),
    "food-poster": Expect(True, "event + poster image", images=1, restored=True, published=True, food="poster"),
    "giveaway-expo": Expect(True, "giveaway wording + event + date", published=True, giveaway=True),
    # A survey with a prize draw and no event to attend is not listed (owner decision 2026-10-15).
    "giveaway-deadline": Expect(True, "giveaway wording + event + date"),
    # A booth with a prize draw and only a sign-up deadline is listed, starting at its deadline.
    "giveaway-booth": Expect(True, "giveaway wording + event + date", published=True, giveaway=True,
                             deadline_only=True),
    "multi-session": Expect(True, "food provision wording + event + date", published=True, food="text"),
    "newsletter": Expect(False, "no event wording"),
    "receipt": Expect(False, "denylist: transactional subject (not opened)", opened=False),
}


# --------------------------------------------------------------------------- radar stage
class Response:
    def __init__(self, status=200, payload=None, body=b""):
        self.status, self.payload, self._body = status, payload, body

    def json(self):
        return self.payload

    def body(self):
        return self._body


class FakeRequest:
    """page.request, served from the fixtures. Records every call, in order."""

    def __init__(self, routes: dict[str, Response]):
        self.routes, self.log = routes, []

    def get(self, url, timeout=None):
        self.log.append(("GET", url))
        return self.routes.get(url) or Response(404)

    def post(self, url, data=None, headers=None, timeout=None):
        self.log.append(("POST", url, json.loads(data)))
        return Response(200, {"header": {"isSuccessful": True}})


def build_mailbox(reference: datetime, mails: list[dict]) -> tuple[list[MailHeader], FakeRequest]:
    from ggongbab.parsers.html_text import html_to_text

    routes: dict[str, Response] = {}
    headers: list[MailHeader] = []
    for mail in mails:
        mail_id = mail["mail_id"]
        files = []
        for index, att in enumerate(mail["attachments"], start=2):
            data = (FIXTURES / att["file"]).read_bytes()
            path = f"/mails/{mail_id}/parts/{index}?type=raw"
            routes[f"https://{HOST}{path}"] = Response(200, body=data)
            files.append({"name": att["name"], "extension": att["extension"], "size": len(data), "downloadUrl": path})
        routes[DETAIL_API.replace("{id}", mail_id)] = Response(200, {"result": {"content": {
            "body": {"content": mail["html"], "mimeType": "text/html"}, "fileList": files}}})
        received_at = (reference - timedelta(minutes=mail["minutes_before"])).replace(second=0, microsecond=0)
        headers.append(MailHeader(mail_id=mail_id, subject=mail["subject"], preview=html_to_text(mail["html"])[:80],
                                  received=received_at.date(), unread=mail["unread"], received_at=received_at))
    return headers, FakeRequest(routes)


class CapturingWriter:
    """Stands in for TaskWriter: keeps the payloads, writes nowhere."""

    def __init__(self):
        self.payloads = []

    def create_task(self, payload, dry_run=False):
        self.payloads.append(payload)
        return f"post-{len(self.payloads):03d}"


@dataclass
class RadarOutcome:
    result: radar.ScanResult
    payloads: list
    request: FakeRequest
    state: AgentState
    flash: list


def run_radar_stage(reference: datetime, mails: list[dict], work: Path) -> RadarOutcome:
    headers, request = build_mailbox(reference, mails)
    session = SimpleNamespace(page=SimpleNamespace(request=request), context=None,
                              contract=SimpleNamespace(detail_api=DETAIL_API, detail_body_path=BODY_PATH))
    state = AgentState.load(work / "ggongbab-mail-state.json")      # a temp file, never the operator's ledger
    writer = CapturingWriter()
    guard = radar.RequestGuard(None, HOST)
    result = radar.scan_once(session, state, writer, list_mails=lambda s, **_: headers, now=reference,
                             since=reference - timedelta(days=2), allow_unread=True, dry_run=False, guard=guard,
                             opener=MailOpener(HOST))
    return RadarOutcome(result, writer.payloads, request, state, result.flash)


# --------------------------------------------------------------------------- cloud stage
class FakeDoorayClient:
    """The Dooray API client, answering from memory: a task's files are the posters the Radar attached."""

    def __init__(self, files: dict[str, list[tuple[str, str, bytes]]]):
        self.files = files      # post id -> [(file id, mime, data)]

    def list_post_files(self, project_id, post_id):
        return [{"id": fid, "name": f"poster-{i}.jpg", "size": len(data)}
                for i, (fid, _mime, data) in enumerate(self.files.get(post_id, []), start=1)]

    def download_post_file(self, project_id, post_id, file_id, max_bytes):
        for fid, mime, data in self.files.get(post_id, []):
            if fid == file_id:
                return data, mime
        raise AssertionError("unknown file")


def to_raw_items(payloads: list, settings: Settings):
    """MailPayload -> the task body TaskWriter writes -> the post JSON Dooray returns -> RawItem."""
    files = {}
    posts = []
    for number, payload in enumerate(payloads, start=1):
        post_id = f"post-{number:03d}"
        task = TaskWriter(settings).build_task(payload)
        posted = [(f"{post_id}-file-{i}", mime, data) for i, (mime, data) in enumerate(payload.images, start=1)]
        files[post_id] = posted
        stamp = (payload.discovered_at or payload.received_at).isoformat()
        posts.append({"id": post_id, "number": number, "subject": task["subject"], "body": task["body"],
                      "files": [{"id": fid, "name": f"poster-{i}.jpg", "size": len(data)}
                                for i, (fid, _m, data) in enumerate(posted, start=1)],
                      "createdAt": stamp, "updatedAt": stamp})
    collector = DoorayCollector(settings, client=FakeDoorayClient(files), fetch_attachments=True)
    items = []
    for post in posts:
        item = collector.normalize_post(post)
        if item.attachments:
            item.attachment_loader = (lambda pid=post["id"], it=item: collector.download_attachments(pid, it))
        items.append((post["id"], item))
    return items


# --------------------------------------------------------------------------- AI
def ev(**kw) -> Evidence:
    return Evidence(**{"event_time": None, "location": None, "food": None, "registration": None, **kw})


def ext(**kw) -> EventExtraction:
    base = dict(is_event=True, title=None, summary=None, event_start=None, event_end=None, date_text=None,
                time_text=None, location_name=None, building=None, room=None, food_provided="unknown",
                food_type="unknown", food_description=None, giveaway=None, giveaway_description=None,
                organizer=None, eligibility=None, registration_required="unknown", registration_deadline=None,
                registration_url=None, confidence=0.9, needs_review=False, review_reason=None,
                evidence=ev())
    base.update(kw)
    return EventExtraction(**base)


# What a faithful model returns for each fixture, keyed by a piece of the subject line.
SCRIPT = {
    "반도체 산업 진로 특강": lambda: ext(
        title="반도체 산업 진로 특강", summary="반도체 산업 진로 특강과 점심 도시락 제공.",
        event_start="2026-09-20T12:30:00+09:00", event_end="2026-09-20T13:30:00+09:00",
        date_text="9월 20일(일)", time_text="12:30~13:30", location_name="N1 101호", building="N1", room="101호",
        food_provided="true", food_type="lunchbox", food_description="점심 도시락",
        registration_required="true", registration_url="https://example.org/career-apply", confidence=0.93,
        evidence=ev(event_time="9월 20일(일) 12:30~13:30", location="N1 101호에서",
                          food="참석자에게 점심 도시락을 제공합니다", registration="사전 신청 필수")),
    "스타트업 네트워킹 데이": lambda: ext(
        title="스타트업 네트워킹 데이", summary="스타트업 네트워킹 데이에서 저녁 식사를 제공합니다.",
        event_start="2026-09-24T18:00:00+09:00", event_end="2026-09-24T20:00:00+09:00",
        date_text="September 24, 2026", time_text="18:00-20:00", location_name="Building E3, room 201",
        building="E3", room="201", food_provided="true", food_type="meal", food_description="저녁 식사",
        registration_required="true", registration_url="https://example.org/networking-day", confidence=0.9,
        evidence=ev(event_time="Date: September 24, 2026, 18:00-20:00", location="Venue: Building E3, room 201",
                          food="Dinner provided for all attendees", registration="Please register at")),
    "진로 토크 콘서트": lambda: ext(
        title="진로 토크 콘서트", summary="진로 토크 콘서트. 점심 도시락이 제공됩니다.",
        event_start="2026-09-22T12:00:00+09:00", event_end="2026-09-22T13:00:00+09:00",
        date_text="9월 22일(화)", time_text="12:00~13:00", location_name="N1 101호", building="N1", room="101호",
        food_provided="true", food_type="lunchbox", food_description="점심 도시락", confidence=0.88,
        evidence=ev(event_time="9월 22일(화) 12:00~13:00", location="N1 101호", food="점심 도시락 제공",
                          registration=None, from_poster=["event_time", "location", "food"])),
    "캠퍼스 창업 엑스포": lambda: ext(
        title="캠퍼스 창업 엑스포", summary="스탬프 투어와 경품 추첨이 있는 창업 엑스포.",
        event_start="2026-09-20T10:00:00+09:00", event_end="2026-09-20T17:00:00+09:00",
        date_text="9월 20일(일)", time_text="10:00~17:00", location_name="KI빌딩 1층 로비", building="KI빌딩",
        giveaway="true", giveaway_description="경품 추첨 (에어팟 3명), 스탬프 투어 기념품", confidence=0.92,
        evidence=ev(event_time="9월 20일(일) 10:00~17:00", location="KI빌딩 1층 로비",
                          food=None, registration=None, giveaway="방문객 대상 경품 추첨(에어팟 3명)을 진행")),
    # A survey with a prize draw and nothing to attend: the model reads it as no event (prompt rule 7).
    "KAIST 설문 참여 이벤트": lambda: ext(
        is_event=False, title="KAIST 설문 참여 이벤트", summary="설문 참여자 추첨으로 문화상품권을 제공합니다.",
        confidence=0.95),
    "굿즈 팝업스토어": lambda: ext(
        title="캠퍼스 굿즈 팝업스토어 경품", summary="팝업스토어 부스를 방문하면 경품 추첨 응모권을 줍니다.",
        date_text="9월 24일(목)", time_text="23:59", location_name="굿즈 팝업스토어 부스",
        giveaway="true", giveaway_description="경품 추첨 응모권",
        registration_required="true", registration_deadline="2026-09-24T23:59:00+09:00", confidence=0.9,
        evidence=ev(registration="응모 마감: 9월 24일(목) 23:59", giveaway="경품 추첨 응모권을 드립니다")),
    "AI 특강 시리즈": lambda: ext(
        title="AI 특강 시리즈", summary="3회에 걸친 AI 특강. 매 회 샌드위치를 제공합니다.",
        event_start="2026-09-21T12:00:00+09:00", event_end="2026-09-23T13:00:00+09:00",
        date_text="9월 21일(월), 22일(화), 23일(수)", time_text="매 회 12:00~13:00",
        location_name="E11 201호", building="E11", room="201호", food_provided="true", food_type="meal",
        food_description="샌드위치", confidence=0.9,
        evidence=ev(event_time="1회: 9월 21일(월) 12:00~13:00", location="장소: E11 201호",
                          food="매 회 참석자에게 샌드위치를 제공합니다")),
}


class ScriptedExtractor:
    """Deterministic stand-in for the model. Fails loudly for a mail it has no script for, which also
    proves the prefilter kept the newsletter and the receipt away from the AI."""

    def __init__(self):
        self.calls: list[dict] = []

    def extract(self, text, images, model):
        subject = re.search(r"^SUBJECT: (.*)$", text, re.M).group(1)
        for key, make in SCRIPT.items():
            if key in subject:
                self.calls.append({"key": key, "images": len(images)})
                return AIResult(extraction=make(), model=model, usage=AIUsage(), input_kind="text+image" if images else "text")
        raise AssertionError("AI called for a mail no script covers")


class RecordingExtractor:
    """Wraps the real extractor to count calls and tokens."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def extract(self, text, images, model):
        result = self.inner.extract(text, images, model)
        self.calls.append({"key": re.search(r"^SUBJECT: (.*)$", text, re.M).group(1), "images": len(images),
                           "in": result.usage.input_tokens, "out": result.usage.output_tokens,
                           "ok": result.extraction is not None})
        return result


def read_ops_env() -> dict[str, str]:
    values = {}
    for line in OPS_ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    return values


# --------------------------------------------------------------------------- safety
@contextmanager
def offline():
    """Refuse every non-loopback socket connection while the fake-AI run is in progress."""
    original = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError("the offline e2e run tried to reach a network host")
        return original(self, address)

    socket.socket.connect = guarded
    try:
        yield
    finally:
        socket.socket.connect = original


# --------------------------------------------------------------------------- the run
@dataclass
class Row:
    key: str
    subject: str
    prefilter: str = ""
    task: str = "-"
    ai: str = "-"
    validator: str = "-"
    published: str = "no"
    card: str = "-"
    event_id: Optional[str] = None
    extraction: Optional[EventExtraction] = None
    candidate: object = None


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    extractor_calls: list = field(default_factory=list)
    payload: dict = field(default_factory=dict)
    archive: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self.problems.append(message)


def make_settings(ai_model: str) -> Settings:
    # Explicit values everywhere an environment variable would otherwise decide.
    return Settings(dooray_token="e2e-offline", dooray_project_id="e2e-project", dooray_base="https://dooray.e2e.invalid",
                    supabase_url="", supabase_secret_key="", openai_api_key="", ai_model=ai_model,
                    ai_fallback_model="", ai_confidence_threshold=0.75, ai_max_images=2, publish_confidence_threshold=0.7,
                    expired_grace_hours=3, export_horizon_days=60, dedup_threshold=0.72)


def run_flow(ai: str = "fake", page: bool = True) -> Report:
    from validate_content import validate_ggongbab_archive_payload, validate_ggongbab_payload

    reference, mails = load_fixtures()
    subjects = {m["key"]: m["subject"] for m in mails}
    report = Report(rows=[Row(m["key"], m["subject"]) for m in mails])
    rows = {row.key: row for row in report.rows}
    latest_before = hashlib.sha256(LATEST.read_bytes()).hexdigest() if LATEST.exists() else ""

    if ai == "real":
        from ggongbab.parsers.ai_parser import OpenAIExtractor

        env = read_ops_env()
        model = env.get("GGONGBAB_AI_MODEL") or "gpt-5.6-luna"
        extractor = RecordingExtractor(OpenAIExtractor(env["OPENAI_API_KEY"]))
    else:
        model = "scripted-extractor"
        extractor = ScriptedExtractor()
    settings = make_settings(model)

    with tempfile.TemporaryDirectory(prefix="e2e-ggongbab-") as tmp:
        work = Path(tmp)
        # ---- 1. Radar -------------------------------------------------------------------------
        outcome = run_radar_stage(reference, mails, work)
        by_mail = {m["mail_id"]: m["key"] for m in mails}
        details = {url: None for kind, url, *_ in outcome.request.log if kind == "GET"}
        for mail in mails:
            row, expect = rows[mail["key"]], EXPECT[mail["key"]]
            record = outcome.state.mails.get(digest(mail["mail_id"]))
            row.prefilter = ("candidate" if record and record.registered else "filtered") + (f" ({record.reason})" if record else "")
            report.check(record is not None, f"{row.key}: no ledger entry")
            if record:
                report.check(record.registered is expect.candidate, f"{row.key}: candidate={record.registered}, expected {expect.candidate}")
                report.check(record.reason == expect.reason, f"{row.key}: prefilter reason {record.reason!r}, expected {expect.reason!r}")
            opened = DETAIL_API.replace("{id}", mail["mail_id"]) in details
            report.check(opened is expect.opened, f"{row.key}: opened={opened}, expected {expect.opened}")
            restore_posts = [e for e in outcome.request.log if e[0] == "POST" and e[2] == {"mailIdList": [mail["mail_id"]]}]
            report.check(bool(restore_posts) is expect.restored,
                         f"{row.key}: unread restore {bool(restore_posts)}, expected {expect.restored}")
            if expect.restored:
                # the restore comes after every download of that mail
                last_get = max((i for i, e in enumerate(outcome.request.log) if e[0] == "GET" and f"/{mail['mail_id']}" in e[1]), default=-1)
                report.check(outcome.request.log.index(restore_posts[0]) > last_get, f"{row.key}: restored before the last download")
        report.check(all(e[0] == "GET" or e[1] == f"https://{HOST}/v2/wapi/mails/unread" for e in outcome.request.log),
                     "the Radar sent a request that is neither a GET nor the unread restore")
        report.check(outcome.result.denied == 1 and outcome.result.opened == 8 and outcome.result.registered == 7,
                     f"radar counts: {outcome.result.counts()}")
        report.check(len(outcome.flash) == 2, f"flash (same-day) candidates: {len(outcome.flash)}, expected 2")

        tasks = {}
        for payload in outcome.payloads:
            key = by_mail[payload.mail_id]
            tasks[key] = payload
            expect = EXPECT[key]
            rows[key].task = f"post, {len(payload.images)} image(s)"
            report.check(len(payload.images) == expect.images, f"{key}: {len(payload.images)} images on the task, expected {expect.images}")
            report.check(("[첨부 1 · PDF 본문]" in payload.body) is expect.attachment_block,
                         f"{key}: PDF text block {'missing' if expect.attachment_block else 'unexpected'} in the task body")
            if key == "food-body":
                report.check("점심 도시락을 제공합니다" in payload.body, f"{key}: body text missing in the task")
        report.check(set(tasks) == {k for k, e in EXPECT.items() if e.candidate}, f"tasks created for {sorted(tasks)}")

        # ---- 2. Cloud -------------------------------------------------------------------------
        repo = MemoryRepository()
        items = to_raw_items(outcome.payloads, settings)
        pipeline = Pipeline(settings, repo, extractor, [])
        key_of_post = {post_id: by_mail[payload.mail_id] for (post_id, _), payload in zip(items, outcome.payloads)}
        for post_id, item in items:
            key = key_of_post[post_id]
            report.check(item.subject == subjects[key], f"{key}: subject changed on the way ({item.subject!r})")
            report.check(len(item.attachments) == EXPECT[key].images, f"{key}: {len(item.attachments)} RawItem attachments")
            parsed = pipeline.process_item(item)
            row = rows[key]
            report.check(parsed is not None and parsed.error is None, f"{key}: pipeline error {getattr(parsed, 'error', None)!r}")
            cand = parsed.candidate if parsed else None
            row.candidate = cand
            if cand is None:
                continue
            raw = repo.find_raw_item("dooray", post_id)
            linked = repo.events_linked_to(raw["id"]) if raw else []
            row.event_id = linked[0] if linked else None
            row.ai = f"event={'Y' if cand.is_event else 'N'} food={cand.food_provided}" + (
                f"/{cand.food_evidence_source}" if cand.food_evidence_source else "") + f" gift={cand.giveaway} c={cand.confidence}"
            if not cand.is_event:       # keep what the model said, to explain the mismatch (fixture text only)
                run = next((r for r in reversed(repo.ai_runs) if r["raw_item_id"] == raw["id"]), None)
                parsed_json = (run or {}).get("parsed_json") or {}
                row.ai += f" model_note={(parsed_json.get('review_reason') or parsed_json.get('summary') or '')[:160]!r}"
            row.validator = "ok" if not cand.needs_review else "review: " + "; ".join(r.split(":")[0] for r in cand.review_reasons)
        report.extractor_calls = extractor.calls
        report.usage = pipeline.stats.model_usage
        if ai == "fake":
            report.check(len(extractor.calls) == 7, f"{len(extractor.calls)} AI calls, expected 7")
            by_key = {c["key"]: c["images"] for c in extractor.calls}
            report.check(by_key.get("진로 토크 콘서트") == 1 and sum(by_key.values()) == 1, f"images sent to the AI: {by_key}")

        # ---- exporter + validator ------------------------------------------------------------------
        rows_db = repo.publishable_events()
        payload = build_payload(rows_db, settings, reference, food_only=True)
        report.payload = payload
        report.archive = build_archive(rows_db, settings, set(), reference)
        out = work / "public"
        (out / "archive").mkdir(parents=True)
        (out / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "archive" / "index.json").write_text(json.dumps(report.archive, ensure_ascii=False, indent=2), encoding="utf-8")
        for error in validate_ggongbab_payload(payload, reference):
            report.problems.append(f"validate_content: {error}")
        for error in validate_ggongbab_archive_payload(report.archive, {e["id"] for e in payload["events"]}):
            report.problems.append(f"validate_content (archive): {error}")
        published = {e["id"]: e for e in payload["events"]}
        for key, row in rows.items():
            expect = EXPECT[key]
            row.published = "yes" if row.event_id in published else "no"
            report.check((row.event_id in published) is expect.published,
                         f"{key}: published={row.event_id in published}, expected {expect.published}"
                         + (f" ({row.validator})" if not expect.published or row.event_id not in published else ""))
            event = published.get(row.event_id)
            if event and expect.published:
                report.check(event["food"].get("source") == (expect.food or None) if expect.food else event["food"]["provided"] != "true",
                             f"{key}: food source {event['food'].get('source')!r}, expected {expect.food!r}")
                report.check(("giveaway" in event) is expect.giveaway, f"{key}: giveaway marker {'giveaway' in event}")
        report.check(payload["count"] == sum(1 for e in EXPECT.values() if e.published),
                     f"{payload['count']} published events, expected {sum(1 for e in EXPECT.values() if e.published)}")
        for event in payload["events"]:
            blob = json.dumps(event, ensure_ascii=False)
            report.check("@" not in blob and "mail_key" not in blob and "Original Message" not in blob,
                         "a published event carries mail plumbing")
        multi = published.get(rows["multi-session"].event_id)
        if multi:
            report.check(multi["startAt"].startswith("2026-09-21T12:00") and multi["endAt"].startswith("2026-09-23T13:00"),
                         f"multi-session spans {multi['startAt']} .. {multi['endAt']}")
        draw = published.get(rows["giveaway-booth"].event_id)
        if draw:
            report.check(draw["startAt"].startswith("2026-09-24T23:59") and draw["registration"]["deadline"] == draw["startAt"],
                         f"deadline-only giveaway startAt {draw['startAt']}")

        # ---- 3. Page --------------------------------------------------------------------------------
        if page:
            check_page(report, rows, published, reference, out)

    after = hashlib.sha256(LATEST.read_bytes()).hexdigest() if LATEST.exists() else ""
    report.check(after == latest_before, "data/ggongbab/latest.json changed during the run")
    return report


def check_page(report: Report, rows: dict, published: dict, reference: datetime, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    import check_ggongbab_ui as ui

    with ui.local_server() as base, sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(timezone_id="Asia/Seoul", locale="ko-KR", reduced_motion="reduce",
                                      viewport={"width": 1280, "height": 900})
        ui.neutralize_public_config(context)
        context.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        context.route("https://fonts.gstatic.com/**", lambda route: route.abort())
        try:
            context.clock.set_fixed_time(reference)
            tab = context.new_page()
            errors = []
            tab.on("pageerror", lambda error: errors.append(type(error).__name__))
            tab.route("**/data/ggongbab/latest.json", lambda route: route.fulfill(path=str(out / "latest.json"), content_type="application/json"))
            tab.route("**/data/ggongbab/archive/index.json", lambda route: route.fulfill(path=str(out / "archive" / "index.json"), content_type="application/json"))
            tab.route("**/data/ggongbab/news.json", lambda route: route.fulfill(status=404, body=""))
            tab.route("**/data/kaist-menu/**", lambda route: route.fulfill(status=404, body=""))
            tab.goto(base + "/ggongbab.html#free")
            tab.evaluate("() => { localStorage.setItem('babdoduk-lang', 'ko'); localStorage.removeItem('babdoduk-ggongbab-filter'); }")
            tab.reload()
            tab.locator(".gg-card").first.wait_for()
            shown = tab.locator(".gg-card").evaluate_all("els => els.map(el => el.dataset.id)")
            report.check(shown == [e["id"] for e in out_events(out)], f"cards on the page {len(shown)}, expected {len(published)} in feed order")
            for key, row in rows.items():
                expect = EXPECT[key]
                present = row.event_id in shown
                report.check(present is expect.published, f"{key}: card shown={present}, expected {expect.published}")
                if not present:
                    continue
                card = tab.locator(f'.gg-card[data-id="{row.event_id}"]')
                row.card = "card"
                gift = card.locator(".gg-gift-badge").count()
                report.check(gift == (1 if expect.giveaway else 0), f"{key}: {gift} gift badge(s)")
                if expect.giveaway:
                    row.card += " 🎁"
                    report.check(card.locator(".gg-giveaway").count() == 1, f"{key}: giveaway line missing")
                if expect.food == "poster":
                    note = " ".join(card.locator(".gg-food-primary").inner_text().split())
                    report.check("포스터 기준" in note, f"{key}: food line {note!r} has no 포스터 기준")
                    row.card += " 포스터 기준"
                elif expect.food:
                    report.check(card.locator(".gg-food-primary").count() == 1 and card.locator(".gg-food-source").count() == 0,
                                 f"{key}: text-sourced food shows a poster note or none")
                else:
                    report.check(card.locator(".gg-food-primary").count() == 0, f"{key}: a giveaway-only card shows a food line")
                if expect.deadline_only:
                    line = " ".join(card.locator(".gg-time.is-deadline").inner_text().split())
                    report.check(line == "신청 마감 9월 24일 (목) 23:59", f"{key}: date line {line!r}")
                    row.card += " 마감일"
            # Only food counts: giveaway-only listings never raise the free-meal count.
            today = reference.date().isoformat()
            food_today = sum(1 for e in published.values() if e["startAt"].startswith(today) and e["food"]["provided"] == "true")
            count = tab.locator(".gg-radar-count").inner_text()
            report.check(count == f"오늘 {food_today}개", f"radar count {count!r}, expected 오늘 {food_today}개")
            counts = tab.locator(".gg-counts").inner_text()
            report.check(counts.startswith(f"오늘 꽁밥 {food_today}개"), f"counts line {counts[:20]!r}")
            text = tab.locator("body").inner_text()
            for key in ("newsletter", "receipt"):
                report.check(rows[key].subject not in text, f"{key}: its subject is on the page")
            report.check(not errors, f"page errors: {errors}")
        finally:
            context.close()
            browser.close()


def out_events(out: Path) -> list:
    return json.loads((out / "latest.json").read_text(encoding="utf-8"))["events"]


# --------------------------------------------------------------------------- output
def print_report(report: Report, ai: str) -> None:
    head = ["fixture", "prefilter", "task", "AI", "validator", "published", "card"]
    table = [head] + [[r.key, r.prefilter, r.task, r.ai, r.validator, r.published, r.card] for r in report.rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(head))]
    print(f"ai: {ai}")
    for number, row in enumerate(table):
        print(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if number == 0:
            print("-+-".join("-" * w for w in widths))
    print(f"published events: {report.payload.get('count')}  archive: {report.archive.get('count')}  "
          f"AI calls: {len(report.extractor_calls)}")
    if report.usage:
        for model, usage in report.usage.items():
            print(f"usage {model}: {usage}")
    if report.problems:
        print(f"MISMATCHES ({len(report.problems)}):")
        for problem in report.problems:
            print(f"  - {problem}")
    else:
        print("OK: every expectation held")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ai", choices=("fake", "real"), default="fake")
    parser.add_argument("--no-page", action="store_true", help="skip the browser stage")
    parser.add_argument("--write-fixtures", action="store_true")
    args = parser.parse_args(argv)
    if args.write_fixtures:
        write_fixtures()
        return 0
    if args.ai == "fake":
        with offline():
            report = run_flow("fake", page=not args.no_page)
    else:
        report = run_flow("real", page=not args.no_page)
    print_report(report, args.ai)
    return 1 if report.problems else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
