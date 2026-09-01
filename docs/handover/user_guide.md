# User guide

One worked example, end to end: pick a scenario pair, set three parameters, run,
and read the results. It assumes you have finished the
[quickstart](quickstart.md) through step 4, so `data/05_model_input/` holds the
three converted input files.

## 1. Pick a scenario pair

A run always compares two IAM scenarios:

* **`baseline_scenario`** - the counterfactual pathway the company is on today
  (a current-policy or reference scenario).
* **`target_scenario`** - the climate-policy pathway the shock forces it onto.

Both names must exist in the `scenario` column of
`data/05_model_input/downloaded_scenarios.csv`, and both must come from the same
IAM provider - the model asserts that the two scenarios also start in the same
year. The [scenario catalog](scenario_catalog.md) lists candidate pairs per
provider; copy one from there, or keep the pair shipped in the file.

For this example we use the shipped REMIND pair:

| Role | Scenario |
| --- | --- |
| Baseline | `AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_3000` |
| Target | `AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_500` |

## 2. Set three keys in `conf/base/parameters.yml`

```yaml
# ── Scenario selection ──
baseline_scenario: "AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_3000"
target_scenario: "AR6_REMIND-MAgPIE 2.1-4.2_EN_NPi2020_500"

# ── Shock timing ──
shock_year: 2033       # the year the policy shock becomes known
alignment_year: 2038   # the year the target pathway must be reached; >= shock_year
```

`shock_year` and `alignment_year` bracket the transition window. A wider window
is a gentler, more realistic phase-out; a narrower one is a harder shock. Setting
`alignment_year` below `shock_year` stops the run immediately with
`ValueError: Alignment year must be greater than shock year`.

Two more keys are worth knowing before your first run, both in the same file:

* `company_ids: []` - an empty list means *all companies*. Put a handful of ids
  in the list to get a fast run while you are still finding your feet.
* `max_forecast_horizon: 5` - how many forecast years past the scenario start
  year each asset is valued over. Bigger horizon, longer run, more terminal-value
  sensitivity.

Everything else in `conf/base/parameters.yml` is annotated in place, and the
advanced knobs live in the per-pipeline `conf/base/parameters_<pipeline>.yml`
files under an `# --- Advanced:` header.

## 3. Run

```bash
kedro run --tags altrisk
```

Wait for `Pipeline execution completed successfully`. Add `,reporting` to the
tags if you also want the charts and export tables.

## 4. Read the two headline tables

### `data/07_model_output/company_npv.csv`

One row per company - the top-line result.

| Column | Meaning |
| --- | --- |
| `company_id`, `company_name` | The company |
| `baseline_npv` | Sum of discounted free cash flow (plus terminal value) across the company's assets on the baseline pathway, in USD |
| `latesudden_npv` | The same, on the late & sudden shock pathway, in USD |
| `baseline_discount_rate`, `latesudden_discount_rate` | Effective discount rates behind those two numbers (asset-level rates, averaged) |
| `asset_count` | How many assets (or synthetic technology buckets) sit behind the row |
| `npv_change` | `(latesudden_npv - baseline_npv) / abs(baseline_npv)` - the fractional value change, not a percentage |

### `data/07_model_output/asset_npv.csv`

One row per asset, and the place to go when a company-level number looks
surprising.

| Column group | Columns | Meaning |
| --- | --- | --- |
| Identity | `asset_id`, `asset_name`, `company_id`, `company_name`, `scenario_geography`, `sector`, `technology` | Which asset, where, whose |
| Classification | `is_synthetic`, `alignment_type` | Whether the row is a synthetic top-up asset rather than a physical plant, and the alignment bucket the company/technology fell into |
| Valuation | `baseline_npv`, `latesudden_npv`, `baseline_discount_rate`, `latesudden_discount_rate`, `npv_change` | Same definitions as above, per asset |
| Components | `baseline_*` / `latesudden_*` of `FCFF`, `EBITDA`, `revenue`, `var_cost`, `fixed_cost`, `carbon_cost_net`, `capex_total` | **Undiscounted** sums across the forecast years, in USD |

The component columns are the diagnostic pair to the NPV columns: `*_npv` is
discounted and includes the terminal value, the components are raw sums of the
yearly figures. A large NPV gap with near-identical revenue and cost sums points
at the terminal value or the discount rates, not at the physical trajectory.

Two tables sit between these and the raw model if you need to go further:
`yearly_npv_trajectories.csv` (per asset, per year, per trajectory: discount
factor, present value, terminal value) and `asset_earnings.csv` (per asset, per
year: production `Q`, revenue, costs, EBITDA, CapEx, FCFF - before any
discounting).

## Reading the sign of npv_change

`npv_change = (latesudden_npv − baseline_npv) / abs(baseline_npv)`

* **Negative** - the shock destroys value relative to the baseline pathway. This
  is the expected direction for carbon-intensive assets.
* **Positive** - the shock leaves the company better off than the baseline
  pathway does. This is a real result, not necessarily a bug: see the framing
  note below.
* **Empty / `NaN`** - `baseline_npv` was zero, so the ratio is undefined. Read
  the two NPV levels directly instead of the ratio.

The denominator is the **absolute value** of the baseline NPV. That is what keeps
the sign of the ratio meaningful when a company's baseline NPV is itself negative:
without it, a loss-making company that loses more under the shock would show a
positive change. Because of this, always sanity-check the two NPV *levels* next
to the ratio - a ratio computed against a baseline NPV near zero is numerically
large and economically meaningless.

!!! note "What the baseline is, and why positive changes happen"
    ALTR's baseline is a **current-policy scenario that already carries
    transition costs**, so the model measures the *marginal* effect of policy
    stricter than current policy. A model whose baseline instead assumes no
    carbon costs at all can only ever show losses from a shock, because the
    shock is the only thing introducing costs. ALTR can show gains where the
    current-policy pathway is already damaging and the shock mostly accelerates
    a decline that was coming anyway. Both framings are used in published
    stress tests - current-policy counterfactuals in economy-wide exercises,
    "no additional headwinds" counterfactuals elsewhere - but they are not
    comparable, and this one is the current-policy framing.

Two more conventions worth holding onto when reading any output table:

* Cost columns are **subtracted**, not added:
  `EBITDA = revenue − var_cost − fixed_cost − carbon_cost_net` and
  `FCFF = EBITDA − capex_total`. `carbon_cost_net` is a *differential* cost - 
  it charges only the emission factor in excess of the marginal generator's,
  net of `market_passthrough` - so it is zero for any asset no dirtier than the
  plant setting the price.
* Everything is in **real** terms - real discount rates, real terminal growth - 
  so figures across years are directly comparable without deflating.

## 5. Sanity checks before you trust a run

Run with `--tags altrisk,reporting` and start here:

* `data/08_reporting/tables/validation_summary.csv` - the reporting stage's
  input validation: whether earnings, asset NPV and company NPV reconcile.
* `data/08_reporting/tables/compliance_ready/reporting_qc.csv` - quality-control
  summary over the reporting views.
* `data/08_reporting/tables/compliance_ready/company_summary.csv` and
  `technology_summary.csv` - the same results as the headline tables, formatted
  for reporting, plus `top_assets.csv` for the largest movers.
* `data/08_reporting/tables/compliance_ready/methodology_parameters.csv` - the
  parameter set the run actually used. Attach it to any result you share; it is
  the cheapest defence against comparing two runs that were configured
  differently.

Then look for the usual suspects: companies whose `asset_count` is 1 (a single
asset drives the whole result), assets with `is_synthetic = True` dominating a
company's NPV, and `npv_change` values whose `baseline_npv` is close to zero.

## Changing one thing at a time

The model has many switches, and their effects interact. When you experiment,
change one key, re-run, and compare `company_npv.csv` against the previous run - 
after copying the previous outputs somewhere else, because a re-run overwrites
`data/07_model_output/` in place. The switches with the largest, most
interpretable effect on the headline number are `enable_mcpr` / `mcpr_mode`
(how output is priced), `market_passthrough` (who pays the carbon cost), and the
three cost switches `include_growth_capex`, `include_replacement_capex` and
`include_decom_costs`.
