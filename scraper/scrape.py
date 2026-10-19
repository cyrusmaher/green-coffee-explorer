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

BASE_URL = "https://www.sweetmarias.com"

# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
CACHE_FILE = DATA_DIR / "detail_cache.json"
CSV_FILE = DATA_DIR / "coffees.csv"
JSON_FILE = DOCS_DIR / "data.json"

# --- Country parsing from coffee name ---
COUNTRY_PREFIXES = [
    ("Papua New Guinea", "Papua New Guinea"),
    ("Costa Rica", "Costa Rica"),
    ("Brazil", "Brazil"),
    ("Colombia", "Colombia"),
    ("Ethiopia", "Ethiopia"),
    ("Flores", "Indonesia (Flores)"),
    ("Guatemala", "Guatemala"),
    ("Hawaii", "USA (Hawaii)"),
    ("Honduras", "Honduras"),
    ("Java", "Indonesia (Java)"),
    ("Kenya", "Kenya"),
    ("Nicaragua", "Nicaragua"),
    ("Peru", "Peru"),
    ("Rwanda", "Rwanda"),
    ("Sulawesi", "Indonesia (Sulawesi)"),
    ("Sumatra", "Indonesia (Sumatra)"),
    ("Zambia", "Zambia"),
    ("Bolivia", "Bolivia"), ("Burundi", "Burundi"), ("Ecuador", "Ecuador"),
    ("El Salvador", "El Salvador"), ("India", "India"), ("Mexico", "Mexico"),
    ("Panama", "Panama"), ("Tanzania", "Tanzania"), ("Uganda", "Uganda"),
    ("Yemen", "Yemen"),
]

COUNTRY_TO_ORIGIN_CATEGORY = {
    "Brazil": "South America",
    "Colombia": "South America",
    "Peru": "South America",
    "Nicaragua": "Central America",
    "Costa Rica": "Central America",
    "Guatemala": "Central America",
    "Honduras": "Central America",
    "Ethiopia": "Africa",
    "Kenya": "Africa",
    "Rwanda": "Africa",
    "Zambia": "Africa",
    "Indonesia (Flores)": "Indonesia & SE Asia",
    "Indonesia (Java)": "Indonesia & SE Asia",
    "Indonesia (Sulawesi)": "Indonesia & SE Asia",
    "Indonesia (Sumatra)": "Indonesia & SE Asia",
    "USA (Hawaii)": "North America",
    "Papua New Guinea": "Oceania",
}

NON_GEO_CATEGORIES = {"Decaf", "Sample Sets", "Sweet Maria's Blends", "Roasted Coffee"}

# --- Score categories ---
CUPPING_CATEGORIES = [
    "Dry Fragrance", "Wet Aroma", "Brightness", "Flavor", "Body",
    "Finish", "Sweetness", "Clean Cup", "Complexity", "Uniformity",
]

FLAVOR_CATEGORIES = [
    "Floral", "Honey", "Sugars", "Caramel", "Fruits", "Citrus",
    "Berry", "Cocoa", "Nuts", "Rustic", "Spice", "Flavor Body",
]

CSV_COLUMNS = [
    "name", "url", "price", "country", "region", "origin_category",
    "total_score", "cupper_correction",
    *[f"cupping_{c.lower().replace(' ', '_')}" for c in CUPPING_CATEGORIES],
    *[f"flavor_{c.lower().replace(' ', '_')}" for c in FLAVOR_CATEGORIES],
    "process_method", "cultivar", "cultivar_detail", "farm_gate",
    "processing", "drying_method", "arrival_date", "lot_size", "bag_size",
    "packaging", "grade", "appearance", "roast_recommendations", "type",
    "recommended_for_espresso",
    "short_description", "full_cupping_notes", "farm_notes",
    # Watchlist matching
    *WATCHLIST_FIELDS,
]


def parse_country(name: str) -> str:
    for prefix, country in COUNTRY_PREFIXES:
        if name.casefold().startswith(prefix.casefold()):
            return country
    return ""


def fix_origin_category(origin_category: str, country: str) -> str:
    if origin_category in NON_GEO_CATEGORIES and country:
        return COUNTRY_TO_ORIGIN_CATEGORY.get(country, origin_category)
    return origin_category


def parse_chart_value(data_str: str) -> dict[str, str]:
    result = {}
    if not data_str:
        return result
    for pair in data_str.split(","):
        parts = pair.split(":", 1)
        if len(parts) == 2:
            result[parts[0].strip()] = parts[1].strip()
    return result


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
    record["country"] = parse_country(listing["name"])
    record["origin_category"] = fix_origin_category(
        listing["origin_category"], record["country"]
    )

    if not detail:
        return record

    record["short_description"] = detail.get("short_description", "")
    record["total_score"] = detail.get("total_score", "") or detail.get("cupping_score", "")
    record["cupper_correction"] = detail.get("cupper_correction", "")
    record["full_cupping_notes"] = detail.get("full_cupping_notes", "")
    record["farm_notes"] = detail.get("farm_notes", "")

    # Cupping scores
    cupping = parse_chart_value(detail.get("cupping_values", ""))
    for cat in CUPPING_CATEGORIES:
        col = f"cupping_{cat.lower().replace(' ', '_')}"
        record[col] = cupping.get(cat, "")

    # Flavor scores
    flavor = parse_chart_value(detail.get("flavor_values", ""))
    for cat in FLAVOR_CATEGORIES:
        source_key = cat if cat != "Flavor Body" else "Body"
        col = f"flavor_{cat.lower().replace(' ', '_')}"
        record[col] = flavor.get(source_key, "")

    # Overview attrs
    ov = detail.get("overview_attrs", {})
    record["process_method"] = ov.get("Process Method", "")
    record["cultivar"] = ov.get("Cultivar", "")
    record["farm_gate"] = ov.get("Farm Gate", "")

    # Specs
    specs = detail.get("specs", {})
    record["region"] = specs.get("Region", "")
    record["processing"] = specs.get("Processing", "")
    record["drying_method"] = specs.get("Drying Method", "")
    record["arrival_date"] = specs.get("Arrival date", "")
    record["lot_size"] = specs.get("Lot size", "")
    record["bag_size"] = specs.get("Bag size", "")
    record["packaging"] = specs.get("Packaging", "")
    record["cultivar_detail"] = specs.get("Cultivar Detail", "")
    record["grade"] = specs.get("Grade", "")
    record["appearance"] = specs.get("Appearance", "")
    record["roast_recommendations"] = specs.get("Roast Recommendations", "")
    record["type"] = specs.get("Type", "")
    record["recommended_for_espresso"] = specs.get("Recommended for Espresso", "")

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
    """Write docs/data.json filtered to coffees that have a price."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    priced = [r for r in records if r.get("price") and r["price"].startswith("$")]
    atomic_json(JSON_FILE, priced)
    log.info("Wrote %d priced coffees to %s", len(priced), JSON_FILE)


# ---------- Main ----------

def main():
    from shared_parser import run
    run("sweetmarias", globals())


if __name__ == "__main__":
    main()
