"""Project pipelines."""
from __future__ import annotations

from kedro.pipeline import Pipeline

from crispy_kedro.pipelines.allocate_company_trajectories_to_assets.pipeline import (
    create_pipeline as create_asset_allocation,
)
from crispy_kedro.pipelines.calculate_asset_and_company_npv import (
    create_pipeline as create_valuation,
)
from crispy_kedro.pipelines.calculate_asset_earnings import (
    create_pipeline as create_earnings,
)
from crispy_kedro.pipelines.calculate_company_trajectories.pipeline import (
    create_pipeline as create_company_trajectory_calculation,
)
from crispy_kedro.pipelines.plot_transition_risk_results import (
    create_pipeline as create_reporting,
)
from crispy_kedro.pipelines.prepare_scenario_asset_and_company_inputs.pipeline import (
    create_pipeline as create_input_preparation,
)


def register_pipelines() -> dict[str, Pipeline]:
    """Register the project's pipelines.

    Returns:
        A mapping from pipeline names to ``Pipeline`` objects.
    """
    pipelines = {
        "prepare_scenario_asset_and_company_inputs": create_input_preparation(),
        "calculate_company_trajectories": create_company_trajectory_calculation(),
        "allocate_company_trajectories_to_assets": create_asset_allocation(),
        "calculate_asset_earnings": create_earnings(),
        "calculate_asset_and_company_npv": create_valuation(),
        "plot_transition_risk_results": create_reporting(),
    }
    pipelines["__default__"] = sum(pipelines.values())
    return pipelines
