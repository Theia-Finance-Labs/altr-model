# Ways to run the model

This directory separates the three user-facing ways to run ALTR:

| Mode | Entry point | Best for |
| --- | --- | --- |
| Notebook | `notebook/generate_results.ipynb` | Interactive exploration and comparing configurations |
| Script | `script/run_kedro_batch.py` | Repeatable batch runs and automation |
| Streamlit | `streamlit/app.py` | A guided browser interface |

Run all commands below from the repository root.

## Notebook

```shell
uv run jupyter lab notebooks/notebook/generate_results.ipynb
```

## Script

```shell
uv run python notebooks/script/run_kedro_batch.py \
    --run-configurations notebooks/script/example_run_configurations.yml \
    --company-ids notebooks/streamlit/example_company_selection.csv \
    --output-dir workspace/results_batch \
    --tags altrisk
```

The example configuration belongs to the script workflow. The demo company
selection lives with the Streamlit app because it is the app's bundled sample
portfolio, but it can also be passed to the script as shown above.

## Streamlit

```shell
uv run --group streamlit streamlit run notebooks/streamlit/app.py
```

Alternatively, run `docker compose up --build` and open
<http://localhost:8501>.
