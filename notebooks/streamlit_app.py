"""Streamlit UI for building and running batches of crispy-kedro configs.

Lets you:
  1. pick a subset of companies (upload a CSV, paste ids, or use the
     bundled example selection),
  2. build one or more named parameter configurations through a form (with
     the baseline/target scenario dropdowns constrained to the same IAM
     provider - see notebooks/scenario_utils.py),
  3. download the resulting config as YAML (for reuse with
     notebooks/run_kedro_batch.py directly, headless),
  4. run the batch and browse/download each run's outputs, which land under
     workspace/ exactly like notebooks/generate_results.ipynb does.

Run with:

    uv run --group streamlit streamlit run notebooks/streamlit_app.py
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import scenario_utils  # noqa: E402
from run_kedro_batch import run_batch  # noqa: E402

EXAMPLE_CONFIG_PATH = APP_DIR / "example_run_configurations.yml"
EXAMPLE_COMPANIES_PATH = APP_DIR / "example_company_selection.csv"
SCENARIOS_CSV = PROJECT_ROOT / "data" / "05_model_input" / "scenarios.csv"

PARAMETER_FILES = {
    "prepare_scenario_asset_and_company_inputs": "parameters_prepare_scenario_asset_and_company_inputs.yml",
    "calculate_company_trajectories": "parameters_calculate_company_trajectories.yml",
    "allocate_company_trajectories_to_assets": "parameters_allocate_company_trajectories_to_assets.yml",
    "calculate_asset_earnings": "parameters_calculate_asset_earnings.yml",
    "calculate_asset_and_company_npv": "parameters_calculate_asset_and_company_npv.yml",
    "plot_transition_risk_results": "parameters_plot_transition_risk_results.yml",
}

CCS_OPTIONS = {
    "Without CCS (False)": False,
    "With CCS (True)": True,
    "No distinction (None)": None,
}
CCS_LABELS_BY_VALUE = {v: k for k, v in CCS_OPTIONS.items()}


st.set_page_config(page_title="Crispy Kedro batch runner", layout="wide")


@st.cache_data
def load_base_defaults() -> dict:
    """Flatten conf/base/parameters_*.yml into one default-value dict.

    Parameter keys don't collide across files, so this is a plain merge -
    it's only used to pre-fill form widgets, never fed back into kedro
    directly (each configuration built in the form carries its own full
    values instead).
    """
    merged: dict = {}
    for filename in PARAMETER_FILES.values():
        path = PROJECT_ROOT / "conf" / "base" / filename
        data = yaml.safe_load(path.read_text()) or {}
        merged.update(data)
    merged.pop("company_ids", None)
    return merged


@st.cache_data
def load_baseline_scenario_options() -> list[str]:
    return scenario_utils.list_baseline_scenarios(SCENARIOS_CSV)


@st.cache_data
def load_target_scenario_options(baseline_scenario: str) -> list[str]:
    return scenario_utils.list_matching_target_scenarios(baseline_scenario, SCENARIOS_CSV)


def _read_company_ids_from_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)
    if "company_id" not in df.columns:
        df = df.rename(columns={df.columns[0]: "company_id"})
    return df


def _zip_directory_bytes(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(directory.glob("*")):
            if file_path.is_file():
                zf.write(file_path, arcname=file_path.name)
    return buffer.getvalue()


if "run_configurations" not in st.session_state:
    st.session_state.run_configurations = {}
if "company_ids" not in st.session_state:
    st.session_state.company_ids = None
if "company_ids_label" not in st.session_state:
    st.session_state.company_ids_label = "All companies (no restriction)"
if "last_summary" not in st.session_state:
    st.session_state.last_summary = None
if "last_workspace_dir" not in st.session_state:
    st.session_state.last_workspace_dir = None


st.title("Crispy Kedro — batch run builder")
st.caption(
    "Build one or more parameter configurations, pick a company subset, run "
    "the altrisk model across all of them, and collect the outputs under "
    "workspace/ — the same pattern as notebooks/generate_results.ipynb."
)

tab_companies, tab_config, tab_run = st.tabs(
    ["1. Companies", "2. Run configurations", "3. Run & results"]
)

# ---------------------------------------------------------------------------
# Tab 1: company selection
# ---------------------------------------------------------------------------
with tab_companies:
    st.subheader("Which companies should every run be restricted to?")
    st.caption(
        "Applied to every configuration below via `company_ids`. Restricting "
        "to a small subset is strongly recommended for interactive runs — "
        "the full universe is 10,000+ companies."
    )

    source = st.radio(
        "Source",
        [
            "Example selection (30 companies, mixed carbon/alignment profile)",
            "Upload a CSV",
            "Paste ids",
            "All companies (no restriction — slow)",
        ],
        key="company_source",
    )

    company_ids: list[str] | None = None
    preview_df: pd.DataFrame | None = None

    if source.startswith("Example selection"):
        preview_df = pd.read_csv(EXAMPLE_COMPANIES_PATH)
        company_ids = preview_df["company_id"].astype(str).tolist()
        st.caption(
            "Selected to skew toward the biggest owners in each quadrant of "
            "carbon intensity × scenario alignment (under the default "
            "AIM/CGE 2.2 scenario pair) — see the `carbon_alignment_quadrant` "
            "column. `aligned_low_carbon` companies are structurally much "
            "smaller in this dataset (there's no such thing as a giant "
            "renewables-only company whose growth exactly matches the "
            "scenario), so that quadrant's picks are smaller than the others."
        )

    elif source == "Upload a CSV":
        uploaded = st.file_uploader(
            "CSV with a `company_id` column (extra columns are ignored)",
            type=["csv"],
        )
        if uploaded is not None:
            preview_df = _read_company_ids_from_csv(uploaded)
            company_ids = preview_df["company_id"].astype(str).tolist()

    elif source == "Paste ids":
        pasted = st.text_area("One company id per line", height=150)
        if pasted.strip():
            company_ids = [line.strip() for line in pasted.splitlines() if line.strip()]
            preview_df = pd.DataFrame({"company_id": company_ids})

    else:
        st.warning(
            "No restriction: every run will process every company in "
            "companies_ownerships.csv. This can take a long time."
        )

    st.session_state.company_ids = company_ids
    st.session_state.company_ids_label = source

    if preview_df is not None:
        st.dataframe(preview_df, width='stretch', height=280)
        st.metric("Companies selected", len(preview_df))
        if "carbon_alignment_quadrant" in preview_df.columns:
            st.bar_chart(preview_df["carbon_alignment_quadrant"].value_counts())

    st.download_button(
        "Download example company selection (CSV)",
        data=EXAMPLE_COMPANIES_PATH.read_bytes(),
        file_name="example_company_selection.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# Tab 2: run configurations
# ---------------------------------------------------------------------------
with tab_config:
    defaults = load_base_defaults()

    st.subheader("Build a configuration")
    run_name = st.text_input("Run name (becomes a workspace subfolder — avoid `/`)", value="my_run")

    with st.expander("Scenario & inputs — prepare_scenario_asset_and_company_inputs", expanded=True):
        baseline_options = load_baseline_scenario_options()
        default_baseline = defaults.get("baseline_scenario")
        baseline_index = (
            baseline_options.index(default_baseline)
            if default_baseline in baseline_options
            else 0
        )
        baseline_scenario = st.selectbox(
            "Baseline scenario (no-transition reference pathway)",
            baseline_options,
            index=baseline_index,
            key="form_baseline_scenario",
        )

        target_options = load_target_scenario_options(baseline_scenario)
        default_target = defaults.get("target_scenario")
        target_index = target_options.index(default_target) if default_target in target_options else 0
        target_scenario = st.selectbox(
            "Target scenario — restricted to scenarios from the same "
            f"provider as the baseline ('{scenario_utils.scenario_provider(baseline_scenario)}')",
            target_options,
            index=target_index,
            key=f"form_target_scenario__{baseline_scenario}",
        )

        col1, col2 = st.columns(2)
        with col1:
            ccs_default_label = CCS_LABELS_BY_VALUE.get(defaults.get("ccs_on"), "Without CCS (False)")
            ccs_label = st.selectbox(
                "ccs_on", list(CCS_OPTIONS.keys()),
                index=list(CCS_OPTIONS.keys()).index(ccs_default_label),
            )
            ccs_on = CCS_OPTIONS[ccs_label]
        with col2:
            reduce_granularity = st.checkbox(
                "reduce_granularity_from_asset_to_company_level",
                value=bool(defaults.get("reduce_granularity_from_asset_to_company_level", False)),
                help="Major impact — aggregates to one synthetic row per company/technology before the model runs.",
            )

        max_forecast_horizon = st.number_input(
            "max_forecast_horizon", min_value=1, max_value=30,
            value=int(defaults.get("max_forecast_horizon", 5)), step=1,
        )

    with st.expander("Company trajectory timing — calculate_company_trajectories"):
        col1, col2 = st.columns(2)
        with col1:
            shock_year = st.number_input(
                "shock_year", min_value=2020, max_value=2100,
                value=int(defaults.get("shock_year", 2033)), step=1,
            )
        with col2:
            alignment_year = st.number_input(
                "alignment_year", min_value=2020, max_value=2100,
                value=int(defaults.get("alignment_year", 2035)), step=1,
            )
        if alignment_year < shock_year:
            st.error("alignment_year must be >= shock_year (this is asserted by the pipeline).")

    with st.expander("Asset allocation & retirement — allocate_company_trajectories_to_assets"):
        col1, col2, col3 = st.columns(3)
        with col1:
            apply_retirement_baseline = st.checkbox(
                "apply_retirement_baseline", value=bool(defaults.get("apply_retirement_baseline", True))
            )
        with col2:
            apply_retirement_shock = st.checkbox(
                "apply_retirement_shock", value=bool(defaults.get("apply_retirement_shock", True))
            )
        with col3:
            apply_decreasing_staggered_shock = st.checkbox(
                "apply_decreasing_staggered_shock",
                value=bool(defaults.get("apply_decreasing_staggered_shock", False)),
            )
        col4, col5 = st.columns(2)
        staggered_defaults = defaults.get("staggered_shock", {})
        with col4:
            staggered_g_k = st.number_input(
                "staggered_shock.g_k", value=float(staggered_defaults.get("g_k", 6.0))
            )
        with col5:
            staggered_n_quantiles = st.number_input(
                "staggered_shock.n_quantiles", min_value=1,
                value=int(staggered_defaults.get("n_quantiles", 3)), step=1,
            )

    with st.expander("Earnings — calculate_asset_earnings"):
        market_passthrough = st.slider(
            "market_passthrough (fraction of carbon price passed through)",
            0.0, 1.0, float(defaults.get("market_passthrough", 0.0)),
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            include_growth_capex = st.checkbox(
                "include_growth_capex", value=bool(defaults.get("include_growth_capex", False))
            )
        with col2:
            include_replacement_capex = st.checkbox(
                "include_replacement_capex", value=bool(defaults.get("include_replacement_capex", False))
            )
        with col3:
            include_decom_costs = st.checkbox(
                "include_decom_costs", value=bool(defaults.get("include_decom_costs", False))
            )
        col4, col5 = st.columns(2)
        with col4:
            apply_continued_om_baseline = st.checkbox(
                "apply_continued_om_baseline", value=bool(defaults.get("apply_continued_om_baseline", False))
            )
        with col5:
            apply_continued_om_shock = st.checkbox(
                "apply_continued_om_shock", value=bool(defaults.get("apply_continued_om_shock", True))
            )

    with st.expander("Valuation / DCF — calculate_asset_and_company_npv"):
        dcf_defaults = defaults.get("dcf", {})
        col1, col2 = st.columns(2)
        with col1:
            discount_rate_baseline = st.number_input(
                "dcf.discount_rate_baseline", value=float(dcf_defaults.get("discount_rate_baseline", 0.07)),
                format="%.3f",
            )
        with col2:
            discount_rate_shock = st.number_input(
                "dcf.discount_rate_shock", value=float(dcf_defaults.get("discount_rate_shock", 0.07)),
                format="%.3f",
            )
        terminal_defaults = dcf_defaults.get("terminal_value", {})
        col3, col4 = st.columns(2)
        with col3:
            terminal_value_method = st.selectbox(
                "dcf.terminal_value.method", ["perpetuity", "none"],
                index=["perpetuity", "none"].index(terminal_defaults.get("method", "perpetuity")),
            )
        with col4:
            g_real_default = st.number_input(
                "dcf.terminal_value.g_real_default",
                value=float(terminal_defaults.get("g_real_default", 0.02)), format="%.3f",
            )

    with st.expander("Reporting / plots — plot_transition_risk_results (only used with the `reporting` tag)"):
        col1, col2, col3 = st.columns(3)
        with col1:
            plot_log_scale = st.checkbox(
                "plot_staggered_shock_use_log_scale",
                value=bool(defaults.get("plot_staggered_shock_use_log_scale", False)),
            )
        with col2:
            plot_shock_absorption = st.checkbox(
                "plot_staggered_shock_show_shock_absorption",
                value=bool(defaults.get("plot_staggered_shock_show_shock_absorption", False)),
            )
        with col3:
            reporting_dpi = st.number_input(
                "reporting.plots.dpi", min_value=50,
                value=int(defaults.get("reporting", {}).get("plots", {}).get("dpi", 160)), step=10,
            )

    add_disabled = alignment_year < shock_year or not run_name.strip()
    if st.button("Add this configuration", type="primary", disabled=add_disabled):
        st.session_state.run_configurations[run_name.strip()] = {
            "baseline_scenario": baseline_scenario,
            "target_scenario": target_scenario,
            "ccs_on": ccs_on,
            "max_forecast_horizon": int(max_forecast_horizon),
            "reduce_granularity_from_asset_to_company_level": bool(reduce_granularity),
            "shock_year": int(shock_year),
            "alignment_year": int(alignment_year),
            "apply_retirement_baseline": bool(apply_retirement_baseline),
            "apply_retirement_shock": bool(apply_retirement_shock),
            "apply_decreasing_staggered_shock": bool(apply_decreasing_staggered_shock),
            "staggered_shock": {
                "g_k": float(staggered_g_k),
                "n_quantiles": int(staggered_n_quantiles),
            },
            "market_passthrough": float(market_passthrough),
            "include_growth_capex": bool(include_growth_capex),
            "include_replacement_capex": bool(include_replacement_capex),
            "include_decom_costs": bool(include_decom_costs),
            "apply_continued_om_baseline": bool(apply_continued_om_baseline),
            "apply_continued_om_shock": bool(apply_continued_om_shock),
            "dcf": {
                "discount_rate_baseline": float(discount_rate_baseline),
                "discount_rate_shock": float(discount_rate_shock),
                "terminal_value": {
                    "method": terminal_value_method,
                    "g_real_default": float(g_real_default),
                },
            },
            "plot_staggered_shock_use_log_scale": bool(plot_log_scale),
            "plot_staggered_shock_show_shock_absorption": bool(plot_shock_absorption),
            "reporting": {"plots": {"dpi": int(reporting_dpi)}},
        }
        st.success(f"Added configuration '{run_name.strip()}'.")

    st.divider()
    st.subheader("Or start from the example configurations")
    st.caption(
        "The six runs from notebooks/generate_results.ipynb (all pairing the "
        "AIM/CGE 2.2 baseline/target scenario, varying granularity, "
        "retirement, and continued O&M cost assumptions)."
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Load example configurations (6 runs)"):
            example_configs = yaml.safe_load(EXAMPLE_CONFIG_PATH.read_text())
            st.session_state.run_configurations.update(example_configs)
            st.success(f"Loaded {len(example_configs)} example configurations.")
    with col2:
        st.download_button(
            "Download example config template (YAML)",
            data=EXAMPLE_CONFIG_PATH.read_bytes(),
            file_name="example_run_configurations.yml",
            mime="text/yaml",
        )

    uploaded_config = st.file_uploader(
        "...or upload a previously downloaded config YAML/JSON to merge in", type=["yml", "yaml", "json"]
    )
    if uploaded_config is not None:
        loaded = yaml.safe_load(uploaded_config.getvalue().decode("utf-8"))
        if isinstance(loaded, dict):
            st.session_state.run_configurations.update(loaded)
            st.success(f"Merged {len(loaded)} configurations from {uploaded_config.name}.")

    st.divider()
    st.subheader(f"Current run configurations ({len(st.session_state.run_configurations)})")

    if not st.session_state.run_configurations:
        st.info("No configurations yet — add one above or load the examples.")
    else:
        summary_rows = []
        for name, params in st.session_state.run_configurations.items():
            summary_rows.append(
                {
                    "run_name": name,
                    "baseline_scenario": params.get("baseline_scenario"),
                    "target_scenario": params.get("target_scenario"),
                    "granularity": "company" if params.get("reduce_granularity_from_asset_to_company_level") else "asset",
                    "shock_year": params.get("shock_year"),
                    "max_forecast_horizon": params.get("max_forecast_horizon"),
                }
            )
        st.dataframe(pd.DataFrame(summary_rows), width='stretch')

        to_remove = st.selectbox(
            "Remove a configuration", ["(none)"] + list(st.session_state.run_configurations.keys())
        )
        if to_remove != "(none)" and st.button(f"Remove '{to_remove}'"):
            del st.session_state.run_configurations[to_remove]
            st.rerun()

        with st.expander("Full parameter values (JSON)"):
            st.json(st.session_state.run_configurations)

        st.download_button(
            "Download current configuration (YAML)",
            data=yaml.dump(st.session_state.run_configurations, sort_keys=False),
            file_name="run_configurations.yml",
            mime="text/yaml",
        )

# ---------------------------------------------------------------------------
# Tab 3: run & results
# ---------------------------------------------------------------------------
with tab_run:
    n_configs = len(st.session_state.run_configurations)
    n_companies = len(st.session_state.company_ids) if st.session_state.company_ids else None

    col1, col2 = st.columns(2)
    col1.metric("Configurations queued", n_configs)
    col2.metric("Companies selected", n_companies if n_companies is not None else "All")

    default_workspace = f"workspace/results_streamlit_{datetime.now():%Y%m%d_%H%M%S}"
    workspace_dir = st.text_input("Workspace directory (relative to the repo root)", value=default_workspace)
    tags = st.multiselect(
        "Kedro tags to run", ["altrisk", "reporting"], default=["altrisk"],
        help="'reporting' also produces plots but only runs after 'altrisk' outputs exist.",
    )
    allow_cross_provider = st.checkbox(
        "Allow baseline/target scenarios from different providers (advanced — normally rejected)",
        value=False,
    )

    run_disabled = n_configs == 0 or not tags
    if st.button("Run batch", type="primary", disabled=run_disabled):
        log_box = st.empty()
        log_lines: list[str] = []

        def log(message: str) -> None:
            log_lines.append(message)
            log_box.code("\n".join(log_lines[-200:]))

        with st.status("Running kedro batch...", expanded=True) as status:
            try:
                summary = run_batch(
                    st.session_state.run_configurations,
                    workspace_dir=PROJECT_ROOT / workspace_dir,
                    tags=tags,
                    company_ids=st.session_state.company_ids,
                    scenarios_csv=str(SCENARIOS_CSV),
                    allow_cross_provider=allow_cross_provider,
                    log=log,
                )
                st.session_state.last_summary = summary
                st.session_state.last_workspace_dir = PROJECT_ROOT / workspace_dir
                n_success = int((summary["status"] == "success").sum())
                status.update(
                    label=f"Done: {n_success}/{len(summary)} runs succeeded.",
                    state="complete" if n_success == len(summary) else "error",
                )
            except Exception as exc:  # surfaced via status + rethrow-free message
                status.update(label=f"Batch failed to start: {exc}", state="error")
                st.exception(exc)

    if st.session_state.last_summary is not None:
        st.divider()
        st.subheader("Last batch results")
        st.dataframe(st.session_state.last_summary, width='stretch')

        workspace_path = st.session_state.last_workspace_dir
        for _, row in st.session_state.last_summary.iterrows():
            if row["status"] != "success":
                continue
            run_dir = Path(row["output_dir"])
            with st.expander(f"{row['run_name']} — {run_dir}"):
                files = sorted(p.name for p in run_dir.glob("*.csv"))
                st.write(files)
                npv_path = run_dir / "company_npv.csv"
                if npv_path.exists():
                    st.caption("company_npv.csv preview")
                    st.dataframe(pd.read_csv(npv_path).head(20), width='stretch')
                st.download_button(
                    f"Download all outputs for '{row['run_name']}' (zip)",
                    data=_zip_directory_bytes(run_dir),
                    file_name=f"{run_dir.name}.zip",
                    mime="application/zip",
                    key=f"zip_{run_dir.name}",
                )

        if workspace_path is not None:
            manifest_path = workspace_path / "run_manifest.csv"
            if manifest_path.exists():
                st.download_button(
                    "Download run manifest (CSV)",
                    data=manifest_path.read_bytes(),
                    file_name="run_manifest.csv",
                    mime="text/csv",
                )
