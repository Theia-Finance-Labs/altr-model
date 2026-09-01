# Stage 3 - `allocate_company_trajectories_to_assets`

| | |
| --- | --- |
| Source | `src/altr_model/pipelines/allocate_company_trajectories_to_assets/` |
| Tags | `altrisk` |
| Runs after | [Stage 2 - `calculate_company_trajectories`](calculate_company_trajectories.md) |
| Runs before | [Stage 4 - `calculate_asset_earnings`](calculate_asset_earnings.md) |
| Nodes | 9 |

## Purpose

Spreads the company-level shock down onto individual assets - deciding, plant by
plant, how much of a company's decline (or growth) each one absorbs. Decreasing
technologies can retire on schedule and can have the cut staggered across assets
via an age-based quantile curve instead of applied proportionally; increasing
technologies keep their real assets on the baseline path and get a single
synthetic build-out asset topping the company up to its requested late & sudden
series.

The stage also records what the fleet could *not* absorb. Alongside the asset
trajectories it emits a company table carrying a fourth `trajectory_type`,
`late_sudden_realized`, which is the sum of the allocated asset capacities - so
the requested company path and the realised one can be compared directly.

The asset panel is extended to the scenario horizon and given a retirement year
here, using two functions that live in
[stage 1](prepare_scenario_asset_and_company_inputs.md)'s
`_asset_preparation.py`.

Retirement is applied against a floor: the effective retirement year is
`max(retirement_year, alignment_year + 1)`, so an asset dated to retire during
or before the transition window keeps running until the year after alignment
(`_allocation_nodes.py`). The `retirement_year` on the panel is the input to
that clip, not the year capacity actually stops — see
[Methodology notes](../methodology_notes.md#asset-retirement-refurbishment-wrap-around-not-a-hard-cutoff).

## Consumes

| Dataset | Produced by |
| --- | --- |
| `company_pathways_pre_allocation` | Stage 2 (in memory) |
| `asset_forecast_panel` | Stage 1 (in memory) |

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `asset_trajectories` | `data/07_model_output/asset_trajectories.csv` | The canonical long asset table: one row per asset/company/year/`trajectory_type`, with the active financial assumptions, emission factor and retirement year attached |
| `company_trajectories` | `data/07_model_output/company_trajectories.csv` | The stage-2 company table plus the `late_sudden_realized` rows derived from the allocated asset capacity |
| `frozen_capacity_at_retirement` | `data/07_model_output/frozen_capacity_at_retirement.csv` | For every retiring asset, the capacity it last stood at, carried across every year from its retirement onward |
| `_extended_asset_panel`, `_assets_with_baseline`, `_decreasing_company_pathways`, `_increasing_company_pathways`, `_decreasing_asset_allocation`, `_increasing_asset_allocation`, `_asset_allocation_wide` | in memory | Private, namespaced working tables between the nodes below |

`frozen_capacity_at_retirement` is produced here rather than in the earnings
stage because this is where `retirement_year` lives — it is a filter on the wide
allocation panel, not a join. Stage 4 merges it onto the asset panel, but
nothing in the earnings maths reads it: fixed costs use first-year capacity.

## Nodes

| Node | What it does |
| --- | --- |
| `extend_assets_and_attach_retirement` | Extends every asset's rows to the scenario end year and carries a `retirement_year` on each row, from asset age and technology lifetime |
| `compute_asset_baselines` | Scales company baseline paths down to assets over the full horizon, zeroing retired asset-years when `apply_retirement_baseline` is on |
| `split_company_pathways_by_technology_direction` | Splits the company table into the decreasing and increasing streams - a named node rather than an inline branch, so the methodology fork is visible in `kedro viz` |
| `allocate_decreasing_company_trajectories_to_assets` | Allocates the company cut across assets - proportional scaling, or age-staggered g-weights with capped reductions - then flags permanently phased-out assets as retired |
| `allocate_increasing_company_trajectories_to_assets` | Keeps real assets on their baseline path and adds the synthetic top-up asset |
| `combine_asset_allocation_branches` | Concatenates both streams and restores the carried asset metadata (emission factor, retirement year, technology lifetime) |
| `build_canonical_asset_trajectories` | Melts the wide asset frame into the long form downstream stages consume and joins the active financial surface onto each row |
| `create_frozen_capacity_at_retirement` | Takes each retiring asset's capacity in the year before its *effective* retirement (the raw `retirement_year`, floored at `alignment_year + 1` exactly as allocation floors it) - from that year on the capacity is zero - and extends that level across every year from retirement onward |
| `reconcile_realized_company_trajectories` | Sums the allocated `latesudden` asset capacity back to company level and appends it as `late_sudden_realized` |

### The functions behind the nodes

The node functions in `nodes.py` are adapters: they translate the canonical
tables into the shapes the allocation maths expects and call into
`_allocation_nodes.py`.

| Function | What it does |
| --- | --- |
| `compute_asset_baseline_trajectories` | Scales company baseline paths down to assets over the full horizon |
| `split_late_sudden_trajectories_by_alignment_type` | Returns the decreasing/increasing split of the requested late & sudden rows |
| `stagger_decreasing_technologies` | Proportional scaling or staggered allocation, both with retirement compensation |
| `flag_phased_out_assets_as_retired` | Marks assets whose capacity the shock permanently phases out |
| `stagger_increasing_technologies` | Baseline passthrough for real assets plus the synthetic top-up |
| `melt_asset_staggered_trajectories` | Melts the wide asset frame into `trajectory_type` / `asset_trajectory` rows |

Private helpers, all in `_allocation_nodes.py`: `_build_retirement_map`,
`_compute_g_weights_array` (the logistic age curve), `_index_company_by_year`,
`_index_assets_by_group`, `_allocate_reduction_with_caps_array` (the
clamp-and-redistribute step), and the two allocation kernels
`_stagger_decreasing_fast` and `_prop_scale_decreasing_fast`. In `nodes.py`,
`_legacy_company_pathways` and `_retirement_lookup` are the two adapters that
reshape the canonical tables for those kernels.

## Parameters read

| Key | Defined in |
| --- | --- |
| `shock_year`, `alignment_year` | `conf/base/parameters_calculate_company_trajectories.yml` |
| `apply_retirement_baseline`, `apply_retirement_shock`, `apply_decreasing_staggered_shock` | `conf/base/parameters_allocate_company_trajectories_to_assets.yml` |
| `staggered_shock.g_k`, `staggered_shock.n_quantiles` | `conf/base/parameters_allocate_company_trajectories_to_assets.yml` |

`shock_year` and `alignment_year` are read here but defined in another
pipeline's file: Kedro merges every parameters file into one namespace, so the
defining file does not have to match the pipeline that reads the key.

`apply_decreasing_staggered_shock` is the switch between the two allocation
modes; `g_k` (curve steepness) and `n_quantiles` (number of age buckets) only
matter when it is on, and it ships `False`. Defaults and the full annotations:
[parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Staggered shock**, which the PDF already calls
`allocate_company_trajectories_to_assets`, plus two of the
[methodology notes](../methodology_notes.md):
[synthetic assets for increasing technologies](../methodology_notes.md#synthetic-assets-for-increasing-technologies),
which explains why a company only gets a synthetic asset in a
country/technology where it already has a real presence, and
[asset retirement](../methodology_notes.md#asset-retirement-refurbishment-wrap-around-not-a-hard-cutoff).
