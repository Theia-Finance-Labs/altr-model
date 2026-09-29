"""EXPERIMENTAL year-by-year closure option (spec 2026-09-29-closure-option).

An owner closes a plant in the first year that paying to decommission it beats
running on. The scenarios are deterministic, so the stopping problem solves
exactly by backward induction in present-value terms:

    V[T+1] = terminal value from the existing tiers
    V[t]   = max(exit[t], pv_fcff[t] + V[t+1])   where exit is allowed
    exit[t] = -|scrap| * capacity[t-1] * discount_factor[t]

Late & sudden series cannot foresee the shock: before `shock_year` they share
the baseline outlook, so they inherit a pre-shock baseline closure and may only
choose to close themselves from `shock_year` on.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BASELINE = "baseline"
LATESUDDEN = "latesudden"


def _padded(values: np.ndarray, gid: np.ndarray, pos: np.ndarray, shape, fill):
    """Rows (group-contiguous, year-sorted) as a [group, position] matrix."""
    out = np.full(shape, fill, dtype=np.asarray(values).dtype)
    out[gid, pos] = values
    return out


def _solve(pv, exit_pv, allowed, forced, valid, tv) -> np.ndarray:
    """First closure position per group by backward induction; -1 = never."""
    value = tv.copy()
    closes = np.zeros(pv.shape, dtype=bool)
    for k in range(pv.shape[1] - 1, -1, -1):
        cont = pv[:, k] + value
        choose = valid[:, k] & (forced[:, k] | (allowed[:, k] & (exit_pv[:, k] > cont)))
        value = np.where(valid[:, k], np.where(choose, exit_pv[:, k], cont), value)
        closes[:, k] = choose
    return np.where(closes.any(axis=1), closes.argmax(axis=1), -1)


def apply_closure_option(
    npv_data: pd.DataFrame,
    gid: np.ndarray,
    starts: np.ndarray,
    sizes: np.ndarray,
    terminal_value: np.ndarray,
    scrap: np.ndarray | None,
    shock_year: int,
    asset_keys: list[str],
    financial_cols: list[str],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Return (npv_data, terminal_value, closure_year per group), all new objects.

    `npv_data` must be sorted by (group, year) with `discount_factor`,
    `pv_fcff` and `yearly_npv` set. Without a capacity column or a scrap quote
    there is no exit arm, and nothing closes.
    """
    n_groups = len(sizes)
    no_closure = np.full(n_groups, np.nan)
    if scrap is None or "asset_trajectory" not in npv_data.columns or not n_groups:
        logger.warning("Closure option: no scrap price or capacity, nothing can close")
        return npv_data, terminal_value, no_closure

    n_rows = len(npv_data)
    pos = np.arange(n_rows) - starts[gid]
    shape = (n_groups, int(sizes.max()))
    years = npv_data["year"].to_numpy(dtype=np.int64)
    capacity = npv_data["asset_trajectory"].to_numpy(dtype=np.float64)
    capacity_prev = np.where(pos == 0, capacity, np.roll(capacity, 1))
    exit_cost = np.abs(scrap)[gid] * capacity_prev  # undiscounted, positive
    exit_pv = -exit_cost * npv_data["discount_factor"].to_numpy(dtype=np.float64)
    can_exit = np.isfinite(exit_pv)

    trajectory = npv_data["trajectory_type"].to_numpy()[starts]
    is_shock_group = trajectory == LATESUDDEN
    is_shock_row = is_shock_group[gid]

    pv = _padded(npv_data["pv_fcff"].to_numpy(dtype=np.float64), gid, pos, shape, 0.0)
    exit_m = _padded(np.where(can_exit, exit_pv, -np.inf), gid, pos, shape, -np.inf)
    valid = _padded(np.ones(n_rows, dtype=bool), gid, pos, shape, False)
    year_m = _padded(years, gid, pos, shape, 0)
    none = np.zeros(shape, dtype=bool)

    # Pass 1: baseline series may close in any year.
    base_allowed = _padded(can_exit & ~is_shock_row, gid, pos, shape, False)
    base_pos = _solve(pv, exit_m, base_allowed, none, valid, terminal_value)
    closure_year = np.where(
        base_pos >= 0, year_m[np.arange(n_groups), np.maximum(base_pos, 0)], np.nan
    )

    # Pass 2: shock series inherit a pre-shock baseline closure, else may close
    # only from the shock year on.
    groups = npv_data.iloc[starts][asset_keys].reset_index(drop=True)
    base_close = (
        groups.assign(_close=closure_year)[~is_shock_group]
        .groupby(asset_keys, dropna=False)["_close"]
        .min()
        .rename("_inherited")
        .reset_index()
    )
    inherited = (
        groups.merge(base_close, on=asset_keys, how="left")["_inherited"].to_numpy()
    )
    inherited = np.where(is_shock_group & (inherited < shock_year), inherited, np.nan)
    forced = valid & (year_m == inherited[:, None]) & np.isfinite(exit_m)
    shock_allowed = _padded(can_exit & is_shock_row & (years >= shock_year), gid, pos, shape, False)
    shock_pos = _solve(pv, exit_m, shock_allowed, forced, valid, terminal_value)
    close_pos = np.where(is_shock_group, shock_pos, base_pos)
    closure_year = np.where(
        close_pos >= 0, year_m[np.arange(n_groups), np.maximum(close_pos, 0)], np.nan
    )

    # Apply: zero every flow from the closure year on, book the exit cost in it.
    row_close = close_pos[gid]
    after = (row_close >= 0) & (pos >= row_close)
    at = (row_close >= 0) & (pos == row_close)
    out = npv_data.copy()
    zero_cols = [c for c in financial_cols + ["pv_fcff", "yearly_npv"] if c in out.columns]
    out.loc[after, zero_cols] = 0.0
    out.loc[at, "FCFF"] = -exit_cost[at]
    if "capex_total" in out.columns:
        out.loc[at, "capex_total"] = exit_cost[at]
    out.loc[at, "pv_fcff"] = exit_pv[at]
    out.loc[at, "yearly_npv"] = exit_pv[at]
    new_tv = np.where(close_pos >= 0, 0.0, terminal_value)

    logger.info(
        "Closure option: %d of %d baseline and %d of %d late & sudden series close "
        "(%d inherit a pre-shock baseline closure)",
        int(((close_pos >= 0) & ~is_shock_group).sum()),
        int((~is_shock_group).sum()),
        int(((close_pos >= 0) & is_shock_group).sum()),
        int(is_shock_group.sum()),
        int(np.isfinite(inherited).sum()),
    )
    return out, new_tv, closure_year
