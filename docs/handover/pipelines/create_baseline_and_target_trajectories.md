# Stage 3 - `create_baseline_and_target_trajectories`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/create_baseline_and_target_trajectories/` |
| Tags | `altrisk` |
| Runs after | [Stage 2 - `inputs_postproc`](inputs_postproc.md) |
| Runs before | [Stage 4 - `create_late_sudden_trajectories`](create_late_sudden_trajectories.md) |

## Purpose

Builds the two reference paths every later comparison rests on. Asset forecasts
are aggregated to company-technology level, each scenario pathway is converted
into a Technology Market Share Rate (TMSR) - a growth factor relative to the
pathway's first year - and those factors are applied to each company's starting
capacity.

The result is one baseline path and one target path per
company/technology/geography: what the company's capacity does if the world
follows the baseline scenario, and what it would do under the target scenario.
Neither is the shock yet; stage 4 turns the gap between them into one.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `companies_forecasts` | Stage 2 (in memory) |
| `scenarios_pathways` | Stage 1 (`data/05_model_output/scenarios_pathways.csv`) |

## Produces

All in-memory; `companies_trajectories` is what stage 4 consumes:

| Dataset | What it is |
| --- | --- |
| `companies_technology_forecasts` | Company-technology capacity, aggregated from the asset panel |
| `traj_scenario_tmsr` | Scenario pathways expressed as growth factors relative to their first year |
| `scenarios_trajectories` | Those factors joined onto each company's technologies |
| `companies_trajectories` | Baseline and target capacity paths per company/technology/geography/year |

## Nodes

| Function | What it does |
| --- | --- |
| `aggregate_assets_to_company_level` | Sums asset activity into company-technology totals |
| `calculate_tmsr` | Converts each scenario pathway into its Technology Market Share Rate growth factor |
| `compute_scenarios_trajectories` | Merges the TMSR factors onto the company forecasts |
| `create_companies_trajectories` | Applies the factors to each company's starting capacity to get both paths |

## Parameters read

None. The stage is driven entirely by the scenario pair chosen in
[stage 1](inputs_processing.md) - `conf/base/parameters_create_baseline_and_target_trajectories.yml`
holds no active keys. See the [parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Shock mechanism**, which covers stages 3 and 4 together
under the name `calculate_company_trajectories`; the PDF's
`company_pathways_pre_allocation` table corresponds to this stage's
`companies_trajectories` plus the late & sudden path added in stage 4.
