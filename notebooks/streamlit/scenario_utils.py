"""Helpers for picking a valid baseline/target scenario pair.

Scenario names in ``scenarios.csv`` encode the source IAM ("provider") as
the token right after the ``AR6_`` prefix, e.g.:

    AR6_AIM/CGE 2.2_EN_NPi2020_1200f   -> provider "AIM/CGE 2.2"
    AR6_AIM/CGE 2.2_EN_NPi2020_900f    -> provider "AIM/CGE 2.2"
    AR6_WITCH 5.0_EN_NPi2020_1200f     -> provider "WITCH 5.0"

``prepare_scenario_asset_and_company_inputs`` (see
``_input_nodes.filter_scenarios``) does not hard-fail on a baseline/target
pair from two different providers - it silently intersects their
geographies and sector/technology combinations and only *warns* about the
mismatch. Mixing providers is almost never intentional (different IAMs
disagree on units, geography splits, and technology coverage), so the
Streamlit scenario picker only presents target scenarios from the same
provider as the selected baseline.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

MIN_SCENARIO_NAME_PARTS = 2

DEFAULT_SCENARIOS_CSV = (
    Path(__file__).resolve().parents[2] / "data" / "05_model_input" / "scenarios.csv"
)


def scenario_provider(scenario_name: str) -> str:
    """Return the IAM/provider token embedded in a scenario name."""
    parts = scenario_name.split("_")
    if len(parts) < MIN_SCENARIO_NAME_PARTS:
        return scenario_name
    return parts[1]


@lru_cache(maxsize=4)
def _load_scenario_types(scenarios_csv: str) -> pd.DataFrame:
    # Some scenarios.csv deliveries use "scenario_name" instead of "scenario"
    # for the scenario identifier column - support both without loading the
    # full (multi-GB) file just to check.
    header = pd.read_csv(scenarios_csv, nrows=0).columns
    scenario_col = "scenario" if "scenario" in header else "scenario_name"
    df = pd.read_csv(scenarios_csv, usecols=[scenario_col, "scenario_type"])
    if scenario_col != "scenario":
        df = df.rename(columns={scenario_col: "scenario"})
    df = df.drop_duplicates().reset_index(drop=True)
    df["provider"] = df["scenario"].map(scenario_provider)
    return df


def load_scenario_options(scenarios_csv: Path | str = DEFAULT_SCENARIOS_CSV) -> pd.DataFrame:
    """Load the distinct (scenario, scenario_type, provider) rows.

    Cached per input path - ``scenarios.csv`` is a multi-MB file and this is
    called repeatedly from the Streamlit app on every rerun.
    """
    return _load_scenario_types(str(scenarios_csv)).copy()


def list_baseline_scenarios(scenarios_csv: Path | str = DEFAULT_SCENARIOS_CSV) -> list[str]:
    df = load_scenario_options(scenarios_csv)
    return sorted(df.loc[df["scenario_type"] == "baseline", "scenario"].unique())


def list_matching_target_scenarios(
    baseline_scenario: str, scenarios_csv: Path | str = DEFAULT_SCENARIOS_CSV
) -> list[str]:
    """Target scenarios sharing a provider with ``baseline_scenario``.

    Note: ``scenario_type`` in the raw file is only a loose hint - the
    pipeline itself decides baseline vs. target purely from which scenario
    name is passed as ``baseline_scenario``/``target_scenario``. Any
    scenario from the same provider (other than the baseline itself) is a
    structurally valid target.
    """
    df = load_scenario_options(scenarios_csv)
    provider = scenario_provider(baseline_scenario)
    same_provider = df.loc[df["provider"] == provider, "scenario"].unique()
    return sorted(s for s in same_provider if s != baseline_scenario)
