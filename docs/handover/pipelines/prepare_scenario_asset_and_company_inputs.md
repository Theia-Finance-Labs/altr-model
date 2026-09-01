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
renamed onto the model's own vocabulary. Companies are filtered by id, with
every stake a company holds in an asset-year consolidated into one row. Assets
get the CCS suffix, the forecast-horizon cut, a scenario geography, their
ownership allocation to companies, the optional collapse to company granularity,
and their technology lifetime.

The stage's second output pivots the scenario pair onto each company-technology
so the trajectory stage receives one wide row per company-year carrying both the
baseline and the target assumptions.

!!! note "Ownership is summed, not tiered"
    Companies are **not** filtered by ownership tier. `_consolidate_ownership_stakes`
    groups on `(company_id, company_name, asset_id, asset_name, sector,
    technology, year)` and **sums** `ownership_percentage`, so a company holding
    two stakes in one asset (say direct and equity) ends up with one row
    carrying their total. The merge is sum-preserving: it cannot bring an
    over-allocated ownership universe back under 100% - see
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
| `filter_scenarios` | Keeps the baseline/target pair only, prefixing `AR6_<provider>_` where it is absent |
| `_consolidate_ownership_stakes` | Sums every stake a company holds in one asset-year into a single row |
| `filter_companies` | Consolidates the stakes, then applies the `company_ids` filter |
| `apply_ccs_suffix` | Points Coal/Gas/Biomass/Oil at the with- or without-CCS scenario variant |
| `filter_assets` | Cuts each asset to `max_forecast_horizon` years from the scenario start year, and asserts both scenarios start in the same year |
| `assign_scenario_geographies_to_assets` | Matches every asset's country to its most granular scenario geography, failing rather than guessing on a tie |
| `allocate_assets_to_companies` | Multiplies asset capacity by each owner's ownership percentage (0-100 scale) |
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
| `company_ids`, `ccs_on`, `max_forecast_horizon` | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |
| `reduce_granularity_from_asset_to_company_level` | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |

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
