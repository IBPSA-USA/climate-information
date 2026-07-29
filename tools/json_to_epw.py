"""Translate a Climate Information v2.1 JSON document back into an EnergyPlus
Weather (EPW) file. This is the inverse of ``tools/epw_to_json.py``.

What is reconstructed:
  * ``LOCATION`` line          <- the ``location`` group
  * ``DESIGN CONDITIONS`` line <- the annual ``summary_data`` (ASHRAE columns P–CL)
  * hourly data records        <- ``time_series_data_sets[0].time_series``; base-SI
                                  values are converted back to EPW units and ``null``
                                  becomes the EPW missing-value sentinel again.

Limitations (inherent to the data model, see docs/ashrae_dd_gap_analysis.md):
  * Quantities the model deliberately drops (humidity ratio, wind shelter factor,
    n-year return periods) come back **blank** in the DESIGN CONDITIONS line.
  * EPW fields the schema has no home for (extraterrestrial radiation, zenith
    luminance, visibility, ceiling height, present weather, …) are written with their
    EPW missing-value sentinels. The other EPW header blocks (TYPICAL/EXTREME PERIODS,
    GROUND TEMPERATURES) are emitted empty.
  * The calendar is a single non-leap year (TMYx month-of-different-years detail is not
    in the JSON), which is harmless because the importer keys time off the
    ``regular_interval`` rather than the date columns.

Usage::

    from tools.json_to_epw import convert_json_to_epw, climate_information_to_epw
    convert_json_to_epw("in.json", "out.epw")
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Resolve the repo root explicitly from a .env file (REPO_ROOT) so the
# `tools` package is importable no matter where the script is invoked from.
load_dotenv()
REPO_ROOT = os.environ.get("REPO_ROOT") or str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO_ROOT)

from tools.climate_common import summary_data_to_ashrae_cols
from tools.epw_to_json import (
    _COOLING_COLS,
    _EXTREMES_COLS,
    _HEATING_COLS,
    EPW_FIELDS,
    json_value_to_epw,
)

# Columns that are whole numbers in the design line (month indices, wind directions).
_INT_DESIGN_COLS = {"P", "AF", "AD", "AU"}

# Days before the start of each month in a non-leap year.
_DAYS_BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]

# Placeholder data-source/uncertainty flag string (EPW field 6).
_FLAGS = "?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9"


def _fmt_design(value) -> str:
    if value is None:
        return ""
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    return f"{value:g}"


def build_location_line(location: dict) -> str:
    city = location.get("name", "").split(",")[0].strip()
    state = location.get("subdivision", "") or ""
    country = location.get("country_code", "") or ""
    source = location.get("data_source", "SRC-Generated") or "SRC-Generated"
    wmo = location.get("wmo_station_id", "") or ""
    fields = [
        "LOCATION",
        city,
        state,
        country,
        source,
        wmo,
        f"{location['latitude']:.5f}",
        f"{location['longitude']:.5f}",
        f"{location['time_zone_offset']:.1f}",
        f"{location['elevation']:.1f}",
    ]
    return ",".join(str(f) for f in fields)


def build_design_conditions_line(summary: dict) -> str:
    cols = summary_data_to_ashrae_cols(summary)

    def section(columns):
        return [_fmt_design(cols.get(c)) for c in columns]

    parts = [
        "DESIGN CONDITIONS",
        "1",
        "2025 ASHRAE Handbook -- Fundamentals - Chapter 14 Climatic Design Information",
        "Heating",
        *section(_HEATING_COLS),
        "Cooling",
        *section(_COOLING_COLS),
        "Extremes",
        *section(_EXTREMES_COLS),
    ]
    return ",".join(parts)


def _month_day(day_of_year: int) -> tuple[int, int]:
    """day_of_year is 1..365 -> (month, day) in a non-leap year."""
    for m in range(12, 0, -1):
        if day_of_year > _DAYS_BEFORE_MONTH[m - 1]:
            return m, day_of_year - _DAYS_BEFORE_MONTH[m - 1]
    return 1, 1


def _fmt_value(v) -> str:
    return f"{v:g}"


def build_data_records(doc: dict) -> list[str]:
    tsds = doc.get("time_series_data_sets")
    if not tsds:
        return []
    series = tsds[0].get("time_series", {})
    interval = tsds[0].get("time_intervals", [{}])[0]
    start_time = interval.get("starting_time", "2020-01-01T01:00:00")
    year = int(str(start_time)[:4])

    lengths = [len(v.get("values", [])) for v in series.values()]
    n = max(lengths) if lengths else 0

    rows = []
    for i in range(n):
        doy = i // 24 + 1
        hour = i % 24 + 1
        month, day = _month_day(doy)
        record = [str(year), str(month), str(day), str(hour), "0", _FLAGS]
        # fields 6..34
        for fld in EPW_FIELDS[6:]:
            if fld.variable and fld.variable in series:
                values = series[fld.variable]["values"]
                value = values[i] if i < len(values) else None
                raw = json_value_to_epw(fld, value)
            elif fld.variable:
                raw = fld.missing  # mapped field, but absent in this document
            else:
                raw = _UNMAPPED_FILL[fld.index]  # field with no schema home
            record.append(_fmt_value(raw) if isinstance(raw, float) else str(raw))
        rows.append(",".join(record))
    return rows


# Fill values for EPW fields with no schema representation (their missing sentinels).
_UNMAPPED_FILL = {
    10: 9999,
    11: 9999,  # extraterrestrial radiation
    19: 9999,  # zenith luminance
    24: 9999,  # visibility
    25: 99999,  # ceiling height
    26: 9,  # present weather observation
    27: 999999999,  # present weather codes
    31: 99,  # days since last snowfall
    34: 99,  # liquid precipitation quantity
}


def climate_information_to_epw(doc: dict) -> str:
    location = doc["location"]
    summary = {}
    if doc.get("summary_data_sets"):
        summary = doc["summary_data_sets"][0].get("summary_data", {})

    header = [
        build_location_line(location),
        build_design_conditions_line(summary) if summary else "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,Generated by tools/json_to_epw.py from a Climate Information v2.1 document.",
        "COMMENTS 2,Design conditions from ASHRAE HOF 2025; unmodeled EPW fields carry "
        "EPW missing-value sentinels.",
        "DATA PERIODS,1,1,Data,Sunday,1/ 1,12/31",
    ]
    return "\n".join(header + build_data_records(doc)) + "\n"


def convert_json_to_epw(json_path, out_path) -> str:
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    text = climate_information_to_epw(doc)
    Path(out_path).write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Convert Climate Information v2.1 JSON to an EPW file"
    )
    ap.add_argument("json")
    ap.add_argument("out")
    args = ap.parse_args()
    convert_json_to_epw(args.json, args.out)
    print(f"Wrote {args.out}")
