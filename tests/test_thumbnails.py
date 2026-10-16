"""The small WebP copies that srcset offers (scripts/make_thumbnails.py) exist for every photo that uses them."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_thumbnails  # noqa: E402


def test_every_world_cup_dish_has_both_thumbnails():
    cup = json.loads((ROOT / "data/content/worldcup.json").read_text(encoding="utf-8"))
    for dish, photo in cup["photos"].items():
        assert photo["image"] == f"images/worldcup/{dish}.jpg"
        for width in (160, 320):
            thumb = ROOT / f"images/worldcup/thumb/{dish}-{width}.webp"
            assert thumb.is_file(), thumb
            with Image.open(thumb) as im:
                assert im.format == "WEBP" and im.width == width, (thumb, im.format, im.size)


def test_make_thumbnails_check_passes():
    assert make_thumbnails.main(["--check"]) == 0


def test_every_srcset_candidate_exists():
    pattern = re.compile(r'(?:data-wc-)?srcset="([^"]+)"')
    for page in ("index.html",):
        html = (ROOT / page).read_text(encoding="utf-8")
        found = pattern.findall(html)
        assert found, page
        for srcset in found:
            for candidate in srcset.split(","):
                path, width = candidate.split()
                assert (ROOT / path).is_file(), (page, path)
                assert width.endswith("w")
                with Image.open(ROOT / path) as im:
                    assert im.width == int(width[:-1]), (page, path, im.width, width)


def test_world_cup_script_offers_the_thumbnails():
    js = (ROOT / "js/worldcup.js").read_text(encoding="utf-8")
    assert "'images/worldcup/thumb/' + m[1] + '-160.webp 160w" in js and "-320.webp 320w" in js
