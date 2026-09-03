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
`data/05_model_input/scenarios.csv`. Two rules govern the pair - one the model
enforces, one it does not:

* **Same start year - enforced.** The model asserts both scenarios start in the
  same year and stops the run if they do not.
* **Same IAM provider - your job.** The model does not check the provider. A
  cross-provider pair that happens to share a start year runs to completion,
  silently intersecting the two providers' geographies and technologies and
  logging one warning you will not spot in a 29-node stream - a completed run
  on a shrunken universe. Enforce same-provider yourself, because the model
  will not.

The [scenario catalog](scenario_catalog.md) lists candidate pairs per provider.
For this example we use the WITCH pair - the best-covered pair in the
2026-09-01 extract, and the one the committed fixture and the full-universe
environment (`conf/full/`) both run:

| Role | Scenario |
| --- | --- |
| Baseline | `AR6_WITCH 5.0_EN_NoPolicy` |
| Target | `AR6_WITCH 5.0_EN_NPi2020_500` |

!!! warning "The pair shipped in `conf/base` is not in the 2026-09-01 extract"
    The parameters file ships AIM/CGE names (`EN_NPi2020_1200f` / `900f`) that
    the 2026-09-01 scenarios extract does not carry - AIM/CGE 2.2 appears there
    as `EN_INDCi2100` / `EN_NPi2020_500f`. Scenario names change between
    extract vintages, so before your first run, list what your extract actually
    carries and set a pair from that list - the one-liner is in
    [Troubleshooting](troubleshooting.md#assertionerror-target-scenario-not-found-in-scenarios-pathways).

## 2. Set three keys, in two files

There is no consolidated `conf/base/parameters.yml`. Scenario selection lives
with the input-preparation pipeline, shock timing with the trajectory pipeline:

```yaml
# set in conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml:
baseline_scenario: "AR6_WITCH 5.0_EN_NoPolicy"
target_scenario: "AR6_WITCH 5.0_EN_NPi2020_500"
```

```yaml
# set in conf/base/parameters_calculate_company_trajectories.yml:
shock_year: 2033       # the year the policy shock becomes known
alignment_year: 2038   # the year the target pathway must be reached; >= shock_year
```

`shock_year` and `alignment_year` bracket the transition window. A wider window
is a gentler, more realistic phase-out; a narrower one is a harder shock. Setting
`alignment_year` below `shock_year` stops the run immediately with
`ValueError: Alignment year cannot be earlier than shock year`; equal years are
legal and leave an empty transition window.

Two more keys are worth knowing before your first run, both in
`parameters_prepare_scenario_asset_and_company_inputs.yml`:

* `company_ids` - check what your copy ships before trusting a "full" run. In
  this repository the file carries a **30-company example selection**, so an
  out-of-the-box run covers those 30 companies, not the universe; a sanitized
  delivered copy carries an **empty list** (the export strips the ids). An
  empty list means *all companies*. In this repository,
  `uv run kedro run --env full --tags altrisk` empties the filter and sets the
  verified scenario pair in one step; `conf/full/` is not part of a delivered
  copy, so there you edit `conf/base` directly.
* `max_forecast_horizon: 5` - how many years of *observed* forecast data each
  asset keeps, counted from the scenario start year (2025 in the 2026-09-01
  extract; the cut is inclusive at both ends, so `5` keeps six calendar years).
  This is **not** the valuation window: after the cut, every asset is
  flat-extended to the scenario's last year (2050), so the 2033 shock and the
  2038 alignment year are always inside the valued period. The knob decides how
  much of the path rests on data versus flat extension - bigger horizon, more
  data, longer run.

Every key in all six files is annotated in place. The generated
[parameters reference](parameters.md) collects the top-level keys with their
defaults; the nested `dcf.*` valuation defaults are collected on
[Stage 5](pipelines/calculate_asset_and_company_npv.md) and annotated in the
YAML file itself.

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

!!! note "One asset can appear more than once, and every number is the owner's share"
    Asset-level tables carry one row per **owning company**, so `asset_id`
    alone is not a unique key - `(asset_id, company_id)` is. Every value in
    these tables is the owner's share: capacity is allocated as
    `capacity × ownership_percentage / 100` before any money is computed, so a
    40%-owned plant contributes 40% of its cash flows to that company's NPV -
    never the whole asset.

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

One historical source of positive values is worth knowing when you compare
against older runs: under a hard price switch (`price_ramp: False`) target
prices sit 30-50% above baseline at the shock year, handing fossil assets a
near-term windfall - a pricing artefact, not economics. The shipped
`price_ramp: True` blends the two surfaces across the transition window and
removes it, so a positive `npv_change` under the shipped configuration is the
real current-policy-baseline effect described above, not the artefact.

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
  `company_npv` - that roll-up is a plain sum. One level down, mind the
  terminal value: per asset and pathway, `yearly_npv_trajectories`'s `pv_fcff`
  summed across years **plus its `terminal_value`** reproduces the `*_npv`
  columns, while hand-discounting `asset_earnings` FCFF reproduces `pv_fcff`
  only - the terminal value is added in the valuation stage and appears in no
  earnings row. A mismatch in the company roll-up is a data problem; a mismatch
  in a hand-discounted check is usually the missing terminal value, not a bug.
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

    Why the asymmetry is deliberate: under a disorderly transition a plant
    sheds output faster than it sheds its fixed cost base - contracts, staffing
    and site obligations keep billing while the shock cuts production, while on
    the baseline pathway the plant winds down on schedule and sheds costs on
    schedule. The asymmetry is the stranded-cost mechanism itself, not an
    accounting trick. Size it on your own data before you present: flip the
    switch, re-run, diff `company_npv.csv`. On the committed fixture slice,
    turning `apply_continued_om_shock` off moves the median `npv_change` from
    -0.42 to -0.16 - the switch carries roughly 60% of the median signal there,
    and per-company effects range far wider.
* **`dcf.discount_rate_shock`** (in `parameters_calculate_asset_and_company_npv.yml`)
  - the scenario base rate for cash flows on the target-scenario surface, and
  inert under the shipped configuration. See [Discount rates](#discount-rates)
  below.
* **`market_passthrough`** (who pays the carbon cost) and the three cost
  switches `include_growth_capex`, `include_replacement_capex` and
  `include_decom_costs`, all in `parameters_calculate_asset_earnings.yml`.
  `include_replacement_capex` and `include_decom_costs` ship `True`, so
  `capex_total` is non-zero out of the box; `include_growth_capex` ships
  `False`, because IAM O&M already bundles annualized capital costs and
  charging growth CapEx on top would double-count. Flipping any of them
  changes `capex_total` and therefore FCFF in both pathways at once.

### Discount rates

Cash flows are discounted at a scenario base rate plus a technology spread. The
base rate is `dcf.discount_rate_baseline` on the baseline surface and
`dcf.discount_rate_shock` on the target surface, both in
`parameters_calculate_asset_and_company_npv.yml`; they ship equal (`0.07`), so
the whole `npv_change` comes from the cash flows rather than the rate. The
spread is `dcf.brown_discount_spread` (+100 bps), charged to the technologies
named in `dcf.brown_technologies` and to nobody else; everything outside that
list takes the base rate. It applies to both pathways alike. There is no
greenium leg - the literature the premium rests on measures a penalty on high
emitters and no discount for clean firms (owner ruling 12).

Raising the shock rate above the baseline rate prices transition risk into the
rate as well. It moves `npv_change` down for every company at once - a level
shift, not a re-ranking, which is what makes it easy to read and easy to
over-interpret.

**Under the shipped configuration that knob is INERT: raising it changes
nothing.** The rate is selected off `scenario_type`, and a *ramped* late &
sudden pathway is a blend of the two scenario surfaces, so it keeps carrying the
*baseline* label rather than falsely claiming the target's. Every row of
`asset_earnings` then reads `scenario_type: baseline`, and every row takes
`dcf.discount_rate_baseline`.

The pathway ramps when **both** of these hold, in
`parameters_calculate_company_trajectories.yml`:

| Condition | Shipped value |
| --- | --- |
| `price_ramp: True` | `True` |
| `alignment_year` strictly greater than `shock_year` | `2038 > 2033` — holds |

Break either one and `dcf.discount_rate_shock` is live again:

* `price_ramp: False` - the hard switch to the target surface at `shock_year`;
* `alignment_year` equal to `shock_year` - legal (`check_input_parameters`
  requires `alignment_year >= shock_year`, not `>`), and it leaves an empty
  transition window, so there is nothing to blend across.

Either is a configuration to run if you want the two pathways discounted at
different rates - but both also change the capacity pathway itself, so the
discount rate is not the only thing that moves. `trajectory_type` separates the
two worlds regardless; it is `scenario_type` alone that collapses under a ramp.
