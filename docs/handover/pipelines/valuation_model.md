# Stage 7 - `valuation_model`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/valuation_model/` |
| Tags | `altrisk` |
| Runs after | [Stage 6 - `earnings_model`](earnings_model.md) |
| Runs before | [Stage 8 - `reporting`](reporting.md) |

## Purpose

Converts the per-asset FCFF series into present values. Each year's cash flow is
discounted at a rate that depends on the trajectory type and, optionally, on
whether the technology is "brown" or "green"; a terminal value is added beyond
the forecast horizon; and the result is rolled up from asset to
company-technology to company level.

The terminal value is where most of the valuation judgement sits. It can be
switched off, computed as a Gordon-growth perpetuity on a normalised
final-years FCFF, or - with `stranding_aware_tv` on - split three ways: zero for
assets whose last years are loss-making (the abandonment option), a finite
annuity for still-profitable carbontech, and the standard perpetuity for
everything else.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `asset_earnings` | Stage 6 (`data/07_model_output/asset_earnings.csv`) |

## Produces

Every output is persisted; these four tables are the model's headline result.

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `yearly_npv_trajectories` | `data/07_model_output/yearly_npv_trajectories.csv` | Year-by-year discounted detail per asset and trajectory type |
| `asset_npv` | `data/07_model_output/asset_npv.csv` | One row per asset: `baseline_npv`, `latesudden_npv`, and the `npv_change` between them |
| `company_technology_npv` | `data/07_model_output/company_technology_npv.csv` | The same comparison per company and technology, with an asset count |
| `company_npv` | `data/07_model_output/company_npv.csv` | The same comparison per company |

How to read `npv_change`, including its sign convention, is covered in the
[user guide](../user_guide.md#reading-the-sign-of-npv_change).

## Nodes

| Function | What it does |
| --- | --- |
| `compute_yearly_npv_trajectories` | Discounts each year's FCFF, applies the discount-rate spreads and adds the terminal value |
| `calculate_npv_per_asset` | Collapses the yearly detail to one row per asset, pivoting by trajectory type |
| `aggregate_to_company_technology_npv` | Sums asset NPVs to company-technology level |
| `aggregate_to_company_npv` | Sums company-technology NPVs to company level |

## Parameters read

Every key sits in the `dcf` block of
`conf/base/parameters_valuation_model.yml`, and is addressed in `pipeline.py` by
its dotted path:

| Key | Default | What it controls |
| --- | --- | --- |
| `dcf.discount_rate_baseline` | `0.07` | Real discount rate for baseline cash flows |
| `dcf.discount_rate_shock` | `0.07` | Real discount rate for late & sudden cash flows |
| `dcf.brown_discount_spread` | `0.01` | Added to the rate for carbon-intensive technologies (carbon risk premium) |
| `dcf.green_discount_spread` | `0.005` | Subtracted from the rate for clean technologies (greenium) |
| `dcf.terminal_value.method` | `"perpetuity"` | `"none"` or `"perpetuity"` |
| `dcf.terminal_value.g_real_default` | `0.02` | Real terminal growth rate when no technology-specific rate applies |
| `dcf.terminal_value.g_real_brown` | `0.0` | Terminal growth for carbontech |
| `dcf.terminal_value.g_real_green` | `0.02` | Terminal growth for greentech |
| `dcf.terminal_value.normalization_window` | `3` | Number of final years averaged into the terminal FCFF |
| `dcf.stranding_aware_tv` | `True` | Switches on the three-tier stranding-aware terminal value |
| `dcf.stranding_consecutive_years` | `3` | Consecutive loss-making years at the horizon that mark an asset stranded |
| `dcf.brown_remaining_life_years` | `10` | Finite annuity horizon for still-profitable carbontech |

The [parameters reference](../parameters.md) lists the `dcf` block as a single
entry - nested sub-keys are annotated in the YAML file itself, which is the
source of truth for their defaults.

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Valuation model** (PDF pipeline name:
`calculate_asset_and_company_npv`), which describes the discounting, the
terminal value and the two roll-ups. The technology-differentiated discount
spreads and the stranding-aware terminal value post-date that section and are
annotated in `conf/base/parameters_valuation_model.yml`.
