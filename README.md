# ALTR Model - Climate Risk Financial Analysis Pipeline

[![Powered by Kedro](https://img.shields.io/badge/powered_by-kedro-ffc900?logo=kedro)](https://kedro.org)

A climate risk financial analysis pipeline that performs transition risk analysis by modeling the financial impact of climate scenarios on companies and their assets in the energy sector.

## Install

Requires Python 3.10 (3.11+ is not supported due to dependency constraints).

```bash
pyenv install 3.10.15
pyenv local 3.10.15

curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

## Code Structure

Main pipeline code lives in `src/altr_model/pipelines/`, one folder per pipeline:

- `prepare_scenario_asset_and_company_inputs/`: Filters scenarios and prepares the asset forecast panel and company projection inputs
- `calculate_company_trajectories/`: Calculates baseline, target, and all four alignment-case transition paths
- `allocate_company_trajectories_to_assets/`: Allocates decreasing/increasing company paths to assets and reconciles realized company paths
- `calculate_asset_earnings/`: Calculates asset-level earnings
- `calculate_asset_and_company_npv/`: Converts earnings to asset, technology, and company NPV using DCF
- `plot_transition_risk_results/`: Generates trajectory and financial visualizations

Each pipeline folder contains `nodes.py` (processing functions) and
`pipeline.py` (node wiring). BigQuery input download is not a pipeline: it's
the standalone, maintainer-only `src/altr_model/bigquery_marts_downloader.py`
script — see [docs/USAGE.md](docs/USAGE.md) for how to run it.

For more on Kedro itself, see the [Kedro documentation](https://docs.kedro.org).

## Tests & Linting

```bash
uv run pytest
uv run ruff check .
```

## License

This project is licensed under the terms specified in the LICENSE file.
