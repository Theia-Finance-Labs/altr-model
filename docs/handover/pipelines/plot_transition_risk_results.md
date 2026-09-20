# Stage 6 — `plot_transition_risk_results`

The reporting stage. It reads three tables the model already wrote and draws
them; it computes no new financial quantity and produces no dataset any other
stage consumes.

Source: `src/altr_model/pipelines/plot_transition_risk_results/`

## Purpose

Turn the numeric outputs into figures a reader can interrogate: how company
trajectories diverge under the shock, how the staggered shock lands across a
fleet, and how an individual asset's earnings and valuation move year by year.

Because it is purely presentational, it is the one stage that can be skipped
without affecting any number. It is also the only stage tagged `reporting`
rather than `altrisk`, so `kedro run --tags altrisk` gives you the full model
without it; a bare `kedro run` runs all six. The fixture regression suite
deliberately runs the five model stages only.

## Consumes

| Dataset | From |
|---|---|
| `company_trajectories` | Stage 3 |
| `asset_earnings` | Stage 4 |
| `yearly_npv_trajectories` | Stage 5 |

## Produces

| Output | Notes |
|---|---|
| `asset_financial_trajectories_plots_dir` | The directory the per-asset figures were written to. It is the pipeline's only declared output, and nothing downstream reads it. |

Everything else this stage writes is a **file on disk, not a catalog dataset**.
The output directories are hardcoded in `nodes.py` rather than declared in
`conf/base/catalog.yml`:

- `data/08_reporting/companies_trajectories_plots/` — filed under the four
  alignment buckets
- `data/08_reporting/companies_staggered_shock_plots/`
- `data/08_reporting/asset_financial_trajectories/` — deleted and recreated on
  every run, so it can never mix stale figures with fresh ones

!!! warning "Functions in `nodes.py` that are not nodes"
    `nodes.py` also defines `reporting_validate_inputs`, `build_reporting_views`,
    `plot_earnings_inner_workings`, `plot_valuation_authority_pack`,
    `export_reporting_tables` and `reporting_qc_summary` — and those functions
    carry the hardcoded `data/08_reporting/earnings_inner/`, `authority_pack/`
    and `tables/` paths. **None of them is wired into `pipeline.py`**, so none
    of them runs. A run of this tree produces no `validation_summary`, no
    `compliance_ready/` export tables and no QC summary. Treat them as unwired
    code, not as output you can expect.

!!! warning "These paths cannot be redirected by configuration"
    Because they are literals in the node functions, a `conf/<env>/catalog.yml`
    override cannot move them — including in the `fixture` environment. That is
    why `tests/integration/test_fixture_run.py` runs the default pipeline
    **minus this one**: a fixture run of the reporting stage would write into
    the real `data/08_reporting/` tree instead of the `data/fixture_run/`
    quarantine. If you need the plots for a fixture run, run this stage
    deliberately and knowing where its files land.

## Nodes

| Node | Function | What it draws |
|---|---|---|
| `plot_late_sudden_trajectories` | `plot_late_sudden_trajectories` | Company pathways: baseline against the late-and-sudden realized path, one figure per company/technology, filed by alignment type. |
| `plot_staggered_shock` | `plot_staggered_shock` | How the company-level shock is distributed across the individual assets of a fleet, and how much of it the fleet absorbs. |
| `plot_asset_financial_trajectories` | `plot_asset_financial_trajectories` | Per-asset financial detail: the earnings components and the yearly NPV trajectory behind a single asset's result. |

`tests/test_run.py` does not pin these three node names the way it pins the
earnings and valuation ones; what it does pin is this pipeline's only declared
output, `asset_financial_trajectories_plots_dir`, which it asserts is one of
exactly two datasets nothing downstream consumes. Renaming that output is a
contract change; renaming a node here is not.

## Parameters read

From `conf/base/parameters_plot_transition_risk_results.yml`:

| Key | Default | Meaning |
|---|---|---|
| `plot_staggered_shock_use_log_scale` | `False` | Draw the staggered-shock capacity axis on a log scale. Useful when one asset dwarfs the rest of the fleet. |
| `plot_staggered_shock_show_shock_absorption` | `False` | Overlay how much of the requested shock the fleet actually absorbed. |
| `reporting.plots.dpi` | `160` | Raster resolution for the per-asset figures. Raise it for print, lower it for a fast pass. |

## Reading the output

Start with the company trajectory plots: they are the visual form of the
`baseline` / `late_sudden_requested` / `late_sudden_realized` distinction
described in [stage 3](allocate_company_trajectories_to_assets.md). Where
*requested* and *realized* separate, the fleet could not deliver the transition
that was asked of it — and the financial consequence of that gap is what the
asset financial trajectories then show.
