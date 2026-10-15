#!/usr/bin/env python3
"""Write the small WebP copies of the site's photos that srcset offers next to the originals.

    python scripts/make_thumbnails.py            # write missing or outdated copies
    python scripts/make_thumbnails.py --check    # exit 1 if one is missing (tests/test_thumbnails.py)

* Every 먹방 월드컵 dish photo images/worldcup/<id>.jpg (720 px) gets images/worldcup/thumb/<id>-160.webp
  and <id>-320.webp: the tiles, the gacha capsules, the ranking and the previews show them at 34-150 px.
  The 720 px JPG stays for the large match photos, the story card and the Kakao share image.
* Every home food photo images/home/food-<name>-<w>.jpg gets food-<name>-<w>-<n>.webp for the widths in
  HOME_WIDTHS below that are smaller than the original.

The copies are committed (the site has no build step); a copy is rewritten only when its source is newer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WORLDCUP = ROOT / "images" / "worldcup"
WORLDCUP_THUMBS = WORLDCUP / "thumb"
WORLDCUP_WIDTHS = (160, 320)
HOME = ROOT / "images" / "home"
HOME_WIDTHS = (240, 400)
QUALITY = 74


def worldcup_jobs() -> list[tuple[Path, Path, int]]:
    jobs = []
    for src in sorted(WORLDCUP.glob("*.jpg")):
        if src.stem.startswith("og-"):          # the share image is never shown on a page
            continue
        for width in WORLDCUP_WIDTHS:
            jobs.append((src, WORLDCUP_THUMBS / f"{src.stem}-{width}.webp", width))
    return jobs


def home_jobs() -> list[tuple[Path, Path, int]]:
    jobs = []
    for src in sorted(HOME.glob("food-*.jpg")):
        with Image.open(src) as im:
            natural = im.width
        for width in HOME_WIDTHS:
            if width < natural:
                jobs.append((src, src.with_name(f"{src.stem}-{width}.webp"), width))
    return jobs


def write(src: Path, out: Path, width: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        height = round(im.height * width / im.width)
        im.resize((width, height), Image.LANCZOS).save(out, "WEBP", quality=QUALITY, method=6)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="only report missing or outdated copies")
    args = parser.parse_args(argv)
    jobs = worldcup_jobs() + home_jobs()
    stale = [(s, o, w) for s, o, w in jobs if not o.is_file() or o.stat().st_mtime < s.stat().st_mtime]
    if args.check:
        missing = [o for s, o, w in jobs if not o.is_file()]
        for out in missing[:20]:
            print("missing:", out.relative_to(ROOT).as_posix())
        print(f"{len(jobs) - len(missing)}/{len(jobs)} thumbnails present")
        return 1 if missing else 0
    for src, out, width in stale:
        write(src, out, width)
    print(f"wrote {len(stale)} of {len(jobs)} thumbnails")
    return 0


if __name__ == "__main__":
    sys.exit(main())
