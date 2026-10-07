"""Fill a missing carbon price from the same scenario in other models.

Six AR6 providers (AIM/CGE 2.2, COFFEE 1.1, GCAM 5.2/5.3, GCAM-PR 5.3,
IMACLIM 1.1) publish no regional `Price|Carbon`, so their scenarios arrive at
0 USD/tCO2 and fossil plants pay nothing for carbon. ENGAGE-style scenario
names encode one protocol shared across models (`EN_NPi2020_900` = the 900 Gt
budget), so the same name in another model is the closest price available.

Rule (owner ruling 2026-10-01): a scenario whose carbon price is 0 or missing
in EVERY row takes, per year, the median over priced peer providers of each
peer's median-across-geographies price, applied to all its geographies. A
peer is another provider with exactly the same protocol name: `900` (budget
never exceeded) and `900f` (end-of-century budget, overshoot allowed) are
different designs with different prices, so they are not pooled (ruling
2026-10-06). No priced peer -> the scenario stays at 0. Must run
BEFORE scenario filtering, which drops the peers.
"""

from __future__ import annotations

import logging

import pandas as pd

from altr_model._validation import validate_choice

logger = logging.getLogger(__name__)

PRICE = "carbon_price_usd_per_tco2"
FLAG = "carbon_price_filled"
METHODS = ("none", "peer_scenario_median")


def _protocol(scenario: pd.Series, provider: pd.Series) -> pd.Series:
    """`AR6_<provider>_<protocol>` -> protocol."""
    prefix_len = provider.str.len() + len("AR6__")
    return pd.Series(
        [s[n:] if s.startswith(f"AR6_{p}_") else s for s, p, n in zip(scenario, provider, prefix_len)],
        index=scenario.index,
    )


def fill_missing_carbon_prices(scenarios: pd.DataFrame, method: str) -> pd.DataFrame:
    """Return a copy with all-zero carbon prices filled from peers, flagged."""
    validate_choice("carbon_price_fill", method, METHODS)
    if method == "none":
        return scenarios

    out = scenarios.copy()
    out["_protocol"] = _protocol(out["scenario"].astype(str), out["scenario_provider"].astype(str))
    price = out[PRICE].fillna(0.0)
    unpriced = price.groupby(out["scenario"]).transform("max") <= 0

    peer_prices = (
        out[~unpriced]
        .groupby(["_protocol", "scenario_provider", "year"])[PRICE]
        .median()  # across geographies (and techs, which share one price)
        .groupby(["_protocol", "year"])
        .median()  # across peer providers
        .rename("_peer_price")
        .reset_index()
    )
    out = out.merge(peer_prices, on=["_protocol", "year"], how="left")
    fill = unpriced & out["_peer_price"].notna()
    out[PRICE] = out[PRICE].where(~fill, out["_peer_price"])
    out[FLAG] = fill

    filled = sorted(out.loc[fill, "scenario"].unique())
    no_peer = sorted(out.loc[unpriced & ~fill, "scenario"].unique())
    logger.info(
        "Carbon-price fill: %d unpriced scenario(s) filled from peers, %d left at 0 "
        "(no priced peer). Filled: %s",
        len(filled),
        len(no_peer),
        filled[:20],
    )
    return out.drop(columns=["_protocol", "_peer_price"])
