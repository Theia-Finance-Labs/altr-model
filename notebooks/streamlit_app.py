"""Streamlit wizard for trying out the ALTR Model.

A deliberately simple three-step flow: pick a portfolio (upload one or use
the bundled demo), pick parameters (recommended defaults or a custom
selection), then run the model and download every output as one zip.

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

STEP_LABELS = ["Portfolio", "Parameters", "Run & results"]

st.set_page_config(page_title="ALTR Model", layout="wide")


@st.cache_data
def load_base_defaults() -> dict:
    """Flatten conf/base/parameters_*.yml into one default-value dict.

    Only used to pre-fill form widgets, never fed back into kedro directly -
    the "recommended defaults" run passes no overrides at all, and a
    "customize" run carries its own full values instead.
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
        for file_path in sorted(directory.rglob("*")):
            if file_path.is_file():
                zf.write(file_path, arcname=file_path.relative_to(directory))
    return buffer.getvalue()


def _init_state() -> None:
    for key, value in {
        "step": 1,
        "company_ids": None,
        "param_mode": "Recommended defaults",
        "custom_params": {},
        "run_summary": None,
    }.items():
        st.session_state.setdefault(key, value)


def _goto(step: int) -> None:
    st.session_state.step = step
    st.rerun()


def _start_over() -> None:
    for key in ["step", "company_ids", "param_mode", "custom_params", "run_summary"]:
        st.session_state.pop(key, None)
    _init_state()


def render_stepper() -> None:
    step = st.session_state.step
    cols = st.columns(len(STEP_LABELS))
    for i, (col, label) in enumerate(zip(cols, STEP_LABELS), start=1):
        if i < step:
            col.markdown(f"✅ {i}. {label}")
        elif i == step:
            col.markdown(f"**▶ {i}. {label}**")
        else:
            col.markdown(f"⬜ {i}. {label}")
    st.progress(step / len(STEP_LABELS))


# ---------------------------------------------------------------------------
# Step 1: portfolio
# ---------------------------------------------------------------------------
def render_step_portfolio() -> None:
    st.header("1. Portfolio")
    st.caption("Try the model on the bundled demo portfolio, or upload your own.")

    source = st.radio(
        "Portfolio source",
        ["Demo portfolio (30 companies)", "Upload your own CSV"],
        key="company_source_choice",
    )

    company_ids: list[str] | None = None
    preview_df: pd.DataFrame | None = None

    if source.startswith("Demo"):
        preview_df = pd.read_csv(EXAMPLE_COMPANIES_PATH)
        company_ids = preview_df["company_id"].astype(str).tolist()
        st.caption(
            "30 large companies picked to cover all four alignment × "
            "carbon-intensity quadrants, so results show a mix of winners "
            "and losers under the transition scenario."
        )
    else:
        uploaded = st.file_uploader(
            "CSV with a `company_id` column (extra columns are ignored)",
            type=["csv"],
        )
        if uploaded is not None:
            preview_df = _read_company_ids_from_csv(uploaded)
            company_ids = preview_df["company_id"].astype(str).tolist()

    if preview_df is not None:
        st.dataframe(preview_df, width="stretch", height=280)
        st.metric("Companies selected", len(preview_df))
        if "carbon_alignment_quadrant" in preview_df.columns:
            st.bar_chart(preview_df["carbon_alignment_quadrant"].value_counts())

    st.session_state.company_ids = company_ids

    st.divider()
    next_disabled = not company_ids
    if st.button("Next →", type="primary", disabled=next_disabled, key="next_1"):
        _goto(2)
    if next_disabled:
        st.caption("Select the demo portfolio or upload a CSV to continue.")


# ---------------------------------------------------------------------------
# Step 2: parameters
# ---------------------------------------------------------------------------
def render_step_parameters() -> None:
    st.header("2. Parameters")
    defaults = load_base_defaults()

    mode = st.radio(
        "How should this run be configured?",
        ["Recommended defaults", "Customize parameters"],
        key="param_mode",
    )

    params: dict = {}
    alignment_invalid = False

    if mode == "Recommended defaults":
        st.info(
            "Uses the model's built-in defaults (baseline/target scenario, "
            "shock timing, cost assumptions, ...) with no changes — a "
            "reasonable starting point for a first run."
        )
    else:
        baseline_options = load_baseline_scenario_options()
        default_baseline = defaults.get("baseline_scenario")
        baseline_index = (
            baseline_options.index(default_baseline) if default_baseline in baseline_options else 0
        )
        baseline_scenario = st.selectbox(
            "Baseline scenario (no-transition reference pathway)",
            baseline_options, index=baseline_index, key="p_baseline",
        )

        target_options = load_target_scenario_options(baseline_scenario)
        default_target = defaults.get("target_scenario")
        target_index = target_options.index(default_target) if default_target in target_options else 0
        target_scenario = st.selectbox(
            "Target scenario — restricted to scenarios from the same "
            f"provider as the baseline ('{scenario_utils.scenario_provider(baseline_scenario)}')",
            target_options, index=target_index, key=f"p_target__{baseline_scenario}",
        )

        col1, col2 = st.columns(2)
        with col1:
            shock_year = st.number_input(
                "Shock year", min_value=2020, max_value=2100,
                value=int(defaults.get("shock_year", 2033)), step=1, key="p_shock_year",
            )
        with col2:
            alignment_year = st.number_input(
                "Alignment year", min_value=2020, max_value=2100,
                value=int(defaults.get("alignment_year", 2035)), step=1, key="p_alignment_year",
            )
        alignment_invalid = alignment_year < shock_year
        if alignment_invalid:
            st.error("Alignment year must be ≥ shock year.")

        col3, col4 = st.columns(2)
        with col3:
            ccs_default_label = CCS_LABELS_BY_VALUE.get(defaults.get("ccs_on"), "Without CCS (False)")
            ccs_label = st.selectbox(
                "CCS handling", list(CCS_OPTIONS.keys()),
                index=list(CCS_OPTIONS.keys()).index(ccs_default_label), key="p_ccs",
            )
            ccs_on = CCS_OPTIONS[ccs_label]
        with col4:
            reduce_granularity = st.checkbox(
                "Aggregate to company level (faster, less detail)",
                value=bool(defaults.get("reduce_granularity_from_asset_to_company_level", False)),
                key="p_granularity",
            )

        market_passthrough = st.slider(
            "Carbon price passthrough to market prices", 0.0, 1.0,
            float(defaults.get("market_passthrough", 0.0)), key="p_passthrough",
        )

        params = {
            "baseline_scenario": baseline_scenario,
            "target_scenario": target_scenario,
            "shock_year": int(shock_year),
            "alignment_year": int(alignment_year),
            "ccs_on": ccs_on,
            "reduce_granularity_from_asset_to_company_level": bool(reduce_granularity),
            "market_passthrough": float(market_passthrough),
        }

        with st.expander("Advanced settings (optional)"):
            max_forecast_horizon = st.number_input(
                "max_forecast_horizon", min_value=1, max_value=30,
                value=int(defaults.get("max_forecast_horizon", 5)), step=1, key="p_horizon",
            )

            col1, col2, col3 = st.columns(3)
            with col1:
                apply_retirement_baseline = st.checkbox(
                    "apply_retirement_baseline",
                    value=bool(defaults.get("apply_retirement_baseline", True)), key="p_retire_base",
                )
            with col2:
                apply_retirement_shock = st.checkbox(
                    "apply_retirement_shock",
                    value=bool(defaults.get("apply_retirement_shock", True)), key="p_retire_shock",
                )
            with col3:
                apply_decreasing_staggered_shock = st.checkbox(
                    "apply_decreasing_staggered_shock",
                    value=bool(defaults.get("apply_decreasing_staggered_shock", False)), key="p_staggered",
                )
            staggered_defaults = defaults.get("staggered_shock", {})
            col4, col5 = st.columns(2)
            with col4:
                staggered_g_k = st.number_input(
                    "staggered_shock.g_k", value=float(staggered_defaults.get("g_k", 6.0)), key="p_g_k",
                )
            with col5:
                staggered_n_quantiles = st.number_input(
                    "staggered_shock.n_quantiles", min_value=1,
                    value=int(staggered_defaults.get("n_quantiles", 3)), step=1, key="p_n_quantiles",
                )

            col6, col7, col8 = st.columns(3)
            with col6:
                include_growth_capex = st.checkbox(
                    "include_growth_capex", value=bool(defaults.get("include_growth_capex", False)), key="p_growth_capex",
                )
            with col7:
                include_replacement_capex = st.checkbox(
                    "include_replacement_capex", value=bool(defaults.get("include_replacement_capex", False)), key="p_repl_capex",
                )
            with col8:
                include_decom_costs = st.checkbox(
                    "include_decom_costs", value=bool(defaults.get("include_decom_costs", False)), key="p_decom",
                )
            col9, col10 = st.columns(2)
            with col9:
                apply_continued_om_baseline = st.checkbox(
                    "apply_continued_om_baseline",
                    value=bool(defaults.get("apply_continued_om_baseline", False)), key="p_om_base",
                )
            with col10:
                apply_continued_om_shock = st.checkbox(
                    "apply_continued_om_shock",
                    value=bool(defaults.get("apply_continued_om_shock", True)), key="p_om_shock",
                )

            dcf_defaults = defaults.get("dcf", {})
            col11, col12 = st.columns(2)
            with col11:
                discount_rate_baseline = st.number_input(
                    "dcf.discount_rate_baseline",
                    value=float(dcf_defaults.get("discount_rate_baseline", 0.07)), format="%.3f", key="p_disc_base",
                )
            with col12:
                discount_rate_shock = st.number_input(
                    "dcf.discount_rate_shock",
                    value=float(dcf_defaults.get("discount_rate_shock", 0.07)), format="%.3f", key="p_disc_shock",
                )
            terminal_defaults = dcf_defaults.get("terminal_value", {})
            col13, col14 = st.columns(2)
            with col13:
                terminal_value_method = st.selectbox(
                    "dcf.terminal_value.method", ["perpetuity", "none"],
                    index=["perpetuity", "none"].index(terminal_defaults.get("method", "perpetuity")), key="p_terminal_method",
                )
            with col14:
                g_real_default = st.number_input(
                    "dcf.terminal_value.g_real_default",
                    value=float(terminal_defaults.get("g_real_default", 0.02)), format="%.3f", key="p_g_real",
                )

            params.update({
                "max_forecast_horizon": int(max_forecast_horizon),
                "apply_retirement_baseline": bool(apply_retirement_baseline),
                "apply_retirement_shock": bool(apply_retirement_shock),
                "apply_decreasing_staggered_shock": bool(apply_decreasing_staggered_shock),
                "staggered_shock": {
                    "g_k": float(staggered_g_k),
                    "n_quantiles": int(staggered_n_quantiles),
                },
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
            })

    st.session_state.custom_params = params

    st.divider()
    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("← Back", key="back_2"):
            _goto(1)
    with col_next:
        if st.button("Next →", type="primary", disabled=alignment_invalid, key="next_2"):
            _goto(3)


# ---------------------------------------------------------------------------
# Step 3: run & results
# ---------------------------------------------------------------------------
def render_results(run_dir: Path) -> None:
    npv_path = run_dir / "company_npv.csv"
    if npv_path.exists():
        npv_df = pd.read_csv(npv_path)

        col1, col2, col3 = st.columns(3)
        col1.metric("Companies", len(npv_df))
        col2.metric("Avg NPV change", f"{npv_df['npv_change'].mean():.1%}")
        col3.metric("Assets covered", int(npv_df["asset_count"].sum()))

        st.subheader("Company NPV impact")
        st.caption("baseline_npv / latesudden_npv are discounted cash flows; npv_change is the % difference.")
        display_df = npv_df.sort_values("npv_change").reset_index(drop=True)
        st.dataframe(display_df, width="stretch", height=320)

        most_affected = display_df.reindex(
            display_df["npv_change"].abs().sort_values(ascending=False).index
        ).head(25)
        st.bar_chart(most_affected.set_index("company_name")["npv_change"])

    plots_dir = run_dir / "companies_trajectories_plots"
    if plots_dir.exists():
        images = sorted(plots_dir.glob("*.png"))[:4]
        if images:
            st.subheader("Sample plots")
            cols = st.columns(len(images))
            for col, img_path in zip(cols, images):
                col.image(str(img_path), caption=img_path.stem, width="stretch")

    st.divider()
    st.download_button(
        "Download all results (zip)",
        data=_zip_directory_bytes(run_dir),
        file_name=f"{run_dir.name}_results.zip",
        mime="application/zip",
        type="primary",
        key="download_results",
    )


def render_step_run() -> None:
    st.header("3. Run & results")

    n_companies = len(st.session_state.company_ids) if st.session_state.company_ids else 0
    col1, col2 = st.columns(2)
    col1.metric("Companies", n_companies)
    col2.metric("Parameters", st.session_state.param_mode)

    include_plots = st.checkbox("Also generate plots (slower)", value=False, key="include_plots")

    st.divider()
    col_back, col_run = st.columns(2)
    with col_back:
        if st.button("← Back", key="back_3"):
            _goto(2)
    run_clicked = col_run.button("Run model", type="primary", key="run_button")

    if run_clicked:
        tags = ["altrisk"] + (["reporting"] if include_plots else [])
        workspace_dir = PROJECT_ROOT / "workspace" / f"results_streamlit_{datetime.now():%Y%m%d_%H%M%S}"

        log_box = st.empty()
        log_lines: list[str] = []

        def log(message: str) -> None:
            log_lines.append(message)
            log_box.code("\n".join(log_lines[-200:]))

        with st.status("Running the model...", expanded=True) as status:
            try:
                summary = run_batch(
                    {"run": st.session_state.custom_params},
                    output_dir=workspace_dir,
                    tags=tags,
                    company_ids=st.session_state.company_ids,
                    scenarios_csv=str(SCENARIOS_CSV),
                    log=log,
                )
                st.session_state.run_summary = summary
                row = summary.iloc[0]
                status.update(
                    label="Done." if row["status"] == "success" else f"Run failed: {row['error']}",
                    state="complete" if row["status"] == "success" else "error",
                )
            except Exception as exc:
                status.update(label=f"Run failed to start: {exc}", state="error")
                st.exception(exc)

    if st.session_state.run_summary is not None:
        row = st.session_state.run_summary.iloc[0]
        if row["status"] == "success":
            st.divider()
            render_results(Path(row["run_dir"]))
        else:
            st.error(f"Run failed: {row['error']}")

        st.divider()
        if st.button("Start over"):
            _start_over()
            st.rerun()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
_init_state()

st.title("ALTR Model")
st.caption("Pick a portfolio, pick parameters, run the model, download the results.")
render_stepper()
st.divider()

if st.session_state.step == 1:
    render_step_portfolio()
elif st.session_state.step == 2:
    render_step_parameters()
else:
    render_step_run()
