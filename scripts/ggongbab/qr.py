# -*- coding: utf-8 -*-
"""Links printed as QR codes on a poster photo (owner 2026-11-04: a tip said "Qr 코드 들어가야 신청할 수
있어요!" and the sign-up link stayed in the photo, so the 꽁밥 list showed no 신청).

Decoding runs here, on the operations PC, with zxing-cpp (a small wheel without other dependencies);
without it nothing is decoded and the caller goes on as before. Only http(s) links are kept, at most
300 characters each (the tip table's `link` check), in the order found.
"""
from __future__ import annotations

import io
import re
from typing import Iterable, Optional
from urllib.parse import urlsplit

MAX_LINK = 300
URL = re.compile(r"https?://[^\s]+")
# A club's chat room or profile is printed next to the sign-up code ("Join our community"): it is
# shown to the owner but never taken as the sign-up link.
NOT_SIGN_UP = ("open.kakao.com", "pf.kakao.com", "instagram.com", "www.instagram.com", "linktr.ee",
               "discord.gg", "discord.com", "chat.whatsapp.com", "t.me")


def decode(images: Iterable[bytes]) -> list[str]:
    """The http(s) links in the QR codes of these photos, without duplicates; [] without zxing-cpp."""
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        return []
    found: list[str] = []
    for data in images:
        try:
            with Image.open(io.BytesIO(data)) as image:
                codes = zxingcpp.read_barcodes(image.convert("RGB"), formats=zxingcpp.BarcodeFormat.QRCode)
        except Exception:  # noqa: BLE001 - an unreadable photo has no links
            continue
        for code in codes:
            text = str(code.text or "").strip()
            if URL.fullmatch(text) and len(text) <= MAX_LINK and text not in found:
                found.append(text)
    return found


def sign_up(links: Iterable[str]) -> Optional[str]:
    """The first link that is not a chat room or a profile."""
    for link in links:
        if (urlsplit(link).hostname or "").lower() not in NOT_SIGN_UP:
            return link
    return None
