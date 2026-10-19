"""Green coffee output adapter. Live storefront parsing is in coffee-explorer/scraper/green.py."""

import csv
import json
import logging
import re
import sys
from pathlib import Path


# Allow importing match_watchlist from same directory
_SCRAPER_DIR = Path(__file__).resolve().parent
if str(_SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_DIR))

from match_watchlist import WATCHLIST_FIELDS, match_products
from scraper.storage import write_json as atomic_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.coffeebeancorral.com"

# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
CACHE_FILE = DATA_DIR / "cbc_detail_cache.json"
CSV_FILE = DATA_DIR / "cbc_coffees.csv"
JSON_FILE = DOCS_DIR / "cbc-data.json"

ATTRIBUTE_NAMES = ["Brightness", "Body", "Aroma", "Complexity", "Balance", "Sweetness"]
FLAVOR_NAMES = ["Spicy", "Chocolaty", "Nutty", "Buttery", "Fruity", "Flowery", "Winey", "Earthy"]

CSV_COLUMNS = [
    "name", "url", "price", "sku", "rating", "review_count",
    "country", "local_region", "category", "process", "variety",
    "altitude", "harvest", "certifications",
    "organic", "fair_trade", "rainforest_alliance", "decaffeinated",
    "cupping_notes",
    *[f"attr_{a.lower()}" for a in ATTRIBUTE_NAMES],
    *[f"flavor_{f.lower()}" for f in FLAVOR_NAMES],
    "description",
    # Watchlist matching
    *WATCHLIST_FIELDS,
]


# ---------- Cache I/O ----------

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load cache (%s), starting fresh", e)
    return {}


def save_cache(cache: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(CACHE_FILE, cache)


# ---------- Record building ----------

def parse_rating(rating_str: str) -> str:
    """Normalize rating string to a number."""
    if not rating_str:
        return ""
    # Already a number like "4.5"
    try:
        return str(float(rating_str))
    except ValueError:
        pass
    # Parse "4 1/2 Stars" format
    match = re.match(r"(\d+)(?:\s+(\d+)/(\d+))?\s*Stars?", rating_str, re.I)
    if match:
        val = int(match.group(1))
        if match.group(2) and match.group(3):
            val += int(match.group(2)) / int(match.group(3))
        return str(val)
    return rating_str


def build_record(listing: dict, detail: dict) -> dict:
    """Merge listing-page data with (possibly cached) detail-page data."""
    record = {col: "" for col in CSV_COLUMNS}
    record["name"] = listing.get("name", "")
    record["url"] = listing.get("url", "")
    record["price"] = listing.get("price", "")
    record["rating"] = parse_rating(listing.get("rating", ""))
    record["review_count"] = listing.get("review_count", "")

    if not detail:
        return record

    # Use detail page price if listing didn't have one
    if not record["price"] and detail.get("price"):
        record["price"] = f"${detail['price']}"

    record["sku"] = detail.get("sku", "")
    record["cupping_notes"] = detail.get("cupping_notes", "")
    record["description"] = detail.get("description", "")

    # Use detail page rating if listing didn't have one
    if not record["rating"] and detail.get("rating"):
        record["rating"] = parse_rating(detail["rating"])

    # Country from detail
    if detail.get("country"):
        record["country"] = detail["country"]

    # Specs
    specs = detail.get("specs", {})
    record["local_region"] = specs.get("Local Region", "")
    record["category"] = specs.get("Category", "")
    record["process"] = specs.get("Process", "")
    record["variety"] = specs.get("Variety", "")
    record["altitude"] = specs.get("Altitude (meters)", specs.get("Altitude", ""))
    record["harvest"] = specs.get("Harvest", "")
    record["certifications"] = specs.get("Certifications", "")
    record["organic"] = specs.get("Organic Certification", "")
    record["fair_trade"] = specs.get("Fair Trade", "")
    record["rainforest_alliance"] = specs.get("Rainforest Alliance Certified", "")
    record["decaffeinated"] = specs.get("Decaffeinated", "")

    # Attribute scores
    attrs = detail.get("attributes", {})
    for attr in ATTRIBUTE_NAMES:
        col = f"attr_{attr.lower()}"
        record[col] = str(attrs.get(attr, "")) if attrs.get(attr) else ""

    # Flavor scores
    flavors = detail.get("flavors", {})
    for flav in FLAVOR_NAMES:
        col = f"flavor_{flav.lower()}"
        record[col] = str(flavors.get(flav, "")) if flavors.get(flav) else ""

    return record


# ---------- Output writers ----------

def write_csv(records: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    log.info("Wrote %d coffees to %s", len(records), CSV_FILE)


def write_json(records: list[dict]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    priced = [r for r in records if r.get("price")]
    atomic_json(JSON_FILE, priced)
    log.info("Wrote %d coffees to %s", len(priced), JSON_FILE)


# ---------- Main ----------

def main():
    from shared_parser import run
    run("cbc", globals())


if __name__ == "__main__":
    main()
