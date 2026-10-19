"""Load the shared parsers from a neighboring checkout (local or CI)."""
import os
from pathlib import Path
import sys

SHARED_ROOT = Path(os.environ.get(
    "COFFEE_EXPLORER_ROOT",
    str(Path(__file__).resolve().parents[2] / "coffee-explorer"),
)).resolve()
if not (SHARED_ROOT / "scraper" / "green.py").exists():
    raise RuntimeError(
        "The shared coffee-explorer checkout is missing or outdated. "
        "Set COFFEE_EXPLORER_ROOT to its location; see README.md."
    )
sys.path.insert(0, str(SHARED_ROOT))
from scraper.green import run_green


def run(source, legacy):
    return run_green(source, legacy)
