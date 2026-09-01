# Stage 5 - `calculate_asset_and_company_npv`

| | |
| --- | --- |
| Source | `src/altr_model/pipelines/calculate_asset_and_company_npv/` |
| Tags | `altrisk` |
| Runs after | [Stage 4 - `calculate_asset_earnings`](calculate_asset_earnings.md) |
| Runs before | [Stage 6 - `plot_transition_risk_results`](plot_transition_risk_results.md) |
| Nodes | 4 |

## Purpose

Converts the per-asset FCFF series into present values. Each year's cash flow is
discounted at a rate that depends on which scenario surface the row sits on -
`dcf.discount_rate_baseline` for baseline rows, `dcf.discount_rate_shock` for
target rows; a terminal value is added beyond the forecast horizon; and the
result is rolled up from asset to company-technology to company level.

!!! note "`dcf.discount_rate_shock` is inert under the shipped configuration"

    The rate is chosen off `scenario_type`, and a *ramped* late & sudden
    pathway is a blend of the two scenario surfaces, so it keeps the baseline
    label rather than falsely claiming the target's. Every row arriving here
    then reads `scenario_type: baseline` and takes
    `dcf.discount_rate_baseline`.

    The pathway ramps when `price_ramp: True` **and** `alignment_year` is
    strictly greater than `shock_year` — both set in stage 2, and both true as
    shipped (`price_ramp: True`, 2038 > 2033). Either half turns the ramp off
    and makes `dcf.discount_rate_shock` live again: `price_ramp: False` (the
    hard switch at `shock_year`), or `alignment_year` equal to `shock_year`,
    which `check_input_parameters` accepts — it requires `alignment_year >=
    shock_year` — and which leaves an empty transition window to blend across.

    The two pathways stay distinguishable by `trajectory_type` regardless. See
    the [user guide](../user_guide.md#discount-rates) for what to change if the
    pathways should be discounted differently.

The terminal value is where most of the valuation judgement sits. It can be
switched off (`terminal_value.method: "none"`) or computed from a **normalized**
terminal FCFF — the mean of the last `terminal_value.normalization_window` years
rather than the final year alone, so that one transition-period CapEx spike
cannot decide an asset's entire terminal value.

With `dcf.stranding_aware_tv` on (the default), that terminal FCFF is routed
through a three-way split rather than a single perpetuity:

| Tier | Condition | Terminal value |
| --- | --- | --- |
| Stranded | FCFF <= 0 for the last `stranding_consecutive_years` years | **Zero.** A rational owner exercises the abandonment option rather than funding perpetual losses |
| Declining carbontech | Still profitable, `alignment_type` is high-carbon | A **finite annuity** over `brown_remaining_life_years`, reflecting a fossil asset's finite remaining economic life in a transition |
| Everything else | — | The standard Gordon-growth **perpetuity** |

The perpetuity tier applies wherever the terminal FCFF is non-zero and the
discount rate exceeds the growth rate. Note the asymmetry that follows: an asset
whose terminal FCFF is negative but which is *not* stranded takes a negative
perpetuity. That is deliberate — a business losing money at the horizon that has
not met the stranding test is worth less than nothing, and rounding it to zero
would flatter it.

Growth rates are technology-differentiated: `g_real_brown` for high-carbon
alignments, `g_real_green` for the rest, both falling back to `g_real_default`.
Discount rates are too — `brown_discount_spread` is added to carbon-intensive
assets and `green_discount_spread` subtracted from the others, on top of the
scenario base rate.

One structural detail worth knowing: before any row-indexed logic runs, the
first node collapses CapEx flow-split rows to **one row per asset-year**.
Upstream, the capacity-flow decomposition can emit separate component rows for
the same (asset, year); their FCFFs sum correctly for present value, but the
terminal-value anchor is the group's last *row*, so duplicate years in the
anchor zone would corrupt it.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `asset_earnings` | Stage 4 (`data/07_model_output/asset_earnings.csv`) |

## Produces

Every output is persisted; these four tables are the model's headline result.

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `yearly_npv_trajectories` | `data/07_model_output/yearly_npv_trajectories.csv` | Year-by-year discounted detail per asset and trajectory type: `discount_rate`, `discount_factor`, `years_from_base`, `pv_fcff`, `terminal_value`, `yearly_npv` and the financial components |
| `asset_npv` | `data/07_model_output/asset_npv.csv` | One row per asset and owning company: `baseline_npv`, `latesudden_npv`, the two discount rates, the undiscounted component sums and the `npv_change` between them |
| `company_technology_npv` | `data/07_model_output/company_technology_npv.csv` | The same comparison per company, technology and geography, with an asset count |
| `company_npv` | `data/07_model_output/company_npv.csv` | The same comparison per company |

How to read `npv_change`, including its sign convention, is covered in the
[user guide](../user_guide.md#reading-the-sign-of-npv_change).

!!! note "Loud rather than silent"
    Three inputs abort the run rather than producing quiet nonsense: a row whose
    `scenario_type` is unresolved, a row whose `year` is `NaN` (the integer
    casts would wrap it and produce astronomical terminal values), and a missing
    required column. Group keys containing `NaN` are deliberately **kept**
    (`dropna=False` throughout), because dropping them would make assets vanish
    between two nodes with no warning.

## Nodes

| Node | Function | What it does |
| --- | --- | --- |
| `calculate_yearly_npv_trajectories` | `compute_yearly_npv_trajectories` | Discounts each year's FCFF and adds the terminal-value row |
| `aggregate_npv_by_asset` | `calculate_npv_per_asset` | Collapses the yearly detail to one row per asset, pivoting by trajectory type |
| `aggregate_npv_by_company_and_technology` | `aggregate_to_company_technology_npv` | Sums asset NPVs to company-technology-geography level |
| `aggregate_npv_by_company` | `aggregate_to_company_npv` | Sums company-technology NPVs to company level |

This set of four node names is pinned by
`tests/test_run.py::test_methodology_steps_are_visible_as_individual_nodes`.

The two roll-ups are plain sums of `baseline_npv` and `latesudden_npv` with the
discount rates averaged and the asset counts carried; `npv_change` is recomputed
at each level from that level's own totals rather than averaged up from below.

## Parameters read

Every key sits in the `dcf` block of
`conf/base/parameters_calculate_asset_and_company_npv.yml`, and is addressed in
`pipeline.py` by its dotted path:

| Key | Default | What it controls |
| --- | --- | --- |
| `dcf.discount_rate_baseline` | `0.07` | Real discount rate for rows on the baseline scenario surface |
| `dcf.discount_rate_shock` | `0.07` | Real discount rate for rows on the target scenario surface |
| `dcf.terminal_value.method` | `"perpetuity"` | `"none"` or `"perpetuity"` |
| `dcf.terminal_value.g_real_default` | `0.02` | Real terminal growth rate, used where a technology-specific rate is not set |
| `dcf.terminal_value.g_real_brown` | `0.0` | Terminal growth for high-carbon alignments - declining assets, no perpetual growth |
| `dcf.terminal_value.g_real_green` | `0.02` | Terminal growth for everything else |
| `dcf.terminal_value.normalization_window` | `3` | How many final years are averaged into the terminal FCFF |
| `dcf.brown_discount_spread` | `0.01` | Carbon risk premium added to high-carbon assets |
| `dcf.green_discount_spread` | `0.005` | Greenium subtracted from the rest |
| `dcf.stranding_aware_tv` | `True` | Use the three-tier terminal value instead of a single perpetuity |
| `dcf.stranding_consecutive_years` | `3` | Consecutive loss-making years at the horizon end that mark an asset stranded |
| `dcf.brown_remaining_life_years` | `10` | Annuity horizon for declining but profitable carbontech |

That is the whole set - `PIPELINE_PARAMETERS` in `pipeline.py` lists them
explicitly, so nothing else in the `dcf` block is visible to this stage. The two
scenario discount rates ship equal, so out of the box the rate differential in
`npv_change` comes from the technology spreads rather than from the scenario.

The [parameters reference](../parameters.md) lists the `dcf` block as a single
entry - nested sub-keys are annotated in the YAML file itself, which is the
source of truth for their defaults.

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Valuation model**, which the PDF already calls
`calculate_asset_and_company_npv` and which describes the discounting, the
terminal value and the two roll-ups.

The PDF predates the stranding-aware terminal value and the
technology-differentiated discount spreads, so it describes a single perpetuity
on a single rate. Where the two disagree, this page is current. The underlying
arguments are Gourdel (2024) for the abandonment logic behind the stranded tier,
Bolton & Kacperczyk (2021, 2023) for the carbon risk premium, and the
Damodaran / McKinsey normalized-terminal-cash-flow convention for the averaging
window.
