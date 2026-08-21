"""Shared helpers for the EPW/DDY -> Climate Information (v2.1) converters.

The EPW header line and the DDY design-day objects both encode the ASHRAE
Handbook of Fundamentals 2025 design conditions. We key everything off the ASHRAE
spreadsheet *column letters* (A..CL), so the EPW reader, the DDY reader and the
spreadsheet test fixture all speak the same language. ``build_summary_data`` turns
a ``{column_letter: value}`` dict (values in the spreadsheet's degC / kJ/kg / deg /
m/s units) into a schema-shaped ``ClimateSummaryData`` group in *base SI* units.

Unit conventions (see the "Units" section of the ClimateInformation specification):
  * absolute temperature  degC -> K          (+ 273.15)
  * temperature range/std degC -> K          (identical value, it is a difference)
  * enthalpy              kJ/kg -> J/kg       (x 1000)
  * wind direction        deg  -> radians     (x pi/180)
  * precipitation depth   mm   -> m           (/ 1000)
"""

import math
import re
import uuid
import zipfile
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# Document metadata (lattice-core ``Metadata`` data group)
# --------------------------------------------------------------------------- #

# Fixed provenance strings shared by every generated document.
SCHEMA_AUTHOR = "IBPSA_BDE"
SCHEMA_NAME = "CLIMATE_INFORMATION"
AUTHOR = "IBPSA USA BDE Climate Working Group"
COPYRIGHT = "Copyright (c) 2026 IBPSA USA. All rights reserved."
LICENSE = (
    "Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0)"
)

# ``time_of_creation`` is a *constant*, not ``datetime.now()``: the generated examples
# under examples/generated/ are committed to the repository, so a wall-clock timestamp
# would make every regeneration dirty them. Bump this deliberately when regenerating.
TIME_OF_CREATION = "2026-07-19T12:00Z"

# ``version`` tracks revisions of the *data* (semver). The generated examples are the
# first published revision of each converted document.
DATA_VERSION = "1.0.0"

# Namespace for deterministic document ids, derived once from the project URL. Document
# ids are UUID5 (name-based) rather than UUID4 so that regenerating an example yields
# the same id instead of a spurious diff.
_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://github.com/IBPSA-USA/climate-information"
)

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema/ClimateInformation.schema.yaml"


def make_document_id(key: str) -> str:
    """Deterministic ``Metadata.id`` (UUID5) for a document identified by ``key``.

    ``key`` must be stable for a given artifact -- the document ``description`` is used
    by the converters, since it names both the station and the source format.
    """
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def schema_version() -> str:
    """Read ``Schema.Version`` out of the schema YAML so metadata cannot drift from it."""
    text = _SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(r'^\s+Version:\s*"([^"]+)"', text, flags=re.MULTILINE)
    if match is None:
        raise ValueError(f"no Schema Version found in {_SCHEMA_PATH}")
    return match.group(1)


def as_timestamp(date: str, time_of_day: str = "00:00") -> str:
    """Format a lattice ``Timestamp``: ``YYYY-MM-DDThh:mmZ`` (UTC, minute precision).

    The core schema pattern is ``^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}Z$``, so a
    date alone and a seconds-bearing timestamp are both invalid.
    """
    return f"{date}T{time_of_day}Z"


def build_metadata(description: str, source: str) -> dict:
    """Build the lattice-core ``Metadata`` group for a generated document."""
    return {
        "schema_author": SCHEMA_AUTHOR,
        "schema_name": SCHEMA_NAME,
        "schema_version": schema_version(),
        "author": AUTHOR,
        "id": make_document_id(description),
        "description": description,
        "time_of_creation": TIME_OF_CREATION,
        "version": DATA_VERSION,
        "source": source,
        "copyright": COPYRIGHT,
        "license": LICENSE,
    }


# --------------------------------------------------------------------------- #
# Unit conversions
# --------------------------------------------------------------------------- #


def c_to_k(celsius: Optional[float]) -> Optional[float]:
    """Absolute temperature: degC -> K."""
    return None if celsius is None else round(celsius + 273.15, 2)


def kjkg_to_jkg(kjkg: Optional[float]) -> Optional[float]:
    """Specific enthalpy: kJ/kg -> J/kg."""
    return None if kjkg is None else round(kjkg * 1000.0, 1)


def deg_to_rad(deg: Optional[float]) -> Optional[float]:
    """Wind direction: degrees clockwise from north -> radians."""
    return None if deg is None else round(deg * math.pi / 180.0, 4)


def mm_to_m(mm: Optional[float]) -> Optional[float]:
    """Depth: mm -> m."""
    return None if mm is None else round(mm / 1000.0, 6)


def diff_c_to_k(celsius: Optional[float]) -> Optional[float]:
    """A temperature *difference* (range, std dev): numerically identical in K."""
    return None if celsius is None else round(celsius, 2)


# Inverses of the conversions above, used by the JSON -> EPW/DDY converters. Results
# are rounded to the precision the ASHRAE design tables publish (one decimal for most
# quantities, whole degrees for wind direction).


def k_to_c(kelvin: Optional[float]) -> Optional[float]:
    return None if kelvin is None else round(kelvin - 273.15, 1)


def jkg_to_kjkg(jkg: Optional[float]) -> Optional[float]:
    return None if jkg is None else round(jkg / 1000.0, 1)


def rad_to_deg(rad: Optional[float]) -> Optional[float]:
    return None if rad is None else round(rad * 180.0 / math.pi)


def diff_k_to_c(kelvin: Optional[float]) -> Optional[float]:
    return None if kelvin is None else round(kelvin, 1)


def _id_round1(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 1)


def _id_round3(x: Optional[float]) -> Optional[float]:
    """Unitless, published to three decimals (the clear-sky optical depths)."""
    return None if x is None else round(float(x), 3)


# Forward converter (as used in _DESIGN_SPEC) -> its inverse.
_INVERSE = {
    c_to_k: k_to_c,
    kjkg_to_jkg: jkg_to_kjkg,
    deg_to_rad: rad_to_deg,
    diff_c_to_k: diff_k_to_c,
    float: _id_round1,
    _id_round3: _id_round3,
}


# --------------------------------------------------------------------------- #
# Summary (design-conditions) construction, keyed by ASHRAE column letter
# --------------------------------------------------------------------------- #

# How each schema ClimateSummaryData variable is built from ASHRAE columns.
# Each entry: display_name, units, source_data_type, and the pieces to populate.
#   "exceedance": (list of percentiles, list of (column, converter)) -- builds the
#                 percent_exceedance grid/lookup pair (skipping pairs whose column
#                 is absent), and
#   "stats":      {statistic_name: (column, converter)} -- single annual statistics.
# A variable is emitted only if at least one of its pieces resolves to a value.

_DESIGN_SPEC = [
    (
        "dry_bulb_temperature",
        "Dry-bulb temperature",
        "K",
        "MEASURED",
        {
            "exceedance": (
                [0.4, 1.0, 2.0, 99.0, 99.6],
                [("AH", c_to_k), ("AJ", c_to_k), ("AL", c_to_k), ("R", c_to_k), ("Q", c_to_k)],
            ),
            "stats": {
                "mean_minimum": ("BO", c_to_k),
                "mean_maximum": ("BP", c_to_k),
                "standard_deviation_minimum": ("BQ", diff_c_to_k),
                "standard_deviation_maximum": ("BR", diff_c_to_k),
            },
        },
    ),
    (
        "dew_point_temperature",
        "Dew-point temperature",
        "K",
        "MEASURED",
        {
            "exceedance": (
                [0.4, 1.0, 2.0, 99.0, 99.6],
                [("AV", c_to_k), ("AY", c_to_k), ("BB", c_to_k), ("V", c_to_k), ("S", c_to_k)],
            ),
        },
    ),
    (
        "wet_bulb_temperature",
        "Wet-bulb temperature",
        "K",
        "MEASURED",
        {
            "exceedance": (
                [0.4, 1.0, 2.0],
                [("AN", c_to_k), ("AP", c_to_k), ("AR", c_to_k)],
            ),
            "stats": {
                "mean_minimum": ("CA", c_to_k),
                "mean_maximum": ("CB", c_to_k),
                "standard_deviation_minimum": ("CC", diff_c_to_k),
                "standard_deviation_maximum": ("CD", diff_c_to_k),
                "maximum": ("BK", c_to_k),
            },
        },
    ),
    (
        "enthalpy",
        "Enthalpy",
        "J/kg",
        "MEASURED",
        {
            "exceedance": (
                [0.4, 1.0, 2.0],
                [("BE", kjkg_to_jkg), ("BG", kjkg_to_jkg), ("BI", kjkg_to_jkg)],
            ),
        },
    ),
    (
        "wind_speed",
        "Wind speed",
        "m/s",
        "MEASURED",
        {
            "exceedance": (
                [1.0, 2.5, 5.0],
                [("BL", float), ("BM", float), ("BN", float)],
            ),
        },
    ),
    # Coincident variables use the PercentTimeExceedanceCoincident form: the lookup
    # carries the *base* variable (`values`, whose percentile is the grid) alongside the
    # *coincident* statistic of a second variable (`coincident_values`). Each
    # "coincident_exceedance" entry is (percentiles, base_columns, coincident_columns).
    (
        "dry_bulb_temperature_coincident_mean_wet_bulb_temperature",
        "Mean wet-bulb temperature coincident with design dry-bulb temperature",
        "K",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 1.0, 2.0],
                [("AH", c_to_k), ("AJ", c_to_k), ("AL", c_to_k)],  # base: cooling DB
                [("AI", c_to_k), ("AK", c_to_k), ("AM", c_to_k)],  # coincident: MCWB
            ),
        },
    ),
    (
        "dry_bulb_temperature_coincident_mean_wind_speed",
        "Mean wind speed coincident with design dry-bulb temperature",
        "m/s",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 99.6],
                [("AH", c_to_k), ("Q", c_to_k)],  # base: cooling/heating DB
                [("AT", float), ("AC", float)],  # coincident: MCWS
            ),
        },
    ),
    (
        "dry_bulb_temperature_coincident_prevailing_wind_direction",
        "Prevailing wind direction coincident with design dry-bulb temperature",
        "radians",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 99.6],
                [("AH", c_to_k), ("Q", c_to_k)],  # base: cooling/heating DB
                [("AU", deg_to_rad), ("AD", deg_to_rad)],  # coincident: PCWD
            ),
        },
    ),
    (
        "dew_point_temperature_coincident_mean_dry_bulb_temperature",
        "Mean dry-bulb temperature coincident with design dew-point temperature",
        "K",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 1.0, 2.0, 99.0, 99.6],
                [("AV", c_to_k), ("AY", c_to_k), ("BB", c_to_k), ("V", c_to_k), ("S", c_to_k)],  # base: DP
                [("AX", c_to_k), ("BA", c_to_k), ("BD", c_to_k), ("X", c_to_k), ("U", c_to_k)],  # coincident: MCDB
            ),
        },
    ),
    (
        "wet_bulb_temperature_coincident_mean_dry_bulb_temperature",
        "Mean dry-bulb temperature coincident with design wet-bulb temperature",
        "K",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 1.0, 2.0],
                [("AN", c_to_k), ("AP", c_to_k), ("AR", c_to_k)],  # base: evaporation WB
                [("AO", c_to_k), ("AQ", c_to_k), ("AS", c_to_k)],  # coincident: MCDB
            ),
        },
    ),
    (
        "enthalpy_coincident_mean_dry_bulb_temperature",
        "Mean dry-bulb temperature coincident with design enthalpy",
        "K",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 1.0, 2.0],
                [("BE", kjkg_to_jkg), ("BG", kjkg_to_jkg), ("BI", kjkg_to_jkg)],  # base: enthalpy
                [("BF", c_to_k), ("BH", c_to_k), ("BJ", c_to_k)],  # coincident: MCDB
            ),
        },
    ),
    (
        "wind_speed_coincident_mean_dry_bulb_temperature",
        "Mean dry-bulb temperature coincident with coldest-month design wind speed",
        "K",
        "MEASURED",
        {
            "coincident_exceedance": (
                [0.4, 1.0],
                [("Y", float), ("AA", float)],  # base: coldest-month WS
                [("Z", c_to_k), ("AB", c_to_k)],  # coincident: MCDB
            ),
        },
    ),
]


def _get(cols: dict, letter: str):
    v = cols.get(letter)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    return float(v)


def _build_exceedance(cols, percentiles, column_converters):
    grid, values = [], []
    for pct, (column, conv) in zip(percentiles, column_converters):
        raw = _get(cols, column)
        if raw is None:
            continue
        grid.append(pct)
        values.append(conv(raw))
    if not grid:
        return None
    return {
        "grid_variables": {"percent_time_exceeded": grid},
        "lookup_variables": {"values": values},
    }


def _build_coincident_exceedance(cols, percentiles, base_cc, coincident_cc):
    """Build a PercentTimeExceedanceCoincident block: `values` (base variable) plus
    `coincident_values` (the coincident statistic). A grid point is emitted only when
    *both* the base and coincident columns are present, so the two arrays stay aligned.
    """
    grid, values, coincident_values = [], [], []
    for pct, (bcol, bconv), (ccol, cconv) in zip(percentiles, base_cc, coincident_cc):
        braw = _get(cols, bcol)
        craw = _get(cols, ccol)
        if braw is None or craw is None:
            continue
        grid.append(pct)
        values.append(bconv(braw))
        coincident_values.append(cconv(craw))
    if not grid:
        return None
    return {
        "grid_variables": {"percent_time_exceeded": grid},
        "lookup_variables": {"values": values, "coincident_values": coincident_values},
    }


def build_summary_data(cols: dict, source_data_period_id: str) -> dict:
    """Build a schema ``ClimateSummaryData`` group from ASHRAE column values.

    ``cols`` maps ASHRAE column letters (A..CL) to raw spreadsheet values (degC,
    kJ/kg, deg, m/s). Variables whose source columns are absent are omitted, so the
    same function serves both the EPW reader (full P..CL) and the DDY reader (the
    subset its design-day objects carry).
    """
    summary: dict = {}
    for name, display, units, source_type, pieces in _DESIGN_SPEC:
        annual: dict = {}
        for stat, (column, conv) in pieces.get("stats", {}).items():
            raw = _get(cols, column)
            if raw is not None:
                annual[stat] = conv(raw)
        # `Statistics.statistic_type` is required whenever `percent_exceedance` is
        # present, and selects which alternative the block uses: SINGLE_VALUE for the
        # plain grid/lookup form, COINCIDENT_VALUES for the form that also carries
        # `coincident_values`. It matches the schema's per-variable
        # `(annual|monthly).statistic_type=...` constraints.
        exc_spec = pieces.get("exceedance")
        if exc_spec is not None:
            exc = _build_exceedance(cols, exc_spec[0], exc_spec[1])
            if exc is not None:
                annual["percent_exceedance"] = exc
                annual["statistic_type"] = "SINGLE_VALUE"
        coinc_spec = pieces.get("coincident_exceedance")
        if coinc_spec is not None:
            exc = _build_coincident_exceedance(cols, *coinc_spec)
            if exc is not None:
                annual["percent_exceedance"] = exc
                annual["statistic_type"] = "COINCIDENT_VALUES"
        if not annual:
            continue
        summary[name] = {
            "display_name": display,
            "units": units,
            "source_data_period": source_data_period_id,
            "source_data_type": source_type,
            "annual": annual,
        }

    coldest = _get(cols, "P")
    if coldest is not None:
        summary["coldest_month"] = int(round(coldest))
    hottest = _get(cols, "AF")
    if hottest is not None:
        summary["hottest_month"] = int(round(hottest))
    return summary


def summary_data_to_ashrae_cols(summary: dict) -> dict:
    """Inverse of :func:`build_summary_data`.

    Recover the ``{ashrae_column_letter: value}`` dict (in the spreadsheet's degC /
    kJ/kg / deg / m/s units) from a base-SI ``ClimateSummaryData`` group, so the
    JSON -> EPW / JSON -> DDY converters can re-emit the design conditions.
    """
    cols: dict = {}
    for name, _display, _units, _source_type, pieces in _DESIGN_SPEC:
        var = summary.get(name)
        if not isinstance(var, dict):
            continue
        annual = var.get("annual") or {}

        for stat, (column, conv) in pieces.get("stats", {}).items():
            val = annual.get(stat)
            if val is not None:
                cols[column] = _INVERSE[conv](val)

        pe = annual.get("percent_exceedance")
        exc_spec = pieces.get("exceedance")
        if exc_spec is not None and pe:
            percentiles, column_converters = exc_spec
            index_by_pct = {p: i for i, p in enumerate(percentiles)}
            grid = pe.get("grid_variables", {}).get("percent_time_exceeded", [])
            values = pe.get("lookup_variables", {}).get("values", [])
            for pct, val in zip(grid, values):
                if pct in index_by_pct and val is not None:
                    column, conv = column_converters[index_by_pct[pct]]
                    cols[column] = _INVERSE[conv](val)

        coinc_spec = pieces.get("coincident_exceedance")
        if coinc_spec is not None and pe:
            percentiles, base_cc, coincident_cc = coinc_spec
            index_by_pct = {p: i for i, p in enumerate(percentiles)}
            grid = pe.get("grid_variables", {}).get("percent_time_exceeded", [])
            lookup = pe.get("lookup_variables", {})
            for pct, val in zip(grid, lookup.get("values", [])):
                if pct in index_by_pct and val is not None:
                    column, conv = base_cc[index_by_pct[pct]]
                    cols[column] = _INVERSE[conv](val)
            for pct, val in zip(grid, lookup.get("coincident_values", [])):
                if pct in index_by_pct and val is not None:
                    column, conv = coincident_cc[index_by_pct[pct]]
                    cols[column] = _INVERSE[conv](val)

    if isinstance(summary.get("coldest_month"), int):
        cols["P"] = summary["coldest_month"]
    if isinstance(summary.get("hottest_month"), int):
        cols["AF"] = summary["hottest_month"]
    return cols


# --------------------------------------------------------------------------- #
# Monthly design-day variables (daily ranges and clear-sky optical depths)
# --------------------------------------------------------------------------- #

# These ClimateSummaryData variables are monthly-only, and a DDY states them one month
# at a time: each design day carries the values for *its own* month. So unlike the annual
# design conditions above they are not addressed by ASHRAE column letter but by
# (variable, month). The display_name and units strings must match the schema's
# per-variable Constraints exactly.
_MONTHLY_SPEC = {
    "daily_dry_bulb_temperature_range": (
        "Mean daily dry-bulb temperature range",
        "K",
        diff_c_to_k,
    ),
    "daily_dry_bulb_temperature_range_at_design_dry_bulb_temperature": (
        "Mean daily dry-bulb temperature range at the design dry-bulb temperature",
        "K",
        diff_c_to_k,
    ),
    "daily_wet_bulb_temperature_range_at_design_dry_bulb_temperature": (
        "Mean daily wet-bulb temperature range at the design dry-bulb temperature",
        "K",
        diff_c_to_k,
    ),
    "daily_dry_bulb_temperature_range_at_design_wet_bulb_temperature": (
        "Mean daily dry-bulb temperature range at the design wet-bulb temperature",
        "K",
        diff_c_to_k,
    ),
    "daily_wet_bulb_temperature_range_at_design_wet_bulb_temperature": (
        "Mean daily wet-bulb temperature range at the design wet-bulb temperature",
        "K",
        diff_c_to_k,
    ),
    "clear_sky_beam_optical_depth": (
        "Clear-sky beam (pseudo-)optical depth",
        "-",
        _id_round3,
    ),
    "clear_sky_diffuse_optical_depth": (
        "Clear-sky diffuse (pseudo-)optical depth",
        "-",
        _id_round3,
    ),
}

# Which daily-range variables an annual design day reports, keyed by the suffix of its
# name (the part after "Condns "). Verified against the climate.onebuilding DDYs for both
# example stations: a DB=>MWB day states the ranges at the design dry-bulb, a WB=>MDB day
# those at the design wet-bulb, and the DP=>MDB / Enth=>MDB days the plain mean daily
# range. The winter days (DB, DP=>MCDB, WS=>MCDB) are deliberately absent: they carry a
# 0.0 dry-bulb range and a blank wet-bulb range, because heating design ignores the
# diurnal swing, so they report no range at all.
DESIGN_DAY_RANGE_VARS = {
    "DB=>MWB": (
        "daily_dry_bulb_temperature_range_at_design_dry_bulb_temperature",
        "daily_wet_bulb_temperature_range_at_design_dry_bulb_temperature",
    ),
    "WB=>MDB": (
        "daily_dry_bulb_temperature_range_at_design_wet_bulb_temperature",
        "daily_wet_bulb_temperature_range_at_design_wet_bulb_temperature",
    ),
    "DP=>MDB": ("daily_dry_bulb_temperature_range", None),
    "Enth=>MDB": ("daily_dry_bulb_temperature_range", None),
}

# The taub / taud fields of a design day, in schema order.
OPTICAL_DEPTH_VARS = (
    "clear_sky_beam_optical_depth",
    "clear_sky_diffuse_optical_depth",
)

MONTHS_IN_YEAR = 12


def build_monthly_summary_data(monthly_values: dict, source_data_period_id: str) -> dict:
    """Build the monthly ``ClimateSummaryData`` entries from per-month raw values.

    ``monthly_values`` maps a variable name to ``{month (1-12): raw value}`` in the
    DDY's units (degC differences, unitless optical depths). A DDY only ever states its
    design months, so the months it says nothing about become empty ``Statistics``
    objects -- the schema requires all twelve slots, and an empty one is the honest way
    to say "no statistics for this month".
    """
    summary: dict = {}
    for name, (display, units, conv) in _MONTHLY_SPEC.items():
        by_month = monthly_values.get(name) or {}
        if not by_month:
            continue
        months = []
        for month in range(1, MONTHS_IN_YEAR + 1):
            raw = by_month.get(month)
            months.append({} if raw is None else {"mean": conv(float(raw))})
        summary[name] = {
            "display_name": display,
            "units": units,
            "source_data_period": source_data_period_id,
            "source_data_type": "MEASURED",
            "monthly": months,
        }
    return summary


def monthly_summary_data_to_values(summary: dict) -> dict:
    """Inverse of :func:`build_monthly_summary_data`.

    Recover ``{variable: {month (1-12): raw value}}`` in the DDY's units, so the
    JSON -> DDY converter can write each design day's ranges and optical depths.
    """
    out: dict = {}
    for name, (_display, _units, conv) in _MONTHLY_SPEC.items():
        var = summary.get(name)
        if not isinstance(var, dict):
            continue
        by_month = {}
        for index, stats in enumerate(var.get("monthly") or [], start=1):
            value = (stats or {}).get("mean") if isinstance(stats, dict) else None
            if value is not None:
                by_month[index] = _INVERSE[conv](value)
        if by_month:
            out[name] = by_month
    return out


# --------------------------------------------------------------------------- #
# Command-line input resolution (zip / epw / ddy)
# --------------------------------------------------------------------------- #


def resolve_weather_inputs(paths, dest_dir):
    """Resolve one or more CLI inputs to an ``(epw_path, ddy_path)`` pair.

    Each entry in ``paths`` may be a ``.zip`` archive (the first ``.epw`` and/or
    ``.ddy`` members are extracted into ``dest_dir``), a bare ``.epw`` file, or a
    bare ``.ddy`` file. Any mix is accepted, so a single zip containing both, a lone
    EPW, a lone DDY, or a separate EPW *and* DDY all resolve correctly. Either side
    of the returned pair is ``None`` when that file type was not supplied.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    epw_path = ddy_path = None
    for raw in paths:
        path = Path(raw)
        suffix = path.suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                for member in zf.namelist():
                    lower = member.lower()
                    if lower.endswith(".epw") and epw_path is None:
                        epw_path = Path(zf.extract(member, dest_dir))
                    elif lower.endswith(".ddy") and ddy_path is None:
                        ddy_path = Path(zf.extract(member, dest_dir))
        elif suffix == ".epw":
            epw_path = path
        elif suffix == ".ddy":
            ddy_path = path
        else:
            raise ValueError(
                f"unsupported input '{path}': expected a .zip, .epw, or .ddy file"
            )
    return epw_path, ddy_path
