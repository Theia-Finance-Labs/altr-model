"""A misspelled retirement_timing must raise even on paths that never retire.

Round-2 review finding: the helper's guard is unreachable when the allocation
is empty, retirement is disabled, or no asset retires — those paths return
early. The three public nodes now validate at entry, so the config fails
loudly on every run shape.
"""
import pandas as pd
import pytest
from altr_model.pipelines.allocate_company_trajectories_to_assets.nodes import (
    allocate_decreasing_company_trajectories_to_assets,
    compute_asset_baselines,
    create_frozen_capacity_at_retirement,
)

_EMPTY = pd.DataFrame()


def test_baselines_rejects_a_bad_timing_before_touching_data():
    with pytest.raises(ValueError, match="retirement_timing"):
        compute_asset_baselines(
            company_pathways_pre_allocation=_EMPTY,
            extended_asset_panel=_EMPTY,
            apply_retirement_baseline=False,
            alignment_year=2038,
            retirement_timing="defered",  # typo
        )


def test_frozen_capacity_rejects_a_bad_timing_before_touching_data():
    with pytest.raises(ValueError, match="retirement_timing"):
        create_frozen_capacity_at_retirement(
            asset_allocation_wide=_EMPTY,
            alignment_year=2038,
            retirement_timing="natrual",  # typo
        )


def test_decreasing_allocation_rejects_a_bad_timing_before_touching_data():
    with pytest.raises(ValueError, match="retirement_timing"):
        allocate_decreasing_company_trajectories_to_assets(
            decreasing_company_pathways=_EMPTY,
            assets_with_baseline=_EMPTY,
            shock_year=2033,
            alignment_year=2038,
            apply_retirement_shock=False,
            apply_decreasing_staggered_shock=False,
            g_k=6.0,
            n_quantiles=3,
            retirement_timing="window",  # not an option
        )
