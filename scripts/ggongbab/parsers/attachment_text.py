# -*- coding: utf-8 -*-
"""Text and preview images from mail attachments: PDF, HWP, HWPX, DOCX, PPTX, XLSX, TXT.

The Dooray Radar runs this on the ops PC, so an event whose food or prize wording exists only in an
attached notice or poster reaches the prefilter and the AI (owner decision 2026-10-14). Pure functions
on bytes: nothing is written to disk and nothing is sent anywhere.

PDF needs pypdfium2 and HWP needs olefile (requirements-ggongbab.txt); without them those types are
reported as "missing-library" and skipped, never guessed. A PDF or HWP with almost no text (a scanned
or designed poster) yields an image of its first page instead, for the AI to read.
"""
from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from html import unescape

MAX_TEXT = 8000             # characters kept per attachment
PDF_PAGES = 6               # pages read from a PDF
POSTER_TEXT = 80            # below this many characters a document is treated as a poster
IMAGE_LONG_EDGE = 1600      # pixels; posters stay legible, tokens stay bounded
MAX_ZIP_MEMBER = 8 * 1024 * 1024

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "bmp"})
TEXT_EXTENSIONS = frozenset({"pdf", "hwp", "hwpx", "docx", "pptx", "xlsx", "txt"})


@dataclass
class Extracted:
    text: str = ""
    images: list[tuple[str, bytes]] = field(default_factory=list)   # (mime, data): page renders, previews
    status: str = "ok"      # ok / empty / unsupported / failed / encrypted / missing-library


def extension(name: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]{1,5})$", name or "")
    return match.group(1).lower() if match else ""


def extract(name: str, data: bytes) -> Extracted:
    """Never raises: a broken or hostile file is reported as "failed"."""
    ext = extension(name)
    if ext not in TEXT_EXTENSIONS:
        return Extracted(status="unsupported")
    try:
        result = _HANDLERS[ext](data)
    except ImportError:
        return Extracted(status="missing-library")
    except Exception:  # noqa: BLE001 - malformed files are common in mail
        return Extracted(status="failed")
    result.text = _tidy(result.text)[:MAX_TEXT]
    if result.status == "ok" and not result.text and not result.images:
        result.status = "empty"
    return result


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in (text or "").splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf(data: bytes) -> Extracted:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        parts = []
        for index in range(min(len(document), PDF_PAGES)):
            page = document[index]
            textpage = page.get_textpage()
            parts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        result = Extracted(text="\n".join(parts))
        if len(_tidy(result.text)) < POSTER_TEXT and len(document):
            page = document[0]
            width, height = page.get_size()
            scale = IMAGE_LONG_EDGE / max(width, height, 1)
            bitmap = page.render(scale=max(0.5, min(scale, 4.0)))
            result.images.append(("image/jpeg", _jpeg(bitmap.to_pil())))
            page.close()
        return result
    finally:
        document.close()


# ---------------------------------------------------------------------------
# HWP 5 (OLE compound file)
# ---------------------------------------------------------------------------
HWPTAG_PARA_TEXT = 0x10 + 51
# Control characters that occupy 8 WCHARs (the code plus 7) in a paragraph's text.
_HWP_WIDE_CONTROLS = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23})


def hwp_records_text(stream: bytes) -> str:
    """The text of every PARA_TEXT record in one (decompressed) BodyText section."""
    out: list[str] = []
    pos = 0
    size_total = len(stream)
    while pos + 4 <= size_total:
        header = struct.unpack_from("<I", stream, pos)[0]
        pos += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 4 > size_total:
                break
            size = struct.unpack_from("<I", stream, pos)[0]
            pos += 4
        payload = stream[pos:pos + size]
        pos += size
        if tag == HWPTAG_PARA_TEXT:
            out.append(_hwp_para_text(payload))
    return "\n".join(out)


def _hwp_para_text(payload: bytes) -> str:
    chars: list[str] = []
    count = len(payload) // 2
    index = 0
    while index < count:
        code = struct.unpack_from("<H", payload, index * 2)[0]
        if code >= 32:
            chars.append(chr(code))
            index += 1
        elif code in (10, 13):
            chars.append("\n")
            index += 1
        elif code in _HWP_WIDE_CONTROLS:
            if code == 9:
                chars.append("\t")
            index += 8
        else:
            index += 1
    return "".join(chars)


def _hwp(data: bytes) -> Extracted:
    import olefile

    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
        compressed, encrypted, distribution = bool(flags & 1), bool(flags & 2), bool(flags & 4)
        if encrypted:
            return Extracted(status="encrypted")
        text = ""
        if not distribution:
            sections = sorted((entry for entry in ole.listdir() if len(entry) == 2 and entry[0] == "BodyText"
                               and entry[1].startswith("Section")), key=lambda e: int(e[1][7:] or 0))
            parts = []
            for entry in sections:
                raw = ole.openstream(entry).read()
                parts.append(hwp_records_text(zlib.decompress(raw, -15) if compressed else raw))
            text = "\n".join(parts)
        if not _tidy(text) and ole.exists("PrvText"):
            text = ole.openstream("PrvText").read().decode("utf-16-le", "ignore")
        result = Extracted(text=text)
        if len(_tidy(text)) < POSTER_TEXT and ole.exists("PrvImage"):
            preview = _image_from_bytes(ole.openstream("PrvImage").read())
            if preview:
                result.images.append(preview)
        return result


# ---------------------------------------------------------------------------
# Zipped XML formats: HWPX, DOCX, PPTX, XLSX
# ---------------------------------------------------------------------------
def _xml_text(xml: bytes, tag: str) -> str:
    """Text of every <prefix:tag> element, one paragraph per line."""
    text = xml.decode("utf-8", "ignore")
    text = re.sub(r"</(?:\w+:)?(?:p|tr|br)>|<(?:\w+:)?(?:br|lineBreak)\s*/>", "\n", text)
    pieces = re.findall(rf"<(?:\w+:)?{tag}(?:\s[^>]*)?>([^<]*)</(?:\w+:)?{tag}>|(\n)", text)
    return unescape("".join(a or b for a, b in pieces))


def _zip_members(data: bytes, pattern: str) -> list[bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted((n for n in archive.namelist() if re.fullmatch(pattern, n)),
                       key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)])
        return [archive.read(n) for n in names if archive.getinfo(n).file_size <= MAX_ZIP_MEMBER]


def _hwpx(data: bytes) -> Extracted:
    text = "\n".join(_xml_text(xml, "t") for xml in _zip_members(data, r"Contents/section\d+\.xml"))
    result = Extracted(text=text)
    if len(_tidy(text)) < POSTER_TEXT:
        for raw in _zip_members(data, r"Preview/PrvImage\.\w+"):
            preview = _image_from_bytes(raw)
            if preview:
                result.images.append(preview)
                break
    return result


def _docx(data: bytes) -> Extracted:
    return Extracted(text="\n".join(_xml_text(xml, "t") for xml in _zip_members(data, r"word/document\.xml")))


def _pptx(data: bytes) -> Extracted:
    return Extracted(text="\n".join(_xml_text(xml, "t") for xml in _zip_members(data, r"ppt/slides/slide\d+\.xml")))


def _xlsx(data: bytes) -> Extracted:
    return Extracted(text="\n".join(_xml_text(xml, "t") for xml in _zip_members(data, r"xl/sharedStrings\.xml")))


def _txt(data: bytes) -> Extracted:
    for encoding in ("utf-8", "cp949"):
        try:
            return Extracted(text=data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return Extracted(text=data.decode("utf-8", "ignore"))


_HANDLERS = {"pdf": _pdf, "hwp": _hwp, "hwpx": _hwpx, "docx": _docx, "pptx": _pptx, "xlsx": _xlsx, "txt": _txt}


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def image_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return ""


def _image_from_bytes(data: bytes):
    mime = image_mime(data or b"")
    return (mime, data) if mime else None


def _jpeg(image) -> bytes:
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


def normalize_image(mime: str, data: bytes) -> tuple[str, bytes]:
    """A poster downscaled to IMAGE_LONG_EDGE and re-encoded, so it costs few tokens and
    stays under the task upload and AI limits. Without Pillow the original is returned."""
    try:
        from PIL import Image
    except ImportError:
        return mime, data
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if getattr(image, "is_animated", False):
                image.seek(0)
            if max(image.size) > IMAGE_LONG_EDGE:
                image.thumbnail((IMAGE_LONG_EDGE, IMAGE_LONG_EDGE))
            elif mime in ("image/png", "image/jpeg") and len(data) <= 1_500_000:
                return mime, data
            if image.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", image.size, (255, 255, 255))
                rgba = image.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            return "image/jpeg", _jpeg(image)
    except Exception:  # noqa: BLE001 - an unreadable image is passed on as it came
        return mime, data
