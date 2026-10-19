"""
Scraper for Genuine Origin (genuineorigin.com) green coffee listings.

Genuine Origin runs on SuiteCommerce (NetSuite), which exposes a JSON items API
that returns listing + detail fields in a single call — no browser needed.
The API gives us rich fields including SCA cupping score, variety, altitude,
processing, flavor/body/acidity descriptors, producer, and harvest schedule.

Outputs:
  - data/genuineorigin_coffees.csv       Full dataset
  - docs/genuineorigin-data.json         For GitHub Pages
"""

import csv
import json
import logging
import math
import re
import sys
import time
from html import unescape
from pathlib import Path


# Allow importing match_watchlist from same directory
_SCRAPER_DIR = Path(__file__).resolve().parent
if str(_SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_DIR))

from match_watchlist import WATCHLIST_FIELDS, match_products
from scraper.storage import write_json as atomic_json
from scraper.catalog import CatalogError, get
from scraper.green import validate_publication

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

BASE_URL = "https://www.genuineorigin.com"
API_URL = f"{BASE_URL}/api/items"
# The API caps limit at 100; we paginate via offset.
PAGE_SIZE = 100

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
CSV_FILE = DATA_DIR / "genuineorigin_coffees.csv"
JSON_FILE = DOCS_DIR / "genuineorigin-data.json"

CSV_COLUMNS = [
    "name", "url", "price", "price_per_pound", "box_price",
    "country", "region", "producer", "varieties", "processing",
    "altitude", "harvest_date", "sca_cupping_score",
    "body", "acidity", "flavor_notes",
    "coffee_type", "package_sizes", "reference_id", "factsheet_url",
    "in_stock",
    "tasting_notes", "story",
    "image_url",
    *WATCHLIST_FIELDS,
]


# ---------- API fetching ----------

def fetch_all_items() -> list[dict]:
    """Fetch all green coffee items from the SuiteCommerce JSON API."""
    all_items: list[dict] = []
    offset = 0
    total = None
    seen = set()

    while True:
        params = {
            "N": "0",  # ignored but required
            "country": "US",
            "currency": "USD",
            "language": "en",
            "pricelevel": "5",
            "use_pcv": "T",
            "fieldset": "details",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        log.info("Fetching items offset=%d limit=%d", offset, PAGE_SIZE)
        resp = get(API_URL, params=params)
        try:
            data = resp.json()
        finally:
            resp.close()

        items = data.get("items")
        if not isinstance(items, list):
            raise CatalogError("Genuine Origin response is missing items")
        for item in items:
            key = item.get("internalid")
            if key is None or key in seen:
                raise CatalogError("Genuine Origin returned repeated or malformed items")
            seen.add(key)
        if total is None:
            total = data.get("total")
            log.info("API reports %s total items", total)
        all_items.extend(items)

        if len(items) < PAGE_SIZE:
            if total is not None and len(all_items) < total:
                raise CatalogError("Genuine Origin catalog ended before its reported total")
            break
        if total is not None and len(all_items) >= total:
            break
        if offset >= 10000:
            raise CatalogError("Genuine Origin exceeded pagination limit")
        offset += PAGE_SIZE
        time.sleep(0.5)  # polite delay

    log.info("Fetched %d items total", len(all_items))
    return all_items


# ---------- Helpers ----------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def format_price(value) -> str:
    """Format a numeric price as '$X.XX'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    return f"${f:.2f}" if math.isfinite(f) and f > 0 else ""


def format_price_per_pound(value) -> str:
    """Format per-lb price as '$X.XX/lb'."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    return f"${f:.2f}/lb" if math.isfinite(f) and f > 0 else ""


def extract_box_price(item: dict) -> str:
    """Find the price of the smallest full-box variant (e.g. '65lb box')."""
    for child in item.get("matrixchilditems_detail", []) or []:
        if child.get("custitem_go_matrix_package") == "65lb box":
            price = child.get("pricelevel5") or child.get("onlinecustomerprice")
            return format_price(price)
    # Fallback: main item price
    return format_price(
        item.get("pricelevel5") or item.get("onlinecustomerprice")
    )


def package_sizes(item: dict) -> str:
    """Comma-separated list of available package sizes (in-stock only)."""
    seen = []
    for child in item.get("matrixchilditems_detail", []) or []:
        pkg = child.get("custitem_go_matrix_package") or ""
        if child.get("isinstock") and pkg and pkg not in seen:
            seen.append(pkg)
    return ", ".join(seen)


# ---------- Record building ----------

def build_record(item: dict) -> dict:
    """Convert a raw API item into our flat CSV record."""
    record = {col: "" for col in CSV_COLUMNS}

    # Names / URL
    name = (
        item.get("storedisplayname2")
        or item.get("custitem_coffee_name")
        or item.get("displayname")
        or ""
    )
    record["name"] = name.strip()
    url_slug = item.get("urlcomponent") or ""
    record["url"] = f"{BASE_URL}/{url_slug}" if url_slug else BASE_URL

    # Pricing — use price-per-pound as the primary comparable price
    ppp_raw = item.get("custitem_price_per_pound")
    record["price_per_pound"] = format_price_per_pound(ppp_raw)
    record["price"] = record["price_per_pound"]  # drives table sort/display
    record["box_price"] = extract_box_price(item)

    # Origin
    record["country"] = (item.get("custitemorigin") or "").strip()
    record["region"] = (item.get("custitem2") or "").strip()
    record["producer"] = (item.get("custitem_go_producer") or "").strip()
    record["varieties"] = (item.get("custitem_go_variety") or "").strip()
    record["processing"] = (item.get("custitem_go_processing") or "").strip()
    record["altitude"] = (item.get("custitem_go_altitude") or "").strip()
    record["harvest_date"] = (item.get("custitem_go_harvestsched") or "").strip()

    # Cupping
    cup = item.get("custitem_go_cuppingscore")
    if cup not in (None, "", 0, "0"):
        try:
            record["sca_cupping_score"] = f"{float(cup):.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            record["sca_cupping_score"] = str(cup)
    record["body"] = (item.get("custitem_go_bodywebtext") or "").strip()
    record["acidity"] = (item.get("custitem_go_aciditywebtext") or "").strip()
    record["flavor_notes"] = (item.get("custitem_go_flavorwebtext") or "").strip()

    # Misc
    record["coffee_type"] = (item.get("custitem_coffeetype") or "").strip()
    record["package_sizes"] = package_sizes(item)
    record["reference_id"] = (item.get("itemid") or "").strip()
    factsheet = item.get("custitem_go_pdfbrochure") or ""
    if factsheet:
        record["factsheet_url"] = (
            factsheet if factsheet.startswith("http") else f"{BASE_URL}{factsheet}"
        )
    record["in_stock"] = "Yes" if item.get("isinstock") else "No"

    # Narrative content — flavor notes double as tasting notes
    record["tasting_notes"] = record["flavor_notes"]
    record["story"] = html_to_text(item.get("storedetaileddescription", ""))

    # Image
    imgs = (item.get("itemimages_detail") or {}).get("urls") or []
    if imgs:
        record["image_url"] = imgs[0].get("url", "")

    return record


# ---------- Output ----------

def write_csv(records: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    log.info("Wrote %d coffees to %s", len(records), CSV_FILE)


def write_json(records: list[dict]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(JSON_FILE, records)
    log.info("Wrote %d coffees to %s", len(records), JSON_FILE)


# ---------- Main ----------

def main():
    items = fetch_all_items()
    if not items:
        log.error("No items returned from API. Exiting.")
        sys.exit(1)

    records = [build_record(it) for it in items
               if it.get("custitemorigin") and it.get("urlcomponent")]
    validate_publication(records, JSON_FILE)

    # Watchlist producer matching
    match_products(records, corpus_fields=[
        "name", "country", "region", "producer", "story",
    ])

    write_csv(records)
    write_json(records)

    log.info("Done. %d total coffees.", len(records))


if __name__ == "__main__":
    main()
