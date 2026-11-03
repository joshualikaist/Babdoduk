# -*- coding: utf-8 -*-
"""QR links in tip photos (scripts/ggongbab/qr.py) and their way into the tip review."""
from __future__ import annotations

import io

import pytest

from ggongbab import qr

from .test_tips import NOW, TIP_A, jpeg, make, report, tips  # noqa: F401 - the `make` fixture

zxingcpp = pytest.importorskip("zxingcpp")


def poster(*links: str) -> bytes:
    """A photo with one QR code per link side by side, like the Codex workshop poster of 2026-11-04."""
    from PIL import Image
    codes = []
    for link in links:
        image = zxingcpp.create_barcode(link, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6)
        height, width = image.shape[:2]
        codes.append(Image.frombytes("L", (width, height), bytes(memoryview(image))))
    sheet = Image.new("L", (sum(c.width for c in codes) + 40 * (len(codes) + 1), max(c.height for c in codes) + 80), 255)
    x = 40
    for code in codes:
        sheet.paste(code, (x, 40))
        x += code.width + 40
    buffer = io.BytesIO()
    sheet.convert("RGB").save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def test_links_are_read_in_order_once_and_only_http():
    photo = poster("https://open.kakao.com/o/club", "https://luma.com/event")
    found = qr.decode([photo, photo, jpeg(), b"not an image"])
    assert sorted(found) == ["https://luma.com/event", "https://open.kakao.com/o/club"]
    assert qr.decode([poster("WIFI:S:campus;;")]) == []


def test_a_chat_room_is_never_the_sign_up_link():
    assert qr.sign_up(["https://open.kakao.com/o/club", "https://luma.com/event"]) == "https://luma.com/event"
    assert qr.sign_up(["https://www.instagram.com/club"]) is None


def test_without_the_decoder_nothing_is_read(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "zxingcpp", None)
    assert qr.decode([poster("https://luma.com/event")]) == []


def test_a_tips_qr_link_reaches_the_owner_and_the_tip(make):
    photo = poster("https://open.kakao.com/o/club", "https://luma.com/event")
    t, db, storage, bot, logs, _ = make([report(TIP_A, details="Qr 코드 들어가야 신청할 수 있어요!")],
                                        files={f"{TIP_A}/1.jpg": photo})
    t.poll()
    text = bot.asked[0][1]
    assert "링크: https://luma.com/event" in text and "사진 속 QR:" in text and "open.kakao.com" in text
    assert db.rows[TIP_A]["link"] == "https://luma.com/event"
    assert "TIP_QR_LINK" in logs


def test_a_visitors_own_link_is_kept(make):
    t, db, storage, bot, logs, _ = make([report(TIP_A, link="https://forms.gle/own")],
                                        files={f"{TIP_A}/1.jpg": poster("https://luma.com/event")})
    t.poll()
    assert db.rows[TIP_A]["link"] == "https://forms.gle/own"
    assert "사진 속 QR: https://luma.com/event" in bot.asked[0][1]
    assert "TIP_QR_LINK" not in logs
