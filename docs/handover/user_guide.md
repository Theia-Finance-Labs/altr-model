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
`data/05_model_input/scenarios.csv`, and both must come from the same IAM
provider - the model asserts that the two scenarios also start in the same year.
The [scenario catalog](scenario_catalog.md) lists candidate pairs per provider;
copy one from there, or keep the pair shipped in the file.

For this example we use the shipped AIM/CGE pair:

| Role | Scenario |
| --- | --- |
| Baseline | `AR6_AIM/CGE 2.2_EN_NPi2020_1200f` |
| Target | `AR6_AIM/CGE 2.2_EN_NPi2020_900f` |

## 2. Set three keys, in two files

There is no consolidated `conf/base/parameters.yml`. Scenario selection lives
with the input-preparation pipeline, shock timing with the trajectory pipeline:

```yaml
# conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml
baseline_scenario: "AR6_AIM/CGE 2.2_EN_NPi2020_1200f"
target_scenario: "AR6_AIM/CGE 2.2_EN_NPi2020_900f"
```

```yaml
# conf/base/parameters_calculate_company_trajectories.yml
shock_year: 2033       # the year the policy shock becomes known
alignment_year: 2035   # the year the target pathway must be reached; >= shock_year
```

`shock_year` and `alignment_year` bracket the transition window. A wider window
is a gentler, more realistic phase-out; a narrower one is a harder shock. Setting
`alignment_year` below `shock_year` stops the run immediately with
`ValueError: Alignment year must be greater than shock year`.

Two more keys are worth knowing before your first run, both in
`parameters_prepare_scenario_asset_and_company_inputs.yml`:

* `company_ids: []` - an empty list means *all companies*. Put a handful of ids
  in the list to get a fast run while you are still finding your feet. The file
  ships with an example selection, not a required one.
* `max_forecast_horizon: 5` - how many forecast years past the scenario start
  year each asset is valued over. Bigger horizon, longer run, more terminal-value
  sensitivity.

Every key in all six files is annotated in place, and the generated
[parameters reference](parameters.md) collects them with their defaults.

## 3. Run

```bash
uv run kedro run --tags altrisk
```

Wait for `Pipeline execution completed successfully`. Drop the `--tags` to also
produce the figure packs.

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

!!! note "One asset can appear more than once"
    Asset-level tables carry one row per **owning company**, so `asset_id`
    alone is not a unique key - `(asset_id, company_id)` is.

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
  `FCFF = EBITDA − capex_total`. `carbon_cost_net` is the asset's own carbon
  bill: `Q × carbon_price_usd_per_tco2 × emission_factor × (1 −
  market_passthrough)`. With the shipped `market_passthrough: 0` the firm
  absorbs all of it, which is the conservative stress-test reading; raising the
  key towards `1` hands the cost to customers and shrinks the charge
  proportionally.
* Everything is in **real** terms - real discount rates, real terminal growth -
  so figures across years are directly comparable without deflating.

## 5. Sanity checks before you trust a run

The model writes no QC tables; the checks are ones you run against the outputs
yourself.

* **Did the asset fleet absorb the company shock?**
  `data/07_model_output/company_trajectories.csv` carries four
  `trajectory_type` values - `baseline`, `target`, `late_sudden_requested` and
  `late_sudden_realized`. The last is the sum of the allocated asset capacities;
  the gap between it and `late_sudden_requested` is what the fleet could not
  absorb. A large persistent gap means the allocation, not the valuation, is
  where a surprising number comes from.
* **Do the levels reconcile?** `asset_npv` summed by company must equal
  `company_npv`, and `asset_earnings` FCFF discounted must reproduce
  `yearly_npv_trajectories`. Both roll-ups are plain sums, so a mismatch is a
  data problem rather than a methodology one.
* **Record the configuration next to the result.** Nothing in the pipeline
  stamps the parameters onto the outputs. Copy the six
  `conf/base/parameters_*.yml` files alongside any result you share - it is the
  cheapest defence against comparing two runs that were configured differently.

Then look for the usual suspects: companies whose `asset_count` is 1 (a single
asset drives the whole result), assets with `is_synthetic = True` dominating a
company's NPV, and `npv_change` values whose `baseline_npv` is close to zero.

The figure packs under `data/08_reporting/` (written by the `reporting` stage)
are the visual version of the first two checks - see
[Stage 6](pipelines/plot_transition_risk_results.md).

## Changing one thing at a time

The model has many switches, and their effects interact. When you experiment,
change one key, re-run, and compare `company_npv.csv` against the previous run -
after copying the previous outputs somewhere else, because a re-run overwrites
`data/07_model_output/` in place.

The switches with the largest, most interpretable effect on the headline number:

* **`apply_continued_om_shock`** (`True`/`False`, in
  `parameters_calculate_asset_earnings.yml`) - the single biggest stranding
  lever. When it is on, a decreasing-technology asset on the shock pathway pays
  fixed O&M on its **first-year** capacity every year, not on the capacity it
  still has. A plant whose output the shock cuts to a fraction keeps paying the
  full fixed bill it can no longer earn against, and its shock NPV collapses.
  Turn it off and stranding largely disappears from the result - which is
  exactly why the shipped default has it on for the shock pathway and off for
  the baseline (`apply_continued_om_baseline: False`). Flipping both to the same
  value removes the asymmetry and, with it, most of the transition signal.
* **`dcf.discount_rate_shock`** (in `parameters_calculate_asset_and_company_npv.yml`)
  - the discount rate applied to every cash flow on the target-scenario surface.
  It ships equal to `dcf.discount_rate_baseline` (`0.07`), so the two pathways
  are discounted identically and the whole `npv_change` comes from the cash
  flows. Raising it above the baseline rate adds a transition-risk premium and
  moves `npv_change` down for every company at once - a level shift, not a
  re-ranking, which is what makes it easy to read and easy to over-interpret.
* **`market_passthrough`** (who pays the carbon cost) and the three cost
  switches `include_growth_capex`, `include_replacement_capex` and
  `include_decom_costs`, all in `parameters_calculate_asset_earnings.yml`. All
  three cost switches ship `False`, so CapEx is zero out of the box; turning one
  on changes `capex_total` and therefore FCFF in both pathways at once.
