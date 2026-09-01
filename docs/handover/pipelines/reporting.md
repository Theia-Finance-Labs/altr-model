# Stage 8 - `reporting`

| | |
| --- | --- |
| Source | `src/crispy_kedro/pipelines/reporting/` |
| Tags | `reporting` |
| Runs after | [Stage 7 - `valuation_model`](valuation_model.md) |
| Runs before | - (last stage) |

!!! note "Not part of `--tags altrisk`"
    Stages 1-7 carry the `altrisk` tag and produce the numbers. This stage
    carries `reporting` instead, so `kedro run --tags altrisk` stops after the
    NPV tables. Run `kedro run --tags reporting` afterwards, or
    `kedro run --pipeline full` for everything.

## Purpose

Turns the trajectory, earnings and NPV tables into the artefacts people actually
look at: validated inputs, four tidy views, five plot packs, four
compliance-ready export tables and a QC summary.

The plotting nodes write their figures to disk themselves and return the
directory they wrote to; only the tables go through the Kedro catalog.

## Consumes

| Dataset | Produced by |
| --- | --- |
| `companies_late_sudden_trajectories` | Stage 4 (`data/07_model_output/companies_late_sudden_trajectories.csv`) |
| `companies_late_sudden_trajectories_corrected`, `asset_level_staggered_shock_melted` | Stage 5 (in memory) |
| `asset_earnings` | Stage 6 (`data/07_model_output/asset_earnings.csv`) |
| `asset_npv`, `company_npv`, `yearly_npv_trajectories` | Stage 7 (`data/07_model_output/`) |

## Produces

Tables, through the catalog:

| Dataset | Persisted to |
| --- | --- |
| `validation_summary` | `data/08_reporting/tables/validation_summary.csv` |
| `report_company_summary` | `data/08_reporting/tables/compliance_ready/company_summary.csv` |
| `report_technology_summary` | `data/08_reporting/tables/compliance_ready/technology_summary.csv` |
| `report_top_assets` | `data/08_reporting/tables/compliance_ready/top_assets.csv` |
| `report_methodology` | `data/08_reporting/tables/compliance_ready/methodology_parameters.csv` |
| `reporting_qc_summary` | `data/08_reporting/tables/compliance_ready/reporting_qc.csv` |

Figures, written directly by the plotting nodes:

| Directory | Contents |
| --- | --- |
| `data/08_reporting/companies_trajectories_plots/` | Baseline vs target vs late & sudden, per company-technology-geography |
| `data/08_reporting/companies_staggered_shock_plots/` | Requested company shock vs what the asset fleet absorbed |
| `data/08_reporting/earnings_inner/` | Engineering / explainability pack for the earnings stack |
| `data/08_reporting/authority_pack/` | Regulator-facing valuation visuals |
| `data/08_reporting/asset_financial_trajectories/` | Revenue / cost / EBITDA / NPV detail per asset |

The four `view_*` tables and the three `*_validated` frames stay in memory; so do
the `*_plots_dir` outputs, which are just the paths the plot nodes wrote to.

## Nodes

The implementation is split by concern; `nodes.py` re-exports every function for
backwards compatibility.

| Function | Module | What it does |
| --- | --- | --- |
| `plot_late_sudden_trajectories` | `plots_trajectories.py` | One figure per company-technology-geography, with the alignment phase spans |
| `plot_staggered_shock` | `plots_staggered.py` | Company shock vs post-allocation asset capacity, plus the per-year residual |
| `reporting_validate_inputs` | `views.py` | Checks required columns and basis alignment; emits `validation_summary` |
| `build_reporting_views` | `views.py` | Builds `view_asset_explain`, `view_asset_npv_decomp`, `view_company_tech`, `view_deltas` |
| `plot_earnings_inner_workings` | `plots_financials.py` | The earnings explainability pack |
| `plot_valuation_authority_pack` | `plots_financials.py` | The regulator-facing valuation pack |
| `export_reporting_tables` | `exports.py` | Writes the four compliance-ready tables |
| `plot_asset_financial_trajectories` | `plots_financials.py` | Per-asset financial component trajectories by trajectory type |
| `reporting_qc_summary` | `views.py` | Quality-control checks and diagnostics |

`_style.py` holds the shared matplotlib/seaborn style and is imported for its
side effects by every plotting module.

## Parameters read

| Key | Defined in |
| --- | --- |
| `plot_staggered_shock_use_log_scale` | `conf/base/parameters_reporting.yml` |
| `reporting` (block) | `conf/base/parameters_reporting.yml` |

The whole `reporting` block is passed to six nodes as `params:reporting`, and
each node reads the sub-keys it needs with a default, so an absent key is never
an error. Read today: `basis` and `base_year` (labelling and the basis check),
`top_n_assets_per_company`, `materiality_threshold_usd`,
`small_numbers_rounding`, and the `plots` sub-block (`save_png`, `save_pdf`,
`dpi`, `width_in`, `height_in`) in `plots_financials.py`.

!!! warning "Declared but not read"
    `reporting.baseline_filter`, `reporting.top_n_companies`,
    `reporting.show_synthetic_assets`, `reporting.show_sensitivity_tornado` and
    `reporting.sensitivity_params` appear in the YAML but no node reads them - 
    changing them has no effect on a run. In particular `baseline_filter` still
    names a WITCH scenario, which is inert rather than inconsistent.

## Methodology reference

*ALTR Model User Guide* ([`altr_documentation.pdf`](../altr_documentation.pdf)),
**Pipeline reference → Reporting plots** (PDF pipeline name:
`plot_transition_risk_results`), which shows the company-trajectory,
staggered-shock and asset-financial plot folders with screenshots. The
compliance-ready export tables and the QC summary post-date that section.
