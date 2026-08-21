# ASHRAE HOF design conditions -> DDY and the Climate Information data model

A companion to the Climate Information specification (`ClimateInformation`) and the worked
examples in `examples/`. The specification describes the data model itself -- its
structure, unit system, conventions, and rules. This document maps the ASHRAE *Handbook of
Fundamentals* (HOF) design conditions onto that model, and onto the EnergyPlus design-day
(DDY) file that is the usual way those conditions are distributed.

The ASHRAE design-conditions spreadsheet (`HOF_2025_Climate_Design_Conditions_SI.xlsx`,
single `Stations` sheet, 588 columns) is the primary source for the summary variable list.
This is the section-level map. Companions:

- `extra_docs/ashrae_dd_gap_analysis.md` (Part 1) -- the column-by-column cross-check of
  all 588 columns, and the YAML/JSON variable parity check.
- `extra_docs/epw_to_model_mapping.md` -- the EPW / TMY time-series format. An EPW's
  optional `DESIGN CONDITIONS` header is columns P-CL of this same table.

The converters in `tools/` implement these mappings in both directions
(`ddy_to_json.py` / `json_to_ddy.py`), and the round-trip is checked by the test suite.

## Reading the percentiles as design conditions

In ASHRAE terms, the low `percent_time_exceeded` values (0.4 / 1 / 2) are the cooling / hot
design conditions and the high values (99 / 99.6) are the heating / cold ones; both live in
the same `percent_exceedance` block. The ASHRAE Extreme Annual block maps directly onto the
`Statistics` `mean_minimum` / `mean_maximum` / `standard_deviation_minimum` /
`standard_deviation_maximum` members, and the Extreme Maximum Wet-Bulb and Max/Min
Precipitation onto `Statistics.maximum` / `minimum`. The two ASHRAE degree-day bases
(10 degC = 283.15 K and 18.3 degC = 291.45 K) are two entries in the degree-day arrays.

## Mapping to the data model

### Station information (cols A-O) -> `location`

| ASHRAE | Model | |
|---|---|---|
| Region | `wmo_region` | added |
| Country / Prov State / Station Name | `country_code` / `subdivision` / `name` | |
| WMO / WBAN | `wmo_station_id` / `wban_station_id` | |
| Lat / Lon / Elev | `latitude` / `longitude` / `elevation` | |
| TZ Offset | `time_zone_offset` | |
| Period / Climate Zone / Grade | `SourceDataPeriod` / `climate_zones` / `ashrae_grade` | |
| **StdP** | -- | *excluded -- derived from elevation (HOF Ch. 1)* |
| **TZ Code** | `iana_time_zone_code` instead | *the IANA code is stored in place of the ASHRAE code* |

### Design conditions -> `summary_data`

| ASHRAE section | Model representation |
|---|---|
| Heating DB (99.6/99.0), Cooling DB (0.4/1/2) | `dry_bulb_temperature.percent_exceedance` |
| Humidification DP (99.6/99.0), Dehumidification DP (0.4/1/2) | `dew_point_temperature.percent_exceedance` |
| Cooling MCWB | `dry_bulb_temperature_coincident_mean_wet_bulb_temperature` |
| Evaporation WB (0.4/1/2) | `wet_bulb_temperature.percent_exceedance` |
| Evaporation MCDB, Monthly-design-WB MCDB | `wet_bulb_temperature_coincident_mean_dry_bulb_temperature` |
| Humidification/Dehumidification MCDB | `dew_point_temperature_coincident_mean_dry_bulb_temperature` |
| Enthalpy (0.4/1/2) + MCDB | `enthalpy` + `enthalpy_coincident_mean_dry_bulb_temperature` |
| Extreme Max WB | `wet_bulb_temperature.annual.maximum` |
| Extreme Annual DB (mean/std of min/max) | `dry_bulb_temperature.annual.mean_minimum/...` |
| Extreme Annual WB (mean/std of min/max) | `wet_bulb_temperature.annual.mean_minimum/...` |
| MCWS / PCWD to 0.4%/99.6% DB | `..._coincident_mean_wind_speed` / `..._coincident_prevailing_wind_direction` |
| Average / Extreme Annual / Coldest-month wind speed | `wind_speed` (mean + percent_exceedance) |
| Coldest-month WS MCDB | `wind_speed_coincident_mean_dry_bulb_temperature` |
| Average Daily Temperature (+ its std) | `daily_average_dry_bulb_temperature` |
| HDD/CDD 10 degC & 18.3 degC | `heating_degree_days` / `cooling_degree_days` |
| Average / Max / Min / Std Precipitation | `liquid_precipitation_depth` (mean/maximum/minimum/standard_deviation) |
| Monthly Design DB (0.4/2/5/10) | `dry_bulb_temperature.monthly.percent_exceedance` |
| Monthly Design WB (0.4/2/5/10) | `wet_bulb_temperature.monthly.percent_exceedance` |
| Hottest/Coldest Month | `hottest_month` / `coldest_month` (convenience indices) |
| Hottest Month DB Range | = `daily_dry_bulb_temperature_range` at the hottest month |
| Mean Daily DB Range | `daily_dry_bulb_temperature_range` |
| Mean Daily DB/WB Range @ 5% design DB/WB | `daily_{dry,wet}_bulb_temperature_range_at_design_{dry,wet}_bulb_temperature` |
| Clear-Sky Optical Depth beam/diffuse (taub/taud) | `clear_sky_beam_optical_depth` / `clear_sky_diffuse_optical_depth` |
| All-Sky Avg/Std Monthly Global Horizontal Radiation | `daily_all_sky_solar_irradiation` (mean + standard_deviation) |

### The coincident variables, by ASHRAE quantity

| Model variable | ASHRAE quantity |
|---|---|
| `dry_bulb_temperature_coincident_mean_wet_bulb_temperature` | Cooling DB -> MCWB |
| `dry_bulb_temperature_coincident_mean_wind_speed` | MCWS to 0.4%/99.6% DB |
| `dry_bulb_temperature_coincident_prevailing_wind_direction` | PCWD to 0.4%/99.6% DB |
| `wet_bulb_temperature_coincident_mean_dry_bulb_temperature` | Evaporation WB -> MCDB |
| `dew_point_temperature_coincident_mean_dry_bulb_temperature` | Humidification/Dehumidification -> MCDB |
| `enthalpy_coincident_mean_dry_bulb_temperature` | Enthalpy -> MCDB |
| `wind_speed_coincident_mean_dry_bulb_temperature` | Coldest-month WS -> MCDB |

## Mapping to the EnergyPlus DDY

A DDY file is an EnergyPlus IDF fragment that carries the ASHRAE design conditions in two
forms: a `Site:Location` object, and a set of `SizingPeriod:DesignDay` objects preceded by
a block of `!` comment lines. The design conditions in a DDY and in the model are the same
ASHRAE columns, so the DDY is best read as a third encoding of this table rather than as an
independent source. `tools/ddy_to_json.py` reads it, `tools/json_to_ddy.py` writes it, and
both work through the same ASHRAE-column dictionary as the EPW reader
(`tools.climate_common.build_summary_data` / `summary_data_to_ashrae_cols`).

The DDY is the *preferred* design-condition source: an EPW's `DESIGN CONDITIONS` header
carries the same columns, but the DDY states each design point as an explicit design-day
object, so nothing has to be recovered by position.

### `Site:Location` -> `location`

`Site:Location, Name, Latitude, Longitude, TimeZone, Elevation`

| DDY | Model |
|---|---|
| Name (e.g. `Chicago.OHare.Intl.AP_IL_USA Design_Conditions`) | `name`, and `subdivision` / `country_code` split off the underscore-separated tail |
| Latitude / Longitude / TimeZone / Elevation | `latitude` / `longitude` / `time_zone_offset` / `elevation` |
| `! ... ASHRAE Climate Zone=` comment | `climate_zones[]` (`system` = `ASHRAE Ch. 14`) |
| *(none)* | `iana_time_zone_code` -- DDY stores only the offset; inferred as `Etc/GMT+/-N` |
| *(none)* | `anemometer_height` (10 m) / `station_height` (1.8 m) -- assumed |

### Design days -> `summary_data`

Each annual `SizingPeriod:DesignDay` encodes one ASHRAE design point as a maximum dry-bulb
temperature plus a coincident humidity value; the day's name identifies which point. The
converters recognise 18 annual days:

| Design-day name | Day type | Max Dry-Bulb (col) | Humidity condition type | Coincident humidity value (col) |
|---|---|---|---|---|
| `Ann Htg 99.6% Condns DB` | Winter | Q | Wetbulb | Q |
| `Ann Htg 99% Condns DB` | Winter | R | Wetbulb | R |
| `Ann Hum_n 99.6% Condns DP=>MCDB` | Winter | U | Dewpoint | S |
| `Ann Hum_n 99% Condns DP=>MCDB` | Winter | X | Dewpoint | V |
| `Ann Htg Wind 99.6% Condns WS=>MCDB` | Winter | Z | Wetbulb | Z |
| `Ann Htg Wind 99% Condns WS=>MCDB` | Winter | AB | Wetbulb | AB |
| `Ann Clg .4% Condns DB=>MWB` | Summer | AH | Wetbulb | AI |
| `Ann Clg 1% Condns DB=>MWB` | Summer | AJ | Wetbulb | AK |
| `Ann Clg 2% Condns DB=>MWB` | Summer | AL | Wetbulb | AM |
| `Ann Clg .4% Condns WB=>MDB` | Summer | AO | Wetbulb | AN |
| `Ann Clg 1% Condns WB=>MDB` | Summer | AQ | Wetbulb | AP |
| `Ann Clg 2% Condns WB=>MDB` | Summer | AS | Wetbulb | AR |
| `Ann Clg .4% Condns DP=>MDB` | Summer | AX | Dewpoint | AV |
| `Ann Clg 1% Condns DP=>MDB` | Summer | BA | Dewpoint | AY |
| `Ann Clg 2% Condns DP=>MDB` | Summer | BD | Dewpoint | BB |
| `Ann Clg .4% Condns Enth=>MDB` | Summer | BF | Enthalpy | BE (in `Enthalpy at Maximum Dry-Bulb`, J/kg) |
| `Ann Clg 1% Condns Enth=>MDB` | Summer | BH | Enthalpy | BG (as above) |
| `Ann Clg 2% Condns Enth=>MDB` | Summer | BJ | Enthalpy | BI (as above) |

Each design day also carries a wind speed and direction. Which ASHRAE columns those are
depends on the day: the cooling days carry the cooling MCWS/PCWD (AT/AU), the
coldest-month `WS=>MCDB` days carry the coldest-month design wind speed itself (Y for
99.6%, AA for 99%), and the remaining heating days carry the heating MCWS/PCWD (AC/AD).

Note that the enthalpy *magnitudes* (BE/BG/BI) are optional in practice: the
climate.onebuilding DDYs leave the `Enthalpy at Maximum Dry-Bulb` field blank, so a DDY
from that source yields the enthalpy MCDB but not the enthalpy itself. DDYs written by
`json_to_ddy.py` do fill the field, which is what makes the round-trip exact.

### Daily ranges and the solar model

Each design day also states the mean daily temperature ranges and the clear-sky optical
depths **for its own month**, so these are read and written per design day rather than by
column letter. Which range a day reports depends on the design variable it is built
around:

| Design day | `Daily Dry-Bulb Temperature Range` | `Daily Wet-Bulb Temperature Range` |
|---|---|---|
| `DB=>MWB` | `daily_dry_bulb_temperature_range_at_design_dry_bulb_temperature` | `daily_wet_bulb_temperature_range_at_design_dry_bulb_temperature` |
| `WB=>MDB` | `daily_dry_bulb_temperature_range_at_design_wet_bulb_temperature` | `daily_wet_bulb_temperature_range_at_design_wet_bulb_temperature` |
| `DP=>MDB`, `Enth=>MDB` | `daily_dry_bulb_temperature_range` | *(blank)* |
| the winter days | `0.0` | *(blank)* |

The winter days are not an omission: a heating design day deliberately has no diurnal
swing and no solar gain, so real DDYs give it a `0.0` range and the `ASHRAEClearSky` model
with `Clearness` at `0.00` and no optical depths. The summer days use `ASHRAETau2017` with
the month's `clear_sky_beam_optical_depth` (taub) and `clear_sky_diffuse_optical_depth`
(taud), and carry no `Clearness` field at all.

Because a design day speaks only for its own month, a DDY-derived document populates the
design months and leaves the other entries of each 12-month array empty -- for the example
stations, only July, since both put every cooling day in the hottest month.

### Statistics carried in the comment block

The `!` comment lines above the design days carry the statistics that have no design-day
representation:

| DDY comment | ASHRAE cols | Model |
|---|---|---|
| `Extreme Annual Wind Speeds, 1%=, 2.5%=, 5%=` | BL / BM / BN | `wind_speed.annual.percent_exceedance` |
| `Extreme Annual Temperatures, Max Drybulb= Min Drybulb=` | BP / BO | `dry_bulb_temperature.annual.mean_maximum` / `mean_minimum` |
| `Extreme Annual Temperatures, Max Wetbulb= Min Wetbulb=` | CB / CA | `wet_bulb_temperature.annual.mean_maximum` / `mean_minimum` |
| `Annual Heating Design Conditions Wind Speed= Wind Dir=` | AC / AD | `dry_bulb_temperature_coincident_mean_wind_speed` / `..._prevailing_wind_direction` |
| `Annual Cooling Design Conditions Wind Speed= Wind Dir=` | AT / AU | as above, at the cooling percentile |
| `Coldest Month=` / `Hottest Month=` | P / AF | `coldest_month` / `hottest_month` |
| `ASHRAE Climate Zone=` | N | `location.climate_zones[]` |

### What a DDY cannot carry

A DDY is a design-conditions file only, so a DDY-derived document is a strict subset of an
ASHRAE-derived one. Absent from the output:

- **Extreme Maximum Wet-Bulb (BK)** -- no design-day or comment slot.
- **Standard deviations of the extreme annual values (BQ/BR, CC/CD)** -- the comment block
  carries the means only.
- **Most of what follows column CM** -- average daily temperature, degree days, monthly
  and annual average wind speed, precipitation, and the all-sky solar columns. These live
  in the `.stat` file. The mean daily ranges (PJ-RQ) and the clear-sky optical depths
  (RR-SO) are the exception: a design day states them for its own month, so a DDY carries
  those months and nothing else.
- **The monthly design DB/WB tables (HZ-PI).** A DDY does hold monthly design days, but
  neither converter reads or writes them yet -- only the 18 annual days above.
- **Any time series.** A DDY has no hourly records; pair it with an EPW for those (the
  converters merge an EPW and a DDY into one document when both are present).

One field is regenerated rather than carried: `json_to_ddy.py` recomputes
`Barometric Pressure` from `elevation` via the US standard atmosphere, which is the ASHRAE
StdP column (J) the model deliberately excludes as derivable.

## ASHRAE quantities deliberately omitted

The model is not a 1:1 re-encoding of the ASHRAE table. Two principles drive exclusion:
derivable quantities are kept out of the base model where the cost of including them
outweighs the convenience (providers can pre-compute them into an ASHRAE-flavour
extension); and obsolete quantities whose use cases no longer exist are dropped.

| Excluded | Cols | Reason |
|---|---|---|
| Clear-Sky Noon Beam Normal Irradiance (21st) | SP-TA | Derivable from `taub` via the HOF Ch. 14 clear-sky model. |
| Clear-Sky Noon Diffuse Horizontal Irradiance (21st) | TB-TM | Derivable from `taud`. |
| n-Year Return Period Extreme **DB** | BS-BZ | Derivable from the extreme-annual mean/std (Gumbel/empirical mixture, HOF Ch. 14). |
| n-Year Return Period Extreme **WB** | CE-CL | Same as above. |
| Humidity ratio (HR) -- humidification **and** dehumidification | T, W, AW, AZ, BC | Derivable from dew point + station pressure. |
| Wind Shelter Factor (WSF) | AE | Obsolete (ASHRAE 62.2-specific). |
| Historical Trends (Station/Regional Trends, Variability, Neighbors) | UL-VP | Committee decided trends are out of scope for the base model. |
| Standard station pressure (StdP) | J | Derived from `elevation` (HOF Ch. 1). |
| ASHRAE TZ Code | L | The IANA time-zone code is stored instead. |

### Included despite being derivable

By explicit decision, the following derivable quantities are carried in the base model
(they round-trip the ASHRAE table without a separate extension):

- Enthalpy + coincident MCDB.
- Hottest/Coldest month indices and the mean daily temperature ranges (including the four
  coincident-with-5%-design ranges).
- Max/Min precipitation (via `Statistics.maximum` / `minimum`).
