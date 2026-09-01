# Stage 4 - `create_late_sudden_trajectories`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/create_late_sudden_trajectories/` |
| Tags | `altrisk` |
| Runs after | [Stage 3 - `create_baseline_and_target_trajectories`](create_baseline_and_target_trajectories.md) |
| Runs before | [Stage 5 - `distribute_impacts_to_asset_level`](distribute_impacts_to_asset_level.md) |

## Purpose

This is where the transition shock is defined. Every company-technology pathway
is classified as aligned or misaligned with the target scenario, and then given
its late & sudden trajectory: production follows the baseline until
`shock_year`, after which it bends steeply enough that the target is still met
by `alignment_year`.

The classification crosses two axes - aligned vs misaligned, and high-carbon
(decreasing) vs low-carbon (increasing) technologies - giving four buckets, each
with its own shock shape. A misaligned coal producer has to fall much faster
after the shock year than an already-aligned one; a low-carbon producer is asked
to build faster instead. The four buckets are concatenated back into a single
table.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `companies_trajectories` | Stage 3 (in memory) |
| `increasing_or_decreasing_techs` | Stage 1 (in memory) |

## Produces

| Dataset | Persisted to | What it is |
| --- | --- | --- |
| `companies_late_sudden_trajectories` | `data/07_model_output/companies_late_sudden_trajectories.csv` | Baseline, target and late & sudden paths per company/technology/geography/year |
| `all_alignment_classifications` | in memory | The aligned/misaligned × high/low-carbon label per company-technology; read again by stage 6 |
| `misaligned_high_carbon_…`, `misaligned_low_carbon_…`, `aligned_high_carbon_…`, `aligned_low_carbon_…` (and their `late_sudden_*` results) | in memory | The four buckets, before and after their shock shape is applied |

## Nodes

| Function | What it does |
| --- | --- |
| `determine_companies_technologies_alignment` | Classifies each company-technology and splits the table into the four buckets |
| `late_sudden_misaligned_high_carbon_companies` | Shock shape for misaligned high-carbon pathways, with asset retirement |
| `late_sudden_misaligned_low_carbon_companies` | Shock shape for misaligned low-carbon pathways |
| `late_sudden_aligned_high_carbon_companies` | Shock shape for aligned high-carbon (decreasing) pathways |
| `late_sudden_aligned_low_carbon_companies` | Shock shape for aligned low-carbon pathways |
| `concatenate_late_sudden_results` | Concatenates the four results into `companies_late_sudden_trajectories` |

Private helper: `_baseline_shock_anchor` - the baseline value at the last grid
year before `shock_year`, which every shock shape starts from.

## Parameters read

| Key | Defined in |
| --- | --- |
| `shock_year`, `alignment_year` | `conf/base/parameters.yml` |

Both are passed to all four shock-shape nodes. Defaults and the full
annotations: [parameters reference](../parameters.md).

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Shock mechanism** (PDF pipeline name:
`calculate_company_trajectories`), which describes the four-case classification
and the late-sudden path that follows baseline assumptions to `shock_year` and
target assumptions from there through `alignment_year`.
