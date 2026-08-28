# CLAUDE.md — crispy-kedro

## Why

ALTR (Asset-Level Transition Risk) — the next generation of the TRISK climate stress-testing methodology, written in Python on Kedro. The model computes firm-level NPV under climate transition scenarios (AR6 / NGFS) by combining IAM scenario data with asset-level capacity and cost information. Output feeds bank stress tests, supervisory exercises (EBA, ECB), and the academic paper "Asset-level analysis of corporate value adjustment in the climate transition" (Tang, Yilmaz, Gallice, Hejazi, Cervenka et al.).

Used by 1in1000 / Theia / Alternative Pathways Lab.

## What

Seven-pipeline Kedro DAG:

```
inputs_processing -> inputs_postproc
  -> create_baseline_and_target_trajectories (TMSR, fair share)
    -> create_late_sudden_trajectories (4-bucket alignment, shock paths)
      -> distribute_impacts_to_asset_level (g-weights by asset age)
        -> earnings_model (Revenue - Fuel - FOM - Carbon - CapEx -> EBITDA -> FCFF)
          -> valuation_model (DCF, terminal value, NPV change, VaR)
            -> reporting
```

Headline mechanisms (what ALTR has vs legacy TRISK):

| Feature | TRISK (R) | ALTR (this repo) |
|---|---|---|
| Profitability | `production * price * margin` | Full EBITDA decomposition |
| Fuel | none | `fuel_price / efficiency` per asset, zero for renewables |
| Fixed O&M | none | `fom_usd_per_mw_yr * capacity`, continues on stranded |
| CapEx | none | 3-stream: growth + replacement + decommissioning |
| Carbon cost | price reduction | differential or full EF above marginal generator |
| Pricing | single exogenous price | MCPR: marginal tech price x value factors |
| Retirement | uniform | staggered by asset age (logistic g-weights) |
| Alignment | binary | 4-bucket (aligned/misaligned x increasing/decreasing) |
| Merton PD | yes (basic) | not yet implemented |

## How

### Conventions

- **Python 3.10+, Kedro, Poetry.** `poetry install`, `kedro run` to execute pipelines.
- **Immutable surfaces.** Scenario surfaces (`scenarios_pathways.csv`, `asset_panel.parquet`) are written once per run, never mutated.
- **Parameterised everything.** Switches in `conf/base/parameters_*.yml`. Code reads from `params:*`; no magic constants.
- **Comparison harness.** `notebooks/run_all_scenarios_comparison.py` runs config matrices (e.g. `vanilla`, `iso_d1`, `mcpr_v2_carbon`, `mcpr_v2_merit`) across IAM providers. Output: `workspace/comparison_results/<provider>/<config>/`.

### Key parameters (current defaults)

```yaml
shock_year: 2033
alignment_year: 2038
discount_rate_baseline: 0.07
discount_rate_shock: 0.07
terminal_growth_rate: 0.02
market_passthrough: 0
enable_mcpr: True
mcpr_mode: "auto"                # v2: "auto" | "carbon_explicit" | "merit_order_decline"
mcpr_merit_order_alpha: 0.006    # IMF: -0.6% wholesale price per 1pp VRE share
mcpr_merit_order_floor: 0.5      # min clearing price as fraction of original
carbon_cost_method: "differential_ef"  # forced to "full_ef" under mcpr_v2_carbon
include_growth_capex: True
include_replacement_capex: True
include_decom_costs: True
apply_continued_om_baseline: False
apply_continued_om_shock: True
```

### Active model architecture decisions

- **MCPR v2 two-mode split** (`docs/superpowers/specs/2026-04-14-mcpr-v2-redesign.md`). `carbon_explicit` for the 18/25 IAMs that ship carbon prices; `merit_order_decline` (P decays with VRE share, alpha=0.006, floor 0.5) for the 7/25 that don't. `auto` detects from data. v1 (single mode, static value factors) is documented in `MCPR/ALTR_MCPR_methodology_v1.md`.
- **Carbon channel routing per IAM.** AR6 electricity prices already embed carbon to varying degrees: WITCH minimal ($9 spread C1->C7, use differential), AIM/CGE full ($64 spread, set carbon_price=0), REMIND/IMAGE check empirically. The `carbon_cost_method` parameter encodes this.
- **Decom sign fix** (Phase 1 of NPV direction fix, `ALTR_NPV_Direction_Fix_Research.md` RC2). `decom_cost = abs(scrap) * retired` not `scrap * retired`. Without this, fossil retirements paid out instead of cost out.
- **Terminal value gate removed** (RC7). `if final_fcff > 0` was an ALTR regression vs original R TRISK and Damodaran/CFA practice. Negative TVs now flow through. Optional `terminal_normalization_window=3` for FCFF averaging.

### Where to look

| Question | File |
|---|---|
| Pipeline DAG / parameters | `conf/base/parameters_*.yml`, `src/crispy_kedro/pipelines/*/pipeline.py` |
| Revenue, MCPR, carbon cost, decom | `src/crispy_kedro/pipelines/earnings_model/nodes.py` |
| DCF, terminal value, NPV | `src/crispy_kedro/pipelines/valuation_model/nodes.py` |
| Shock surface construction | `src/crispy_kedro/pipelines/create_late_sudden_trajectories/nodes.py` |
| MCPR v1 methodology | `MCPR/ALTR_MCPR_methodology_v1.md` |
| MCPR v2 spec + findings | `docs/superpowers/specs/2026-04-14-mcpr-v2-redesign.md` |
| NPV direction root causes | `ALTR_NPV_Direction_Fix_Research.md` |
| 31-improvement roadmap | `docs/research/ALTR_IMPROVEMENT_BRIEF.md` |
| Comparison harness | `notebooks/run_all_scenarios_comparison.py` |

### Open architectural issues (June 2026)

- **RC4 — near-term price windfall** at hard baseline->target switch (target prices +30-51% at shock year). Open.
- **RC5 — gas as marginal generator** has zero differential carbon cost. Partially addressed by MCPR v2 mode 1 (forces full_ef) but mixed empirical results (helps WITCH +7.9pp, hurts MESSAGEix -5.4pp).
- **GasCap structural positive NPV** in some geographies. Open architectural issue with baseline comparison.
- **Merton PD layer** not implemented. M1 in roadmap.

### Related repos (Jakub's `~/Documents/repos/`)

- `trisk.model`, `trisk.analysis`, `trisk.r.docker` — legacy R stack.
- `crispy-app` — enterprise platform wrapping crispy-kedro (FastAPI + React).
