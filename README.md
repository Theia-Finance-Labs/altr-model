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

### 2. Install Dependencies with Poetry

```bash
# Install Poetry if you don't have it
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install

# Activate the Poetry shell
poetry shell
```

## Running the Pipeline

### Step 1: Download Input Data

If you have GCP credentials for BigQuery:

```bash
kedro run --tags=download_inputs
```

If you **don't have GCP credentials**, manually place these files in the `data/05_model_input/` folder:
- `downloaded_assets.csv`
- `downloaded_scenarios.csv`
- `downloaded_companies.csv`

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
3. **Kedro Download Trisk data (Debug)**: Runs with `--tags=download_inputs` (data download)

#### Option C: Using Jupyter Notebook for Batch Processing

Use `notebooks/generate_results.ipynb` to:
- Generate batches of results with parameter overriding
- Run with or without plots
- Currently configured to run over all companies (not just the selection in `conf/base/`)

## Code Structure

The main pipeline code is located in `src/crispy_kedro/pipelines/`. Each pipeline is in its own folder:

- `download_inputs/`: Downloads data from BigQuery
- `inputs_processing/`: Filters and processes input data
- `inputs_postproc/`: Final data preparation
- `create_baseline_and_target_trajectories/`: Creates production trajectories
- `create_late_sudden_trajectories/`: Models delayed policy scenarios
- `distribute_impacts_to_asset_level/`: Applies staggered shock methodology
- `earnings_model/`: Calculates asset-level earnings
- `valuation_model/`: Converts earnings to NPV using DCF
- `reporting/`: Generates outputs and visualizations

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
