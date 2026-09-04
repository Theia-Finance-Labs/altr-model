# Stage 1 - `prepare_scenario_asset_and_company_inputs`

| | |
| --- | --- |
| Source | `src/altr_model/pipelines/prepare_scenario_asset_and_company_inputs/` |
| Tags | `altrisk` |
| Runs after | - (first stage) |
| Runs before | [Stage 2 - `calculate_company_trajectories`](calculate_company_trajectories.md) |
| Nodes | 3 |

## Purpose

Turns the three input tables into the model's working inputs, and does it in one
stage. Earlier versions of the model split this work across two pipelines - a
filtering stage and a post-processing stage; here the post-processing is
absorbed, and its transformations live in
`prepare_scenario_asset_and_company_inputs/_asset_preparation.py` alongside the
filters.

Three things happen. The baseline/target scenario pair is filtered out of the
scenarios file, given its Technology Market Share Rate growth factors and its
increasing/decreasing technology labels, and the financial surface columns are
renamed onto the model's own vocabulary. Companies are filtered by id, and
their ownership rows are cut to one tier of the ownership tree before the stakes
within that tier are consolidated into one row per asset-year. Assets
get the CCS suffix, the forecast-horizon cut, a scenario geography, their
ownership allocation to companies, the optional collapse to company granularity,
and their technology lifetime.

The stage's second output pivots the scenario pair onto each company-technology
so the trajectory stage receives one wide row per company-year carrying both the
baseline and the target assumptions.

!!! note "Ownership: tiered first, or summed - `ownership_aggregation` decides"
    A company's stake in an asset is recorded at several tiers - a direct
    holding, and the equity stakes rolling up through subsidiaries.
    `ownership_aggregation` chooses how they combine, and the two modes are not
    comparable in absolute terms.

    **`"tier_filter"` (default)** treats the tiers as alternative **views** of
    the same capacity, not additive components of it, so `ownership_type`
    selects one rung (`"direct"` by default) before anything is summed.
    `_consolidate_ownership_stakes` then groups on `(company_id, asset_id,
    sector, technology, year)` and **sums** `ownership_percentage` within that
    rung, collapsing several same-tier stakes in one asset-year into one row.
    `company_name` and `asset_name` are carried along as labels rather than
    grouped on: as keys, a blank name deletes the stake outright, and a name
    filled on one sibling row but not the other splits one stake into two. The order matters: consolidating first would
    give a company holding a plant at 50.00% direct **and** 0.45% equity a
    50.45% claim on it. This is the validated baseline - the pinned fixture NPVs
    were produced under it.

    **`"sum"`** skips the tier selection and hands every rung to the same
    consolidation, so that company's claim *is* 50.45% and a holder with only
    equity stakes stays in the universe. That is TRISK's reading of ownership,
    and the mode to run when results must line up with a TRISK run; on the
    fixture slice it grows the owner-asset universe roughly 2.2×, and every
    absolute output with it.

    In both modes the merge is sum-preserving, so it cannot bring a genuinely
    over-allocated ownership universe - two different companies claiming the
    same capacity - back under 100%; see
    [Troubleshooting](../troubleshooting.md#companies-n-of-asset-years-sum-to-105-warning-not-an-error).

## Consumes

| Dataset | Where it comes from |
| --- | --- |
| `scenarios` | `data/05_model_input/scenarios.csv` - IAM pathways, prices, capacity factors, costs |
| `assets_forecasts` | `data/05_model_input/assets_forecasts.csv` - one row per asset per forecast year |
| `companies_ownerships` | `data/05_model_input/companies_ownerships.csv` - asset↔company ownership stakes |

All three are produced by `scripts/prepare_inputs.py` from the delivered files
in `data/01_raw/` ([quickstart](../quickstart.md)). The scenario frame is
indexed on its `year` column.

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `asset_forecast_panel` | in memory | Asset-year rows with their owning company, ownership-weighted activity, scenario geography, technology lifetime, increasing/decreasing label and the scenario start/end years - read again by [stage 3](allocate_company_trajectories_to_assets.md) |
| `company_projection_inputs` | in memory | One wide row per company/geography/sector/technology/year carrying the baseline **and** target scenario activity and financial surfaces - read by [stage 2](calculate_company_trajectories.md) |
| `_scenario_pathways` | in memory | The filtered, enriched scenario pair. Private to this namespace: the leading underscore keeps it from fanning out across the project graph |

Neither public output is declared in `conf/base/catalog.yml`, so both are
`MemoryDataset`s that live for one run.

## Nodes

Run in this order (`pipeline.py`):

| Node | Function | What it does |
| --- | --- | --- |
| `prepare_scenarios` | `prepare_scenario_pathways` | Filters to the scenario pair, computes TMSR growth factors, labels increasing/decreasing technologies, and maps the raw scenario columns onto the model's financial surface names |
| `prepare_asset_forecast_panel` | `prepare_asset_forecast_panel` | Filters companies and assets, applies the CCS suffix and the horizon cut, assigns scenario geographies, allocates capacity by ownership, optionally collapses to company granularity, and attaches technology lifetimes |
| `prepare_company_projection_inputs` | `prepare_company_projection_inputs` | Aggregates the asset panel to company level and pivots the scenario pair onto it, one wide row per company-year |

Node names are namespaced, so they appear in the log as
`prepare_scenario_asset_and_company_inputs.prepare_scenarios` and so on.

### The functions behind the nodes

The three node functions in `nodes.py` are thin: the work is in two private
modules, and both are called from inside those nodes rather than wired as nodes
of their own.

`_input_nodes.py` - filtering and matching:

| Function | What it does |
| --- | --- |
| `check_input_parameters` | Raises if `alignment_year` is below `shock_year`. Wired as a node in [stage 2](calculate_company_trajectories.md), where the two keys live |
| `filter_scenarios` | Keeps the baseline/target pair only. Names are matched verbatim against the `scenario` column — it asserts both are present and prefixes nothing (the data must already carry `AR6_<provider>_`; `workspace/stage_marts_inputs.py` restores it for marts extracts that ship bare names) |
| `_select_ownership_tier` | Keeps one rung of the ownership tree, per `ownership_type`; handles both the `ownership_type` and `ownership_level` company schemas. Skipped under `ownership_aggregation: "sum"` |
| `_consolidate_ownership_stakes` | Sums the stakes it is given - one tier's worth under `"tier_filter"`, every tier under `"sum"` - into a single row per company-asset-year |
| `filter_companies` | Selects the tier (`"tier_filter"` only), consolidates, then applies the `company_ids` filter; raises on an `ownership_aggregation` that is neither mode |
| `apply_ccs_suffix` | Points Coal/Gas/Biomass/Oil at the with- or without-CCS scenario variant |
| `filter_assets` | Cuts each asset to `max_forecast_horizon` years from the scenario start year, and asserts both scenarios start in the same year |
| `assign_scenario_geographies_to_assets` | Matches every asset's country to its most granular scenario geography, failing rather than guessing on a tie |
| `allocate_assets_to_companies` | Allocates `capacity × ownership_percentage / 100` to each owner - the column is on the 0-100 scale, and the node raises rather than guessing if it looks like a 0-1 fraction |
| `determine_increasing_or_decreasing_techs` | Labels each technology as increasing or decreasing under the scenario |
| `determine_lifetime_per_technology` | Derives the technology lifetime used to date asset retirement |

`_asset_preparation.py` - the absorbed post-processing:

| Function | What it does | Called from |
| --- | --- | --- |
| `apply_reduce_granularity_from_asset_to_company_level` | Passes the panel through, or aggregates it to one synthetic row per company-technology-geography when the switch is on | this stage, inside `prepare_asset_forecast_panel` |
| `extend_allocated_assets_to_companies` | Extends each asset's rows to the scenario horizon | [stage 3](allocate_company_trajectories_to_assets.md), inside `extend_assets_and_attach_retirement` |
| `determine_assets_retirement_dates` | Dates each asset's retirement from its age and its technology's lifetime | [stage 3](allocate_company_trajectories_to_assets.md), same node |

The granularity switch has large consequences: it decides whether the rest of
the run reasons about real plants or about one synthetic row per
company-technology, and the plots lose their per-asset detail when it is on.

## Parameters read

| Key | Defined in |
| --- | --- |
| `baseline_scenario`, `target_scenario` | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |
| `company_ids`, `ownership_type`, `ownership_aggregation`, `ccs_on`, `max_forecast_horizon` | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |
| `reduce_granularity_from_asset_to_company_level` | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |
| `decom_cost_fraction_of_capex`, `price_floor`, `capture_price` | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |

Three keys adjust the scenario surface before anything downstream reads it, in
this order: `price_floor` (method `lrmc` lifts the regional power price to at
least the levelised cost of the region-year's price-setting thermal technology —
the largest thermal generator whose cost inputs are usable — one market price for
every technology; the raw IAM value stays in `scenario_price` and the floor is
reported in `price_floor_lrmc`, 0.0 where none applies), `decom_cost_fraction_of_capex`
(rewrites `scrap_usd_per_mw` as a share of build cost) and `capture_price`
(method `hirth2013` adds a per-technology `capture_price_factor` the earnings
stage multiplies into revenue). `price_floor` and `capture_price` ship at
`none`, the delivered behaviour; `decom_cost_fraction_of_capex` ships at 0.15 by
owner ruling (null restores the delivered scrap value). The order matters only
for which columns exist when each step runs: none of the three reads another's
output, and the earnings stage multiplies the (floored) price by the capture
factor regardless.

Every key this stage reads is defined in its own file - the pipeline declares
them explicitly in `PIPELINE_PARAMETERS`, so a key it does not list is not
visible to it. Defaults and the full annotations:
[parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Inputs preparation**, which the PDF already calls
`prepare_scenario_asset_and_company_inputs`. Four of the
[methodology notes](../methodology_notes.md) bear directly on this stage:
[economic viability of a scenario pair](../methodology_notes.md#economic-viability-of-a-scenario-pair)
(before you pick one),
[geography matching](../methodology_notes.md#how-assets-are-matched-to-a-scenario-geography)
(this stage fails rather than guessing when a country maps to more than one
scenario geography),
[granularity](../methodology_notes.md#granularity-changes-the-shape-of-every-output),
and
[asset retirement](../methodology_notes.md#asset-retirement-refurbishment-wrap-around-not-a-hard-cutoff).
