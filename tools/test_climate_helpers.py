"""Tests for the EPW/DDY -> Climate Information v2.1 converters.

All self-contained -- only local paths in this repo are used. The two headline checks:

1. ``test_ddy_matches_ashrae`` -- the design conditions parsed out of each DDY file
   are identical to the matching row of the ASHRAE HOF 2025 spreadsheet. The
   spreadsheet itself is huge and lives off-repo, so we compare against the small
   committed extract in ``tools/testdata/ashrae_hof2025_design_extract.json`` (see
   ``tools/extract_ashrae_reference.py`` for how that fixture is produced).

2. ``test_null_roundtrip_epw_json`` -- EPW has no blank/missing concept (it uses
   numeric sentinels like 99.9, 999, 9999); the v2.1 schema supports explicit
   ``null``. This checks that a sentinel becomes ``null`` on the way into JSON and the
   same sentinel comes back on the way out, and that ``null`` survives a JSON
   serialisation round-trip.

The rest cover the reverse converters, the opt-in EPW design header, and the design-day
daily ranges and solar model in both directions.

Run directly (``python tools/test_climate_helpers.py``) or with pytest.
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Resolve the repo root explicitly from a .env file (REPO_ROOT) so the
# `tools` package is importable no matter where the tests are invoked from.
load_dotenv()
REPO_ROOT = os.environ.get("REPO_ROOT") or str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO_ROOT)

from tools.climate_common import DESIGN_DAY_RANGE_VARS, OPTICAL_DEPTH_VARS
from tools.ddy_to_json import (
    ddy_design_columns,
    ddy_monthly_values,
    ddy_to_climate_information,
    extract_member,
    parse_idf_objects,
    parse_site_location,
)
from tools.epw_to_json import EPW_FIELDS, epw_field_to_json, epw_to_climate_information
from tools.json_to_ddy import climate_information_to_ddy
from tools.json_to_epw import climate_information_to_epw

REPO = Path(REPO_ROOT)
EXAMPLES = REPO / "examples"
EXTRACT_PATH = REPO / "tools" / "testdata" / "ashrae_hof2025_design_extract.json"

# zip in examples/ -> station key in the ASHRAE extract fixture
STATIONS = {
    "chicago": EXAMPLES / "USA_IL_Chicago.OHare.Intl.AP.725300_TMYx.2011-2025.zip",
    "glasgow": EXAMPLES / "GBR_SCT_Glasgow.Bishopton.031340_TMYx.2011-2025.zip",
}

# Design-condition columns are published to one decimal place; identity at that
# precision is what "identical" means here.
TOL = 0.05


# --------------------------------------------------------------------------- #
# Test 1: DDY design conditions == ASHRAE spreadsheet row
# --------------------------------------------------------------------------- #


def test_ddy_matches_ashrae():
    extract = json.loads(EXTRACT_PATH.read_text(encoding="utf-8"))
    column_labels = extract["columns"]

    total_checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        for station, zip_path in STATIONS.items():
            assert zip_path.exists(), f"missing test input: {zip_path}"
            ddy_path = extract_member(zip_path, ".ddy", tmp)
            text = ddy_path.read_text(encoding="utf-8", errors="replace")
            ddy_cols = ddy_design_columns(text)
            ref = extract["stations"][station]["values"]

            mismatches = []
            checked = 0
            for col, ddy_val in sorted(ddy_cols.items()):
                ref_val = ref.get(col)
                if ref_val is None:
                    mismatches.append(
                        f"{col}: DDY has {ddy_val} but spreadsheet is blank"
                    )
                    continue
                checked += 1
                if abs(float(ddy_val) - float(ref_val)) > TOL:
                    mismatches.append(
                        f"{col} ({column_labels.get(col, '?')}): "
                        f"DDY={ddy_val} vs ASHRAE={ref_val}"
                    )
            assert not mismatches, f"[{station}] DDY != ASHRAE:\n  " + "\n  ".join(
                mismatches
            )
            # Guard against a vacuous pass: each DDY carries ~35 annual design values.
            assert checked >= 30, f"[{station}] only {checked} columns compared"
            total_checked += checked

            # Location should also line up with the spreadsheet (informational columns).
            site = parse_site_location(text)
            for col, key in (
                ("G", "latitude"),
                ("H", "longitude"),
                ("K", "time_zone_offset"),
            ):
                if ref.get(col) is not None:
                    assert abs(site[key] - float(ref[col])) <= TOL, (
                        f"[{station}] {key}: DDY={site[key]} vs ASHRAE={ref[col]}"
                    )

            print(
                f"  [{station}] {checked} design columns identical to ASHRAE row "
                f"{extract['stations'][station]['row']}"
            )

    print(f"test_ddy_matches_ashrae OK ({total_checked} column comparisons)")


# --------------------------------------------------------------------------- #
# Test 2: NULL / blank round-trips EPW <-> JSON
# --------------------------------------------------------------------------- #

# variable -> (epw missing sentinel, to_si, from_si). from_si inverts to_si so we can
# round-trip raw EPW values through the JSON representation.
ROUNDTRIP = {
    "dry_bulb_temperature": (
        99.9,
        lambda c: round(c + 273.15, 2),
        lambda k: round(k - 273.15, 1),
    ),
    "relative_humidity": (
        999,
        lambda p: round(p / 100.0, 4),
        lambda f: round(f * 100.0),
    ),
    "atmospheric_pressure": (999999, lambda x: x, lambda x: x),
    "wind_direction": (
        999,
        lambda d: round(d * math.pi / 180.0, 4),
        lambda r: round(r * 180.0 / math.pi),
    ),
    "wind_speed": (999, lambda x: x, lambda x: x),
    "snow_depth": (999, lambda cm: round(cm / 100.0, 4), lambda m: round(m * 100.0)),
}


def _epw_sentinels():
    return {spec[1]: spec[4] for spec in EPW_FIELDS if spec[1]}


def test_null_roundtrip_epw_json():
    sentinels = _epw_sentinels()

    # Representative raw EPW values, each list mixing real readings with the field's
    # missing sentinel. The sentinel must become null and round-trip back unchanged.
    samples = {
        "dry_bulb_temperature": [-4.4, 0.0, 25.3, 99.9],  # 99.9 = missing
        "relative_humidity": [68, 100, 0, 999],  # 999  = missing
        "atmospheric_pressure": [99832, 101325, 999999],  # 999999 = missing
        "wind_direction": [250, 0, 359, 999],  # 999  = missing
        "wind_speed": [7.7, 0.0, 999],  # 999  = missing
        "snow_depth": [4, 0, 999],  # 999  = missing
    }

    null_count = 0
    for var, raws in samples.items():
        sentinel, to_si, from_si = ROUNDTRIP[var]
        assert sentinels[var] == sentinel, f"sentinel table mismatch for {var}"
        for raw in raws:
            json_val = epw_field_to_json(float(raw), sentinel, to_si)
            if raw >= sentinel:
                assert json_val is None, (
                    f"{var}: sentinel {raw} should map to null, got {json_val}"
                )
                # null -> back to the sentinel on export
                back = sentinel if json_val is None else from_si(json_val)
                assert back == sentinel, (
                    f"{var}: null should export to {sentinel}, got {back}"
                )
                null_count += 1
            else:
                assert json_val is not None, f"{var}: real value {raw} became null"
                back = from_si(json_val)
                assert abs(back - raw) <= 0.5, (
                    f"{var}: round-trip {raw} -> {json_val} -> {back}"
                )

    assert null_count == 6, f"expected 6 sentinel->null conversions, got {null_count}"

    # null also has to survive plain JSON serialisation (the scenario in
    # extra_examples/test_20251017.json and nan_handling_python.py).
    fixture = REPO / "extra_examples" / "test_20251017.json"
    if fixture.exists():
        data = json.loads(fixture.read_text())
        assert any(v is None for row in data for v in row), (
            "fixture should contain nulls"
        )
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=True) as fh:
            json.dump(data, fh)
            fh.flush()
            fh.seek(0)
            reloaded = json.load(fh)
        assert reloaded == data, "null values changed across a JSON write/read cycle"
        assert reloaded[1][1] is None and reloaded[2][3] is None

    print(f"test_null_roundtrip_epw_json OK ({null_count} sentinel<->null round-trips)")


# --------------------------------------------------------------------------- #
# Test 3: reverse converters round-trip (EPW/DDY -> JSON -> EPW/DDY -> JSON)
# --------------------------------------------------------------------------- #


def _dump(obj) -> str:
    return json.dumps(obj, sort_keys=True)


def test_roundtrip_json_epw():
    """EPW -> JSON -> EPW -> JSON preserves the summary and the hourly series."""
    with tempfile.TemporaryDirectory() as tmp:
        epw = extract_member(STATIONS["chicago"], ".epw", tmp)
        # This test exercises the EPW-header design round-trip, so opt into it
        # explicitly (it is off by default in epw_to_climate_information).
        doc1 = epw_to_climate_information(epw, max_records=96, epw_header_design=True)
        epw_text = climate_information_to_epw(doc1)
        epw2 = Path(tmp) / "roundtrip.epw"
        epw2.write_text(epw_text, encoding="utf-8")
        doc2 = epw_to_climate_information(epw2, epw_header_design=True)

        s1 = doc1["summary_data_sets"][0]["summary_data"]
        s2 = doc2["summary_data_sets"][0]["summary_data"]
        assert _dump(s1) == _dump(s2), "summary changed across JSON->EPW->JSON"

        ts1 = doc1["time_series_data_sets"][0]["time_series"]
        ts2 = doc2["time_series_data_sets"][0]["time_series"]
        assert set(ts1) == set(ts2), "time-series variables changed"
        for var, block in ts1.items():
            got = ts2[var]["values"][: len(block["values"])]
            assert got == block["values"], f"{var} values changed in round-trip"
    print("test_roundtrip_json_epw OK (summary + 96 h of every variable preserved)")


def test_roundtrip_json_ddy():
    """DDY -> JSON -> DDY -> JSON preserves the design conditions."""
    with tempfile.TemporaryDirectory() as tmp:
        ddy = extract_member(STATIONS["chicago"], ".ddy", tmp)
        doc1 = ddy_to_climate_information(ddy)
        ddy_text = climate_information_to_ddy(doc1)
        ddy2 = Path(tmp) / "roundtrip.ddy"
        ddy2.write_text(ddy_text, encoding="utf-8")
        doc2 = ddy_to_climate_information(ddy2)

        s1 = doc1["summary_data_sets"][0]["summary_data"]
        s2 = doc2["summary_data_sets"][0]["summary_data"]
        assert _dump(s1) == _dump(s2), "summary changed across JSON->DDY->JSON"
        assert _dump(doc1["location"]) == _dump(doc2["location"]), "location changed"
    print("test_roundtrip_json_ddy OK (design conditions + location preserved)")


# --------------------------------------------------------------------------- #
# Test 4: EPW-header design conditions are opt-in (off by default)
# --------------------------------------------------------------------------- #


def test_epw_header_design_default_off():
    """EPW DESIGN CONDITIONS populate the summary only when explicitly requested."""
    with tempfile.TemporaryDirectory() as tmp:
        epw = extract_member(STATIONS["chicago"], ".epw", tmp)
        default_doc = epw_to_climate_information(epw, include_time_series=False)
        assert "summary_data_sets" not in default_doc, (
            "EPW-header design conditions should be excluded by default"
        )
        opted_in = epw_to_climate_information(
            epw, include_time_series=False, epw_header_design=True
        )
        assert opted_in.get("summary_data_sets"), (
            "epw_header_design=True should populate summary_data_sets"
        )
    print("test_epw_header_design_default_off OK (default excludes EPW-header design)")


# --------------------------------------------------------------------------- #
# Test 5: design-day daily ranges and solar model, in both directions
# --------------------------------------------------------------------------- #

# SizingPeriod:DesignDay fields compared below, by field index.
_DAY_FIELDS = (
    (2, "month"),
    (6, "daily dry-bulb range"),
    (14, "daily wet-bulb range"),
    (21, "solar model"),
    (24, "taub"),
    (25, "taud"),
    (26, "clearness"),
)

# 18 annual design days: 6 heating (winter) and 12 cooling (summer).
EXPECTED_COOLING_DAYS = 12


def _annual_design_days(text: str) -> dict:
    """``{day name suffix: {field label: raw value}}`` for the annual design days."""
    days = {}
    for obj in parse_idf_objects(text):
        if obj[0].strip() != "SizingPeriod:DesignDay":
            continue
        name = obj[1].strip()
        if "Ann " not in name:
            continue  # monthly design days: out of scope for both converters
        days[name.split("Ann ", 1)[1]] = {
            label: (obj[i].strip() if len(obj) > i else "") for i, label in _DAY_FIELDS
        }
    return days


def test_ddy_design_day_fields_roundtrip():
    """DDY -> JSON -> DDY reproduces every annual design day's range and solar fields.

    These are the fields the converters used to drop. The writer emitted every day with a
    0.0 dry-bulb range, a blank wet-bulb range and an ASHRAEClearSky / Clearness 0.00
    stub -- in EnergyPlus, an isothermal design day with no sun. The reader did not pick
    them up either, so the loss was symmetric and a summary-only round-trip could not see
    it; hence the explicit assertions on the values below.
    """
    with tempfile.TemporaryDirectory() as tmp:
        for station, zip_path in STATIONS.items():
            ddy = extract_member(zip_path, ".ddy", tmp)
            source = ddy.read_text(encoding="utf-8", errors="replace")
            regenerated = climate_information_to_ddy(ddy_to_climate_information(ddy))

            before = _annual_design_days(source)
            after = _annual_design_days(regenerated)
            assert set(before) == set(after), (
                f"[{station}] annual design days changed: "
                f"{sorted(set(before) ^ set(after))}"
            )
            mismatches = [
                f"{day} {label}: source={before[day][label]!r} "
                f"regenerated={after[day][label]!r}"
                for day in sorted(before)
                for _index, label in _DAY_FIELDS
                if before[day][label] != after[day][label]
            ]
            assert not mismatches, (
                f"[{station}] DDY round-trip changed design-day fields:\n  "
                + "\n  ".join(mismatches)
            )

            # Assert the intent, not just the equality: a cooling design day must have a
            # real diurnal swing and a real solar model, or it under-sizes cooling plant.
            cooling = sorted(day for day in after if day.startswith("Clg"))
            assert len(cooling) == EXPECTED_COOLING_DAYS, (
                f"[{station}] expected {EXPECTED_COOLING_DAYS} cooling days, "
                f"got {len(cooling)}"
            )
            for day in cooling:
                fields = after[day]
                assert float(fields["daily dry-bulb range"]) > 0.0, (
                    f"[{station}] {day} has no diurnal swing"
                )
                assert fields["solar model"] == "ASHRAETau2017", (
                    f"[{station}] {day} solar model is {fields['solar model']!r}"
                )
                assert float(fields["taub"]) > 0.0 and float(fields["taud"]) > 0.0, (
                    f"[{station}] {day} carries no clear-sky optical depths"
                )
            print(
                f"  [{station}] {len(before)} annual design days identical across "
                f"DDY->JSON->DDY"
            )

    print("test_ddy_design_day_fields_roundtrip OK (ranges + solar model preserved)")


def test_ddy_monthly_values_read():
    """The reader recovers the daily ranges and optical depths a DDY states.

    Cross-checked against the design-day fields parsed straight out of the file rather
    than against the round-trip, so this fails if the reader starts dropping them again.
    The round-trip test cannot catch that on its own: a loss shared by both directions
    round-trips perfectly, which is exactly how this went unnoticed.
    """
    expected_variables = set(OPTICAL_DEPTH_VARS)
    for range_variables in DESIGN_DAY_RANGE_VARS.values():
        expected_variables.update(v for v in range_variables if v)

    with tempfile.TemporaryDirectory() as tmp:
        for station, zip_path in STATIONS.items():
            ddy = extract_member(zip_path, ".ddy", tmp)
            text = ddy.read_text(encoding="utf-8", errors="replace")
            days = _annual_design_days(text)
            monthly = ddy_monthly_values(text)

            missing = expected_variables - set(monthly)
            assert not missing, f"[{station}] reader found nothing for: {sorted(missing)}"

            checked = 0
            for day, fields in sorted(days.items()):
                month = int(float(fields["month"]))
                suffix = day.rsplit(None, 1)[-1]
                pairs = list(
                    zip(
                        DESIGN_DAY_RANGE_VARS.get(suffix, (None, None)),
                        ("daily dry-bulb range", "daily wet-bulb range"),
                    )
                ) + list(zip(OPTICAL_DEPTH_VARS, ("taub", "taud")))
                for variable, label in pairs:
                    raw = fields[label]
                    if not variable or not raw:
                        continue
                    got = monthly.get(variable, {}).get(month)
                    assert got is not None, (
                        f"[{station}] {day}: {variable} missing for month {month} "
                        f"(DDY says {raw})"
                    )
                    assert abs(float(got) - float(raw)) <= TOL, (
                        f"[{station}] {day}: {variable}[{month}] = {got} "
                        f"but DDY says {raw}"
                    )
                    checked += 1
            # Each of the 12 cooling days states a dry-bulb range and both optical
            # depths, so a healthy read is comfortably above this floor.
            assert checked >= 30, f"[{station}] only {checked} values cross-checked"
            print(f"  [{station}] {checked} design-day values match the reader's output")

    print("test_ddy_monthly_values_read OK (ranges + optical depths recovered)")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def _run_all():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}:\n{exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {exc!r}")
    if failures:
        raise SystemExit(f"{failures} test(s) failed")
    print("All tests passed.")


if __name__ == "__main__":
    _run_all()
