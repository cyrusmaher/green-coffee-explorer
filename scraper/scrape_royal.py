"""Green coffee output adapter. Live storefront parsing is in coffee-explorer/scraper/green.py."""

import csv
import json
import logging
import re
import sys
from pathlib import Path


from match_watchlist import WATCHLIST_FIELDS, match_products
from scraper.storage import write_json as atomic_json

# Allow importing extract_royal from same directory
_SCRAPER_DIR = Path(__file__).resolve().parent
if str(_SCRAPER_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

BASE_URL = "https://royalcoffee.com"

# Paths relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
CACHE_FILE = DATA_DIR / "royal_detail_cache.json"
INFOGRAM_CACHE_FILE = DATA_DIR / "royal_infogram_cache.json"
CSV_FILE = DATA_DIR / "royal_coffees.csv"
JSON_FILE = DOCS_DIR / "royal-data.json"

CSV_COLUMNS = [
    "name", "url", "price_per_lb", "total_price", "bag_size", "bag_type",
    "country", "region", "altitude", "grower", "variety", "process",
    "flavor_notes", "about", "warehouse", "position", "certifications",
    "is_staff_pick", "inventory",
    # Tab text content
    "overview_text", "taste_text", "source_text",
    # Infogram data
    "word_cloud", "sweetness", "acidity", "viscosity", "balance",
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


def load_infogram_cache() -> dict:
    if INFOGRAM_CACHE_FILE.exists():
        try:
            return json.loads(INFOGRAM_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load infogram cache (%s), starting fresh", e)
    return {}


def save_infogram_cache(cache: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(INFOGRAM_CACHE_FILE, cache)


def _extract_text_entity(props: dict) -> str:
    """Extract text content from an Infogram TEXT entity's props."""
    try:
        text_blocks = props.get("content", {}).get("blocks", [])
        text = ""
        for tb in text_blocks:
            text += tb.get("text", "")
        return text.strip()
    except (AttributeError, TypeError):
        return ""


def _parse_infogram(data: dict) -> dict:
    """Parse infographicData JSON for word cloud terms and gauge values."""
    try:
        content = data["elements"]["content"]["content"]
        entities = content["entities"]
    except (KeyError, TypeError):
        return {}

    # Get ordered entity IDs from blocks
    blocks = content.get("blocks", {})
    ordered_ids = []
    for block_key in sorted(blocks.keys(), key=str):
        block_entities = blocks[block_key].get("entities", [])
        ordered_ids.extend(block_entities)

    word_cloud = {}
    gauges = []
    text_queue = []

    for eid in ordered_ids:
        entity = entities.get(str(eid)) or entities.get(eid)
        if not entity:
            continue

        etype = entity.get("type", "")
        props = entity.get("props", {})

        if etype == "CHART":
            chart_data_obj = props.get("chartData") or {}
            chart_type = chart_data_obj.get("chart_type_nr")
            chart_data = chart_data_obj.get("data", [[]])
            rows = chart_data[0] if chart_data else []

            if chart_type == 18:  # Word Cloud
                for row in rows[1:]:  # skip header
                    if len(row) >= 2 and row[0] and row[1]:
                        term = (row[0].get("value") or "").strip()
                        weight_str = (row[1].get("value") or "0").strip()
                        if term:
                            try:
                                word_cloud[term] = int(weight_str)
                            except ValueError:
                                word_cloud[term] = 1

            elif chart_type == 5:  # Gauge
                value = None
                for row in rows:
                    if (len(row) >= 2 and row[0]
                            and row[0].get("value") == "Value" and row[1]):
                        try:
                            value = int(float(row[1]["value"]))
                        except (ValueError, TypeError):
                            pass
                        break
                if value is not None and text_queue:
                    gauges.append({"label": text_queue[-1].lower(), "value": value})
                text_queue = []

        elif etype == "TEXT":
            text = _extract_text_entity(props)
            if text:
                text_queue.append(text)

    result = {}
    if word_cloud:
        result["word_cloud"] = word_cloud

    for g in gauges:
        label = g["label"]
        if "sweet" in label:
            result["sweetness"] = g["value"]
        elif "acid" in label:
            result["acidity"] = g["value"]
        elif "viscos" in label:
            result["viscosity"] = g["value"]
        elif "balanc" in label:
            result["balance"] = g["value"]

    return result


# ---------- Staff picks ----------


# Using raw string (r"""...""") so JS regex backslashes pass through correctly.


# ---------- Record building ----------

def parse_price(s: str) -> str:
    """Clean a price string to a numeric value."""
    if not s:
        return ""
    s = s.replace(",", "").replace("$", "").strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return ""


def compute_price_per_lb(total_price: str, weight_lbs: str) -> str:
    """Calculate price per pound from total price and weight."""
    try:
        total = float(total_price)
        weight = float(weight_lbs)
        if weight > 0:
            return f"{total / weight:.2f}"
    except (ValueError, TypeError):
        pass
    return ""


# Known coffee-producing countries for title-based extraction
COFFEE_COUNTRIES = [
    "Ethiopia", "Kenya", "Colombia", "Brazil", "Guatemala", "Costa Rica",
    "Honduras", "El Salvador", "Nicaragua", "Mexico", "Peru", "Bolivia",
    "Ecuador", "Panama", "Jamaica", "Haiti", "Dominican Republic",
    "Rwanda", "Burundi", "Tanzania", "Uganda", "DR Congo", "Congo",
    "Malawi", "Zambia", "Zimbabwe", "Cameroon",
    "Indonesia", "Sumatra", "Java", "Bali", "Sulawesi", "Papua New Guinea",
    "India", "Vietnam", "Myanmar", "Thailand", "Laos", "China", "Yemen",
    "Nepal", "Philippines", "East Timor", "Timor-Leste",
    "Hawaii", "Puerto Rico",
]


def extract_country_from_title(title: str) -> str:
    """Try to find a coffee-producing country in the product title."""
    for country in COFFEE_COUNTRIES:
        if country.lower() in title.lower():
            return country
    return ""


def build_record(
    listing: dict, detail: dict, staff_pick_urls: set,
    infogram_data: dict | None = None, llm_data=None,
) -> dict:
    """Merge listing data with detail-page + infogram + LLM data into a flat record."""
    record = {col: "" for col in CSV_COLUMNS}
    url = listing["url"]
    record["url"] = url
    # Bag type: prefer listing source, but use JSON-LD category as authoritative override
    bag_type = listing.get("bag_type", "")
    jsonld_cat = detail.get("jsonld_category", "") if detail else ""
    if "Crown Jewel" in jsonld_cat:
        bag_type = "Crown Jewel"
    elif "Royal Gem" in jsonld_cat or "50 lb" in jsonld_cat:
        bag_type = "Royal Gem"
    elif "Full Size" in jsonld_cat:
        bag_type = "Full Bag"
    record["bag_type"] = bag_type
    record["is_staff_pick"] = "Yes" if url in staff_pick_urls else ""

    if not detail:
        return record

    # Name: prefer clean h1 title over JSON-LD (which has suffixes)
    record["name"] = detail.get("title", "") or detail.get("jsonld_name", "")

    # Total price from JSON-LD
    total_price = parse_price(detail.get("jsonld_price", ""))
    record["total_price"] = f"${total_price}" if total_price else ""

    # Weight / bag size from JSON-LD
    weight = detail.get("jsonld_weight", "")
    weight_unit = detail.get("jsonld_weight_unit", "")
    if weight:
        record["bag_size"] = f"{weight} lb" if weight_unit == "LBR" else f"{weight} {weight_unit}"

    # Price per lb: try page text first, then compute from total/weight
    # Skip pricing entirely for quote-only products
    if detail.get("is_quote_only"):
        ppl_text = ""
        ppb_text = ""
        has_visible_price = False
    else:
        # Only use JSON-LD price as fallback if the page shows a visible price
        # (products with only "Get a Quote" have JSON-LD prices but no visible pricing)
        ppl_text = parse_price(detail.get("price_per_lb_text", ""))
        ppb_text = detail.get("price_per_box_text", "")
        has_visible_price = bool(ppl_text or ppb_text)

    if ppl_text:
        record["price_per_lb"] = f"${ppl_text}"
    elif has_visible_price and total_price and weight:
        computed = compute_price_per_lb(total_price, weight)
        if computed:
            record["price_per_lb"] = f"${computed}"

    # For Crown Jewels/Royal Gems: compute from box price / weight
    if not record["price_per_lb"] and ppb_text and weight:
        box_price = parse_price(ppb_text)
        if box_price:
            computed = compute_price_per_lb(box_price, weight)
            if computed:
                record["price_per_lb"] = f"${computed}"

    # Structured fields from page text regex
    record["region"] = detail.get("region", "")
    record["altitude"] = detail.get("altitude", "")
    record["grower"] = detail.get("grower", "")
    record["variety"] = detail.get("variety", "")
    record["process"] = detail.get("process", "")
    record["warehouse"] = detail.get("warehouse", "")
    record["certifications"] = detail.get("certifications", "")
    record["position"] = detail.get("position", "")
    record["inventory"] = detail.get("inventory", "")

    # Country: try to extract from title or region
    name = record["name"]
    jsonld_name = detail.get("jsonld_name", "")
    record["country"] = (
        extract_country_from_title(name)
        or extract_country_from_title(jsonld_name)
        or extract_country_from_title(record["region"])
    )

    # Flavor notes
    record["flavor_notes"] = detail.get("flavor_text", "")

    # About text: pick from tab panes
    # For Full Bags: pane[0] has specs (Grower/Altitude/etc), pane[1] has about text
    # For Crown Jewels: pane[0] has Overview (the about text)
    pane_texts = detail.get("pane_texts", [])
    about_text = ""
    for pane in pane_texts:
        # Skip panes that are just the specs section (start with "Grower\n")
        if pane.strip().startswith("Grower"):
            continue
        # Skip very short panes
        if len(pane) < 50:
            continue
        # Use the first substantial non-specs pane as the about text
        about_text = pane.strip()
        break
    record["about"] = about_text

    # Tab-specific texts (matched by prefix, not index)
    for pane in pane_texts:
        stripped = pane.strip()
        if stripped.startswith("Overview") and not record["overview_text"]:
            record["overview_text"] = stripped
        elif stripped.startswith("Taste") and not record["taste_text"]:
            record["taste_text"] = stripped
        elif stripped.startswith("Source") and not record["source_text"]:
            record["source_text"] = stripped

    # Infogram data (word cloud + gauges)
    if infogram_data:
        wc = infogram_data.get("word_cloud")
        if wc:
            record["word_cloud"] = wc  # dict; serialized to JSON string in write_csv
        for gauge_field in ("sweetness", "acidity", "viscosity", "balance"):
            if gauge_field in infogram_data:
                record[gauge_field] = str(infogram_data[gauge_field])

    # LLM-extracted fields as fallback for empty regex results
    if llm_data:
        if not record["region"] and llm_data.region:
            record["region"] = llm_data.region
        if not record["altitude"] and llm_data.altitude:
            record["altitude"] = llm_data.altitude
        if not record["variety"] and llm_data.variety:
            record["variety"] = ", ".join(llm_data.variety)
        if not record["process"] and llm_data.process:
            record["process"] = llm_data.process
        if not record["grower"] and llm_data.grower:
            record["grower"] = llm_data.grower

    return record


# ---------- Output writers ----------

def write_csv(records: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_records = []
    for r in records:
        row = dict(r)
        # Serialize dict/list fields to JSON strings for CSV
        if isinstance(row.get("word_cloud"), dict):
            row["word_cloud"] = json.dumps(row["word_cloud"], ensure_ascii=False)
        csv_records.append(row)
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_records)
    log.info("Wrote %d coffees to %s", len(records), CSV_FILE)


def write_json(records: list[dict]) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    # Selection, identity, and price checks run before either output is written.
    atomic_json(JSON_FILE, records)
    log.info("Wrote %d coffees to %s", len(records), JSON_FILE)



# ---------- Main ----------

def main():
    from shared_parser import run
    run("royal", globals())


if __name__ == "__main__":
    main()
