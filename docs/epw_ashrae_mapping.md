# Climate Information Data Model -- External Format Mappings

A companion to the Climate Information specification (`ClimateInformation`) and the worked
examples in `examples/`. The specification describes the data model itself -- its
structure, unit system, conventions, and rules. This document maps two widely used
external climate formats onto that model: the ASHRAE Handbook of Fundamentals (HOF) design
conditions and the EnergyPlus Weather (EPW / TMY) format. The converters in `tools/`
implement these mappings in both directions, and the round-trip is checked by the test
suite.

## Mapping: ASHRAE Handbook of Fundamentals design conditions

The ASHRAE design-conditions spreadsheet (`HOF_2025_Climate_Design_Conditions_SI.xlsx`,
single `Stations` sheet, 588 columns) is the primary source for the summary variable list.
This is the section-level map.

### Reading the percentiles as design conditions

In ASHRAE terms, the low `percent_time_exceeded` values (0.4 / 1 / 2) are the cooling / hot
design conditions and the high values (99 / 99.6) are the heating / cold ones; both live in
the same `percent_exceedance` block. The ASHRAE Extreme Annual block maps directly onto the
`Statistics` `mean_minimum` / `mean_maximum` / `standard_deviation_minimum` /
`standard_deviation_maximum` members, and the Extreme Maximum Wet-Bulb and Max/Min
Precipitation onto `Statistics.maximum` / `minimum`. The two ASHRAE degree-day bases
(10 degC = 283.15 K and 18.3 degC = 291.45 K) are two entries in the degree-day arrays.

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

### ASHRAE quantities deliberately omitted

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

#### Included despite being derivable

By explicit decision, the following derivable quantities are carried in the base model
(they round-trip the ASHRAE table without a separate extension):

- Enthalpy + coincident MCDB.
- Hottest/Coldest month indices and the mean daily temperature ranges (including the four
  coincident-with-5%-design ranges).
- Max/Min precipitation (via `Statistics.maximum` / `minimum`).

## Mapping: EnergyPlus Weather (EPW / TMY)

The EnergyPlus Weather format (`.epw`, and the closely related TMY/DDY files) is
fundamentally a time-series format with an optional design-conditions header. See the
original EPW documentation at
https://climate.onebuilding.org/papers/EnergyPlus_Weather_File_Format.pdf.

### `LOCATION` line -> `location`

`LOCATION, City, State, Country, Source, WMO, Lat, Lon, TZ, Elevation`

| EPW field | Model |
|---|---|
| City / State / Country | `name` / `subdivision` / `country_code` |
| WMO | `wmo_station_id` |
| Lat / Lon / TZ / Elevation | `latitude` / `longitude` / `time_zone_offset` / `elevation` |
| *(none)* | `iana_time_zone_code` -- EPW has no IANA code; inferred as `Etc/GMT+/-N` from the offset |
| *(none)* | `anemometer_height` (10 m) / `station_height` (1.8 m) -- assumed |

### `DESIGN CONDITIONS` line -> `summary_data`

The EPW `DESIGN CONDITIONS` header is the ASHRAE spreadsheet columns P-CL laid end to end
(`Heating` = P-AE, `Cooling` = AF-BK, `Extremes` = BL-CL). It maps to the annual design
conditions exactly as in the Design conditions mapping above. It is the only summary an EPW
carries -- everything from spreadsheet column CM onward (degree days, monthly design
tables, precipitation, solar) lives in the `.stat` file, not the EPW. The header is
optional, so the converter treats it as opt-in.

### Hourly records (35 fields) -> `time_series`

| EPW field (index) | Model `ClimateTimeSeries` variable | Conversion to base SI |
|---|---|---|
| Dry-bulb temperature (6) | `dry_bulb_temperature` | degC -> K |
| Dew-point temperature (7) | `dew_point_temperature` | degC -> K |
| Relative humidity (8) | `relative_humidity` | % -> fraction |
| Atmospheric pressure (9) | `atmospheric_pressure` | Pa (as-is) |
| Horizontal IR sky (12) | `horizontal_infrared_sky_irradiance` | Wh/m2-h ~= W/m2 |
| Global horizontal radiation (13) | `global_horizontal_irradiation` (SUM) | Wh/m2 -> J/m2 (x3600) |
| Direct normal radiation (14) | `direct_normal_irradiation` (SUM) | Wh/m2 -> J/m2 |
| Diffuse horizontal radiation (15) | `diffuse_horizontal_irradiation` (SUM) | Wh/m2 -> J/m2 |
| Global/Direct/Diffuse illuminance (16/17/18) | `*_illuminance` | lux (as-is) |
| Wind direction (20) | `wind_direction` | degrees -> radians |
| Wind speed (21) | `wind_speed` | m/s (as-is) |
| Total / Opaque sky cover (22/23) | `total_sky_cover` / `opaque_sky_cover` | tenths -> fraction |
| Precipitable water (28) | `precipitable_water` | mm -> m |
| Aerosol optical depth (29) | `aerosol_optical_depth` | unitless |
| Snow depth (30) | `snow_depth` | cm -> m |
| Albedo (32) | `albedo` | unitless |
| Liquid precipitation depth (33) | `liquid_precipitation_depth` (SUM) | mm -> m |

EPW reports radiation as energy received over the hour (Wh/m2), so it maps to the model's
irradiation (`J/m2`, `value_type = SUM`) variables rather than the instantaneous irradiance
(`W/m2`) ones. The date/time columns are not stored as variables -- they are encoded in the
`TimeInterval` instead.

### EPW / TMY exclusions and missing values

#### EPW fields with no model home

Year/Month/Day/Hour/Minute (encoded in the `TimeInterval` instead), the
data-source/uncertainty flag string, extraterrestrial horizontal & direct-normal radiation
(10/11), zenith luminance (19), visibility (24), ceiling height (25), present-weather
observation & codes (26/27), days since last snowfall (31), and liquid-precipitation
quantity/hours (34).

#### Model time-series variables not present in an EPW

`wet_bulb_temperature`, `humidity_ratio`, the instantaneous irradiance forms
(`global/direct/diffuse_*_irradiance`), `sky_type`, and the whole air-quality / pollutant
set (`particulate_matter_*`, `carbon_dioxide`, `nitrogen_dioxide`, `nitrogen_oxide`,
`sulphur_dioxide`, `ozone`, `ammonia`, `carbon_monoxide`, `formaldehyde`, `benzene`, `voc`,
`turbidity`, `lead`, `mercury`).

#### Missing values: EPW sentinels and model null

EPW has no blank/missing concept -- every field carries a numeric sentinel (99.9 degC for
temperature, 999 for %/direction/speed, 9999 for Wh/m2, 999999 for pressure/illuminance,
...). The model supports an explicit `null`, so on import each sentinel becomes `null` and
on export each `null` returns to the sentinel (round-trip-checked by the test suite). On
reverse conversion, quantities the model deliberately omits (humidity ratio, wind shelter
factor, n-year return periods) come back blank, and the EPW fields listed above come back
as their sentinels. The modeled data round-trips exactly.
