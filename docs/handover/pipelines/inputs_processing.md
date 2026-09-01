# Stage 1 — `inputs_processing`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/inputs_processing/` |
| Tags | `altrisk`, `trisk` |
| Runs after | — (first stage) |
| Runs before | [Stage 2 — `inputs_postproc`](inputs_postproc.md) |

## Purpose

Turns the three `downloaded_*` tables into the model's working inputs. The
baseline/target scenario pair is filtered out of the scenarios file and
interpolated onto an annual grid, its electricity price is scaled for CapEx
recovery, and its carbon prices are injected from the AR6 database. Companies
are filtered by id and ownership type; assets get the CCS suffix, the
forecast-horizon cut, a scenario geography, and their ownership allocation to
companies.

The stage also derives two small lookup tables the later stages depend on: the
per-technology direction (is this technology growing or shrinking under the
scenario?) and the per-technology asset lifetime used to date retirements.

## Consumes

| Dataset | Where it comes from |
| --- | --- |
| `downloaded_scenarios` | `data/05_model_input/downloaded_scenarios.csv` — IAM pathways, prices, capacity factors, costs |
| `downloaded_assets` | `data/05_model_input/downloaded_assets.csv` — one row per asset per forecast year |
| `downloaded_companies` | `data/05_model_input/downloaded_companies.csv` — asset↔company ownership links |
| `ar6_carbon_prices` | `6_final_AR6_viable_scenarios.csv` (repository root) — carbon prices per scenario/geography/year |

!!! note "The carbon-price input is a fourth file"
    `conf/base/catalog.yml` reads `ar6_carbon_prices` from
    `6_final_AR6_viable_scenarios.csv` at the repository root, and only the
    columns listed under its `load_args`. It is separate from the three files
    `scripts/prepare_inputs.py` produces. The `fixture` environment overrides it
    to a committed slice (`tests/fixtures/data/ar6_carbon_prices.csv`). For IAMs
    that report no carbon price the injected value stays at `0` and the price
    signal alone carries the transition effect.

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `scenarios_pathways` | `data/05_model_output/scenarios_pathways.csv` | The scenario pair, annual, price-scaled, with carbon prices — read by stages 2, 3 and 6 |
| `allocated_assets_to_companies` | `data/07_model_output/allocated_assets_to_companies.csv` | Asset-year rows with their owning company and ownership-weighted capacity |
| `companies_ownership_tree`, `assets_forecasts`, `assets_forecasts_with_scenario_geographies`, `increasing_or_decreasing_techs`, `lifetime_per_technology`, and the `scenarios_pathways_*` intermediates | in memory | Not written to disk; declared nowhere in the catalog, so Kedro keeps them for the duration of the run |

## Nodes

Run in this order (`nodes.py`):

| Function | What it does |
| --- | --- |
| `check_input_parameters` | Fails the run early if `alignment_year` is not after `shock_year` |
| `filter_scenarios` | Keeps the baseline/target pair only, prefixing `AR6_<provider>_` as needed |
| `interpolate_scenarios_annually` | Linearly interpolates the 5- or 10-year scenario grid to every year and extends it |
| `scale_electricity_price` | Scales the electricity price for CapEx recovery by `theta_capex_recovery` |
| `inject_carbon_prices` | Merges the AR6 carbon price onto each scenario/geography/year |
| `filter_companies` | Applies the `company_ids` filter and the `ownership_type` tier, then totals the stakes each company holds in one asset-year into a single row |
| `apply_ccs_suffix` | Points Coal/Gas/Biomass at the with- or without-CCS scenario variant |
| `filter_assets` | Cuts each asset to `max_forecast_horizon` years from the scenario start year |
| `assign_scenario_geographies_to_assets` | Matches every asset's country to a scenario geography |
| `allocate_assets_to_companies` | Multiplies asset capacity by the ownership percentage of each owner |
| `determine_increasing_or_decreasing_techs` | Labels each technology as increasing or decreasing under the scenario |
| `determine_lifetime_per_technology` | Derives the technology lifetime used to date asset retirement |

## Parameters read

| Key | Defined in |
| --- | --- |
| `baseline_scenario`, `target_scenario` | `conf/base/parameters.yml` |
| `shock_year`, `alignment_year` | `conf/base/parameters.yml` |
| `company_ids`, `ownership_type`, `ccs_on`, `max_forecast_horizon` | `conf/base/parameters.yml` |
| `theta_capex_recovery` | `conf/base/parameters_inputs_postproc.yml` |

`theta_capex_recovery` is read here but defined in another pipeline's file:
Kedro merges every parameters file into one namespace, so the defining file does
not have to match the pipeline that reads the key. Defaults and the full
annotations: [parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Inputs preparation**, which covers stages 1 and 2
together and calls the pipeline `prepare_scenario_asset_and_company_inputs`.
Also relevant in **Additional notes**: *Conditions a scenario has to respect to
be economically viable* (before you pick a pair) and *How assets get matched to
a scenario geography* (this stage fails rather than guessing when a country maps
to more than one scenario geography).
