# Stage 6 — `earnings_model`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/earnings_model/` |
| Tags | `altrisk` |
| Runs after | [Stage 5 — `distribute_impacts_to_asset_level`](distribute_impacts_to_asset_level.md) |
| Runs before | [Stage 7 — `valuation_model`](valuation_model.md) |

## Purpose

Converts each asset's physical trajectory into money. Scenario pathways become
per-(geography, sector, technology, year) price and cost surfaces; the power
price is rewritten towards a market clearing price set by the marginal
dispatchable technology (the MCPR adjustment); the surfaces are joined onto the
asset panel; year-on-year capacity changes are decomposed into new-build,
roll-over and retirement flows and priced into growth, replacement and
decommissioning CapEx. Production, fuel, fixed O&M and net carbon cost then net
to EBITDA, and EBITDA less CapEx gives free cash flow to the firm.

This is the stage where the modelling choices bite hardest: whether the clearing
price falls as renewables enter (`mcpr_mode`), how carbon costs are charged
(`carbon_cost_method`, `market_passthrough`), and which cost elements are
charged at all (the three `include_*` switches).

## Consumes

| Dataset | Produced by |
| --- | --- |
| `asset_level_staggered_shock_melted` | Stage 5 (in memory) |
| `frozen_capacity_at_retirement` | Stage 5 (`data/07_model_output/frozen_capacity_at_retirement.csv`) |
| `scenarios_pathways` | Stage 1 (`data/05_model_output/scenarios_pathways.csv`) |
| `all_alignment_classifications` | Stage 4 (in memory) |
| `companies_forecasts` | Stage 2 (in memory) |

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `asset_earnings` | `data/07_model_output/asset_earnings.csv` | One row per asset/year/trajectory type: production, revenue, costs, EBITDA, FCFF and the identifying columns reporting needs |
| `_temp_*` (validated inputs, scenario surfaces, VRE share, asset panel, capex block, ops block, cashflows) | in memory | Intermediate blocks between the nodes below; the leading underscore marks them as internal |

## Nodes

The implementation is split by concern; `nodes.py` re-exports every function for
backwards compatibility.

| Function | Module | What it does |
| --- | --- | --- |
| `validate_and_standardize_inputs` | `validation.py` | Harmonises schemas, dtypes and emission factors across the asset panel, scenarios and alignment labels |
| `build_scenario_surfaces` | `mcpr.py` | Builds tidy per-(geography, sector, technology, year) price and cost surfaces |
| `compute_scenario_vre_share` | `mcpr.py` | Derives the variable-renewable capacity share per geography and year |
| `apply_mcpr_adjustment` | `mcpr.py` | Rewrites the power price towards the market clearing price and applies value factors |
| `assemble_asset_panel` | `capacity.py` | Joins the surfaces onto the asset trajectories, including synthetic assets, and ramps prices across the shock window |
| `compute_flow_based_capex` | `capacity.py` | Prices the capacity flows into growth, replacement and decommissioning CapEx |
| `compute_ops_block` | `ops.py` | Production, fuel, fixed O&M and net carbon cost into EBITDA |
| `compute_fcff` | `ops.py` | EBITDA less CapEx — free cash flow to the firm |
| `write_asset_earnings_series` | `ops.py` | Writes the final `asset_earnings` table with every column downstream stages expect |

Two functions in this pipeline are not nodes:

* `compute_capacity_flows` (`capacity.py`) derives the new-build / roll-over /
  retirement flows from year-on-year capacity changes; it is called from inside
  `compute_flow_based_capex`.
* `validate_capacity_flow_identity` (`validation.py`) checks the flow identity
  `K_t = K_{t-1} − retired + replaced + new_build`. It is a diagnostic; its call
  site in `capacity.py` is commented out, so it does not run in a normal run.

## Parameters read

| Key | Defined in |
| --- | --- |
| `enable_mcpr`, `mcpr_mode`, `market_passthrough`, `price_ramp` | `conf/base/parameters.yml` |
| `include_growth_capex`, `include_replacement_capex`, `include_decom_costs` | `conf/base/parameters.yml` |
| `shock_year`, `alignment_year` | `conf/base/parameters.yml` |
| `mcpr_method`, `mcpr_markup_factor`, `mcpr_merit_order_alpha`, `mcpr_merit_order_floor` | `conf/base/parameters_earnings_model.yml` |
| `enable_regional_mcpr_vf`, `mcpr_regional_value_factors`, `enable_dynamic_capture_ratios` | `conf/base/parameters_earnings_model.yml` |
| `apply_continued_om_baseline`, `apply_continued_om_shock` | `conf/base/parameters_earnings_model.yml` |
| `dynamic_marginal_ef`, `carbon_cost_method` | `conf/base/parameters_earnings_model.yml` |

Defaults, units and the literature references behind the MCPR and carbon-cost
knobs: [parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Earnings model** (PDF pipeline name:
`calculate_asset_earnings`), which describes the revenue/cost stack and the
CapEx switches. The MCPR adjustment and the carbon-cost methods post-date that
section: they are documented in place, in
`conf/base/parameters_earnings_model.yml` and the `mcpr.py` / `ops.py` module
docstrings.
