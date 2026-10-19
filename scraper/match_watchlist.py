"""Match explicit producer/farm identities using the shared, country-aware matcher.

No paid inference is required for a green-coffee refresh. Ambiguous or absent
identities remain unmatched; they are never cached as model rejections.
"""
import csv
import logging
from pathlib import Path
from types import SimpleNamespace

from shared_parser import SHARED_ROOT
from scraper.match import _direct_match

log = logging.getLogger(__name__)
WATCHLIST_FILE = Path(__file__).resolve().parent.parent / "data" / "producer_watchlist.csv"
if not WATCHLIST_FILE.exists():
    WATCHLIST_FILE = SHARED_ROOT / "data" / "producer_watchlist.csv"

WATCHLIST_FIELDS = [
    "watchlist_match", "watchlist_farm", "watchlist_tier", "watchlist_credential_type",
    "watchlist_credential_detail", "watchlist_notes", "watchlist_url",
]


def load_watchlist():
    with WATCHLIST_FILE.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError("Producer watchlist is empty")
    return rows


def build_watchlist_ref(watchlist):
    return "\n".join(f"- {p['producer_name']} ({p.get('farm_or_station', '')})" for p in watchlist)


def match_products(records, corpus_fields):
    watchlist = load_watchlist()
    columns = ["producer_name", "farm_or_station", "tier", "credential_type",
               "credential_detail", "notes", "direct_sales_url"]
    for record in records:
        product = SimpleNamespace(
            title=record.get("name", ""),
            producer_or_farm=" ".join(str(record.get(field) or "") for field in corpus_fields if field != "country"),
            origin_country=record.get("country", ""),
        )
        row = _direct_match(product, watchlist) or {}
        for field, column in zip(WATCHLIST_FIELDS, columns):
            record[field] = row.get(column, "")
        record["watchlist_match"] = row.get("producer_name") or row.get("farm_or_station", "")
    log.info("Explicit watchlist matches: %d/%d", sum(bool(r['watchlist_match']) for r in records), len(records))
