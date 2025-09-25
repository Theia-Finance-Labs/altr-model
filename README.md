# Crispy Kedro - Climate Risk Financial Analysis Pipeline

[![Powered by Kedro](https://img.shields.io/badge/powered_by-kedro-ffc900?logo=kedro)](https://kedro.org)

## Overview

Crispy Kedro is a comprehensive climate risk financial analysis pipeline built with Kedro. It performs transition risk analysis by modeling the financial impact of climate scenarios on companies and their assets in the energy sector. The pipeline downloads climate scenario data, processes asset and company information, calculates earnings trajectories, and performs valuation using discounted cash flow (DCF) methodology.

### 🔍 Explore the Pipeline Visually

Before diving into the details, you can explore the entire pipeline structure interactively using Kedro Viz:

```bash
kedro viz
```

This opens a web interface showing:
- **Pipeline Flow**: Visual representation of all data processing steps
- **Data Lineage**: How data flows through the pipeline from inputs to outputs
- **Node Dependencies**: Which steps depend on others
- **Data Catalog**: All datasets and their relationships

Kedro Viz is invaluable for understanding the pipeline architecture and debugging data flow issues.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Pipeline Architecture](#pipeline-architecture)
- [Running the Pipeline](#running-the-pipeline)
- [Data Structure](#data-structure)
- [Outputs](#outputs)
- [Development](#development)

## Prerequisites

- **Python**: Version 3.10.x (3.11+ not supported due to dependency constraints)
- **Poetry**: For dependency management
- **Google Cloud Platform**: Access to BigQuery for data sources
- **Git**: For version control

## Installation

### 1. Install Python 3.10

Ensure you have Python 3.10 installed on your system. You can check your version with:

```bash
python --version
```

### 2. Install Poetry

If you don't have Poetry installed, install it following the [official Poetry installation guide](https://python-poetry.org/docs/#installation):

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

### 3. Clone the Repository

```bash
git clone <repository-url>
cd crispy-kedro
```

### 4. Install Dependencies with Poetry

```bash
# Install all dependencies including dev dependencies
poetry install

# Activate the virtual environment
poetry shell
```

### 5. Set up Credentials

Configure your Google Cloud credentials for BigQuery access:

1. Copy the credentials template:
   ```bash
   cp conf/base/credentials.yml conf/local/credentials.yml
   ```

2. Edit `conf/local/credentials.yml` with your GCP project details and authentication.

## Configuration

The pipeline is highly configurable through YAML files in the `conf/` directory:

### Key Configuration Files

- **`conf/base/parameters.yml`**: Global parameters including shock year and alignment year
- **`conf/base/parameters_inputs_processing.yml`**: Input data filtering and processing parameters
- **`conf/base/parameters_valuation_model.yml`**: DCF model parameters including discount rates
- **`conf/base/parameters_reporting.yml`**: Output and visualization settings
- **`conf/base/catalog.yml`**: Data catalog defining all inputs, intermediates, and outputs

### Important Parameters

#### Core Analysis Parameters
- `shock_year`: Year when the climate policy shock occurs
- `alignment_year`: Reference year for alignment calculations
- `baseline_scenario` & `target_scenario`: Climate scenarios to compare

#### Valuation Parameters
- `discount_rate_baseline`: Discount rate for baseline scenarios (default: 7%)
- `discount_rate_shock`: Higher discount rate for shock scenarios (default: 8%)
- `terminal_growth_rate`: Long-term growth rate for terminal value (default: 2%)

#### Company Selection
- `company_ids`: List of specific company IDs to analyze
- `ownership_type`: Type of ownership to consider ("direct" or "ultimate")

## Pipeline Architecture

The pipeline consists of 9 main stages, each implemented as a separate Kedro pipeline:

### 1. Download Inputs (`download_inputs`)
- **Tag**: `download_inputs`
- **Purpose**: Downloads raw data from BigQuery
- **Outputs**: Scenarios, assets, and company ownership data

### 2. Inputs Processing (`inputs_processing`)
- **Tag**: `altrisk`, `trisk`
- **Purpose**: Filters and processes input data
- **Key Functions**:
  - Filter scenarios and companies based on parameters
  - Apply CCS (Carbon Capture and Storage) logic
  - Allocate assets to companies
  - Determine technology lifetimes

### 3. Inputs Post-processing (`inputs_postproc`)
- **Tag**: `altrisk`
- **Purpose**: Final data preparation
- **Key Functions**:
  - Reduce granularity from asset to company level
  - Determine asset retirement dates
  - Extend forecast horizons

### 4. Create Baseline and Target Trajectories (`create_baseline_and_target_trajectories`)
- **Tag**: `altrisk`
- **Purpose**: Create production trajectories for different scenarios
- **Key Functions**:
  - Aggregate assets to company level
  - Calculate Technology Market Share Ratios (TMSR)
  - Generate company trajectories

### 5. Create Late Sudden Trajectories (`create_late_sudden_trajectories`)
- **Purpose**: Model delayed climate policy implementation scenarios

### 6. Distribute Impacts to Asset Level (`distribute_impacts_to_asset_level`)
- **Purpose**: Apply staggered shock methodology to individual assets
- **Key Parameters**:
  - `apply_retirement`: Whether to model asset retirement
  - `staggered_shock.g_k`: Shock intensity parameter
  - `staggered_shock.n_quantiles`: Number of shock quantiles

### 7. Earnings Model (`earnings_model`)
- **Tag**: `altrisk`
- **Purpose**: Calculate asset-level earnings under different scenarios
- **Key Functions**:
  - Validate inputs
  - Build scenario surfaces
  - Compute flow-based CapEx
  - Calculate Free Cash Flow to Firm (FCFF)

### 8. Valuation Model (`valuation_model`)
- **Tag**: `altrisk`
- **Purpose**: Convert earnings to Net Present Value using DCF methodology
- **Key Functions**:
  - Compute yearly NPV trajectories
  - Calculate asset-level NPV
  - Aggregate to company level

### 9. Reporting (`reporting`)
- **Tag**: `reporting`
- **Purpose**: Generate analysis outputs and visualizations
- **Outputs**: Charts, tables, and summary reports

## Running the Pipeline

### Full Pipeline
```bash
# Run the complete pipeline
kedro run

# Run with specific tags
kedro run --tags=altrisk
kedro run --tags=altrisk,reporting
```

### Specific Pipeline Stages
```bash
# Download data only
kedro run --tags=download_inputs

# Run core analysis without reporting
kedro run --tags=altrisk

# Run reporting only (requires previous stages to be completed)
kedro run --tags=reporting
```

### Using VS Code Debug Configurations

The repository includes pre-configured debug settings in `.vscode/launch.json`:

1. **Kedro Run AltRisk with reporting (Debug)**: Full analysis with reporting
2. **Kedro Run AltRisk (Debug)**: Core analysis without reporting  
3. **Kedro Download Trisk data (Debug)**: Data download only

### Pipeline Visualization

View the pipeline structure:
```bash
kedro viz
```

This opens an interactive visualization of the pipeline in your browser.

## Data Structure

### Input Data Sources (BigQuery)
- **`assets_forecasts`**: Asset-level production forecasts
- **`companies_ownership_tree`**: Company ownership relationships
- **`scenarios`**: Climate scenario pathways
- **`financial_averages`**: Financial benchmarks

### Key Intermediate Outputs
- **`allocated_assets_to_companies`**: Assets mapped to owning companies
- **`asset_level_staggered_shock`**: Shock impacts at asset level
- **`asset_earnings`**: Projected earnings by asset and scenario
- **`company_npv`**: Net present values by company

### Directory Structure
```
data/
├── 01_raw/              # Raw downloaded data
├── 02_intermediate/     # Processed intermediate data
├── 03_primary/          # Primary analysis datasets
├── 04_feature/          # Feature engineered data
├── 05_model_input/      # Model-ready inputs
├── 06_models/           # Model artifacts
├── 07_model_output/     # Model results
└── 08_reporting/        # Final reports and visualizations
```

## Outputs

The pipeline generates several types of outputs:

### Financial Analysis
- **Company NPV**: Net present values by company and scenario
- **Asset NPV**: Asset-level valuations
- **Earnings Trajectories**: Projected cash flows over time

### Risk Analysis  
- **Staggered Shock Results**: Asset-level impact distributions
- **Trajectory Comparisons**: Baseline vs. target scenario analysis

### Reporting
- **Charts**: Company trajectory plots and shock impact visualizations
- **Tables**: Summary statistics and rankings
- **Authority Pack**: Standardized reporting package

## Development

### Code Quality
The project uses several tools for code quality:

```bash
# Run linting
poetry run ruff check src/

# Run formatting  
poetry run ruff format src/

# Run tests
poetry run pytest
```

### Jupyter Notebooks
For interactive analysis:

```bash
# Start Jupyter with Kedro context
kedro jupyter notebook

# Or use JupyterLab
kedro jupyter lab
```

This provides access to `context`, `catalog`, and `pipelines` objects for interactive data exploration.

### Adding New Pipelines
To create a new pipeline:

```bash
kedro pipeline create <pipeline_name>
```

### Environment Configuration
- **Development**: Use `conf/local/` for local overrides
- **Production**: Configure `conf/prod/` for production settings
- **Credentials**: Always store in `conf/local/credentials.yml` (never commit)

## Troubleshooting

### Common Issues

1. **Python Version**: Ensure you're using Python 3.10.x
2. **BigQuery Access**: Verify GCP credentials are properly configured
3. **Memory Issues**: Large datasets may require increased memory allocation
4. **Dependency Conflicts**: Use `poetry update` to resolve version conflicts

### Getting Help

- Check the [Kedro documentation](https://docs.kedro.org) for framework-specific questions
- Review pipeline logs in the `logs/` directory
- Use `kedro catalog list` to verify data catalog configuration

## License

This project is licensed under the terms specified in the LICENSE file.