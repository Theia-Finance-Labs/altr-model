# Stage 2 - `inputs_postproc`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/inputs_postproc/` |
| Tags | `altrisk` |
| Runs after | [Stage 1 - `inputs_processing`](inputs_processing.md) |
| Runs before | [Stage 3 - `create_baseline_and_target_trajectories`](create_baseline_and_target_trajectories.md) |

## Purpose

Takes the ownership-allocated asset forecasts from stage 1 and prepares them for
the trajectory stages: optionally collapsing asset-level rows to company level,
extending each company's forecast to the full scenario horizon, and deriving the
retirement year of every asset from its age and its technology's lifetime.

This is a small stage with large consequences. Its granularity switch decides
whether the rest of the run reasons about real plants or about one synthetic row
per company-technology, and its retirement dates drive the capacity drop-off
that stages 5 and 6 charge for.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `allocated_assets_to_companies` | Stage 1 (persisted to `data/07_model_output/allocated_assets_to_companies.csv`) |
| `scenarios_pathways` | Stage 1 (persisted to `data/05_model_output/scenarios_pathways.csv`) |
| `lifetime_per_technology` | Stage 1 (in memory) |

## Produces

All three outputs are in-memory datasets, read by stages 3, 5 and 6:

| Dataset | What it is |
| --- | --- |
| `companies_forecasts` | The asset panel, at asset granularity or collapsed to company-technology rows |
| `extended_companies_forecasts` | The same panel extended across the full scenario year range |
| `assets_retirement_dates` | One retirement year per asset, from asset age and technology lifetime |

## Nodes

| Function | What it does |
| --- | --- |
| `apply_reduce_granularity_from_asset_to_company_level` | Passes the panel through, or aggregates it to one row per company-technology when the switch is on |
| `extend_allocated_assets_to_companies` | Extends each company's forecast to every year present in the scenario pathways |
| `determine_assets_retirement_dates` | Dates each asset's retirement from its age and its technology's lifetime |

## Parameters read

| Key | Defined in |
| --- | --- |
| `reduce_granularity_from_asset_to_company_level` | `conf/base/parameters_inputs_postproc.yml` |

`theta_capex_recovery` is also defined in this pipeline's parameters file, but it
is read by [stage 1](inputs_processing.md). Defaults and the full annotations:
[parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Inputs preparation** (the PDF treats stages 1 and 2 as
one pipeline, `prepare_scenario_asset_and_company_inputs`). Two entries under
**Additional notes** describe this stage's two decisions directly: *Granularity
changes the shape of every output* and *Asset retirement age: refurbishment
wrap-around, not a hard cutoff*.
