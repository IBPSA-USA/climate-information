"""Translate an EnergyPlus design-day (DDY) file into a Climate Information v2.1
JSON document (schema: ``schema/ClimateInformation.schema.yaml``).

A DDY file carries the ASHRAE HOF 2025 design conditions in two forms:
  * a ``Site:Location`` object             -> the ``location`` group
  * ``SizingPeriod:DesignDay`` objects and -> a ``summary_data_sets`` entry
    leading ``!`` comment lines

Each annual ``SizingPeriod:DesignDay`` encodes one ASHRAE design point as a maximum
dry-bulb temperature plus a coincident humidity value; the comment block carries the
extreme-annual statistics, the heating wind speed/direction and the coldest/hottest
month. We map every value back to its ASHRAE spreadsheet column letter and reuse
``tools.climate_common.build_summary_data`` (shared with the EPW reader) to emit the
schema-shaped summary in base SI units.

The DDY does *not* contain the extreme-max wet-bulb (BK), the standard deviations of
the extreme annual values (BQ/BR/CC/CD), or any hourly time series, so those are simply
absent from the output. (The enthalpy magnitudes BE/BG/BI *are* present — in the
design days' ``Enthalpy at Maximum Dry-Bulb`` field.)
"""

import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Resolve the repo root explicitly from a .env file (REPO_ROOT) so the
# `tools` package is importable no matter where the script is invoked from.
load_dotenv()
REPO_ROOT = os.environ.get("REPO_ROOT") or str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO_ROOT)

from tools.climate_common import (
    DESIGN_DAY_RANGE_VARS,
    OPTICAL_DEPTH_VARS,
    as_timestamp,
    build_metadata,
    build_monthly_summary_data,
    build_summary_data,
    resolve_weather_inputs,
)
from tools.epw_to_json import build_climate_document

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ],
        start=1,
    )
}

# (suffix after "Condns ") -> mapping of percentile-string -> (maxdb_col, humval_col)
# maxdb_col receives field[5] (Maximum Dry-Bulb), humval_col (if not None) receives
# field[10] (the coincident wet-bulb / dew-point value).
_HEATING_DB = {"99.6": ("Q", None), "99": ("R", None)}
_HUMIDIFICATION = {"99.6": ("U", "S"), "99": ("X", "V")}
# The WS=>MCDB days also carry the coldest-month design wind speed itself (field 16),
# which is ASHRAE column Y (0.4%, named "99.6%" here) / AA (1%, named "99%").
_HEATING_WIND = {"99.6": ("Z", None, "Y"), "99": ("AB", None, "AA")}
_COOLING_DB = {".4": ("AH", "AI"), "1": ("AJ", "AK"), "2": ("AL", "AM")}
_EVAPORATION = {".4": ("AO", "AN"), "1": ("AQ", "AP"), "2": ("AS", "AR")}
_DEHUMIDIFICATION = {".4": ("AX", "AV"), "1": ("BA", "AY"), "2": ("BD", "BB")}
_ENTHALPY = {".4": ("BF", None), "1": ("BH", None), "2": ("BJ", None)}

_SUFFIX_DISPATCH = {
    "DB": _HEATING_DB,
    "DP=>MCDB": _HUMIDIFICATION,
    "WS=>MCDB": _HEATING_WIND,
    "DB=>MWB": _COOLING_DB,
    "WB=>MDB": _EVAPORATION,
    "DP=>MDB": _DEHUMIDIFICATION,
    "Enth=>MDB": _ENTHALPY,
}


# --------------------------------------------------------------------------- #
# IDF parsing
# --------------------------------------------------------------------------- #


def parse_idf_objects(text: str) -> list[list[str]]:
    """Split EnergyPlus IDF text into objects (comments stripped)."""
    code = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
    objects = []
    for chunk in code.split(";"):
        fields = [f.strip() for f in chunk.split(",")]
        fields = [f for f in fields if f != ""] if len(fields) == 1 else fields
        if fields and fields[0]:
            objects.append([f.strip() for f in chunk.split(",")])
    return objects


# SizingPeriod:DesignDay field indices (0 is the object type).
_F_NAME = 1
_F_MONTH = 2
_F_MAX_DRY_BULB = 5
_F_DAILY_DRY_BULB_RANGE = 6
_F_HUMIDITY_VALUE = 10
_F_ENTHALPY = 13
_F_DAILY_WET_BULB_RANGE = 14
_F_WIND_SPEED = 16
_F_TAUB = 24
_F_TAUD = 25

_ANNUAL_DAY_RE = re.compile(r"Ann (?:Htg Wind|Htg|Clg|Hum_n)\s+([\d.]+)%\s+Condns\s+(\S+)")


def _field(obj: list, index: int) -> str:
    """One field of an IDF object, or '' when the object is shorter than that."""
    return obj[index].strip() if len(obj) > index else ""


def _annual_day_parts(name: str) -> Optional[tuple]:
    """``(percentile, suffix)`` for an annual design-day name, else None.

    Monthly design days (``... January .4% Condns DB=>MCWB``) do not match, so they are
    skipped throughout: their design values live in ASHRAE columns HZ-PI, which neither
    converter handles yet.
    """
    m = _ANNUAL_DAY_RE.search(name)
    return (m.group(1), m.group(2)) if m else None


def _design_day_columns(name: str) -> Optional[dict]:
    """Return ``{role: column}`` for one design-day name, or None if not annual."""
    parts = _annual_day_parts(name)
    if parts is None:
        return None
    pct, suffix = parts
    table = _SUFFIX_DISPATCH.get(suffix)
    if table is None or pct not in table:
        return None
    entry = table[pct]
    maxdb_col, humval_col = entry[0], entry[1]
    windspeed_col = entry[2] if len(entry) > 2 else None
    return {"maxdb": maxdb_col, "humval": humval_col, "windspeed": windspeed_col}


def ddy_design_columns(text: str) -> dict:
    """Parse a DDY's annual design conditions into ``{ashrae_column: value}``."""
    cols: dict = {}

    for obj in parse_idf_objects(text):
        if obj[0] != "SizingPeriod:DesignDay":
            continue
        name = obj[1]
        roles = _design_day_columns(name)
        if roles is None:
            continue
        maxdb = _field(obj, _F_MAX_DRY_BULB)
        humval = _field(obj, _F_HUMIDITY_VALUE)
        windspeed = _field(obj, _F_WIND_SPEED)
        if maxdb:
            cols[roles["maxdb"]] = float(maxdb)
        if roles["humval"] and humval:
            cols[roles["humval"]] = float(humval)
        # WS=>MCDB days carry the coldest-month design wind speed in the Wind Speed field.
        if roles.get("windspeed") and windspeed:
            cols[roles["windspeed"]] = float(windspeed)
        # Enthalpy design days may carry the enthalpy magnitude in field 13 {J/kg}.
        # The onebuilding DDYs leave it blank; JSON-generated DDYs fill it.
        em = re.search(r"Ann Clg ([\d.]+)% Condns Enth=>MDB", name)
        if em and _field(obj, _F_ENTHALPY):
            enth_col = {".4": "BE", "1": "BG", "2": "BI"}.get(em.group(1))
            if enth_col:
                # J/kg -> kJ/kg
                cols[enth_col] = round(float(_field(obj, _F_ENTHALPY)) / 1000.0, 1)

    # Comment-line statistics.
    def grab(pattern, *col_groups):
        m = re.search(pattern, text)
        if m:
            for col, grp in col_groups:
                cols[col] = float(m.group(grp))

    grab(
        r"Extreme Annual Wind Speeds,\s*1%=([\d.]+)m/s,\s*2\.5%=([\d.]+)m/s,\s*5%=([\d.]+)m/s",
        ("BL", 1),
        ("BM", 2),
        ("BN", 3),
    )
    grab(
        r"Extreme Annual Temperatures,\s*Max Drybulb=([-\d.]+)C\s*Min Drybulb=([-\d.]+)C",
        ("BP", 1),
        ("BO", 2),
    )
    grab(
        r"Extreme Annual Temperatures,\s*Max Wetbulb=([-\d.]+)C\s*Min Wetbulb=([-\d.]+)C",
        ("CB", 1),
        ("CA", 2),
    )
    grab(
        r"Annual Heating Design Conditions Wind Speed=([\d.]+)m/s\s*Wind Dir=(\d+)",
        ("AC", 1),
        ("AD", 2),
    )
    grab(
        r"Annual Cooling Design Conditions Wind Speed=([\d.]+)m/s\s*Wind Dir=(\d+)",
        ("AT", 1),
        ("AU", 2),
    )

    m = re.search(r"Coldest Month=(\w{3})", text)
    if m and m.group(1).upper() in _MONTHS:
        cols["P"] = _MONTHS[m.group(1).upper()]
    m = re.search(r"Hottest Month=(\w{3})", text)
    if m and m.group(1).upper() in _MONTHS:
        cols["AF"] = _MONTHS[m.group(1).upper()]
    return cols


def ddy_monthly_values(text: str) -> dict:
    """Parse the per-design-day daily ranges and optical depths from a DDY.

    Returns ``{variable: {month (1-12): raw value}}`` in the DDY's own units. These are
    the ASHRAE monthly columns PJ-RQ (mean daily ranges) and RR-SO (clear-sky optical
    depths). Each annual design day states them for its own month only, so a DDY
    populates the design months and says nothing about the rest of the year.

    Which range a day reports depends on the design variable it is built around, hence
    ``DESIGN_DAY_RANGE_VARS``. The winter days report none.
    """
    monthly: dict = {}

    def put(variable: Optional[str], month: int, raw: str) -> None:
        if variable and raw:
            monthly.setdefault(variable, {})[month] = float(raw)

    for obj in parse_idf_objects(text):
        if obj[0] != "SizingPeriod:DesignDay":
            continue
        parts = _annual_day_parts(_field(obj, _F_NAME))
        if parts is None:
            continue
        month_field = _field(obj, _F_MONTH)
        if not month_field:
            continue
        month = int(float(month_field))
        db_var, wb_var = DESIGN_DAY_RANGE_VARS.get(parts[1], (None, None))
        put(db_var, month, _field(obj, _F_DAILY_DRY_BULB_RANGE))
        put(wb_var, month, _field(obj, _F_DAILY_WET_BULB_RANGE))
        # taub/taud belong to the ASHRAETau solar models; the winter days use
        # ASHRAEClearSky and leave both blank, so nothing is picked up there.
        beam_var, diffuse_var = OPTICAL_DEPTH_VARS
        put(beam_var, month, _field(obj, _F_TAUB))
        put(diffuse_var, month, _field(obj, _F_TAUD))
    return monthly


def parse_site_location(text: str) -> Optional[dict]:
    for obj in parse_idf_objects(text):
        if obj[0] == "Site:Location":
            return {
                "name": obj[1],
                "latitude": float(obj[2]),
                "longitude": float(obj[3]),
                "time_zone_offset": float(obj[4]),
                "elevation": float(obj[5]),
            }
    return None


def _climate_zone(text: str) -> Optional[str]:
    m = re.search(r"ASHRAE Climate Zone=(\S+)", text)
    return m.group(1) if m else None


def _etc_gmt_from_offset(offset: float) -> str:
    if offset == 0:
        return "UTC"
    if float(offset).is_integer():
        return f"Etc/GMT{'+' if offset < 0 else '-'}{abs(int(offset))}"
    return f"UTC{offset:+g}"


# --------------------------------------------------------------------------- #
# Main conversion
# --------------------------------------------------------------------------- #


def ddy_to_climate_information(
    ddy_path, *, location_overrides: Optional[dict] = None
) -> dict:
    text = Path(ddy_path).read_text(encoding="utf-8", errors="replace")
    site = parse_site_location(text)
    if site is None:
        raise ValueError(f"No Site:Location object found in {ddy_path}")

    cols = ddy_design_columns(text)
    period_id = "ASHRAE Handbook - Fundamentals 2025 design conditions"

    # The Site:Location name looks like "Chicago.OHare.Intl.AP_IL_USA Design_Conditions".
    raw_name = (
        site["name"].replace("_Design_Conditions", "").replace("Design_Conditions", "")
    )
    name = raw_name.replace(".", " ").replace("_", ", ").strip().rstrip(",")

    # The underscore-separated Site:Location name also carries the administrative
    # subdivision and the country, e.g. "Glasgow.Bishopton_SCT_GBR" -> "Glasgow
    # Bishopton, SCT, GBR". Split them back out so a DDY-derived location is as
    # complete as an EPW-derived one (the EPW LOCATION line has its own fields).
    parts = [p.strip() for p in name.split(",")]
    country_code = parts[-1] if len(parts) >= 2 else None
    subdivision = parts[-2] if len(parts) >= 3 else None

    location = {
        "name": name,
        "country_code": country_code,
        "subdivision": subdivision,
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        "time_zone_offset": site["time_zone_offset"],
        "iana_time_zone_code": _etc_gmt_from_offset(site["time_zone_offset"]),
        "elevation": site["elevation"],
        "anemometer_height": 10.0,
        "station_height": 1.8,
        "notes": (
            "Generated from the DDY Site:Location object. IANA time zone inferred "
            "from the UTC offset (DDY stores only the offset). Anemometer (10 m) and "
            "station (1.8 m) heights assumed."
        ),
    }
    for optional in ("country_code", "subdivision"):
        if location[optional] is None:
            del location[optional]
    cz = _climate_zone(text)
    if cz:
        location["climate_zones"] = [
            {
                "system": "ASHRAE Ch. 14",
                "system_version": "2025",
                "zone": cz,
                "notes": "From the DDY ASHRAE Climate Zone comment.",
            }
        ]
    if location_overrides:
        location.update(location_overrides)

    return {
        "metadata": build_metadata(
            description=f"{name} - converted from DDY (design conditions only)",
            source=(
                "[SCHEMA EXAMPLE, generated by tools/ddy_to_json.py.] EnergyPlus DDY "
                "design-day file; design conditions originate from the ASHRAE "
                "Handbook - Fundamentals 2025 (Chapter 14)."
            ),
        ),
        "location": location,
        "summary_data_sets": [
            {
                "source_data_periods": [
                    {
                        "id": period_id,
                        "start_time": as_timestamp("1999-01-01"),
                        "end_time": as_timestamp("2023-12-31"),
                        "notes": "ASHRAE HOF 2025 period of record (representative).",
                        "ashrae_grade": "A",
                    }
                ],
                "notes": (
                    "Annual design conditions parsed from the DDY SizingPeriod:DesignDay "
                    "objects and header comments, converted to base SI units. The DDY does "
                    "not carry the extreme-max wet-bulb or the standard deviations of the "
                    "extreme-annual values. The daily ranges and clear-sky optical depths "
                    "are populated only for the design months the design days state."
                ),
                "summary_data": {
                    **build_summary_data(cols, period_id),
                    **build_monthly_summary_data(ddy_monthly_values(text), period_id),
                },
            }
        ],
    }


def convert_ddy(ddy_path, out_path, **kwargs) -> dict:
    doc = ddy_to_climate_information(ddy_path, **kwargs)
    Path(out_path).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return doc


def extract_member(zip_path, suffix: str, dest_dir) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(suffix.lower()))
        zf.extract(member, dest_dir)
        return dest_dir / member


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Convert a DDY (or a .zip containing one) to Climate Information "
        "v2.1 JSON. An EPW supplied alongside it (inside the same zip, or as "
        "an extra path) is merged in, adding its hourly time series."
    )
    ap.add_argument(
        "inputs",
        nargs="+",
        help="one or more inputs: a .zip (with a .ddy and/or .epw), a .ddy, "
        "and/or a .epw file",
    )
    ap.add_argument("out", help="output JSON path")
    ap.add_argument(
        "--no-time-series",
        action="store_true",
        help="omit the hourly time series even when an EPW is present",
    )
    ap.add_argument("--max-records", type=int, default=None)
    ap.add_argument(
        "--epw-header-design",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also fold the EPW DESIGN CONDITIONS header into the design summary when "
        "an EPW is present (off by default; the DDY is the design-conditions source)",
    )
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        epw_path, ddy_path = resolve_weather_inputs(args.inputs, tmp)
        if ddy_path is None:
            ap.error(
                "no .ddy found in the given input(s); use tools/epw_to_json.py "
                "for an EPW-only conversion"
            )
        doc = build_climate_document(
            epw_path,
            ddy_path,
            include_time_series=not args.no_time_series,
            max_records=args.max_records,
            epw_header_design=args.epw_header_design,
        )
    Path(args.out).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.out}")
