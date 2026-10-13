# -*- coding: utf-8 -*-
"""Whole-mail reading for the Radar (owner decision 2026-10-14): body, attachment text, posters and
the unread restore. Synthetic payloads and files only - no browser, mailbox or Dooray call."""
from __future__ import annotations

import io
import json
import struct
import sys
import types
import zipfile
import zlib
from datetime import datetime

import pytest

from ggongbab.config import KST
from ggongbab.parsers import attachment_text as at
from ggongbab.prefilter import classify
from ggongbab.web import mail_detail as md

HOST = "mail.example.invalid"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=KST)


# --------------------------------------------------------------------------- attachments
def _zip(members: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return out.getvalue()


def test_hwpx_docx_pptx_and_xlsx_text():
    hwpx = _zip({"Contents/section0.xml": '<hs:sec xmlns:hp="x"><hp:p><hp:run><hp:t>10월 16일(목) 18:00</hp:t>'
                                          '</hp:run></hp:p><hp:p><hp:run><hp:t>저녁 도시락 제공 &amp; 경품</hp:t>'
                                          '</hp:run></hp:p></hs:sec>',
                 "Contents/section1.xml": "<hp:p><hp:t>창의학습관</hp:t></hp:p>"})
    assert at.extract("안내.hwpx", hwpx).text == "10월 16일(목) 18:00\n저녁 도시락 제공 & 경품\n\n창의학습관"
    docx = _zip({"word/document.xml": "<w:body><w:p><w:r><w:t>점심</w:t></w:r><w:r><w:t xml:space=\"preserve\"> 제공"
                                      "</w:t></w:r></w:p><w:p><w:r><w:tab/><w:t>N1</w:t></w:r></w:p></w:body>"})
    assert at.extract("a.DOCX", docx).text == "점심 제공\nN1"
    pptx = _zip({"ppt/slides/slide2.xml": "<a:p><a:r><a:t>두 번째</a:t></a:r></a:p>",
                 "ppt/slides/slide10.xml": "<a:p><a:r><a:t>열 번째</a:t></a:r></a:p>",
                 "ppt/slides/slide1.xml": "<a:p><a:r><a:t>첫 번째</a:t></a:r></a:p>"})
    assert at.extract("s.pptx", pptx).text == "첫 번째\n\n두 번째\n\n열 번째"     # slides in order, one blank line apart
    xlsx = _zip({"xl/sharedStrings.xml": "<sst><si><t>피자 제공</t></si></sst>"})
    assert "피자 제공" in at.extract("x.xlsx", xlsx).text


def _record(tag: int, payload: bytes) -> bytes:
    return struct.pack("<I", tag | (len(payload) << 20)) + payload


def _para(text: str, wide_control: bool = False) -> bytes:
    body = text.encode("utf-16-le")
    if wide_control:     # a table/drawing control: the code plus 7 more WCHARs, none of them text
        body = struct.pack("<H", 11) + b"\x41\x00" * 7 + body
    return body + struct.pack("<H", 13)


def test_hwp_section_records_keep_text_and_skip_controls():
    stream = (_record(66, b"\x00" * 22)                                     # PARA_HEADER: not text
              + _record(at.HWPTAG_PARA_TEXT, _para("세미나 안내"))
              + _record(at.HWPTAG_PARA_TEXT, _para("다과 제공", wide_control=True)))
    assert at.hwp_records_text(stream) == "세미나 안내\n\n다과 제공\n"


class _Stream:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class _FakeOle:
    def __init__(self, streams):
        self.streams = streams

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def openstream(self, name):
        key = "/".join(name) if isinstance(name, list) else name
        return _Stream(self.streams[key])

    def listdir(self):
        return [key.split("/") for key in self.streams]

    def exists(self, name):
        return name in self.streams


def _fake_olefile(monkeypatch, streams):
    module = types.SimpleNamespace(OleFileIO=lambda _f: _FakeOle(streams))
    monkeypatch.setitem(sys.modules, "olefile", module)


def _file_header(flags: int) -> bytes:
    return b"HWP Document File".ljust(32, b"\x00") + b"\x00\x00\x05\x05" + struct.pack("<I", flags) + b"\x00" * 216


def test_hwp_compressed_body_and_its_fallbacks(monkeypatch):
    section = _record(at.HWPTAG_PARA_TEXT, _para("10월 20일 12:00, 점심 도시락 제공"))
    deflate = zlib.compressobj(wbits=-15)
    packed = deflate.compress(section) + deflate.flush()
    _fake_olefile(monkeypatch, {"FileHeader": _file_header(1), "BodyText/Section0": packed})
    assert at.extract("공지.hwp", b"ole").text == "10월 20일 12:00, 점심 도시락 제공"
    # distribution documents keep their body encrypted: the preview text is used instead
    _fake_olefile(monkeypatch, {"FileHeader": _file_header(1 | 4), "BodyText/Section0": b"??",
                                "PrvText": "미리보기 다과 제공".encode("utf-16-le")})
    assert at.extract("배포용.hwp", b"ole").text == "미리보기 다과 제공"
    _fake_olefile(monkeypatch, {"FileHeader": _file_header(2)})
    assert at.extract("암호.hwp", b"ole").status == "encrypted"


def _pdf(text: str = "") -> bytes:
    content = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1") if text else b""
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


def test_pdf_text_and_a_poster_pdf_becomes_an_image():
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    text = "Free lunch provided for all attendees on October 20 at 12:00 in N1 room 102, please register."
    result = at.extract("notice.pdf", _pdf(text))
    assert "Free lunch provided" in result.text and result.images == []
    poster = at.extract("poster.pdf", _pdf())
    assert poster.text == "" and len(poster.images) == 1 and poster.images[0][0] == "image/jpeg"


def test_missing_library_broken_and_unsupported_files_are_reported_never_raised(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    assert at.extract("a.pdf", b"%PDF").status == "missing-library"
    assert at.extract("a.hwpx", b"not a zip").status == "failed"
    assert at.extract("a.exe", b"MZ").status == "unsupported"
    assert at.extract("a.txt", "점심 제공".encode("cp949")).text == "점심 제공"


def test_a_large_poster_is_shrunk_to_a_jpeg():
    Image = pytest.importorskip("PIL.Image")
    out = io.BytesIO()
    Image.new("RGBA", (3200, 4000), (255, 0, 128, 255)).save(out, "PNG")
    mime, data = at.normalize_image("image/png", out.getvalue())
    with Image.open(io.BytesIO(data)) as image:
        assert mime == "image/jpeg" and max(image.size) == at.IMAGE_LONG_EDGE


# --------------------------------------------------------------------------- mail detail
class Response:
    def __init__(self, status=200, payload=None, body=b""):
        self.status, self.payload, self._body = status, payload, body

    def json(self):
        return self.payload

    def body(self):
        return self._body


class Request:
    def __init__(self, routes, post_ok=True):
        self.routes, self.post_ok, self.gets, self.posts = routes, post_ok, [], []

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self.routes.get(url) or Response(404)

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append((url, json.loads(data)))
        if not self.post_ok:
            return Response(500)
        return Response(200, {"header": {"isSuccessful": True}})


CONTRACT = types.SimpleNamespace(detail_api=f"https://{HOST}/v2/wapi/mails/{{id}}?render=html",
                                 detail_body_path="result.content.body.content")
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 30000
JPG = b"\xff\xd8\xff" + b"j" * 40000


def _detail(html, files=()):
    return Response(200, {"result": {"content": {"body": {"content": html, "mimeType": "text/html"},
                                                 "fileList": list(files)}}})


def _page(post_ok=True):
    html = ("<p>자연과학 토크 콘서트</p><p>자세한 내용은 포스터를 참고하세요.</p>"
            f'<img src="/mails/1/contents/c1@dooray.com?type=raw"><img src="https://{HOST}/mails/1/contents/c2?type=raw">'
            '<img src="https://tracker.example.com/open.gif?u=1"><img src="/mails/1/contents/c1@dooray.com?type=raw">')
    files = [{"name": "포스터.png", "extension": "png", "size": 30008, "downloadUrl": "/mails/1/parts/2?type=raw"},
             {"name": "안내문.pdf", "extension": "pdf", "size": 900, "downloadUrl": "/mails/1/parts/3?type=raw"},
             {"name": "old.png", "extension": "png", "size": 30008, "downloadUrl": "/mails/1/parts/4?type=raw", "deleted": True},
             {"name": "big.hwp", "extension": "hwp", "size": 50 * 1024 * 1024, "downloadUrl": "/mails/1/parts/5?type=raw"},
             {"name": "drive.pdf", "extension": "pdf", "size": 10, "downloadUrl": "https://drive.example.com/x"}]
    routes = {
        CONTRACT.detail_api.replace("{id}", "1"): _detail(html, files),
        f"https://{HOST}/mails/1/parts/2?type=raw": Response(200, body=PNG),
        f"https://{HOST}/mails/1/parts/3?type=raw": Response(200, body=_zip({"word/document.xml": ""})),
        f"https://{HOST}/mails/1/contents/c1@dooray.com?type=raw": Response(200, body=JPG),
        f"https://{HOST}/mails/1/contents/c2?type=raw": Response(200, body=PNG),     # same bytes as the attachment
    }
    return types.SimpleNamespace(request=Request(routes, post_ok))


def test_a_mail_is_read_with_its_files_and_images_but_never_a_third_party_image():
    page = _page()
    mail = md.read_mail(page, CONTRACT, "1", HOST)
    assert mail.body.startswith("자연과학 토크 콘서트")
    assert [kind for kind, _, _ in mail.image_refs] == ["attachment", "inline", "inline"]
    assert mail.statuses["external-image-skipped"] == 1 and mail.statuses["file-skipped"] == 3
    assert not any("tracker.example.com" in url or "drive.example.com" in url for url in page.request.gets)
    images = md.load_images(page, mail)
    assert [m for m, _ in images] == ["image/png", "image/jpeg"]       # the duplicate PNG is dropped
    decision = classify("자연과학 토크 콘서트", mail.filter_text(), NOW, images=mail.image_count)
    assert decision.candidate and decision.reason == "event + poster image"


def test_attachment_text_is_labelled_without_the_file_name_and_bounded():
    mail = md.OpenedMail(body="본문", attachment_texts=[("첨부 1 · PDF 본문", "가" * 9000), ("첨부 2 · HWP 본문", "나")])
    body = mail.task_body()
    assert body.startswith("본문\n\n[첨부 1 · PDF 본문]\n") and body.count("가") == md.ATTACHMENT_CHARS
    assert "첨부 2" not in body and "안내문" not in body


def test_an_unread_mail_is_marked_unread_again_and_a_read_one_is_left_alone():
    page = _page()
    with md.opened_mail(page, CONTRACT, "1", HOST, unread=True) as mail:
        md.load_images(page, mail)
        assert page.request.posts == []                     # the restore comes after every download
    assert page.request.posts == [(f"https://{HOST}/v2/wapi/mails/unread", {"mailIdList": ["1"]})]
    assert mail.restored is True
    page = _page()
    with md.opened_mail(page, CONTRACT, "1", HOST, unread=False) as mail:
        pass
    assert page.request.posts == [] and mail.restored is None


def test_a_failed_restore_raises_even_when_the_mail_could_not_be_read():
    with pytest.raises(md.UnreadRestoreFailed):
        with md.opened_mail(_page(post_ok=False), CONTRACT, "1", HOST, unread=True):
            pass
    page = _page()
    with pytest.raises(md.MailUnavailable):
        with md.opened_mail(page, CONTRACT, "404", HOST, unread=True):
            pass
    assert page.request.posts == [(f"https://{HOST}/v2/wapi/mails/unread", {"mailIdList": ["404"]})]


# --------------------------------------------------------------------------- prefilter
@pytest.mark.parametrize("subject,body,images,expected", [
    ("INNOVATE KOREA 2026", "행사장 방문객 대상 경품 추첨을 진행합니다.", 0, True),
    ("설문조사 참여 요청", "추첨을 통해 상품권을 드립니다. 10월 20일까지", 0, True),
    ("선물 고마워", "잘 받았어", 0, False),                       # no event, no date
    ("토크 콘서트 안내", "포스터를 참고해 주세요.", 1, True),
    ("토크 콘서트 안내", "포스터를 참고해 주세요.", 0, False),
    ("사진 공유", "주말 사진입니다.", 2, False),                   # images without an event
])
def test_giveaway_and_poster_candidates(subject, body, images, expected):
    assert classify(subject, body, NOW, images=images).candidate is expected


# --------------------------------------------------------------------------- task files
class _Res:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _Opener:
    def __init__(self, steps):
        self.steps, self.calls = list(steps), []

    def open(self, req, timeout=None):
        self.calls.append((req.full_url, req.get_header("Authorization"), req.get_method()))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _redirect(url):
    import urllib.error
    return urllib.error.HTTPError("https://api.gov-dooray.com/x", 307, "Temporary Redirect", {"Location": url}, None)


@pytest.mark.parametrize("target,auth", [("https://file-api.gov-dooray.com/upload/1", True),
                                         ("https://files.example.com/upload/1", False)])
def test_a_poster_upload_follows_the_file_host_redirect_and_keeps_the_token_on_dooray(settings, monkeypatch, target, auth):
    import urllib.request
    from ggongbab.web.task_writer import TaskWriter
    settings.dooray_token, settings.dooray_project_id = "t", "1"
    settings.dooray_base = "https://api.gov-dooray.com"
    opener = _Opener([_redirect(target), _Res({"header": {"isSuccessful": True}, "result": {"id": "f1"}})])
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: opener)
    assert TaskWriter(settings).upload_file("p1", "poster-1.jpg", "image/jpeg", JPG) == "f1"
    first, second = opener.calls
    assert first == ("https://api.gov-dooray.com/project/v1/projects/1/posts/p1/files", "dooray-api t", "POST")
    assert second[0] == target and (second[1] == "dooray-api t") is auth


def test_a_new_task_carries_its_posters_and_a_failed_upload_never_fails_the_task(settings, monkeypatch):
    from ggongbab.web.exit_codes import ProjectNotFound
    from ggongbab.web.task_writer import MailPayload, TaskWriter
    settings.dooray_token, settings.dooray_project_id = "t", "1"

    class Writer(TaskWriter):
        def _request(self, method, path, body=None):
            if path.endswith("/posts") and method == "POST":
                return {"result": {"id": "9001"}}
            return {"result": []}

        def upload_file(self, post_id, filename, mime, data):
            if filename == "poster-2.png":
                raise ProjectNotFound("file upload: HTTP 500")
            uploaded.append((post_id, filename, mime))
            return "f"

    uploaded = []
    writer = Writer(settings)
    writer._verified = True
    post = writer.create_task(MailPayload(mail_id="m1", subject="토크 콘서트", body="본문",
                                          images=[("image/jpeg", JPG), ("image/png", PNG)]))
    assert post == "9001" and uploaded == [("9001", "poster-1.jpg", "image/jpeg")]
    assert writer.uploads == {"uploaded": 1, "failed": 1}
