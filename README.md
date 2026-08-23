# Crispy Kedro - Climate Risk Financial Analysis Pipeline

[![Powered by Kedro](https://img.shields.io/badge/powered_by-kedro-ffc900?logo=kedro)](https://kedro.org)

A climate risk financial analysis pipeline that performs transition risk analysis by modeling the financial impact of climate scenarios on companies and their assets in the energy sector.

## Installation

### 1. Create a Virtual Environment with Python 3.10

The project requires Python 3.10 (3.11+ is not supported due to dependency constraints).

```bash
# Using pyenv (recommended)
pyenv install 3.10.15
pyenv local 3.10.15

# Or using venv with Python 3.10
python3.10 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies with uv

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync

# Activate the virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

## Running the Pipeline

### Step 1: Get Input Data

Most users receive these three files through another channel and place them directly in the `data/05_model_input/` folder:
- `downloaded_assets.csv`
- `downloaded_scenarios.csv`
- `downloaded_companies.csv`

If you're a maintainer with GCP credentials for BigQuery, generate them instead with:

```bash
uv sync --group bigquery
uv run python src/crispy_kedro/bigquery_marts_downloader.py
```

### Step 2: Run the Model

#### Option A: Using Kedro CLI

Run the model with basic configuration from `conf/base/`:

```bash
# Get results only
kedro run --tags=altrisk

# Get results with plots and reporting
kedro run --tags=altrisk,reporting
```

The basic configuration includes company selection and other parameters defined in the `conf/base/` folder.

#### Option B: Using VS Code Debug Configurations

Use the pre-configured debug settings in `.vscode/launch.json`:

1. **Kedro Run AltRisk with reporting (Debug)**: Runs with `--tags=altrisk,reporting` (results + plots)
2. **Kedro Run AltRisk (Debug)**: Runs with `--tags=altrisk` (results only)
3. **Download BigQuery Input Data (Debug)**: Runs `bigquery_marts_downloader.py` (maintainers only, see Step 1 above)

#### Option C: Using Jupyter Notebook for Batch Processing

Use `notebooks/generate_results.ipynb` to:
- Generate batches of results with parameter overriding
- Run with or without plots
- Currently configured to run over all companies (not just the selection in `conf/base/`)

## Code Structure

The main pipeline code is located in `src/crispy_kedro/pipelines/`. Each pipeline is in its own folder:

- `inputs_processing/`: Filters and processes input data
- `inputs_postproc/`: Final data preparation
- `create_baseline_and_target_trajectories/`: Creates production trajectories
- `create_late_sudden_trajectories/`: Models delayed policy scenarios
- `distribute_impacts_to_asset_level/`: Applies staggered shock methodology
- `earnings_model/`: Calculates asset-level earnings
- `valuation_model/`: Converts earnings to NPV using DCF
- `reporting/`: Generates outputs and visualizations

BigQuery input download is not a pipeline: it's the standalone, maintainer-only
`src/crispy_kedro/bigquery_marts_downloader.py` script (see Step 1 above).

Each pipeline folder contains:
- `nodes.py`: The actual data processing functions
- `pipeline.py`: Pipeline definition and node connections

For more information on Kedro pipelines and project structure, see the [Kedro documentation](https://docs.kedro.org).

## Configuration

The pipeline uses configuration files in the `conf/base/` folder, which includes:
- Company selection
- Scenario parameters
- Valuation parameters
- Other model settings

You can override these parameters when using the Jupyter notebook approach.

## Outputs

Results are saved in the `data/` directory:
- `data/07_model_output/`: Model results (NPV, earnings, etc.)
- `data/08_reporting/`: Charts and reports (when using `reporting` tag)

## Visualization

Explore the pipeline structure interactively:

```bash
kedro viz
```

This opens a web interface showing the pipeline flow, data lineage, and dependencies.

## License

This project is licensed under the terms specified in the LICENSE file.
