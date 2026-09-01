"""Regression: stranding needs N observations, not N-or-fewer.

The stranded tier zeroes an asset's whole terminal value on the grounds that it
is loss-making for `stranding_consecutive_years` CONSECUTIVE years at the end
of the horizon (Gourdel 2024). A group whose entire history is shorter than N
cannot demonstrate that: taking "every year I have is a loss" from a one- or
two-year history classified assets stranded on evidence the criterion does not
have. Short histories are real - a run with a small `max_forecast_horizon`, or
an asset whose rows start late - so the guard is not hypothetical.
"""

import pandas as pd
from altr_model.pipelines.calculate_asset_and_company_npv.nodes import (
    compute_yearly_npv_trajectories,
)

META = dict(
    asset_name="a1",
    asset_id="A1",
    company_id="C1",
    company_name="c",
    scenario_geography="EU",
    sector="Power",
    technology="GasCap - w/o CCS",
    is_synthetic=False,
    alignment_type="misaligned_high_carbon",
    trajectory_type="baseline",
    scenario_type="baseline",
)

#: The default `stranding_consecutive_years`; the frames below sit either side.
N = 3


def _loss_making_years(count: int) -> pd.DataFrame:
    """`count` consecutive loss years ending at 2050."""
    years = range(2051 - count, 2051)
    return pd.DataFrame([{**META, "year": y, "FCFF": -10.0} for y in years])


def _terminal_value(df: pd.DataFrame) -> float:
    """Total TV under the stranding-aware tiering (off by default)."""
    out = compute_yearly_npv_trajectories(
        df, stranding_aware_tv=True, stranding_consecutive_years=N
    )
    return float(out.terminal_value.sum())


def test_a_history_shorter_than_n_is_not_stranded():
    """Two loss years are not three consecutive ones. The asset falls through
    to the ordinary perpetuity tier, whose TV is negative here - the point is
    that it is not the stranded tier's hard zero."""
    assert _terminal_value(_loss_making_years(N - 1)) < 0


def test_a_full_length_loss_history_is_stranded():
    """N loss years is exactly the criterion: TV is written to zero."""
    assert _terminal_value(_loss_making_years(N)) == 0.0
