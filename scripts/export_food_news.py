"""Campus food news in two steps (docs/CAMPUS_FOOD_NEWS.md).

    python scripts/export_food_news.py --review [PATH]   # operator PC: review file -> public input
    python scripts/export_food_news.py                   # public input -> data/ggongbab/news.json

The review file holds the source excerpts (some from the KAIST Portal) and stays on the
operator PC (.local/, never committed). --review writes only the public items to
inputs/ggongbab/food-news.json; that file is what gets committed and what the refresh publishes.
"""
import argparse
from pathlib import Path

from ggongbab.food_news import export_news, publish_review

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / ".local" / "ggongbab" / "food-news-review.json"
PUBLIC_INPUT = ROOT / "inputs" / "ggongbab" / "food-news.json"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--review", nargs="?", const=REVIEW, type=Path,
                        help=f"publish the public items of a review file (default {REVIEW.relative_to(ROOT)})")
    args = parser.parse_args()
    try:
        if args.review:
            count = publish_review(args.review, PUBLIC_INPUT)
            print(f"campus food news public input written: count={count} -> {PUBLIC_INPUT.relative_to(ROOT)}")
        else:
            payload = export_news(PUBLIC_INPUT, ROOT / "data/ggongbab/news.json")
            print(f"campus food news exported: count={payload['count']}")
    except Exception:
        raise SystemExit("NEWS_EXPORT_FAILED: previous files retained; diagnostic values suppressed") from None
