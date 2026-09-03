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
this stage joins only one thing - the `frozen_capacity_at_retirement` lookup
produced by stage 3, merged onto the panel in `validate_asset_trajectories`. It
validates the contract, decomposes year-on-year capacity changes into
new-build, roll-over and retirement flows and prices them into growth,
replacement and decommissioning CapEx, then turns capacity into production and
production into earnings. Fuel, fixed O&M and net carbon cost net to EBITDA,
and EBITDA less CapEx gives free cash flow to the firm.

### What `validate_asset_trajectories` repairs

It is not only a contract check - it also normalises and repairs the table in
place before the earnings maths runs, and every step changes numbers:

* **Every numeric column is coerced first.** The eleven price, cost and factor
  columns go through `pd.to_numeric(errors="coerce")`, so an unparseable value
  - a stray text artefact in a price column - becomes `NaN` with no log line,
  and then flows into the repairs below (a coerced emission factor is
  forward-filled or zero-filled; a coerced price simply stays `NaN`). If a
  number looks impossibly clean, check the raw input for text.
* **NaN years are dropped.** A row with no year cannot be discounted or
  ordered, and downstream integer casts would turn it into an astronomical
  outlier rather than an error.
* **Emission factors are forward-filled within each asset series.** A gap in
  the EF column would otherwise zero that year's carbon cost, which reads as a
  free year rather than a missing input.
* **Renewables missing an emission factor are zero-filled.** For the seven
  zero-carbon technologies a missing EF genuinely is zero, so they are filled
  rather than dropped - a forward-fill alone cannot help an asset whose EF is
  missing from its very first year.
* **Synthetic top-ups arrive with an inherited emission factor.** A synthetic
  asset has no plant record and so no measured EF. Rather than reaching this
  stage empty and being zero-filled - which priced 181 biomass and oil top-ups
  as emitting nothing - allocation gives each one the capacity-weighted EF of
  the real assets it was built out from, in
  [Stage 3](allocate_company_trajectories_to_assets.md). Nothing here treats
  those rows specially; by the time they arrive their EF is populated like any
  other asset's.

This is the stage where the modelling choices bite hardest: how carbon costs are
shared (`market_passthrough`), which cost elements are charged at all (the three
`include_*` switches), and whether a retiring asset keeps paying fixed O&M it can
no longer earn against (`apply_continued_om_baseline` /
`apply_continued_om_shock`).

The arithmetic, in order:

```
Q_t          = K_t × capacity_factor × 8760
fuel_cost_per_mwh = fuel_price_usd_per_mwh_fuel ÷ efficiency_decimal
var_cost_t   = Q_t × fuel_cost_per_mwh
fixed_cost_t = fom_usd_per_mw_yr × K_for_fixed_cost_t
carbon_t     = Q_t × carbon_price_usd_per_tco2 × emission_factor × (1 − market_passthrough)
revenue_t    = Q_t × power_price_excarbon_usd_per_mwh
EBITDA_t     = revenue_t − var_cost_t − fixed_cost_t − carbon_t

capex_total_t = growth_t + replacement_t + decom_t, where
  growth_t      = capex_usd_per_mw × new_buildout_cap_t    (if include_growth_capex)
  replacement_t = capex_usd_per_mw × roll_over_cap_t       (if include_replacement_capex)
  decom_t       = |scrap_usd_per_mw| × retired_max_cap_t   (if include_decom_costs)

FCFF_t       = EBITDA_t − capex_total_t
```

The three capacity flows come from the year-on-year capacity decomposition:
`new_buildout_cap` is net new capacity on synthetic assets, `roll_over_cap` is
`replacement_capex_rate` times the year's rolled-over real capacity, and
`retired_max_cap` is the capacity a retirement removes. `scrap_usd_per_mw`
arrives negative in the extracts; the `abs()` makes decommissioning a positive
outflow either way, so retiring an asset always costs money and never pays its
owner. The symbol names left of the `=` map back to input columns via the
[rename table](../input_data.md#how-the-scenario-columns-appear-inside-the-model).

`K_for_fixed_cost` is where continued O&M enters: for a decreasing-technology
asset on a trajectory the switch covers, it is the trajectory's **first-year**
capacity for every year rather than that year's actual capacity. Everything is
tax-neutral - no corporate tax rate and no depreciation shield, which is why
EBITDA rather than EBIT is the operating measure.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `asset_trajectories` | Stage 3 (`data/07_model_output/asset_trajectories.csv`) |
| `frozen_capacity_at_retirement` | Stage 3 (`data/07_model_output/frozen_capacity_at_retirement.csv`) |

That is the whole input list: the pipeline declares both in `PIPELINE_INPUTS`
and `tests/test_run.py` asserts that its non-parameter inputs are exactly that
set.

`frozen_capacity_at_retirement` is merged onto the panel in
`validate_asset_trajectories` and carried, but no calculation reads it — fixed
costs use first-year capacity (see `apply_continued_om_*` below), not
retirement-year capacity. It is the surface a stranded-capacity view would be
built on.

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
| `carbon_cost_method` | `conf/base/parameters_calculate_asset_earnings.yml` |

Every key this stage reads is defined in its own file. `include_replacement_capex`
and `include_decom_costs` ship `True` and `include_growth_capex` ships `False` -
IAM O&M already bundles annualized capital costs, so charging growth CapEx on top
would double-count. `replacement_capex_rate` is read only when
`include_replacement_capex` is on. Defaults and units:
[parameters reference](../parameters.md).

`carbon_cost_method` chooses between charging each technology's **full** emission
factor (`"full_ef"`, the default) and charging only the **excess** over the
price-setting generator (`"differential_ef"`). The differential method suits IAMs
whose electricity prices already embed the marginal generator's carbon cost;
`"full_ef"` suits IAMs whose prices barely move with carbon stringency, where
there is nothing to double-count.

The key acts on a marginal emission factor produced by the market-clearing-price
adjustment, which this codebase does not carry. The marginal EF is therefore 0,
the two methods coincide on today's inputs, and every technology pays its full
emission factor net of `market_passthrough`. The key is present so the
differential path works if that adjustment is ever adopted, and
`tests/pipelines/calculate_asset_earnings/test_carbon_cost_method.py` exercises
it against an injected non-zero marginal EF rather than leaving a switch nothing
can currently reach untested.

A companion key, `dynamic_marginal_ef`, decayed that marginal EF with the VRE
capacity share. **Owner ruling 14 deleted it** (proposal branch
`feat/decision-proposals`): it scaled a value that is always zero, so it could
not change a number, and its `(1 - vre_share)²` merit-order curve was an
untested assumption waiting to become live. `_vre_capacity_share` went with it.

The price ramp that phases the financial surfaces across the shock window is a
**stage 2** parameter, not one of this stage's: see
[`calculate_company_trajectories`](calculate_company_trajectories.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Earnings model**, which the PDF already calls
`calculate_asset_earnings` and which describes the revenue/cost stack and the
CapEx switches. The continued-O&M switches post-date that section: they are
documented in place, in `conf/base/parameters_calculate_asset_earnings.yml` and
the `nodes.py` docstrings.
