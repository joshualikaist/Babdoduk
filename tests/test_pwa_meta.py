"""iOS home-screen web app: manifest, icons and head tags on the main public pages.
Static checks only; no browser or network."""
import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("index.html", "ggongbab.html", "mukbang.html", "history.html", "event.html")
ICONS = {"/images/icons/apple-touch-icon.png": 180, "/images/icons/icon-192.png": 192,
         "/images/icons/icon-512.png": 512}


def png_size(path):
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", path.name
    return struct.unpack(">II", data[16:24])


def test_manifest_fields_and_icons():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "밥도둑 Babdoduk" and manifest["short_name"] == "밥도둑"
    assert manifest["start_url"] == "/" and manifest["display"] == "standalone"
    assert manifest["background_color"] == "#ffffff" and manifest["theme_color"] == "#ffffff"
    icons = {icon["src"]: icon for icon in manifest["icons"]}
    assert set(icons) == set(ICONS)
    for src, size in ICONS.items():
        assert icons[src]["sizes"] == f"{size}x{size}" and icons[src]["type"] == "image/png"


@pytest.mark.parametrize("src,size", sorted(ICONS.items()))
def test_icon_files_are_square_pngs_of_the_declared_size(src, size):
    assert png_size(ROOT / src.lstrip("/")) == (size, size)


@pytest.mark.parametrize("page", PAGES)
def test_public_pages_declare_the_home_screen_app_once(page):
    head = (ROOT / page).read_text(encoding="utf-8").split("</head>", 1)[0]
    expected = [
        '<link rel="apple-touch-icon" sizes="180x180" href="/images/icons/apple-touch-icon.png" />',
        '<link rel="icon" type="image/png" href="/images/icons/icon-192.png" />',
        '<link rel="manifest" href="/manifest.json" />',
        '<meta name="apple-mobile-web-app-capable" content="yes" />',
        '<meta name="apple-mobile-web-app-status-bar-style" content="default" />',
        '<meta name="apple-mobile-web-app-title" content="밥도둑" />',
    ]
    for tag in expected:
        assert head.count(tag) == 1, (page, tag)
    for href in re.findall(r'<link rel="(?:apple-touch-icon|icon|manifest)"[^>]*href="([^"]+)"', head):
        assert (ROOT / href.lstrip("/")).is_file(), (page, href)
