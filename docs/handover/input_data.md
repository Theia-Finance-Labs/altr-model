# Input data

The model is fed by exactly three CSV files. The [quickstart](quickstart.md)
places them in `data/01_raw/` and converts them with
`scripts/prepare_inputs.py`; this page is the column-level contract for what is
inside them.

The deliverables schema and the model-input schema are the same data under
slightly different column names - the only reshape the conversion performs is
`scenario_name` → `scenario` in the scenarios file. Everything else the script
does is validation: every required column below is checked before anything is
written, so a schema problem stops the script with a named missing column
rather than leaving `data/05_model_input/` half-converted.

## `assets_forecasts.csv`

Physical power-generation assets and their technical characteristics -
capacity, technology, location, age - one row per asset per forecast year.

| Column | Type | Meaning |
| --- | --- | --- |
| `asset_id` | string | Unique identifier for the physical asset. |
| `sector` | string | Economic sector the asset belongs to. |
| `technology` | string | Technology the asset uses within its sector. |
| `year` | int | Year this row's forecast values apply to. |
| `capacity_unit` | string | Unit that `capacity` is expressed in. |
| `capacity` | float | Production capacity of the asset in that year. |
| `asset_age` | float | Age of the asset, in years, as of that row's year. |
| `country_iso2` | string | ISO 3166-1 alpha-2 code of the asset's country. |
| `country_name` | string | Human-readable name of the asset's country. |
| `asset_name` | string | Human-readable name of the asset. |
| `latitude` | float | Asset location, latitude. |
| `longitude` | float | Asset location, longitude. |
| `age_is_inferred` | bool | Whether `asset_age` was inferred rather than sourced directly. |
| `capacity_factor` | float | Fraction of nameplate capacity the asset is expected to run at. |
| `emission_factor` | float | Emissions per unit of output for this asset/technology. |

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

!!! warning "Percent scale, not fraction"
    `ownership_percentage` is on the 0-100 scale: a half-owned asset carries
    `50`, not `0.5`. The methodology PDF describes it as a fraction - that is
    wrong for this package, and the model enforces the percent scale at run
    time (`ValueError: ownership_percentage looks like a 0-1 fraction`). Rescale
    a fraction-convention extract upstream; see
    [Troubleshooting](troubleshooting.md#valueerror-ownership_percentage-looks-like-a-0-1-fraction-max).

Ownership stakes are consolidated, not tiered: every stake a company holds in
one asset-year is summed into a single row before the run, and
`prepare_inputs.py` warns when consolidated ownership per asset-year exceeds
105% - an over-allocated extract inflates every downstream number silently. The
details are in
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
| `scenario` | string | Identifier of the climate scenario/pathway model run. |
| `scenario_type` | string | Whether the row belongs to a `baseline` or a `target` pathway. |
| `scenario_geography` | string | Geography the pathway applies to. |
| `sector` | string | Economic sector the pathway applies to. |
| `technology` | string | Technology the pathway applies to within its sector. |
| `technology_type` | string | Carbon classification of the technology (`carbontech` / `greentech`). |
| `scenario_price` | float | Output price projected under this scenario. |
| `scenario_pathway` | float | Projected production/capacity pathway value for this row. |
| `scenario_capacity_factor` | float | Fraction of nameplate capacity assumed under this scenario. |
| `year` | int | Year this row's pathway values apply to. |
| `country_iso2_list` | string (comma-list) | ISO 3166-1 alpha-2 codes of the countries covered by `scenario_geography`. |
| `lifetime_years` | float | Assumed operating lifetime of the technology, in years. |
| `efficiency_decimal` | float | Conversion efficiency of the technology, as a fraction. |
| `capital_cost_usd_per_mw` | float | Capital expenditure per MW of capacity. |
| `om_cost_usd_per_mw_per_yr` | float | Fixed operations & maintenance cost per MW per year. |
| `capacity_additions_mw_per_yr` | float | Projected annual capacity additions under the scenario. |
| `scrap_usd_per_mw` | float | Decommissioning scrap value per MW of capacity. |
| `carbon_price_usd_per_tco2` | float | Carbon price assumed under this scenario, per tonne of CO2. |
| `fuel_price` | float | Fuel input price projected under this scenario. |

All nineteen columns are required - the scenarios check is the strictest of the
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
