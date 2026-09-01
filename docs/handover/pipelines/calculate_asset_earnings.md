# Stage 4 - `calculate_asset_earnings`

| | |
| --- | --- |
| Source | `src/altr_model/pipelines/calculate_asset_earnings/` |
| Tags | `altrisk` |
| Runs after | [Stage 3 - `allocate_company_trajectories_to_assets`](allocate_company_trajectories_to_assets.md) |
| Runs before | [Stage 5 - `calculate_asset_and_company_npv`](calculate_asset_and_company_npv.md) |
| Nodes | 5 |

## Purpose

Converts each asset's physical trajectory into money. The canonical asset table
arrives with the active price and cost surface already attached to every row, so
this stage does no joining: it validates the contract, decomposes year-on-year
capacity changes into new-build, roll-over and retirement flows and prices them
into growth, replacement and decommissioning CapEx, then turns capacity into
production and production into earnings. Fuel, fixed O&M and net carbon cost net
to EBITDA, and EBITDA less CapEx gives free cash flow to the firm.

This is the stage where the modelling choices bite hardest: how carbon costs are
shared (`market_passthrough`), which cost elements are charged at all (the three
`include_*` switches), and whether a retiring asset keeps paying fixed O&M it can
no longer earn against (`apply_continued_om_baseline` /
`apply_continued_om_shock`).

The arithmetic, in order:

```
Q_t          = K_t × capacity_factor × 8760
var_cost_t   = Q_t × fuel_cost_per_mwh
fixed_cost_t = fom_usd_per_mw_yr × K_for_fixed_cost_t
carbon_t     = Q_t × carbon_price_usd_per_tco2 × emission_factor × (1 − market_passthrough)
revenue_t    = Q_t × power_price_excarbon_usd_per_mwh
EBITDA_t     = revenue_t − var_cost_t − fixed_cost_t − carbon_t
FCFF_t       = EBITDA_t − capex_total_t
```

`K_for_fixed_cost` is where continued O&M enters: for a decreasing-technology
asset on a trajectory the switch covers, it is the trajectory's **first-year**
capacity for every year rather than that year's actual capacity. Everything is
tax-neutral - no corporate tax rate and no depreciation shield, which is why
EBITDA rather than EBIT is the operating measure.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `asset_trajectories` | Stage 3 (`data/07_model_output/asset_trajectories.csv`) |

That is the whole input list: the pipeline declares
`PIPELINE_INPUTS = {"asset_trajectories"}` and `tests/test_run.py` asserts that
its non-parameter inputs are exactly that set.

!!! warning "Pending adjudication — Q4"
    This table also carried a row for the frozen-capacity-at-retirement dataset
    as a second input to this stage, which this codebase deliberately retired
    (it is listed in `REMOVED_DATASETS` in `tests/test_run.py`). The behaviour
    it describes is not present in this codebase and the question of whether to
    adopt it is open (ledger question Q4). The row will be rewritten once the
    ruling is recorded; it is deliberately not documented in the meantime.

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `asset_earnings` | `data/07_model_output/asset_earnings.csv` | One row per asset/company/year/trajectory type: `Q`, `revenue`, `var_cost`, `fixed_cost`, `carbon_cost_net`, `EBITDA`, `capex_total`, `FCFF`, plus the identifying and reporting columns (`alignment_type`, `late_sudden_phase`, `is_synthetic`, `asset_age`, `capacity_factor`, `scenario_type`) |
| `_temp_asset_panel_enriched`, `_temp_asset_capex_block`, `_temp_asset_ops_block`, `_temp_asset_cashflows` | in memory | Intermediate blocks between the nodes below; the leading underscore marks them as internal, and `tests/test_run.py` asserts no `_temp` dataset escapes as a pipeline output |

## Nodes

| Node | Function | What it does |
| --- | --- | --- |
| `validate_asset_trajectories` | `validate_asset_trajectories` | Checks the canonical contract: required columns present, no duplicate asset-trajectory years, no gaps in the year series |
| `calculate_capacity_flows_and_capex` | `compute_flow_based_capex` | Derives the capacity flows and prices them into growth, replacement and decommissioning CapEx |
| `calculate_operating_earnings` | `compute_ops_block` | Production, fuel, fixed O&M and net carbon cost into EBITDA |
| `calculate_free_cash_flow` | `compute_fcff` | EBITDA less CapEx - free cash flow to the firm |
| `write_asset_earnings` | `write_asset_earnings_series` | Writes the final `asset_earnings` table with every column downstream stages expect |

This set of five node names is pinned by
`tests/test_run.py::test_methodology_steps_are_visible_as_individual_nodes` -
a node added, removed or renamed here fails that test.

Two functions in this pipeline are not nodes:

* `compute_capacity_flows` derives the new-build / roll-over / retirement flows
  from year-on-year capacity changes; it is called from inside
  `compute_flow_based_capex`.
* `validate_capacity_flow_identity` checks the flow identity
  `K_t = K_{t-1} − retired + replaced + new_build`. It is a diagnostic; its call
  site in `compute_flow_based_capex` is commented out, so it does not run in a
  normal run.

## Parameters read

| Key | Defined in |
| --- | --- |
| `market_passthrough` | `conf/base/parameters_calculate_asset_earnings.yml` |
| `include_growth_capex`, `include_replacement_capex`, `replacement_capex_rate`, `include_decom_costs` | `conf/base/parameters_calculate_asset_earnings.yml` |
| `apply_continued_om_baseline`, `apply_continued_om_shock` | `conf/base/parameters_calculate_asset_earnings.yml` |

Every key this stage reads is defined in its own file. All three `include_*`
switches ship `False`, so `capex_total` is zero out of the box;
`replacement_capex_rate` is read only when `include_replacement_capex` is on.
Defaults and units: [parameters reference](../parameters.md).

!!! warning "Pending adjudication — Q2"
    This table also carried rows for a price-ramp parameter that phases prices
    across the shock window. The behaviour it describes is not present in this
    codebase and the question of whether to adopt it is open (ledger question
    Q2). The rows will be rewritten once the ruling is recorded; they are
    deliberately not documented in the meantime.

!!! warning "Pending adjudication — Q2"
    This table also carried rows for a dynamic marginal-emission-factor switch
    and a carbon-cost-method selector, which would charge carbon on the excess
    over a marginal generator rather than on the asset's own emission factor.
    The behaviour they describe is not present in this codebase - the carbon
    charge here is the asset's full emission factor, net of
    `market_passthrough` - and the question of whether to adopt it is open
    (ledger question Q2). The rows will be rewritten once the ruling is
    recorded; they are deliberately not documented in the meantime.

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Earnings model**, which the PDF already calls
`calculate_asset_earnings` and which describes the revenue/cost stack and the
CapEx switches. The continued-O&M switches post-date that section: they are
documented in place, in `conf/base/parameters_calculate_asset_earnings.yml` and
the `nodes.py` docstrings.
