"""Tests for project-level pipeline registration and namespacing."""

from pathlib import Path

from altr_model.pipeline_registry import register_pipelines
from kedro.framework.startup import bootstrap_project

PIPELINE_NAMES = {
    "allocate_company_trajectories_to_assets",
    "calculate_asset_and_company_npv",
    "calculate_asset_earnings",
    "calculate_company_trajectories",
    "plot_transition_risk_results",
    "prepare_scenario_asset_and_company_inputs",
}

# Datasets the migration retired. `frozen_capacity_at_retirement` was on this
# list until 2026-09-01, when the owner ruling in
# docs/superpowers/plans/implementation-notes-handover.md ("Owner decisions
# 2026-09-01", item 2, Q4) ported it back from the handover branch. This test
# defended its removal; the ruling supersedes that, so it is no longer listed.
REMOVED_DATASETS = {
    "all_alignment_classifications",
    "asset_level_staggered_shock_melted",
    "assets_retirement_dates",
    "companies_late_sudden_trajectories_corrected",
    "extended_companies_forecasts",
    "scenario_pathways",
    "scenarios_pathways",
}


def _registered_pipelines():
    bootstrap_project(Path.cwd())
    return register_pipelines()


def test_each_registered_pipeline_has_a_matching_namespace():
    pipelines = _registered_pipelines()

    assert set(pipelines) == PIPELINE_NAMES | {"__default__"}
    for pipeline_name in PIPELINE_NAMES:
        registered_pipeline = pipelines[pipeline_name]

        assert set(registered_pipeline.grouped_nodes_by_namespace) == {pipeline_name}
        assert all(
            node.name.startswith(f"{pipeline_name}.")
            for node in registered_pipeline.nodes
        )


def test_default_pipeline_keeps_only_raw_datasets_as_free_data_inputs():
    default_pipeline = _registered_pipelines()["__default__"]
    data_inputs = {
        dataset_name
        for dataset_name in default_pipeline.inputs()
        if not dataset_name.startswith("params:")
    }

    assert data_inputs == {
        "assets_forecasts",
        "companies_ownerships",
        "scenarios",
    }
    assert not any(
        parameter_name.startswith(f"params:{pipeline_name}.")
        for parameter_name in default_pipeline.inputs()
        for pipeline_name in PIPELINE_NAMES
    )


def test_pipeline_public_contracts_are_narrow_and_canonical():
    pipelines = _registered_pipelines()

    input_preparation = pipelines["prepare_scenario_asset_and_company_inputs"]
    assert input_preparation.outputs() == {"company_projection_inputs"}
    assert "asset_forecast_panel" in {
        dataset_name
        for pipeline_node in input_preparation.nodes
        for dataset_name in pipeline_node.outputs
    }
    assert pipelines["calculate_company_trajectories"].outputs() == {
        "company_pathways_pre_allocation"
    }
    allocation = pipelines["allocate_company_trajectories_to_assets"]
    # `frozen_capacity_at_retirement` joins `company_trajectories` on the public
    # contract under the 2026-09-01 owner ruling (Q4): it is produced here, where
    # retirement years live, and consumed by the earnings stage.
    assert allocation.outputs() == {
        "company_trajectories",
        "frozen_capacity_at_retirement",
    }
    assert "asset_trajectories" in {
        dataset_name
        for pipeline_node in allocation.nodes
        for dataset_name in pipeline_node.outputs
    }
    earnings_data_inputs = {
        dataset_name
        for dataset_name in pipelines["calculate_asset_earnings"].inputs()
        if not dataset_name.startswith("params:")
    }
    assert earnings_data_inputs == {
        "asset_trajectories",
        "frozen_capacity_at_retirement",
    }


def test_methodology_steps_are_visible_as_individual_nodes():
    pipelines = _registered_pipelines()
    company_node_names = {
        node.name.split(".")[-1]
        for node in pipelines["calculate_company_trajectories"].nodes
    }
    assert {
        "classify_company_trajectory_alignment",
        "calculate_misaligned_decreasing_technology_transition",
        "calculate_misaligned_increasing_technology_transition",
        "calculate_aligned_decreasing_technology_transition",
        "calculate_aligned_increasing_technology_transition",
        "combine_company_trajectory_cases",
    }.issubset(company_node_names)

    allocation_node_names = {
        node.name.split(".")[-1]
        for node in pipelines["allocate_company_trajectories_to_assets"].nodes
    }
    assert {
        "split_company_pathways_by_technology_direction",
        "allocate_decreasing_company_trajectories_to_assets",
        "allocate_increasing_company_trajectories_to_assets",
        "combine_asset_allocation_branches",
        "build_canonical_asset_trajectories",
        "reconcile_realized_company_trajectories",
    }.issubset(allocation_node_names)

    earnings_node_names = {
        node.name.split(".")[-1] for node in pipelines["calculate_asset_earnings"].nodes
    }
    assert earnings_node_names == {
        "validate_asset_trajectories",
        "calculate_capacity_flows_and_capex",
        "calculate_operating_earnings",
        "calculate_free_cash_flow",
        "write_asset_earnings",
        "write_asset_horizon_attributes",
    }

    valuation_node_names = {
        node.name.split(".")[-1]
        for node in pipelines["calculate_asset_and_company_npv"].nodes
    }
    assert valuation_node_names == {
        "calculate_yearly_npv_trajectories",
        "aggregate_npv_by_asset",
        "aggregate_npv_by_company_and_technology",
        "aggregate_npv_by_company",
    }


def test_default_pipeline_has_no_dead_private_or_removed_datasets():
    default_pipeline = _registered_pipelines()["__default__"]
    all_datasets = set()
    for pipeline_node in default_pipeline.nodes:
        all_datasets.update(pipeline_node.inputs)
        all_datasets.update(pipeline_node.outputs)

    assert not {
        dataset_name.split(".")[-1] for dataset_name in all_datasets
    }.intersection(REMOVED_DATASETS)
    assert not any(
        dataset_name.split(".")[-1].startswith("_temp")
        for dataset_name in default_pipeline.outputs()
    )

    consumed_outputs = {
        dataset_name
        for pipeline_node in default_pipeline.nodes
        for dataset_name in pipeline_node.inputs
    }
    unconsumed_outputs = {
        dataset_name
        for pipeline_node in default_pipeline.nodes
        for dataset_name in pipeline_node.outputs
        if dataset_name not in consumed_outputs
    }
    assert unconsumed_outputs == {
        "asset_financial_trajectories_plots_dir",
        "company_npv",
    }
