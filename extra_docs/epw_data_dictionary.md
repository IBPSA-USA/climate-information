# EnergyPlus Weather File (EPW) Data Dictionary

> **Local reference copy.** Transcribed 2026-07-03 from the Big Ladder Software mirror of
> the EnergyPlus Auxiliary Programs documentation:
> <https://bigladdersoftware.com/epx/docs/8-3/auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html>
>
> Kept in-repo so the EPW <-> Climate Information converters (`tools/epw_to_json.py`,
> `tools/json_to_epw.py`) can be validated against a stable snapshot of the format. The
> field-by-field mapping onto the schema -- and which fields the converter carries -- is in
> `docs/ashrae_dd_gap_analysis.md` (Part 2). Numeric *missing* / *min* / *max* values below
> are reproduced exactly as published.
>
> **License:** Documentation copyright (c) 1996-2015 The Board of Trustees of the University
> of Illinois and the Regents of the University of California, made available under the
> [EnergyPlus Open Source License v1.0](http://bigladdersoftware.com/epx/open_source_agreement.pdf).

---

## Overview

An EPW file is a set of **header records** followed by **hourly weather data records**.
Semicolons do not terminate lines. The format follows IDD (Input Data Dictionary)
conventions, using backslash notations for constraints:

- `\minimum` / `\minimum>` -- values must be >= or > the specified number
- `\maximum` / `\maximum<` -- values must be <= or < the specified number
- `\missing` -- a value >= this number indicates missing data
- `\default` -- default value for blank fields
- `\units` -- expected measurement units

---

## Header Records

### LOCATION

Geographic and reference information for the weather-file location.

| Field | Type | Description | Units | Range / Notes |
|---|---|---|---|---|
| City | Alpha | Location city name | -- | -- |
| State/Province/Region | Alpha | State, province, or region | -- | -- |
| Country | Alpha | Country name | -- | -- |
| Source | Alpha | Data source identifier | -- | -- |
| WMO | Alpha | World Meteorological Organization number (typically 6 digits) | -- | Used for design-condition matching |
| Latitude | Real | Geographic latitude | degrees | -90.0 ... +90.0; + is North, - is South |
| Longitude | Real | Geographic longitude | degrees | -180.0 ... +180.0; - is West, + is East |
| Time Zone | Real | Offset from GMT | hours | -12.0 ... +12.0 |
| Elevation | Real | Station elevation | meters | -1000.0 ... +9999.9 |

*Location-header values override any Location object in the input file when a RunPeriod is used.*

### DESIGN CONDITIONS

Design-day conditions matched to the location by WMO number (typically ASHRAE Handbook of
Fundamentals, Canadian, or World design conditions).

| Field | Type | Description |
|---|---|---|
| Number of Design Conditions | Numeric | Count of condition sets |
| Design Condition Source | Alpha | Source reference (e.g. "ASHRAE HOF 2009 US Design Conditions") |
| Design Condition Type (Heating) | Alpha | Heating design parameters (format varies by source) |
| Design Condition Type (Cooling) | Alpha | Cooling design parameters (format varies by source) |

*Detailed design-condition data are shown in the audit (.rpt) and CSV output files from WeatherConverter.*

### TYPICAL/EXTREME PERIODS

Heuristically identified typical and extreme weather periods within the annual data.

| Field | Type | Description |
|---|---|---|
| Number of Typical/Extreme Periods | Numeric | Count of periods identified |
| Period Name | Alpha | Descriptive label (e.g. "Winter Design Day") |
| Period Type | Alpha | Classification (e.g. "Extreme Cold Week") |
| Period Start Day | Alpha | Start date (date-format options below) |
| Period End Day | Alpha | End date |

**Date-format options** (used by several header records):

- `<number>` -- Julian day of year
- `<number>/<number>` -- Month/Day
- `<number> Month` -- Day and Month (e.g. "15 January")
- `Month <number>` -- Month and Day (e.g. "January 15")
- First 3 letters of month/weekday names are acceptable abbreviations.

### GROUND TEMPERATURES

Monthly undisturbed ground temperatures at specified depths, with soil properties.
Calculated by WeatherConverter from the annual weather data.

| Field | Type | Units | Description |
|---|---|---|---|
| Number of Ground Temperature Depths | Numeric | -- | Count of depth levels |
| Ground Temperature Depth *N* | Numeric | m | Depth of soil-temperature measurement |
| Depth *N* Soil Conductivity | Numeric | W/m-K | Thermal conductivity |
| Depth *N* Soil Density | Numeric | kg/m3 | Mass density |
| Depth *N* Soil Specific Heat | Numeric | J/kg-K | Heat capacity |
| Depth *N* Jan-Dec Average Temps | Numeric (x12) | degC | Monthly ground temperatures |

*"Undisturbed" temperatures are reference-only and too extreme for building-loss
calculations; use the Slab/Basement preprocessors, or ~2 degC below average indoor space
temperature for typical US commercial buildings.*

### HOLIDAYS/DAYLIGHT SAVINGS

| Field | Type | Description |
|---|---|---|
| Leap Year Observed | Choice (Yes/No) | Whether February 29 is included |
| Daylight Saving Start Day | Alpha | Period start date (date format) |
| Daylight Saving End Day | Alpha | Period end date |
| Number of Holidays | Numeric | Count of special days |
| Holiday *N* Name | Alpha | Holiday label |
| Holiday *N* Day | Alpha | Holiday date (date format) |

*EnergyPlus-processed files from the official site typically omit special days and daylight-saving definitions.*

### COMMENTS 1 / COMMENTS 2

Two optional free-text records for metadata or source/processing information.

### DATA PERIODS

Describes the structure and coverage of the hourly data blocks.

| Field | Type | Description | Notes |
|---|---|---|---|
| Number of Data Periods | Numeric | Count of distinct data blocks | -- |
| Number of Records per Hour | Numeric | Time steps per hour | Must match the RunPeriod setting |
| Data Period *N* Name/Description | Alpha | Period label | -- |
| Data Period *N* Start Day of Week | Choice | Day of week of the first record | Sunday ... Saturday |
| Data Period *N* Start Day | Alpha | Period start date (date format) | -- |
| Data Period *N* End Day | Alpha | Period end date (date format) | -- |

*RunPeriod objects cannot cross DataPeriod boundaries; multiple records per hour must match the simulation timestep.*

---

## Weather Data -- Hourly Records

Each data line is comma-separated: 34 numeric fields (N1-N34) plus the data-source /
uncertainty flag string (A1). Field order below is authoritative.

### Timestamp fields (N1-N5) and flags (A1)

| # | Field | Units | Range | Missing | Notes |
|---|---|---|---|---|---|
| N1 | Year | -- | -- | -- | Display only; not used by EnergyPlus |
| N2 | Month | -- | 1-12 | Cannot be missing | -- |
| N3 | Day | -- | 1-31 | Cannot be missing | -- |
| N4 | Hour | -- | 1-24 | Cannot be missing | Hour 1 = 00:01-01:00 |
| N5 | Minute | -- | 1-60 | -- | -- |
| A1 | Data Source and Uncertainty Flags | -- | -- | -- | Consolidated source/uncertainty indicators from the original data format |

### Temperature & moisture (N6-N9)

| # | Field | Units | Min | Max | Missing | Notes |
|---|---|---|---|---|---|---|
| N6 | Dry Bulb Temperature | degC | >-70 | <70 | 99.9 | Full precision (e.g. 23.6) |
| N7 | Dew Point Temperature | degC | >-70 | <70 | 99.9 | Full precision |
| N8 | Relative Humidity | % | 0 | 110 | 999 | -- |
| N9 | Atmospheric Station Pressure | Pa | >31000 | <120000 | 999999 | Barometric pressure |

### Radiation (N10-N15)

| # | Field | Units | Min | Missing | Notes |
|---|---|---|---|---|---|
| N10 | Extraterrestrial Horizontal Radiation | Wh/m2 | 0 | 9999 | Not currently used by EnergyPlus |
| N11 | Extraterrestrial Direct Normal Radiation | Wh/m2 | 0 | 9999 | Not currently used |
| N12 | Horizontal Infrared Radiation Intensity | Wh/m2 | 0 | 9999 | Calculated from opaque sky cover if missing (see below) |
| N13 | Global Horizontal Radiation | Wh/m2 | 0 | 9999 | Direct + diffuse on a horizontal surface |
| N14 | Direct Normal Radiation | Wh/m2 | 0 | 9999 | Missing or <0 values set to 0 |
| N15 | Diffuse Horizontal Radiation | Wh/m2 | 0 | 9999 | Missing or <0 values set to 0 |

**Horizontal IR, if missing** -- computed as `HorizontalIR = eps_sky * sigma * T_drybulb^4`, with
sigma = 5.6697e-8 W/m2-K4 (Stefan-Boltzmann) and
`eps_sky = (0.787 + 0.764*ln(T_dewpoint/273.0)) * (1 + 0.0224N - 0.0035N^2 + 0.00028N^3)`,
where `T_dewpoint` is in K and `N` is opaque sky cover in tenths.

### Illuminance & luminance (N16-N19)

| # | Field | Units | Min | Missing | Notes |
|---|---|---|---|---|---|
| N16 | Global Horizontal Illuminance | lux | 0 | 999999 | Not currently used; **missing if >= 999900** |
| N17 | Direct Normal Illuminance | lux | 0 | 999999 | Not currently used; **missing if >= 999900** |
| N18 | Diffuse Horizontal Illuminance | lux | 0 | 999999 | Not currently used; **missing if >= 999900** |
| N19 | Zenith Luminance | Cd/m2 | 0 | 9999 | Not currently used; missing if >= 9999 |

### Wind (N20-N21)

| # | Field | Units | Min | Max | Missing | Notes |
|---|---|---|---|---|---|---|
| N20 | Wind Direction | degrees | 0 | 360 | 999 | N=0deg, E=90deg, S=180deg, W=270deg; 0 if calm |
| N21 | Wind Speed | m/s | 0 | 40 | 999 | -- |

### Sky cover (N22-N23)

| # | Field | Units | Min | Max | Missing | Notes |
|---|---|---|---|---|---|---|
| N22 | Total Sky Cover | tenths | 0 | 10 | 99 | 1 = 1/10 covered, 10 = fully covered |
| N23 | Opaque Sky Cover | tenths | 0 | 10 | 99 | Used to calculate IR intensity if N12 missing |

### Visibility & ceiling (N24-N25)

| # | Field | Units | Missing | Notes |
|---|---|---|---|---|
| N24 | Visibility | km | 9999 | Not currently used |
| N25 | Ceiling Height | m | 99999 | 77777 = unlimited; 88888 = cirroform; not used |

### Present weather (N26-N27)

| # | Field | Format | Values | Notes |
|---|---|---|---|---|
| N26 | Present Weather Observation | single digit | 0 = observed; 9 = missing | Indicates whether the weather codes are present |
| N27 | Present Weather Codes | 9 single digits | 0-9 per position | TMY2 convention; see table below |

**Present-weather codes (9-position field):**

| Position | Element | Values |
|---|---|---|
| 1 | Thunderstorm / Tornado / Squall | 0=TS (<25.7 m/s); 1=Severe TS (>25.7 m/s); 2=Tornado/waterspout; 4=Squall; 6=Waterspout; 7=Funnel cloud; 8=Tornado; 9=None/Unknown |
| 2 | Rain / Rain Showers / Freezing Rain | 0=Light; 1=Moderate; 2=Heavy; 3=Light showers; 4=Moderate showers; 5=Heavy showers; 6=Light freezing; 7=Moderate freezing; 8=Heavy freezing; 9=None/Unknown |
| 3 | Rain Squalls / Drizzle / Freezing Drizzle | 0=Light squalls; 1=Moderate squalls; 3=Light drizzle; 4=Moderate drizzle; 5=Heavy drizzle; 6=Light freezing; 7=Moderate freezing; 8=Heavy freezing; 9=None/Unknown |
| 4 | Snow / Snow Pellets / Ice Crystals | 0=Light snow; 1=Moderate snow; 2=Heavy snow; 3=Light pellets; 4=Moderate pellets; 5=Heavy pellets; 6=Light crystals; 7=Moderate crystals; 8=Heavy crystals; 9=None/Unknown |
| 5 | Snow Showers / Squalls / Grains | 0=Light snow; 1=Moderate showers; 2=Heavy showers; 3=Light squall; 4=Moderate squall; 5=Heavy squall; 6=Light grains; 7=Moderate grains; 9=None/Unknown |
| 6 | Sleet / Sleet Showers / Hail | 0=Light ice-pellet showers; 1=Moderate showers; 2=Heavy showers; 4=Hail; 9=None/Unknown |
| 7 | Fog / Blowing Dust / Blowing Sand | 0=Fog; 1=Ice fog; 2=Ground fog; 3=Blowing dust; 4=Blowing sand; 5=Heavy fog; 6=Glaze; 7=Heavy ice fog; 8=Heavy ground fog; 9=None/Unknown |
| 8 | Smoke / Haze / Blowing Snow / Spray / Dust | 0=Smoke; 1=Haze; 2=Smoke+haze; 3=Dust; 4=Blowing snow; 5=Blowing spray; 6=Dust storm; 7=Volcanic ash; 9=None/Unknown |
| 9 | Ice Pellets | 0=Light; 1=Moderate; 2=Heavy; 9=None/Unknown |

*Example: codes "929999999" with observation 0 indicate heavy rain during the period.*

### Atmospheric & precipitation tracers (N28-N34)

| # | Field | Units | Missing | Notes |
|---|---|---|---|---|
| N28 | Precipitable Water | mm | 999 | Not current usage; reporting unreliable |
| N29 | Aerosol Optical Depth | thousandths | 0.999 | Not currently used |
| N30 | Snow Depth | cm | 999 | Indicates snow on ground; affects surface reflectance |
| N31 | Days Since Last Snowfall | -- | 99 | Not currently used |
| N32 | Albedo | unitless | 999 | Ratio of reflected to global solar; not used |
| N33 | Liquid Precipitation Depth | mm | 999 | Overrides weather codes if present; set to 1.5 if codes show rain but this is missing |
| N34 | Liquid Precipitation Quantity | hours | 99 | Accumulation period; not currently used |

---

## References

- Walton, G. N. 1983. *Thermal Analysis Research Program Reference Manual.* NBSSIR 83-2655. National Bureau of Standards.
- Clark, G. and C. Allen. 1978. "The Estimation of Atmospheric Radiation for Clear and Cloudy Skies." *Proceedings 2nd National Passive Solar Conference (AS/ISES)*, 675-678.
