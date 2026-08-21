"""Generate Climate Information v2.1 example JSON files from the EPW and DDY files
bundled (as zips) in ``examples/``, generate EPW and DDY *back* from the JSON using the
reverse converters, then run the test suite.

Everything uses local paths inside this repository: the EPW/DDY members are pulled
straight out of the ``*.zip`` archives in ``examples/`` into a temporary directory,
converted, and written to ``examples/generated/``. The curated, hand-built drafts in
``examples/`` are never overwritten.

    python tools/generate_examples.py
"""

import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Resolve the repo root explicitly from a .env file (REPO_ROOT) so the
# `tools` package is importable no matter where the script is invoked from.
load_dotenv()
REPO_ROOT = os.environ.get("REPO_ROOT") or str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO_ROOT)

from tools.ddy_to_json import convert_ddy, extract_member
from tools.epw_to_json import convert_epw
from tools.json_to_ddy import convert_json_to_ddy
from tools.json_to_epw import convert_json_to_epw

REPO = Path(REPO_ROOT)
EXAMPLES = REPO / "examples"
OUT_DIR = EXAMPLES / "generated"

# zip -> output basename
SOURCES = {
    "USA_IL_Chicago": EXAMPLES
    / "USA_IL_Chicago.OHare.Intl.AP.725300_TMYx.2011-2025.zip",
    "GBR_Scotland_Glasgow-Bishopton": EXAMPLES
    / "GBR_SCT_Glasgow.Bishopton.031340_TMYx.2011-2025.zip",
}

# Canonical station metadata to apply on import, overriding what the onebuilding
# EPW/DDY happen to carry. Chicago: ASHRAE WMO 725300 and elevation 205 m
# (the EPW/DDY report 201.8 m).
CANONICAL = {
    "USA_IL_Chicago": {"wmo_station_id": "725300", "elevation": 205.0},
}


def generate() -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        for base, zip_path in SOURCES.items():
            if not zip_path.exists():
                print(f"  skip {base}: {zip_path} not found")
                continue
            overrides = CANONICAL.get(base)
            epw = extract_member(zip_path, ".epw", tmp)
            ddy = extract_member(zip_path, ".ddy", tmp)

            # Forward: EPW/DDY -> JSON. The from-EPW example opts into the EPW-header
            # design conditions (off by default in epw_to_json) so it keeps
            # demonstrating the full design summary an EPW header can carry.
            epw_json = OUT_DIR / f"{base}-from-epw.v2.1.json"
            ddy_json = OUT_DIR / f"{base}-from-ddy.v2.1.json"
            convert_epw(
                epw, epw_json, location_overrides=overrides, epw_header_design=True
            )
            convert_ddy(ddy, ddy_json, location_overrides=overrides)

            # Reverse: each format is written from the JSON that actually feeds it. The
            # EPW-derived JSON is the richer one overall -- it alone carries the hourly
            # series -- but for a DDY it is the poorer source: an EPW header holds ASHRAE
            # columns P-CL only, so it has none of the monthly daily ranges or clear-sky
            # optical depths the design days need. Writing the DDY from the DDY-derived
            # JSON keeps those, and makes this a true DDY -> JSON -> DDY round-trip.
            epw_back = OUT_DIR / f"{base}-from-json.epw"
            ddy_back = OUT_DIR / f"{base}-from-json.ddy"
            convert_json_to_epw(epw_json, epw_back)
            convert_json_to_ddy(ddy_json, ddy_back)

            written += [epw_json, ddy_json, epw_back, ddy_back]
            for p in (epw_json, ddy_json, epw_back, ddy_back):
                print(f"  {p.name} ({p.stat().st_size // 1024} KB)")
    return written


def main() -> None:
    print("Generating examples (EPW/DDY -> JSON -> EPW/DDY) ...")
    generate()
    print("\nRunning tests ...")
    from tools.test_climate_helpers import _run_all

    _run_all()


if __name__ == "__main__":
    main()
