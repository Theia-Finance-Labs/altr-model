# Stage 2 - `calculate_company_trajectories`

| | |
| --- | --- |
| Source | `src/altr_model/pipelines/calculate_company_trajectories/` |
| Tags | `altrisk` |
| Runs after | [Stage 1 - `prepare_scenario_asset_and_company_inputs`](prepare_scenario_asset_and_company_inputs.md) |
| Runs before | [Stage 3 - `allocate_company_trajectories_to_assets`](allocate_company_trajectories_to_assets.md) |
| Nodes | 8 |

## Purpose

Builds both reference paths **and** the shock, in one pipeline. Earlier versions
of the model split these across two stages; here they are one, because the shock
is defined entirely in terms of the two reference paths and nothing else reads
the intermediate.

The first half builds the references. Each scenario pathway is expressed as a
Technology Market Share Rate (TMSR) - a growth factor relative to the pathway's
first year - and those factors are applied to each company's starting capacity,
giving one baseline path and one target path per
company/geography/sector/technology.

The second half defines the transition shock. Every company-technology pathway
is classified against two axes - aligned vs misaligned with the target, and
high-carbon (decreasing) vs low-carbon (increasing) - giving four cases, each
with its own shock shape. Production follows the baseline until `shock_year`,
after which it bends steeply enough that the target is met by `alignment_year`.
A misaligned coal producer has to fall much faster after the shock year than an
already-aligned one; a low-carbon producer is asked to build faster instead.

The four cases are then concatenated and melted into one canonical table
carrying three `trajectory_type` values - `baseline`, `target` and
`late_sudden_requested` - with the financial surface columns switched onto the
target scenario's values for every row on the target surface (the target path,
and the requested path from `shock_year` onwards).

## Consumes

| Dataset | Produced by |
| --- | --- |
| `company_projection_inputs` | Stage 1 (in memory) |

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `company_pathways_pre_allocation` | in memory | The canonical company table: baseline, target and requested late & sudden paths per company/geography/sector/technology/year, with the alignment case and the active financial assumptions on every row |
| `_baseline_target_trajectories`, `_classified_company_trajectories`, and the four `_*_trajectories` case frames | in memory | Private, namespaced intermediates between the nodes below |

## Nodes

| Node | Function | What it does |
| --- | --- | --- |
| `validate_model_years` | `validate_model_years` | Fails the run early if `alignment_year` is below `shock_year` |
| `calculate_baseline_and_target_trajectories` | `compute_baseline_and_target_trajectories` | Applies the TMSR growth factors to each company's starting capacity, producing both reference paths |
| `classify_company_trajectory_alignment` | `classify_company_trajectory_alignment` | Labels every company-technology with `aligned`, `increasing` and the four-way `alignment_type` |
| `calculate_misaligned_decreasing_technology_transition` | same | Shock shape for `misaligned_high_carbon` pathways, with asset retirement |
| `calculate_misaligned_increasing_technology_transition` | same | Shock shape for `misaligned_low_carbon` pathways |
| `calculate_aligned_decreasing_technology_transition` | same | Shock shape for `aligned_high_carbon` (decreasing) pathways |
| `calculate_aligned_increasing_technology_transition` | same | Shock shape for `aligned_low_carbon` pathways |
| `combine_company_trajectory_cases` | same | Concatenates the four cases, melts them into `trajectory_type` rows and resolves the active financial surface per row |

The four case nodes are deliberately separate rather than one dispatching node:
each is visible on its own in `kedro viz`, and each takes the same
`shock_year` / `alignment_year` pair.

### The functions behind the nodes

`_baseline_nodes.py` - the reference paths:

| Function | What it does |
| --- | --- |
| `aggregate_assets_to_company_level` | Sums asset activity into company-technology totals |
| `calculate_tmsr` | Converts each scenario pathway into its Technology Market Share Rate growth factor |
| `compute_scenarios_trajectories` | Merges the TMSR factors onto the company forecasts |
| `create_companies_trajectories` | Applies the factors to each company's starting capacity to get both paths |

`aggregate_assets_to_company_level` and `calculate_tmsr` are also imported by
[stage 1](prepare_scenario_asset_and_company_inputs.md), which needs them while
building `company_projection_inputs`.

`_late_sudden_nodes.py` - the four shock shapes:

| Function | What it does |
| --- | --- |
| `determine_companies_technologies_alignment` | Decides whether each company-technology is aligned with the target and splits the table into the four buckets |
| `late_sudden_misaligned_high_carbon_companies` | Shock shape for misaligned high-carbon pathways, with asset retirement |
| `late_sudden_misaligned_low_carbon_companies` | Shock shape for misaligned low-carbon pathways |
| `late_sudden_aligned_high_carbon_companies` | Shock shape for aligned high-carbon (decreasing) pathways |
| `late_sudden_aligned_low_carbon_companies` | Shock shape for aligned low-carbon pathways |

Private helper: `_baseline_shock_anchor` - the baseline value at the last grid
year before `shock_year`, which every shock shape starts from. It falls back to
the first grid year when the scenario grid starts at or after the shock year,
rather than crashing on an empty selection.

Each shock shape labels its years with a `late_sudden_phase`
(`forecast` / `bau` / `transition` / `aligned` / `aligned_compensation`), which
survives all the way into `asset_earnings` and drives the phase bands on the
trajectory plots.

## Parameters read

| Key | Defined in |
| --- | --- |
| `shock_year`, `alignment_year` | `conf/base/parameters_calculate_company_trajectories.yml` |

Both are passed to all four shock-shape nodes and to the validator; `shock_year`
is also passed to `combine_company_trajectory_cases`, which uses it to decide
from which year the requested path switches onto the target financial surface.
Defaults and the full annotations: [parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Shock mechanism**, which the PDF already calls
`calculate_company_trajectories` and which describes the four-case
classification and the late-sudden path that follows baseline assumptions to
`shock_year` and target assumptions from there through `alignment_year`. The
PDF's `company_pathways_pre_allocation` table is this stage's output, and it
carries that name in the code.
