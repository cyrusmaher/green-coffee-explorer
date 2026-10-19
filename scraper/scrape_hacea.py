"""Green coffee output adapter. Live storefront parsing is in coffee-explorer/scraper/green.py."""

import csv
import json
import logging
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

BASE_URL = "https://haceacoffee.com"

# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
CACHE_FILE = DATA_DIR / "hacea_detail_cache.json"
CSV_FILE = DATA_DIR / "hacea_coffees.csv"
JSON_FILE = DOCS_DIR / "hacea-data.json"

CSV_COLUMNS = [
    "name", "url", "price", "country", "region", "tags",
    "washing_station", "cooperative", "coordinates", "farmer_grower",
    "varieties", "processing", "altitude", "humidity", "density",
    "harvest_date", "arrival_date", "grade", "marks", "reference_id",
    "sca_cupping_score", "tariff_cost",
    "tasting_notes", "roasting_notes", "story",
    "image_url",
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

def build_record(listing: dict, detail: dict) -> dict:
    """Merge listing-page data with (possibly cached) detail-page data."""
    record = {col: "" for col in CSV_COLUMNS}
    record["name"] = listing["name"]
    record["url"] = listing["url"]
    record["price"] = listing["price"]
    record["country"] = listing.get("country", "")
    record["tags"] = listing.get("tags", "")
    record["image_url"] = listing.get("image_url", "")

    if not detail:
        return record

    specs = detail.get("specs", {})

    # Override country from specs if available (more reliable)
    if specs.get("Country"):
        record["country"] = specs["Country"]

    record["region"] = specs.get("Region", "")
    record["washing_station"] = specs.get("Washing Station", "")
    record["cooperative"] = specs.get("Cooperative", "")
    record["coordinates"] = specs.get("Coordinates", "")
    record["farmer_grower"] = specs.get("Farmer/Grower", "")
    record["varieties"] = specs.get("Varieties", "")
    record["processing"] = specs.get("Processing", "")
    record["altitude"] = specs.get("Altitude", "")
    record["humidity"] = specs.get("Humidity", "")
    record["density"] = specs.get("Density", "")
    record["harvest_date"] = specs.get("Harvest Date", "")
    record["arrival_date"] = specs.get("Arrival Date", "")
    record["grade"] = specs.get("Grade", "")
    record["marks"] = specs.get("Marks", "")
    record["reference_id"] = specs.get("Reference ID", "")
    record["sca_cupping_score"] = specs.get("SCA Cupping Score", "")
    record["tariff_cost"] = specs.get("Tariff Cost", "")

    record["tasting_notes"] = detail.get("tasting_notes", "")
    record["roasting_notes"] = detail.get("roasting_notes", "")
    record["story"] = detail.get("story", "")

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
    """Write docs/hacea-data.json with all coffees that have detail data."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Include all coffees that have a price
    priced = [r for r in records if r.get("price")]
    atomic_json(JSON_FILE, priced)
    log.info("Wrote %d coffees to %s", len(priced), JSON_FILE)


# ---------- Main ----------

def main():
    from shared_parser import run
    run("hacea", globals())


if __name__ == "__main__":
    main()
