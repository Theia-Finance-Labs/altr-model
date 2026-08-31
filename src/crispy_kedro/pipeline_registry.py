"""Project pipelines.

The ALTR model runs as eight ordered stages, each a Kedro pipeline:

1. ``inputs_processing`` — filter/interpolate scenarios, assets and ownership
2. ``inputs_postproc`` — post-process the processed inputs for the trajectory stages
3. ``create_baseline_and_target_trajectories`` — company-level baseline/target paths
4. ``create_late_sudden_trajectories`` — apply the late & sudden shock to the paths
5. ``distribute_impacts_to_asset_level`` — push company impacts down to assets
6. ``earnings_model`` — prices, carbon costs, capex/opex and FCFF per asset
7. ``valuation_model`` — DCF and NPV per asset, technology and company
8. ``reporting`` — reporting views, plots and export tables

``download_inputs`` (BigQuery ingestion) is internal-only and is not part of the
eight-stage sequence.
"""
from __future__ import annotations

from kedro.framework.project import find_pipelines
from kedro.pipeline import Pipeline

#: The eight ALTR stages, in the order they run.
STAGE_ORDER = (
    "inputs_processing",
    "inputs_postproc",
    "create_baseline_and_target_trajectories",
    "create_late_sudden_trajectories",
    "distribute_impacts_to_asset_level",
    "earnings_model",
    "valuation_model",
    "reporting",
)


def register_pipelines() -> dict[str, Pipeline]:
    """Register the project's pipelines.

    Returns:
        A mapping from pipeline names to ``Pipeline`` objects: the eight stages
        in ``STAGE_ORDER`` first, then any other discovered pipeline, then
        ``full`` (the eight stages combined) and ``__default__`` (every
        discovered pipeline, as before).
    """
    pipelines = find_pipelines()
    stages = [name for name in STAGE_ORDER if name in pipelines]

    ordered: dict[str, Pipeline] = {name: pipelines[name] for name in stages}
    ordered.update(
        {
            name: pipeline
            for name, pipeline in pipelines.items()
            if name not in ordered and name != "__default__"
        }
    )
    ordered["full"] = sum(pipelines[name] for name in stages)
    ordered["__default__"] = sum(pipelines.values())
    return ordered
