# Stage 5 - `distribute_impacts_to_asset_level`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/distribute_impacts_to_asset_level/` |
| Tags | `altrisk` |
| Runs after | [Stage 4 - `create_late_sudden_trajectories`](create_late_sudden_trajectories.md) |
| Runs before | [Stage 6 - `earnings_model`](earnings_model.md) |

## Purpose

Spreads the company-level shock down onto individual assets - deciding, plant by
plant, how much of a company's decline (or growth) each one absorbs. Decreasing
technologies can retire on schedule and can have the cut staggered across assets
via an age-based quantile curve instead of applied uniformly; increasing
technologies keep their real assets on the baseline path and get a single
synthetic build-out asset topping the company up to its late & sudden series.

The stage also records what the fleet could *not* absorb: alongside the asset
trajectories it emits a corrected company table, so the requested company path
and the realised sum of asset capacity can be compared.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `companies_late_sudden_trajectories` | Stage 4 (`data/07_model_output/companies_late_sudden_trajectories.csv`) |
| `extended_companies_forecasts`, `assets_retirement_dates` | Stage 2 (in memory) |

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `asset_level_staggered_shock` | `data/07_model_output/asset_level_staggered_shock.csv` | Wide asset-level capacities per trajectory type |
| `frozen_capacity_at_retirement` | `data/07_model_output/frozen_capacity_at_retirement.csv` | Last active capacity of each retiring asset, for continued fixed-cost charging in stage 6 |
| `asset_level_staggered_shock_melted` | in memory | The long form (`trajectory_type`, `asset_trajectory`) stage 6 consumes |
| `companies_late_sudden_trajectories_corrected` | in memory | Company paths after allocation - the realised counterpart of the requested path |
| `assets_with_baseline_trajectory`, the decreasing/increasing splits and their staggered results | in memory | Working tables between the nodes below |

## Nodes

The implementation is split by concern; `nodes.py` re-exports every function for
backwards compatibility.

| Function | Module | What it does |
| --- | --- | --- |
| `compute_asset_baseline_trajectories` | `baseline.py` | Scales company baseline paths down to assets over the full horizon, zeroing retired asset-years when retirement is on |
| `split_late_sudden_trajectories_by_alignment_type` | `assembly.py` | Splits the company late & sudden table into decreasing and increasing streams |
| `stagger_decreasing_technologies` | `staggering_decrease.py` | Allocates the company cut across assets - proportional scaling, or age-staggered g-weights with capped reductions |
| `flag_phased_out_assets_as_retired` | `retirement.py` | Marks assets whose capacity the shock permanently phases out |
| `stagger_increasing_technologies` | `staggering_increase.py` | Keeps real assets on their baseline path and adds the synthetic top-up asset |
| `concatenate_staggered_shock_results` | `assembly.py` | Concatenates both streams and emits the corrected company table |
| `melt_asset_staggered_trajectories` | `assembly.py` | Melts the wide asset frame into the long form used downstream |
| `create_frozen_capacity_at_retirement` | `retirement.py` | Freezes each retiring asset's last active capacity |

Private helpers: `_build_retirement_map` (`retirement.py`),
`_compute_g_weights_array` and `_index_company_by_year` (`baseline.py`),
`_stagger_decreasing_fast` and `_prop_scale_decreasing_fast`
(`staggering_decrease.py`), and `_allocate_reduction_with_caps_array` /
`_index_assets_by_group` in `_shared.py`, which both staggering modules use.

## Parameters read

| Key | Defined in |
| --- | --- |
| `shock_year`, `alignment_year` | `conf/base/parameters.yml` |
| `apply_retirement_baseline`, `apply_retirement_shock`, `apply_decreasing_staggered_shock` | `conf/base/parameters_distribute_impacts_to_asset_level.yml` |
| `staggered_shock.g_k`, `staggered_shock.n_quantiles` | `conf/base/parameters_distribute_impacts_to_asset_level.yml` |

`apply_decreasing_staggered_shock` is the switch between the two allocation
modes; `g_k` (curve steepness) and `n_quantiles` (number of age buckets) only
matter when it is on. Defaults and the full annotations:
[parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Staggered shock** (PDF pipeline name:
`allocate_company_trajectories_to_assets`), plus **Additional notes →
*Synthetic assets for increasing technologies***, which explains why a company
only gets a synthetic asset in a country/technology where it already has a real
presence, and **Additional notes → *Asset retirement age: refurbishment
wrap-around, not a hard cutoff***.
