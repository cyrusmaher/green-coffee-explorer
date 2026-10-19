# Green Coffee Explorer parsers

The scheduled scrapers support Sweet Maria’s, Coffee Bean Corral, Hacea, Royal
Coffee, and Genuine Origin. The Shopify transport and current page adapters live
in the neighboring `coffee-explorer` repository under `scraper/catalog.py` and
`scraper/green.py`. This repository keeps its existing CSV/JSON schemas and pages.

## Run locally

Keep both repositories beside each other, or set `COFFEE_EXPLORER_ROOT` to the
coffee-explorer checkout. Update that checkout before running these entry points.
Install both repositories’ `scraper/requirements.txt` files and `pytest`.

```sh
python scraper/scrape.py
python scraper/scrape_cbc.py
python scraper/scrape_hacea.py
python scraper/scrape_royal.py
python scraper/scrape_genuineorigin.py
PYTHONPATH="$COFFEE_EXPLORER_ROOT" python -m pytest tests --import-mode=importlib -q
```

A full refresh needs no Gemini, NVIDIA, or browser credentials. Current product
specifications come from storefront HTML and Royal’s structured infographics.
Producer matches require explicit names and compatible countries; ambiguous
identities remain unmatched. The old optional Royal LLM utility remains available
for historical data, but is not part of scheduled refreshes.

## Publishing and migration

Deploy the shared parser changes to `cyrusmaher/coffee-explorer` **before** these
workflow changes. Workflows check out shared `main`, run both test suites, and
run all five sources in a single weekly workflow with sequential jobs and
independent failure reporting. Genuine Origin is included in that schedule. Chromium installation is no longer needed.

Product details are cached for at most 24 hours and invalidated when Shopify’s
`updated_at` changes. Old empty/legacy entries are fetched again. Errors, missing
pages, invalid prices, and empty or severely reduced outputs stop publication.
The first migration from old storefront URLs establishes a new count baseline:
Coffee Bean Corral’s current collection has fewer products than the old site.
Only available individual coffees are exported by the Shopify adapters; samples,
subscriptions and sampler bundles are excluded. Genuine Origin retains its
explicit stock flags for each coffee.

Existing HTML pages and data are not migrated automatically until a successful
scrape. To audit without changing published data, run the scrapers in a temporary
copy with `COFFEE_EXPLORER_ROOT` pointing to the shared checkout.
