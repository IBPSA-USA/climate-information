"""Translate an EnergyPlus Weather (EPW) file into a Climate Information v2.1
JSON document (schema: ``schema/ClimateInformation.schema.yaml``).

An EPW file contributes:
  * ``LOCATION`` header line          -> the ``location`` group
  * the 8760 hourly data records      -> a ``time_series_data_sets`` entry
  * ``DESIGN CONDITIONS`` header line -> a ``summary_data_sets`` entry (the ASHRAE
                                         HOF 2025 annual design conditions, columns
                                         P..CL of the spreadsheet) — **only** when
                                         ``epw_header_design=True`` is passed. It is
                                         off by default; the DDY is the preferred
                                         source of design conditions.

EPW has no concept of a missing/blank value: every field carries a numeric
sentinel (99.9 degC, 999 %, 9999 Wh/m2, ...). The v2.1 schema *does* support an
explicit ``null``, so on import each sentinel becomes ``null`` and on export each
``null`` becomes the sentinel again (see ``epw_field_to_json`` /
``json_value_to_epw`` and the round-trip test).

Usage::

    from tools.epw_to_json import epw_to_climate_information, convert_epw
    doc = epw_to_climate_information("path/to/file.epw")
    convert_epw("path/to/file.epw", "out.json")
"""

import json
import math
import os
import sys
import tempfile
import zipfile
from collections import namedtuple
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Resolve the repo root explicitly from a .env file (REPO_ROOT) so the
# `tools` package is importable no matter where the script is invoked from.
load_dotenv()
REPO_ROOT = os.environ.get("REPO_ROOT") or str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO_ROOT)

from tools.climate_common import build_summary_data, resolve_weather_inputs

# --------------------------------------------------------------------------- #
# EPW hourly data record: the 35 comma-separated fields, in order.
#
# Each field is an EpwField(index, variable, units, value_type, missing, to_si, from_si):
#   * variable: ClimateTimeSeries member to emit, or None to skip the field
#   * missing:  EPW "missing" sentinel; a raw value >= this becomes null on import,
#               and null becomes this sentinel on export
#   * to_si:    EPW value -> base SI (import);  from_si: base SI -> EPW value (export)
# --------------------------------------------------------------------------- #

EpwField = namedtuple(
    "EpwField", "index variable units value_type missing to_si from_si"
)

_IDENTITY = lambda x: x  # noqa: E731


def _to_k(x):
    return round(x + 273.15, 2)


def _from_k(x):
    return round(x - 273.15, 1)


def _frac_pct(x):
    return round(x / 100.0, 4)


def _from_frac_pct(x):
    return round(x * 100.0)


def _frac_tenths(x):
    return round(x / 10.0, 3)


def _from_frac_tenths(x):
    return round(x * 10.0)


def _wh_to_j(x):
    return round(x * 3600.0, 1)


def _from_wh(x):
    return round(x / 3600.0)


def _deg_to_rad(x):
    return round(x * math.pi / 180.0, 4)


def _from_rad(x):
    return round(x * 180.0 / math.pi)


def _cm_to_m(x):
    return round(x / 100.0, 4)


def _from_cm(x):
    return round(x * 100.0, 1)


def _mm_to_m(x):
    return round(x / 1000.0, 6)


def _from_mm(x):
    return round(x * 1000.0, 1)


def _f(
    index,
    variable=None,
    units=None,
    value_type=None,
    missing=None,
    to_si=None,
    from_si=None,
):
    return EpwField(index, variable, units, value_type, missing, to_si, from_si)


EPW_FIELDS = [
    _f(0),
    _f(1),
    _f(2),
    _f(3),
    _f(4),
    _f(5),  # year, month, day, hour, minute, flags
    _f(6, "dry_bulb_temperature", "K", "INSTANTANEOUS", 99.9, _to_k, _from_k),
    _f(7, "dew_point_temperature", "K", "INSTANTANEOUS", 99.9, _to_k, _from_k),
    _f(8, "relative_humidity", "-", "INSTANTANEOUS", 999, _frac_pct, _from_frac_pct),
    _f(9, "atmospheric_pressure", "Pa", "INSTANTANEOUS", 999999, _IDENTITY, round),
    _f(10),
    _f(11),  # extraterrestrial horizontal / direct normal radiation
    _f(
        12,
        "horizontal_infrared_sky_irradiance",
        "W/m2",
        "INSTANTANEOUS",
        9999,
        _IDENTITY,
        round,
    ),
    _f(13, "global_horizontal_irradiation", "J/m2", "SUM", 9999, _wh_to_j, _from_wh),
    _f(14, "direct_normal_irradiation", "J/m2", "SUM", 9999, _wh_to_j, _from_wh),
    _f(15, "diffuse_horizontal_irradiation", "J/m2", "SUM", 9999, _wh_to_j, _from_wh),
    _f(16, "global_horizontal_illuminance", "lx", "AVERAGE", 999999, _IDENTITY, round),
    _f(17, "direct_normal_illuminance", "lx", "AVERAGE", 999999, _IDENTITY, round),
    _f(18, "diffuse_horizontal_illuminance", "lx", "AVERAGE", 999999, _IDENTITY, round),
    _f(19),  # zenith luminance
    _f(20, "wind_direction", "radians", "INSTANTANEOUS", 999, _deg_to_rad, _from_rad),
    _f(21, "wind_speed", "m/s", "INSTANTANEOUS", 999, _IDENTITY, lambda x: round(x, 1)),
    _f(
        22, "total_sky_cover", "-", "INSTANTANEOUS", 99, _frac_tenths, _from_frac_tenths
    ),
    _f(
        23,
        "opaque_sky_cover",
        "-",
        "INSTANTANEOUS",
        99,
        _frac_tenths,
        _from_frac_tenths,
    ),
    _f(24),
    _f(25),
    _f(26),
    _f(27),  # visibility, ceiling, present weather obs/codes
    _f(28, "precipitable_water", "m", "INSTANTANEOUS", 999, _mm_to_m, _from_mm),
    _f(
        29,
        "aerosol_optical_depth",
        "-",
        "INSTANTANEOUS",
        0.999,
        _IDENTITY,
        lambda x: round(x, 4),
    ),
    _f(30, "snow_depth", "m", "INSTANTANEOUS", 999, _cm_to_m, _from_cm),
    _f(31),  # days since last snowfall
    _f(32, "albedo", "-", "INSTANTANEOUS", 999, _IDENTITY, lambda x: round(x, 3)),
    _f(33, "liquid_precipitation_depth", "m", "SUM", 999, _mm_to_m, _from_mm),
    _f(34),  # liquid precipitation quantity
]


def epw_field_to_json(raw: float, sentinel: Optional[float], to_si):
    """Convert one raw EPW numeric value to its JSON value: sentinel -> ``None``."""
    if sentinel is not None and raw >= sentinel:
        return None
    return to_si(raw)


def json_value_to_epw(field: EpwField, value):
    """Convert a JSON value back to its raw EPW value: ``None`` -> sentinel."""
    if value is None:
        return field.missing
    return field.from_si(value)


# --------------------------------------------------------------------------- #
# Header parsing
# --------------------------------------------------------------------------- #

# The DESIGN CONDITIONS line (one design set) is the ASHRAE spreadsheet columns
# P..CL laid end to end, in three labelled sections. This is the column letter for
# each numeric position within a section.
_HEATING_COLS = [
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "AA",
    "AB",
    "AC",
    "AD",
    "AE",
]
_COOLING_COLS = [
    "AF",
    "AG",
    "AH",
    "AI",
    "AJ",
    "AK",
    "AL",
    "AM",
    "AN",
    "AO",
    "AP",
    "AQ",
    "AR",
    "AS",
    "AT",
    "AU",
    "AV",
    "AW",
    "AX",
    "AY",
    "AZ",
    "BA",
    "BB",
    "BC",
    "BD",
    "BE",
    "BF",
    "BG",
    "BH",
    "BI",
    "BJ",
    "BK",
]
_EXTREMES_COLS = [
    "BL",
    "BM",
    "BN",
    "BO",
    "BP",
    "BQ",
    "BR",
    "BS",
    "BT",
    "BU",
    "BV",
    "BW",
    "BX",
    "BY",
    "BZ",
    "CA",
    "CB",
    "CC",
    "CD",
    "CE",
    "CF",
    "CG",
    "CH",
    "CI",
    "CJ",
    "CK",
    "CL",
]


def parse_location_line(line: str) -> dict:
    f = [x.strip() for x in line.split(",")]
    # LOCATION, City, State, Country, Source, WMO, Lat, Lon, TZ, Elevation
    return {
        "name": f[1].replace(".", " ").strip(),
        "subdivision": f[2],
        "country_code": f[3],
        "data_source": f[4],
        "wmo_station_id": f[5],
        "latitude": float(f[6]),
        "longitude": float(f[7]),
        "time_zone_offset": float(f[8]),
        "elevation": float(f[9]),
    }


def parse_design_conditions_line(line: str) -> Optional[dict]:
    """Parse the EPW DESIGN CONDITIONS line into ``{ashrae_column: value}``.

    Returns ``None`` if the file declares no design condition sets.
    """
    f = [x.strip() for x in line.split(",")]
    if len(f) < 3 or int(f[1]) < 1:
        return None
    # f[0]=DESIGN CONDITIONS, f[1]=count, f[2]=source title, then the sections.
    cols: dict = {}

    def consume(start_label, columns, after):
        i = f.index(start_label)
        # values run from i+1 until the next section label `after` (or end)
        end = f.index(after) if after else len(f)
        nums = f[i + 1 : end]
        for col, val in zip(columns, nums):
            if val != "":
                cols[col] = float(val)

    consume("Heating", _HEATING_COLS, "Cooling")
    consume("Cooling", _COOLING_COLS, "Extremes")
    consume("Extremes", _EXTREMES_COLS, None)
    return cols


# --------------------------------------------------------------------------- #
# Main conversion
# --------------------------------------------------------------------------- #


def _etc_gmt_from_offset(offset: float) -> str:
    """Best-effort IANA zone from a UTC offset (EPW carries no IANA code).

    POSIX-style ``Etc/GMT`` zones invert the sign (Etc/GMT+6 == UTC-6).
    """
    if offset == 0:
        return "UTC"
    if float(offset).is_integer():
        return f"Etc/GMT{'+' if offset < 0 else '-'}{abs(int(offset))}"
    return f"UTC{offset:+g}"


def _read_lines(epw_path) -> list[str]:
    text = Path(epw_path).read_text(encoding="utf-8", errors="replace")
    return text.splitlines()


def epw_to_climate_information(
    epw_path,
    *,
    include_time_series: bool = True,
    max_records: Optional[int] = None,
    location_overrides: Optional[dict] = None,
    epw_header_design: bool = False,
) -> dict:
    """Build the full v2.1 document dict from an EPW file path.

    ``location_overrides`` is merged into the ``location`` group after parsing — used
    to apply canonical station metadata (e.g. the ASHRAE WMO id / elevation) that
    differs from what the source EPW happens to carry.

    ``epw_header_design`` is **off by default**: the EPW DESIGN CONDITIONS header line
    is *not* used to populate ``summary_data_sets`` unless this is set to ``True``. The
    DDY is the preferred source of design conditions; set this flag only when an EPW is
    the sole input and its header design conditions are wanted.
    """
    lines = _read_lines(epw_path)
    loc_raw = parse_location_line(lines[0])

    design_cols = None
    data_start = 8
    for i, line in enumerate(lines[:8]):
        if epw_header_design and line.startswith("DESIGN CONDITIONS"):
            design_cols = parse_design_conditions_line(line)
        if line.startswith("DATA PERIODS"):
            data_start = i + 1

    period_id = "ASHRAE Handbook - Fundamentals 2025 design conditions"

    location = {
        "name": f"{loc_raw['name']}, {loc_raw['subdivision']}, {loc_raw['country_code']}".replace(
            ", ,", ","
        ),
        "country_code": loc_raw["country_code"],
        "subdivision": loc_raw["subdivision"],
        "wmo_station_id": loc_raw["wmo_station_id"],
        "latitude": loc_raw["latitude"],
        "longitude": loc_raw["longitude"],
        "time_zone_offset": loc_raw["time_zone_offset"],
        "iana_time_zone_code": _etc_gmt_from_offset(loc_raw["time_zone_offset"]),
        "elevation": loc_raw["elevation"],
        "anemometer_height": 10.0,
        "station_height": 1.8,
        "notes": (
            "Generated from the EPW LOCATION/DESIGN CONDITIONS header and hourly "
            "records. IANA time zone inferred from the UTC offset (EPW stores only "
            "the offset). Anemometer (10 m) and station (1.8 m) heights assumed."
        ),
    }
    if location_overrides:
        location.update(location_overrides)

    data_source = (
        "[SCHEMA EXAMPLE, generated by tools/epw_to_json.py.] "
        f"EPW source field: {loc_raw['data_source']}."
    )
    if design_cols:
        data_source += (
            " Design conditions: ASHRAE Handbook - Fundamentals 2025 "
            "(EPW DESIGN CONDITIONS line)."
        )

    doc = {
        "metadata": {
            "data_model": "IBPSA_BDE",
            "schema": "CLIMATE_INFORMATION",
            "schema_version": "0.2.0",
            "id": "",
            "description": f"{location['name']} - converted from EPW",
            "data_source": data_source,
            "copyright_holder": "IBPSA USA",
            "copyright_year": 2026,
            "licensee": "IBPSA USA BDE Climate Working Group",
            "license": "Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0)",
        },
        "location": location,
    }

    if design_cols:
        doc["summary_data_sets"] = [
            {
                "source_data_periods": [
                    {
                        "id": period_id,
                        "start_time": "1999-01-01",
                        "end_time": "2023-12-31",
                        "notes": "ASHRAE HOF 2025 period of record (representative).",
                        "ashrae_grade": "A",
                    }
                ],
                "notes": (
                    "Annual design conditions parsed from the EPW DESIGN CONDITIONS "
                    "header line (ASHRAE spreadsheet columns P-CL) and converted to "
                    "base SI units. Monthly design tables, degree days, precipitation "
                    "and solar are not carried in the EPW header."
                ),
                "summary_data": build_summary_data(design_cols, period_id),
            }
        ]

    if include_time_series:
        doc["time_series_data_sets"] = [
            _build_time_series(lines[data_start:], max_records=max_records)
        ]
    return doc


def _build_time_series(data_lines: list[str], *, max_records: Optional[int]) -> dict:
    """Build a TimeSeriesDataSet (regular hourly interval) from EPW data rows."""
    rows = [ln for ln in data_lines if ln.strip()]
    if max_records is not None:
        rows = rows[:max_records]

    # Collect per-variable value arrays.
    series: dict = {}
    for fld in EPW_FIELDS:
        if fld.variable is None:
            continue
        series[fld.variable] = {
            "display_name": fld.variable.replace("_", " ").capitalize(),
            "units": fld.units,
            "value_type": fld.value_type,
            "value_time_intervals": "hourly",
            "values": [],
        }

    interval_id = "hourly"
    first = rows[0].split(",") if rows else []
    start_year = first[0] if first else "2020"

    for row in rows:
        f = row.split(",")
        for fld in EPW_FIELDS:
            if fld.variable is None:
                continue
            raw = float(f[fld.index])
            series[fld.variable]["values"].append(
                epw_field_to_json(raw, fld.missing, fld.to_si)
            )

    return {
        "time_intervals": [
            {
                "id": interval_id,
                "starting_time": f"{start_year}-01-01T01:00:00",
                "regular_interval": 3600,
                "notes": [
                    "Hourly typical-meteorological-year series. EPW missing-value "
                    "sentinels (99.9, 999, 9999, ...) are represented as null."
                ],
            }
        ],
        "time_series": series,
        "notes": (
            f"{len(rows)} hourly records converted from the EPW data block. "
            "TMYx files draw each month from a different source year; a single "
            "regular hourly interval is used for the example."
        ),
    }


_DESIGN_PERIOD_ID = "ASHRAE Handbook - Fundamentals 2025 design conditions"


def _design_cols_from_epw(epw_path) -> Optional[dict]:
    """Return the EPW DESIGN CONDITIONS columns (``{ashrae_column: value}``), or None."""
    for line in _read_lines(epw_path)[:8]:
        if line.startswith("DESIGN CONDITIONS"):
            return parse_design_conditions_line(line)
    return None


def build_climate_document(
    epw_path=None,
    ddy_path=None,
    *,
    include_time_series: bool = True,
    max_records: Optional[int] = None,
    location_overrides: Optional[dict] = None,
    epw_header_design: bool = False,
) -> dict:
    """Build one Climate Information v2.1 document from an EPW and/or a DDY.

    * EPW only  -> location + hourly time series (and the EPW-header design summary
      *only* when ``epw_header_design=True``).
    * DDY only  -> location (+ climate zone) + design summary (design-day objects).
    * Both      -> a single merged document: the EPW's hourly time series, a design
      summary from the DDY's design-day objects, and the DDY's climate-zone metadata.
      With ``epw_header_design=True`` the EPW DESIGN CONDITIONS header is folded into
      that summary as well (EPW values win where the two overlap).

    ``epw_header_design`` is **off by default** — the EPW header is not trusted as a
    design-conditions source unless explicitly requested. At least one of
    ``epw_path`` / ``ddy_path`` must be supplied.
    """
    if epw_path is None and ddy_path is None:
        raise ValueError("build_climate_document needs an EPW and/or a DDY path")

    # DDY only: defer entirely to the DDY reader.
    if epw_path is None:
        from tools.ddy_to_json import ddy_to_climate_information

        return ddy_to_climate_information(
            ddy_path, location_overrides=location_overrides
        )

    # EPW present (the richer source): location, hourly series, and — only when asked —
    # the EPW-header design summary.
    doc = epw_to_climate_information(
        epw_path,
        include_time_series=include_time_series,
        max_records=max_records,
        location_overrides=location_overrides,
        epw_header_design=epw_header_design,
    )
    if ddy_path is None:
        return doc

    # Both present: merge the DDY's design columns and climate zone into the EPW doc.
    from tools.ddy_to_json import _climate_zone, ddy_design_columns

    ddy_text = Path(ddy_path).read_text(encoding="utf-8", errors="replace")
    ddy_cols = ddy_design_columns(ddy_text)
    # The DDY is the design-conditions source; the EPW header is folded in only when
    # explicitly requested (off by default).
    epw_cols = (_design_cols_from_epw(epw_path) or {}) if epw_header_design else {}
    merged_cols = {**ddy_cols, **epw_cols}  # EPW header wins where both carry a column

    if merged_cols:
        if epw_header_design:
            design_notes = (
                "Annual design conditions merged from the EPW DESIGN CONDITIONS header "
                "and the DDY SizingPeriod:DesignDay objects (the same ASHRAE HOF 2025 "
                "source), converted to base SI units."
            )
        else:
            design_notes = (
                "Annual design conditions parsed from the DDY SizingPeriod:DesignDay "
                "objects and header comments, converted to base SI units."
            )
        doc["summary_data_sets"] = [
            {
                "source_data_periods": [
                    {
                        "id": _DESIGN_PERIOD_ID,
                        "start_time": "1999-01-01",
                        "end_time": "2023-12-31",
                        "notes": "ASHRAE HOF 2025 period of record (representative).",
                        "ashrae_grade": "A",
                    }
                ],
                "notes": design_notes,
                "summary_data": build_summary_data(merged_cols, _DESIGN_PERIOD_ID),
            }
        ]

    cz = _climate_zone(ddy_text)
    if cz and not doc["location"].get("climate_zones"):
        doc["location"]["climate_zones"] = [
            {
                "system": "ASHRAE Ch. 14",
                "system_version": "2025",
                "zone": cz,
                "notes": "From the DDY ASHRAE Climate Zone comment.",
            }
        ]

    doc["metadata"]["description"] = doc["metadata"]["description"].replace(
        "converted from EPW", "converted from EPW + DDY"
    )
    doc["metadata"]["data_source"] = doc["metadata"]["data_source"].replace(
        "generated by tools/epw_to_json.py.",
        "generated by tools/epw_to_json.py from a merged EPW + DDY input.",
    )
    return doc


def convert_epw(epw_path, out_path, **kwargs) -> dict:
    doc = epw_to_climate_information(epw_path, **kwargs)
    Path(out_path).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return doc


def extract_member(zip_path, suffix: str, dest_dir) -> Path:
    """Extract the single member ending in ``suffix`` (e.g. ``.epw``) from a zip."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(suffix.lower()))
        zf.extract(member, dest_dir)
        return dest_dir / member


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Convert an EPW (or a .zip containing one) to Climate Information "
        "v2.1 JSON. A DDY supplied alongside it (inside the same zip, or as "
        "an extra path) is merged into the same document."
    )
    ap.add_argument(
        "inputs",
        nargs="+",
        help="one or more inputs: a .zip (with an .epw and/or .ddy), a .epw, "
        "and/or a .ddy file",
    )
    ap.add_argument("out", help="output JSON path")
    ap.add_argument("--no-time-series", action="store_true")
    ap.add_argument("--max-records", type=int, default=None)
    ap.add_argument(
        "--epw-header-design",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="derive design conditions from the EPW DESIGN CONDITIONS header line "
        "(off by default; prefer a DDY for design data)",
    )
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        epw_path, ddy_path = resolve_weather_inputs(args.inputs, tmp)
        if epw_path is None:
            ap.error(
                "no .epw found in the given input(s); use tools/ddy_to_json.py "
                "for a DDY-only conversion"
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
