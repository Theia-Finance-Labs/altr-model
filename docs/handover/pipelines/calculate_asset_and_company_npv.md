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

The terminal value is where most of the valuation judgement sits. It can be
switched off (`terminal_value.method: "none"`) or computed as a Gordon-growth
perpetuity on the group's final-year FCFF, discounted back from one year past
the horizon. The perpetuity is applied only where the final FCFF is **positive**
and the discount rate exceeds the growth rate; everywhere else the terminal
value is zero, which is what keeps a loss-making asset from being handed a
negative perpetuity.

!!! warning "Pending adjudication — Q2"
    This section also described a three-way stranding-aware split of the
    terminal value - zero for assets whose last years are loss-making, a finite
    annuity for still-profitable carbon-intensive assets, and the standard
    perpetuity for everything else. The behaviour it describes is not present in
    this codebase and the question of whether to adopt it is open (ledger
    question Q2). The paragraph will be rewritten once the ruling is recorded;
    it is deliberately not documented in the meantime.

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
| `dcf.terminal_value.g_real_default` | `0.02` | Real terminal growth rate |

Those four are the whole set - `PIPELINE_PARAMETERS` in `pipeline.py` lists them
explicitly, so nothing else in the `dcf` block is visible to this stage. The two
discount rates ship equal, so out of the box the whole `npv_change` comes from
the cash flows rather than from a rate differential.

!!! warning "Pending adjudication — Q2"
    This table also carried rows for a stranding-aware terminal-value switch and
    the number of consecutive loss-making years that would mark an asset
    stranded. The behaviour they describe is not present in this codebase and
    the question of whether to adopt it is open (ledger question Q2). The rows
    will be rewritten once the ruling is recorded; they are deliberately not
    documented in the meantime.

The [parameters reference](../parameters.md) lists the `dcf` block as a single
entry - nested sub-keys are annotated in the YAML file itself, which is the
source of truth for their defaults.

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Valuation model**, which the PDF already calls
`calculate_asset_and_company_npv` and which describes the discounting, the
terminal value and the two roll-ups.

!!! warning "Pending adjudication — Q2"
    This section also pointed at the PDF's treatment of technology-differentiated
    discount spreads and the stranding-aware terminal value. Neither is present
    in this codebase and the question of whether to adopt them is open (ledger
    question Q2). The line will be rewritten once the ruling is recorded; it is
    deliberately not documented in the meantime.
