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
    """Total TV under the stranding-aware tiering, switched on explicitly.

    The two "defaults" disagree, so neither name is used bare here:
    `compute_yearly_npv_trajectories`'s signature default is
    `stranding_aware_tv=False`, while the shipped
    `conf/base/parameters_calculate_asset_and_company_npv.yml` sets
    `dcf.stranding_aware_tv: True`. A real run therefore has the tiering ON;
    a direct call to the node without the parameter has it OFF. These tests
    pass it explicitly so they pin the shipped behaviour either way.
    """
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


def test_a_missing_fcff_year_is_not_counted_as_a_loss_year():
    """A gap in the middle of the trailing window is not a loss.

    `compute_yearly_npv_trajectories` collapses the CapEx flow-split rows with
    `groupby(...).sum()`, and pandas sums an all-NaN cell to 0.0. That filled
    zero satisfies `FCFF <= 0`, so a year with no data used to complete a run
    of N consecutive loss years and write off the asset's whole terminal value
    on evidence that was never measured. "loss, gap, loss" is not a run of
    three."""
    frame = _loss_making_years(N)
    frame.loc[frame.year == 2049, "FCFF"] = float("nan")

    assert _terminal_value(frame) != 0.0


def test_a_history_of_only_missing_years_is_not_stranded():
    """The minimum-history guard counts OBSERVED years, not rows: a group whose
    FCFF is missing throughout has no evidence of anything."""
    frame = _loss_making_years(N + 2)
    frame.loc[frame.year <= 2050, "FCFF"] = float("nan")

    assert _terminal_value(frame) == 0.0, (
        "an all-missing group has no terminal FCFF either, so it falls out at "
        "`has_terminal_fcff` with TV 0 — but never via the stranded tier"
    )
