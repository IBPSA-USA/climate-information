# EPW / DDY <-> Climate Information v2.1 helpers

Small, self-contained Python helpers that translate EnergyPlus weather files to and from
Climate Information v2.1 JSON (the data model defined in
`schema/ClimateInformation.schema.yaml`), plus the tests that check them. Everything
uses local paths inside this repository.

| File | What it does |
|---|---|
| `climate_common.py` | Shared unit conversions and the design-conditions mapping, in both directions: `build_summary_data()` (`{ASHRAE column -> value}` -> schema `ClimateSummaryData`, base SI) and its inverse `summary_data_to_ashrae_cols()`. |
| `epw_to_json.py` | **EPW -> v2.1 JSON.** `LOCATION` -> `location`, 8760 hourly records -> `time_series_data_sets`. EPW missing-value sentinels become `null`. The `DESIGN CONDITIONS` header -> `summary_data_sets` only with `--epw-header-design` (off by default -- the DDY is the preferred design source). |
| `ddy_to_json.py` | **DDY -> v2.1 JSON.** `Site:Location` -> `location`, `SizingPeriod:DesignDay` objects + header comments -> `summary_data_sets`. |
| `json_to_epw.py` | **v2.1 JSON -> EPW** (reverse of `epw_to_json.py`). `null` becomes the EPW sentinel again. |
| `json_to_ddy.py` | **v2.1 JSON -> DDY** (reverse of `ddy_to_json.py`). |
| `extract_ashrae_reference.py` | One-off: pulls the two test rows out of the (off-repo, ~45 MB) ASHRAE HOF 2025 spreadsheet into the fixture below. |
| `testdata/ashrae_hof2025_design_extract.json` | Committed fixture: Chicago + Glasgow rows, columns A-CL, in the spreadsheet's units. |
| `test_climate_helpers.py` | The tests (see below). |
| `generate_examples.py` | Runs the full pipeline EPW/DDY -> JSON -> EPW/DDY for both stations, then the tests. |

## Setup

This repository uses [uv](https://docs.astral.sh/uv/). `uv run` resolves the
environment from `pyproject.toml`/`uv.lock` automatically (run `uv sync` once to
materialise the `.venv`), so no manual activation is needed.

The tools locate the repo (to import the `tools` package) by reading
`REPO_ROOT` from a `.env` file via `python-dotenv`, so they can be run from any
working directory. Copy the template once and point it at your clone:

```bash
uv sync                       # one-time: create/refresh the venv
cp .env_example .env          # then edit REPO_ROOT to your repo path
```

`.env` is git-ignored (machine-specific); `.env_example` is the tracked template. If
`.env` is absent the tools fall back to a path derived from the script location.

## Run

```bash
# from the repo root, with uv
uv run python tools/generate_examples.py      # full pipeline + tests
uv run python tools/test_climate_helpers.py   # tests only

# EPW/DDY -> JSON. Each forward converter accepts a .zip (with an .epw and/or .ddy),
# a bare .epw, a bare .ddy, or both files. When both an EPW and a DDY are present the
# result is a single merged document (EPW hourly series + the DDY design summary + the
# DDY's climate zone). Run epw_to_json.py when an EPW is present, ddy_to_json.py otherwise.
uv run python tools/epw_to_json.py  weather.zip        out.json   # zip with epw (+ ddy)
uv run python tools/epw_to_json.py  file.epw           out.json   # bare epw (no design data)
uv run python tools/epw_to_json.py  file.epw file.ddy  out.json   # both, merged
uv run python tools/ddy_to_json.py  weather.zip        out.json   # zip / bare ddy
#   options: --no-time-series, --max-records N (cap the hourly series)
#   --epw-header-design: also use the EPW DESIGN CONDITIONS header for design data
#                        (OFF by default; the DDY is the preferred design source)

# JSON -> EPW/DDY (reverse converters take a JSON document)
uv run python tools/json_to_epw.py  in.json  out.epw
uv run python tools/json_to_ddy.py  in.json  out.ddy

# doit tasks (validate examples, build web docs) are in the dev group
uv run --group dev doit
```

If you prefer to work inside an already-activated virtualenv, drop the `uv run`
prefix and call `python tools/...` directly.

The bundled inputs are the `*.zip` archives in `examples/` (the `.epw`/`.ddy` members
are read straight from the zip). Generated files are written to `examples/generated/`
and the curated hand-built drafts in `examples/` are never touched. The EPW JSON
examples include the full hourly year (~3 MB); the DDY JSON examples are
design-conditions only (~10 KB).

## Canonical station metadata

`generate_examples.py` applies canonical overrides on import. For Chicago O'Hare it
uses **WMO `725300`** and **elevation `205 m`** (the ASHRAE row), overriding the
`201.8 m` the onebuilding EPW/DDY carry, so every generated artifact for Chicago -- JSON,
round-tripped EPW, round-tripped DDY -- reports the ASHRAE values.

## The tests

1. **`test_ddy_matches_ashrae`** -- the design conditions parsed out of each DDY file are
   *identical* (to the published 0.1-unit precision) to the matching row of the ASHRAE
   HOF 2025 spreadsheet. 47 design columns per station are compared against the committed
   extract. The EPW `DESIGN CONDITIONS` line, the DDY design days and the spreadsheet all
   map onto the same ASHRAE column letters, so the comparison is direct.
2. **`test_null_roundtrip_epw_json`** -- EPW has no blank/missing value (numeric sentinels
   99.9, 999, 9999 ...); the schema supports `null`. A sentinel becomes `null` on import and
   the same sentinel returns on export, and `null` survives a JSON serialisation
   round-trip (the `extra_examples/test_20251017.json` scenario).
3. **`test_roundtrip_json_epw` / `test_roundtrip_json_ddy`** -- the reverse converters are
   faithful: EPW -> JSON -> EPW -> JSON preserves the summary and every hourly value, and
   DDY -> JSON -> DDY -> JSON preserves the design conditions and the location.

## Notes / caveats

- **Units.** The ASHRAE "SI" sheet is *not* base SI (degC, kJ/kg, mm, degrees). The
  converters move to/from base SI (K, J/kg, m, radians). The DDY test compares in the
  spreadsheet's own units, so no conversion is involved there.
- **What the EPW header carries.** Only annual design conditions (columns P-CL). Monthly
  design tables, degree days, precipitation and solar live in the `.stat` file, so they
  are absent from an EPW-derived summary.
- **What the DDY carries.** The annual design conditions, *including* the enthalpy
  magnitudes (cols BE/BG/BI, in the design days' `Enthalpy at Maximum Dry-Bulb` field).
  It does not carry the extreme-max wet-bulb (BK) or the standard deviations of the
  extreme-annual values (BQ/BR/CC/CD).
- **Reverse-converter fidelity.** Quantities the model deliberately drops (humidity
  ratio, wind shelter factor, n-year return periods) come back **blank** in a generated
  EPW `DESIGN CONDITIONS` line; EPW fields the schema has no home for (extraterrestrial
  radiation, zenith luminance, visibility, ceiling, present weather, ...) come back as EPW
  missing-value sentinels; the other EPW header blocks (TYPICAL/EXTREME PERIODS, GROUND
  TEMPERATURES) are emitted empty; and the calendar is a single non-leap year. None of
  these affect the modeled data, which round-trips exactly.
- **Schema validation.** The schema YAML does not currently compile under `lattice` (a
  pre-existing `ashrae_grade` constraint-syntax issue), so these helpers target the
  documented v2.1 structure rather than a generated JSON Schema.
