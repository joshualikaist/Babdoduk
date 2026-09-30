"""Generate the campus news snapshot from source-reviewed, sanitized facts only."""
from pathlib import Path
from ggongbab.food_news import export_news

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    try:
        payload = export_news(ROOT / "research/ggongbab/food-news.json", ROOT / "data/ggongbab/news.json")
        print(f"campus food news exported: count={payload['count']}")
    except Exception:
        raise SystemExit("NEWS_EXPORT_FAILED: previous snapshot retained; diagnostic values suppressed") from None
