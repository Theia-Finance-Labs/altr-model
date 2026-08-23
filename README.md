# Crispy Kedro - Climate Risk Financial Analysis Pipeline

[![Powered by Kedro](https://img.shields.io/badge/powered_by-kedro-ffc900?logo=kedro)](https://kedro.org)

A climate risk financial analysis pipeline that performs transition risk analysis by modeling the financial impact of climate scenarios on companies and their assets in the energy sector.

This README covers dev setup for people working on the codebase. For running
the model end-to-end (including how to get input data without BigQuery
access, parameters, outputs, and troubleshooting), see **[docs/USAGE.md](docs/USAGE.md)**.

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

Main pipeline code lives in `src/crispy_kedro/pipelines/`, one folder per pipeline:

- `inputs_processing/`: Filters and processes input data
- `inputs_postproc/`: Final data preparation
- `create_baseline_and_target_trajectories/`: Creates production trajectories
- `create_late_sudden_trajectories/`: Models delayed policy scenarios
- `distribute_impacts_to_asset_level/`: Applies staggered shock methodology
- `earnings_model/`: Calculates asset-level earnings
- `valuation_model/`: Converts earnings to NPV using DCF
- `reporting/`: Generates outputs and visualizations

Each pipeline folder contains `nodes.py` (processing functions) and
`pipeline.py` (node wiring). BigQuery input download is not a pipeline: it's
the standalone, maintainer-only `src/crispy_kedro/bigquery_marts_downloader.py`
script — see [docs/USAGE.md](docs/USAGE.md) for how to run it.

For more on Kedro itself, see the [Kedro documentation](https://docs.kedro.org).

## Tests & Linting

```bash
uv run pytest
uv run ruff check .
```

## License

This project is licensed under the terms specified in the LICENSE file.
