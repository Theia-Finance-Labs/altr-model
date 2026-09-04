# Input data

The model is fed by exactly three CSV files. The [quickstart](quickstart.md)
places them in `data/01_raw/` and converts them with
`scripts/prepare_inputs.py`; this page is the column-level contract for what is
inside them.

The deliverables schema and the model-input schema are the same data under one
renamed column: the raw scenarios file carries `scenario_name`, which
`prepare_inputs.py` renames to `scenario` - deliver `scenario_name`; every
other column below is identical in both schemas. Everything else the script
does is validation: every required column below is checked before anything is
written, so a schema problem stops the script with a named missing column
rather than leaving `data/05_model_input/` half-converted. The check is
presence-only - dtypes and value ranges are not validated here. The scale and
tier guards run inside the pipeline, and stage 4 coerces every numeric column
(`pd.to_numeric(errors="coerce")`), so an unparseable value becomes `NaN`
silently rather than an error - see
[Stage 4](pipelines/calculate_asset_earnings.md).

## `assets_forecasts.csv`

Physical power-generation assets and their technical characteristics -
capacity, technology, location, age - one row per asset per forecast year.

| Column | Type | Meaning |
| --- | --- | --- |
| `asset_id` | string | Unique identifier for the physical asset. |
| `sector` | string | Economic sector the asset belongs to. |
| `technology` | string | Technology the asset uses within its sector. |
| `year` | int | Year this row's forecast values apply to. |
| `capacity_unit` | string | Unit label for `capacity`. Carried to outputs, never read for conversion - deliver `MW`. |
| `capacity` | float | Nameplate capacity of the asset in that year, in **MW**. Every scenario cost column is per-MW and nothing converts units anywhere - a GW-scale value silently multiplies against per-MW costs. |
| `asset_age` | float | Age of the asset, in years, as of that row's year. |
| `country_iso2` | string | ISO 3166-1 alpha-2 code of the asset's country. |
| `country_name` | string | Human-readable name of the asset's country. |
| `asset_name` | string | Human-readable name of the asset. |
| `latitude` | float | Asset location, latitude. |
| `longitude` | float | Asset location, longitude. |
| `age_is_inferred` | bool | Whether `asset_age` was inferred rather than sourced directly. |
| `capacity_factor` | float | Fraction of nameplate capacity the asset is expected to run at. Note: the earnings formulas read the *scenario-side* factor - `scenario_capacity_factor` reaches them renamed to `capacity_factor` (see the rename table below). |
| `emission_factor` | float | Emissions per MWh of output, in **tonnes CO2 per MWh** - the carbon charge is `Q [MWh] × carbon_price [USD/tCO2] × emission_factor`, so only tCO2/MWh yields USD. A kg-scale factor passes every validation and inflates the carbon bill 1000×. |

Two of these columns do more than they look like they do. `asset_age` is not
used as-is - the model wraps it modulo the technology lifetime before dating
retirement (see
[Methodology notes](methodology_notes.md#asset-retirement-refurbishment-wrap-around-not-a-hard-cutoff)) -
and `country_iso2` is the key that assigns each asset its scenario geography
(see
[Methodology notes](methodology_notes.md#how-assets-are-matched-to-a-scenario-geography)).

## `companies_ownerships.csv`

Which companies own which assets, and to what degree - one row per
asset-company ownership link per year.

| Column | Type | Meaning |
| --- | --- | --- |
| `asset_id` | string | Unique identifier for the physical asset. |
| `asset_name` | string | Human-readable name of the asset. |
| `company_id` | string | Unique identifier for the owning company. |
| `company_name` | string | Human-readable name of the owning company. |
| `sector` | string | Economic sector the asset belongs to. |
| `technology` | string | Technology the asset uses within its sector. |
| `year` | int | Year this ownership link applies to. |
| `ownership_percentage` | float | Share of the asset owned by the company, on the **0-100 percent scale**. |
| `ownership_type` | string | Which rung of the ownership tree the row records: `direct` or `equity`. Matching is case- and whitespace-insensitive; any other value raises rather than silently selecting the wrong tier. |
| `ownership_level` | int | Alternative to `ownership_type`: numbers the rungs - `1` = direct, `2` and above = indirect/equity. Under this schema the configured `ownership_type: "direct"` selects level 1, `"indirect"`/`"equity"` select levels 2+, and a bare number selects exactly that level. Deliver one of the two columns, not both. |

!!! warning "The ownership tier column is required"
    A companies file carrying neither `ownership_type` nor `ownership_level`
    is rejected by `scripts/prepare_inputs.py` with a `ValueError` naming the
    column. It is not an optional refinement: the tiers are alternative views
    of the same capacity, so without one the whole ownership chain enters the
    run and the same plant is allocated to every rung that claims it. On the
    2026-08-25 deliverables drop, which predates the column, 92% of
    asset-years summed above 105% (median 227%). If your drop lacks it, ask
    for a re-export that includes `ownership_type` rather than converting
    what you have.

!!! warning "Percent scale, not fraction"
    `ownership_percentage` is on the 0-100 scale: a half-owned asset carries
    `50`, not `0.5`. The methodology PDF describes it as a fraction - that is
    wrong for this package, and the model enforces the percent scale at run
    time (`ValueError: ownership_percentage looks like a 0-1 fraction`). The
    guard trips when the column's **maximum is at or below 1.5** - which also
    means a portfolio whose largest genuine stake is under 1.5% is rejected as
    fraction-scaled. Rescale a fraction-convention extract upstream; see
    [Troubleshooting](troubleshooting.md#valueerror-ownership_percentage-looks-like-a-0-1-fraction-max).

How the stakes a company holds in one asset-year combine is set by
`ownership_aggregation`. Under `"tier_filter"` (the default) they are tiered
first, then consolidated: `ownership_type` picks one rung of the ownership tree,
and the stakes **within that rung** are summed into a single row before the run.
Under `"sum"` no rung is dropped - direct and equity holdings are totalled per
company-asset-year, the reading TRISK uses. Absolute outputs are not comparable
between the two modes.

`prepare_inputs.py` also checks over-allocation - on the **delivered rows,
before any tier is selected**: it totals `ownership_percentage` per
`(asset_id, year)` across every rung and warns when more than 1% of asset-years
exceed 105%. Two consequences of that design: a correct multi-tier file
legitimately totals above 100% raw (each rung is an alternative view of the
same capacity), which is why the threshold is a share, not a single row; and
below the 1% share the check stays **silent**, so a quiet run is not proof of a
clean ownership universe. Under `ownership_aggregation: "sum"` the warning is
expected, not a data fault. Details:
[Stage 1](pipelines/prepare_scenario_asset_and_company_inputs.md) and
[Troubleshooting](troubleshooting.md#companies-n-of-asset-years-sum-to-105-warning-not-an-error).

## `scenarios.csv`

Climate transition scenario pathways - projected prices, capacity, efficiency
and cost assumptions per scenario, technology, geography and year. These are
the reference trajectories used to extend assets' and companies' production
paths and to price their forecast earnings. One row per
scenario/technology/geography/year.

| Column | Type | Meaning |
| --- | --- | --- |
| `scenario_provider` | string | The IAM that produced the scenario (e.g. a `WITCH` or `AIM/CGE` release). Both members of a run's scenario pair must share it. |
| `scenario_name` | string | Identifier of the climate scenario/pathway model run, with the `AR6_<provider>_` prefix already in place - nothing downstream adds it. Renamed to `scenario` by the conversion; the only column whose name differs between the two schemas. |
| `scenario_type` | string | Whether the row belongs to a `baseline` or a `target` pathway in the source taxonomy. Informational on input: the pipeline overwrites it from the configured `baseline_scenario` / `target_scenario`, so a scenario's role in a run comes from the parameters, not from this column. |
| `scenario_geography` | string | Geography the pathway applies to. |
| `sector` | string | Economic sector the pathway applies to. |
| `technology` | string | Technology the pathway applies to within its sector. |
| `technology_type` | string | Carbon classification of the technology (`carbontech` / `greentech`). |
| `scenario_price` | float | Output (power) price under this scenario, in **USD per MWh, real terms, excluding carbon**. The carbon charge is added separately from `carbon_price_usd_per_tco2`, so a carbon-inclusive price double-charges every carbontech asset. |
| `scenario_pathway` | float | Projected production/capacity pathway value for this row. |
| `scenario_capacity_factor` | float | Fraction of nameplate capacity assumed under this scenario. |
| `year` | int | Year this row's pathway values apply to. |
| `country_iso2_list` | string (comma-list) | ISO 3166-1 alpha-2 codes of the countries covered by `scenario_geography`. |
| `lifetime_years` | float | Assumed operating lifetime of the technology, in years. |
| `efficiency_decimal` | float | Conversion efficiency of the technology, as a fraction. Deliver `1.0` for non-fuel technologies (solar, wind, hydro, nuclear, geothermal) - the fuel cost divides by this column, and a zero divides by zero. |
| `capital_cost_usd_per_mw` | float | Capital expenditure per MW of capacity. |
| `om_cost_usd_per_mw_per_yr` | float | Fixed operations & maintenance cost per MW per year. |
| `capacity_additions_mw_per_yr` | float | Projected annual capacity additions under the scenario. |
| `scrap_usd_per_mw` | float | Decommissioning cost anchor per MW. The extract convention is **negative** (`-capital_cost/2`); the model charges `abs(scrap_usd_per_mw)` as a positive outflow at retirement, so either sign produces a cost - never a receipt. |
| `carbon_price_usd_per_tco2` | float | Carbon price assumed under this scenario, in USD per tonne of CO2, real terms. |
| `fuel_price` | float | Fuel input price, in **USD per MWh of fuel energy** - the model divides it by `efficiency_decimal` to get fuel cost per MWh of output. Deliver `0.0` for non-fuel technologies. |

All twenty columns are required - the scenarios check is the strictest of the
three, and a bare prices-and-pathways extract that passes a casual eyeball
fails it (see
[Troubleshooting](troubleshooting.md#valueerror-naming-a-missing-column-raised-by-prepare_inputspy)).
Two of the required columns are contract-only today: `technology_type` and
`capacity_additions_mw_per_yr` are validated and carried but not read by any
node, so changing their values changes nothing downstream.

!!! note "Not every combination in the file is economically viable"
    The model will run the arithmetic on a scenario × technology × geography
    combination that can never turn a profit. Two quick checks worth running
    against this file before you pick a scenario pair are in
    [Methodology notes](methodology_notes.md#economic-viability-of-a-scenario-pair).

Candidate `baseline_scenario` / `target_scenario` values for this file's
`scenario` column: [scenario catalog](scenario_catalog.md).

## How the scenario columns appear inside the model

Stage 1 renames the financial columns onto the model's own vocabulary. The
stage-4 formulas, the earnings outputs and the per-stage pages all use the
right-hand names - this is the map that ties an output number back to an input
column:

| Input column | Name inside the model |
| --- | --- |
| `scenario_price` | `power_price_excarbon_usd_per_mwh` (lifted to `price_floor_lrmc` when `price_floor.method` is `lrmc`) |
| `fuel_price` | `fuel_price_usd_per_mwh_fuel` |
| `scenario_capacity_factor` | `capacity_factor` |
| `capital_cost_usd_per_mw` | `capex_usd_per_mw` |
| `om_cost_usd_per_mw_per_yr` | `fom_usd_per_mw_yr` |
| `lifetime_years`, `efficiency_decimal`, `carbon_price_usd_per_tco2`, `scrap_usd_per_mw` | unchanged |

One quantity is derived on the way rather than renamed:
`fuel_cost_per_mwh = fuel_price_usd_per_mwh_fuel ÷ efficiency_decimal` - the
fuel cost per MWh of *output* that the variable-cost formula multiplies against
production.

## Technology names are a controlled vocabulary

The asset-scenario join and three behaviours key off exact, case-sensitive
strings. The canonical technology names, as they appear in the 2026-09-01
extract (`sector` is `Power` throughout):

`BiomassCap`, `CoalCap`, `GasCap`, `OilCap`, `HydroCap`, `NuclearCap`,
`GeothermalCap`, `SolarCap - CSP`, `SolarCap - PV`, `WindCap - Offshore`,
`WindCap - Onshore`, `Hydrogen` - plus CCS variants of the fossil four (below).

* **CCS variants.** The scenarios file carries them as literal suffixes on the
  base name - `CoalCap - w/ CCS` / `CoalCap - w/o CCS`, spaces included - for
  `BiomassCap`, `CoalCap`, `GasCap` and `OilCap`. The assets file carries the
  plain base name: with `ccs_on` set to `True`/`False`, the model appends the
  matching suffix to those four technologies on the asset side to select the
  variant. See [Troubleshooting](troubleshooting.md#valueerror-with-ccs-technologies-are-not-present-in-the-scenarios-pathways).
* **The zero-carbon seven.** A missing `emission_factor` is zero-filled for
  exactly `SolarCap - CSP`, `SolarCap - PV`, `WindCap - Offshore`,
  `WindCap - Onshore`, `HydroCap`, `NuclearCap`, `GeothermalCap`. Any other
  spelling (`Solar PV`, `Coal`) is not repaired - it silently fails to join
  the scenario surface or keeps a `NaN` emission factor.

## Coverage contracts the column tables cannot show

* **Years.** The delivered scenario grid is annual, 2025-2050; coarser (IAM
  5-year) grids also run - the shock anchors on the last grid year before
  `shock_year`. Assets need observed rows overlapping
  `[scenario start, start + max_forecast_horizon]` - inclusive at both ends, so
  the default `5` keeps six calendar years; rows outside the window are cut,
  and the panel is then flat-extended to the scenario's last year. An asset
  with no row in the window leaves the run.
* **Ownership coverage.** The asset-ownership join is **inner** on asset and
  year: an asset-year with no ownership row is dropped, and an ownership row
  for a year the asset file lacks does nothing. One backfill exists -
  company-asset combinations that begin after the scenario start year are
  zero-backfilled to the start year. Deliver ownership rows for every
  asset-year you want valued.
* **`country_iso2_list` encoding.** Comma-separated with **no spaces**
  (`CN,HK,KP,KR`), quoted as one CSV field - the parser splits on bare commas
  and does not trim, so `DE, FR` produces a ` FR` that matches nothing. A
  "global" geography is nothing special: it is a geography whose list carries
  all covered countries, and it matches last under most-specific-wins. The
  geography → country mapping is the union of the distinct
  (`scenario_geography`, `country_iso2_list`) rows in the file.
