"""Shared helpers for the EPW/DDY -> Climate Information (v2.1) converters.

The EPW header line and the DDY design-day objects both encode the ASHRAE
Handbook of Fundamentals 2025 design conditions. We key everything off the ASHRAE
spreadsheet *column letters* (A..CL), so the EPW reader, the DDY reader and the
spreadsheet test fixture all speak the same language. ``build_summary_data`` turns
a ``{column_letter: value}`` dict (values in the spreadsheet's degC / kJ/kg / deg /
m/s units) into a schema-shaped ``ClimateSummaryData`` group in *base SI* units.

Unit conventions (see docs/implementation_and_application_notes.md section 2):
  * absolute temperature  degC -> K          (+ 273.15)
  * temperature range/std degC -> K          (identical value, it is a difference)
  * enthalpy              kJ/kg -> J/kg       (x 1000)
  * wind direction        deg  -> radians     (x pi/180)
  * precipitation depth   mm   -> m           (/ 1000)
"""

import math
import zipfile
from pathlib import Path
from typing import Optional

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


# Forward converter (as used in _DESIGN_SPEC) -> its inverse.
_INVERSE = {
    c_to_k: k_to_c,
    kjkg_to_jkg: jkg_to_kjkg,
    deg_to_rad: rad_to_deg,
    diff_c_to_k: diff_k_to_c,
    float: _id_round1,
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
        exc_spec = pieces.get("exceedance")
        if exc_spec is not None:
            exc = _build_exceedance(cols, exc_spec[0], exc_spec[1])
            if exc is not None:
                annual["percent_exceedance"] = exc
        coinc_spec = pieces.get("coincident_exceedance")
        if coinc_spec is not None:
            exc = _build_coincident_exceedance(cols, *coinc_spec)
            if exc is not None:
                annual["percent_exceedance"] = exc
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
