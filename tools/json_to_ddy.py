"""Translate a Climate Information v2.1 JSON document back into an EnergyPlus
design-day (DDY) file. This is the inverse of ``tools/ddy_to_json.py``.

What is reconstructed:
  * a ``Site:Location`` object             <- the ``location`` group
  * the annual ``SizingPeriod:DesignDay``  <- the annual ``summary_data`` design
    objects + the header comment block        conditions (ASHRAE columns), each design
                                              point written as a max dry-bulb plus a
                                              coincident humidity value, with the
                                              extreme-annual / wind / month statistics
                                              in the comments.

The generated DDY is round-trip-faithful with ``ddy_to_json.py`` for every design value
the model carries (including the enthalpy magnitude, which is written into the design
day's ``Enthalpy at Maximum Dry-Bulb`` field). Each summer day also carries the daily
dry-/wet-bulb ranges and the clear-sky optical depths for its month, so the generated
design days have a real diurnal swing and a real solar model rather than an isothermal
day with no sun. Monthly design days are not emitted (the JSON design summary is
annual).

Usage::

    from tools.json_to_ddy import convert_json_to_ddy, climate_information_to_ddy
    convert_json_to_ddy("in.json", "out.ddy")
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

from tools.climate_common import (
    DESIGN_DAY_RANGE_VARS,
    OPTICAL_DEPTH_VARS,
    monthly_summary_data_to_values,
    summary_data_to_ashrae_cols,
)

_MONTH_NAMES = [
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
]

# Each design day: (name suffix, day-type, max-DB column, humidity type,
# humidity-value column, enthalpy-magnitude column, wind-speed column, wind-dir column).
# The wind columns let each day carry its own design wind: cooling days carry the
# cooling MCWS/PCWD (AT/AU), the coldest-month WS=>MCDB days carry the coldest-month
# design wind speed itself (Y/AA), and the remaining heating days carry the heating
# MCWS/PCWD (AC/AD). Mirrors the dispatch table in tools/ddy_to_json.py.
_DESIGN_DAYS = [
    ("Ann Htg 99.6% Condns DB", "WinterDesignDay", "Q", "Wetbulb", "Q", None, "AC", "AD"),
    ("Ann Htg 99% Condns DB", "WinterDesignDay", "R", "Wetbulb", "R", None, "AC", "AD"),
    ("Ann Hum_n 99.6% Condns DP=>MCDB", "WinterDesignDay", "U", "Dewpoint", "S", None, "AC", "AD"),
    ("Ann Hum_n 99% Condns DP=>MCDB", "WinterDesignDay", "X", "Dewpoint", "V", None, "AC", "AD"),
    ("Ann Htg Wind 99.6% Condns WS=>MCDB", "WinterDesignDay", "Z", "Wetbulb", "Z", None, "Y", "AD"),
    ("Ann Htg Wind 99% Condns WS=>MCDB", "WinterDesignDay", "AB", "Wetbulb", "AB", None, "AA", "AD"),
    ("Ann Clg .4% Condns DB=>MWB", "SummerDesignDay", "AH", "Wetbulb", "AI", None, "AT", "AU"),
    ("Ann Clg 1% Condns DB=>MWB", "SummerDesignDay", "AJ", "Wetbulb", "AK", None, "AT", "AU"),
    ("Ann Clg 2% Condns DB=>MWB", "SummerDesignDay", "AL", "Wetbulb", "AM", None, "AT", "AU"),
    ("Ann Clg .4% Condns WB=>MDB", "SummerDesignDay", "AO", "Wetbulb", "AN", None, "AT", "AU"),
    ("Ann Clg 1% Condns WB=>MDB", "SummerDesignDay", "AQ", "Wetbulb", "AP", None, "AT", "AU"),
    ("Ann Clg 2% Condns WB=>MDB", "SummerDesignDay", "AS", "Wetbulb", "AR", None, "AT", "AU"),
    ("Ann Clg .4% Condns DP=>MDB", "SummerDesignDay", "AX", "Dewpoint", "AV", None, "AT", "AU"),
    ("Ann Clg 1% Condns DP=>MDB", "SummerDesignDay", "BA", "Dewpoint", "AY", None, "AT", "AU"),
    ("Ann Clg 2% Condns DP=>MDB", "SummerDesignDay", "BD", "Dewpoint", "BB", None, "AT", "AU"),
    ("Ann Clg .4% Condns Enth=>MDB", "SummerDesignDay", "BF", "Enthalpy", None, "BE", "AT", "AU"),
    ("Ann Clg 1% Condns Enth=>MDB", "SummerDesignDay", "BH", "Enthalpy", None, "BG", "AT", "AU"),
    ("Ann Clg 2% Condns Enth=>MDB", "SummerDesignDay", "BJ", "Enthalpy", None, "BI", "AT", "AU"),
]


def _std_pressure(elevation_m: float) -> float:
    """US standard atmosphere pressure at a given elevation (Pa)."""
    return round(101325.0 * (1.0 - 2.25577e-5 * elevation_m) ** 5.2559)


def _g(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:g}"


def _g1(value) -> str:
    """A temperature range: always one decimal, the way real DDYs write them."""
    return "" if value is None else f"{float(value):.1f}"


def _design_day_block(  # noqa: PLR0913
    name,
    day_type,
    maxdb,
    hum_type,
    hum_val,
    enth_jkg,
    month,
    pressure,
    wind_speed,
    wind_dir,
    db_range,
    wb_range,
    taub,
    taud,
) -> str:
    """One SizingPeriod:DesignDay object.

    The solar tail follows the design day's own model, matching what real DDYs do. A
    summer day uses ASHRAETau2017 with the month's clear-sky optical depths and has no
    Clearness field at all; a winter day uses ASHRAEClearSky with Clearness 0.00 and no
    optical depths, because heating design ignores solar gain. A summer day falls back to
    the winter form only if the document carries no optical depths for its month.
    """
    use_tau = taub is not None and taud is not None
    lines = [
        " SizingPeriod:DesignDay,",
        f"  {name},     !- Name",
        f"  {month},      !- Month",
        "  21,      !- Day of Month",
        f"  {day_type},!- Day Type",
        f"  {_g(maxdb)},      !- Maximum Dry-Bulb Temperature {{C}}",
        f"  {_g1(db_range) or '0.0'},      !- Daily Dry-Bulb Temperature Range {{C}}",
        " DefaultMultipliers, !- Dry-Bulb Temperature Range Modifier Type",
        "           ,      !- Dry-Bulb Temperature Range Modifier Day Schedule Name",
        f"  {hum_type},      !- Humidity Condition Type",
        f"  {_g(hum_val)},      !- Wetbulb or DewPoint at Maximum Dry-Bulb {{C}}",
        "           ,      !- Humidity Indicating Day Schedule Name",
        "           ,      !- Humidity Ratio at Maximum Dry-Bulb {kgWater/kgDryAir}",
        f"  {_g(enth_jkg)},      !- Enthalpy at Maximum Dry-Bulb {{J/kg}}",
        f"  {_g1(wb_range)},      !- Daily Wet-Bulb Temperature Range {{deltaC}}",
        f"  {_g(pressure)}.,      !- Barometric Pressure {{Pa}}",
        f"  {_g(wind_speed)},      !- Wind Speed {{m/s}}",
        f"  {_g(wind_dir)},      !- Wind Direction {{Degrees; N=0, S=180}}",
        "         No,      !- Rain {Yes/No}",
        "         No,      !- Snow on ground {Yes/No}",
        "         No,      !- Daylight Savings Time Indicator",
    ]
    if use_tau:
        lines += [
            "  ASHRAETau2017, !- Solar Model Indicator",
            "           ,      !- Beam Solar Day Schedule Name",
            "           ,      !- Diffuse Solar Day Schedule Name",
            f"  {_g(taub)},      !- ASHRAE Clear Sky Optical Depth for Beam Irradiance (taub)",
            f"  {_g(taud)};      !- ASHRAE Clear Sky Optical Depth for Diffuse Irradiance (taud)",
        ]
    else:
        lines += [
            "  ASHRAEClearSky, !- Solar Model Indicator",
            "           ,      !- Beam Solar Day Schedule Name",
            "           ,      !- Diffuse Solar Day Schedule Name",
            "           ,      !- ASHRAE Clear Sky Optical Depth for Beam Irradiance (taub)",
            "           ,      !- ASHRAE Clear Sky Optical Depth for Diffuse Irradiance (taud)",
            "       0.00;      !- Clearness {0.0 to 1.1}",
        ]
    return "\n".join(lines)


def climate_information_to_ddy(doc: dict) -> str:
    location = doc["location"]
    summary = {}
    if doc.get("summary_data_sets"):
        summary = doc["summary_data_sets"][0].get("summary_data", {})
    cols = summary_data_to_ashrae_cols(summary)
    # Monthly daily-ranges and clear-sky optical depths, read at each design day's month.
    monthly = monthly_summary_data_to_values(summary)

    full_name = location.get("name", "Station")
    pre = full_name.split(",")[0].strip()
    # Re-encode "City, State, Country" as the underscore form the DDY reader decodes.
    site_name = "_".join(p.strip() for p in full_name.split(",")) + " Design_Conditions"
    elevation = float(location.get("elevation", 0.0))
    pressure = _std_pressure(elevation)
    wind_speed = cols.get("AC")  # annual heating MCWS
    wind_dir = cols.get("AD")  # annual heating PCWD
    coldest = cols.get("P", 1)
    hottest = cols.get("AF", 7)

    out = [
        " ! Generated by tools/json_to_ddy.py from a Climate Information v2.1 document.",
        " ! Design conditions originate from the ASHRAE Handbook - Fundamentals 2025.",
        "",
        " Site:Location,",
        f"  {site_name},     !- Location Name",
        f"  {location['latitude']:.2f},     !- Latitude {{N+ S-}}",
        f"  {location['longitude']:.2f},     !- Longitude {{W- E+}}",
        f"  {location['time_zone_offset']:.2f},     !- Time Zone Relative to GMT {{GMT+/-}}",
        f"  {elevation:.2f};     !- Elevation {{m}}",
        "",
        " ! ===== Annual Design Conditions SizingPeriod:DesignDay =====",
    ]

    # Comment block (recovers extremes / wind / months on the way back in).
    def cm(*letters):
        return all(cols.get(x) is not None for x in letters)

    if cm("BL", "BM", "BN"):
        out.append(
            f" ! {pre} Extreme Annual Wind Speeds, 1%={_g(cols['BL'])}m/s, "
            f"2.5%={_g(cols['BM'])}m/s, 5%={_g(cols['BN'])}m/s"
        )
    if cm("BP", "BO"):
        out.append(
            f" ! {pre} Extreme Annual Temperatures, Max Drybulb={_g(cols['BP'])}C "
            f"Min Drybulb={_g(cols['BO'])}C"
        )
    if cm("CB", "CA"):
        out.append(
            f" ! {pre} Extreme Annual Temperatures, Max Wetbulb={_g(cols['CB'])}C "
            f"Min Wetbulb={_g(cols['CA'])}C"
        )
    czones = location.get("climate_zones") or []
    if czones and czones[0].get("zone"):
        out.append(f" ! {pre} ASHRAE Climate Zone={czones[0]['zone']}")
    if cm("AC", "AD"):
        out.append(
            f" ! {pre} Annual Heating Design Conditions Wind Speed={_g(cols['AC'])}m/s "
            f"Wind Dir={_g(cols['AD'])}"
        )
    if cm("AT", "AU"):
        out.append(
            f" ! {pre} Annual Cooling Design Conditions Wind Speed={_g(cols['AT'])}m/s "
            f"Wind Dir={_g(cols['AU'])}"
        )
    out.append(f" ! Coldest Month={_MONTH_NAMES[int(coldest) - 1]}")
    out.append(f" ! Hottest Month={_MONTH_NAMES[int(hottest) - 1]}")
    out.append("")

    for suffix, day_type, maxdb_col, hum_type, humval_col, enth_col, ws_col, wd_col in _DESIGN_DAYS:
        if cols.get(maxdb_col) is None:
            continue
        month = coldest if day_type == "WinterDesignDay" else hottest
        enth_jkg = None
        if enth_col is not None and cols.get(enth_col) is not None:
            enth_jkg = round(cols[enth_col] * 1000.0)  # kJ/kg -> J/kg
        # Per-day design wind: fall back to the heating MCWS/PCWD when the day's own
        # column is absent, so the field is never blank.
        day_ws = cols.get(ws_col) if cols.get(ws_col) is not None else wind_speed
        day_wd = cols.get(wd_col) if cols.get(wd_col) is not None else wind_dir
        # Which daily ranges this day reports depends on the design variable it is built
        # around; the winter days report none (see DESIGN_DAY_RANGE_VARS).
        db_var, wb_var = DESIGN_DAY_RANGE_VARS.get(suffix.rsplit(None, 1)[-1], (None, None))
        db_range = monthly.get(db_var, {}).get(int(month)) if db_var else None
        wb_range = monthly.get(wb_var, {}).get(int(month)) if wb_var else None
        # Optical depths go on the summer days only: heating design ignores solar gain,
        # so the winter days keep the ASHRAEClearSky / Clearness 0.00 form.
        taub = taud = None
        if day_type == "SummerDesignDay":
            beam_var, diffuse_var = OPTICAL_DEPTH_VARS
            taub = monthly.get(beam_var, {}).get(int(month))
            taud = monthly.get(diffuse_var, {}).get(int(month))
        out.append(
            _design_day_block(
                name=f"{pre} {suffix}",
                day_type=day_type,
                maxdb=cols.get(maxdb_col),
                hum_type=hum_type,
                hum_val=cols.get(humval_col) if humval_col else None,
                enth_jkg=enth_jkg,
                month=int(month),
                pressure=pressure,
                wind_speed=day_ws,
                wind_dir=day_wd,
                db_range=db_range,
                wb_range=wb_range,
                taub=taub,
                taud=taud,
            )
        )
        out.append("")

    return "\n".join(out) + "\n"


def convert_json_to_ddy(json_path, out_path) -> str:
    doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    text = climate_information_to_ddy(doc)
    Path(out_path).write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Convert Climate Information v2.1 JSON to a DDY file"
    )
    ap.add_argument("json")
    ap.add_argument("out")
    args = ap.parse_args()
    convert_json_to_ddy(args.json, args.out)
    print(f"Wrote {args.out}")
