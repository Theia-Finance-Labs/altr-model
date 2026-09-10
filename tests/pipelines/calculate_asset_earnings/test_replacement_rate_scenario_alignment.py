"""Is `replacement_capex_rate: 0.02` aligned with what the scenarios imply?

`compute_capacity_flows` charges 2% of a real asset's INSTALLED capacity every
year as roll-over CapEx. The 2% is a literature number (EPRI / Lazard put
routine capital maintenance at 1-3% of replacement cost per year); nothing in
the model has ever checked it against the scenario data it is charged on. The
scenarios carry `lifetime_years`, `capital_cost_usd_per_mw`,
`om_cost_usd_per_mw_per_yr` and `capacity_additions_mw_per_yr` per
provider/technology/geography/year, so the check is available.

METHOD - and its limits
    A plant fully replaced once over its economic life spends, on average,
    `1 / lifetime_years` of its capital cost per year. That is the
    scenario-IMPLIED full-replacement rate. Aggregated to a fleet it is the
    capacity-weighted mean of `1 / lifetime_years`, i.e.
    `sum(MW_i / life_i) / sum(MW_i)` - the share of the fleet's capital that
    has to be renewed each year. `capacity_additions_mw_per_yr` is the only
    capacity column the scenarios carry, so it stands in for stock as the
    weight; it tilts the aggregate toward technologies the pathway is
    currently building.

    The two rates are NOT the same quantity and the test does not pretend
    otherwise. `1 / lifetime` is REPLACEMENT-scale: the whole plant, once.
    `replacement_capex_rate` is MAINTENANCE-scale: the annual refurbishment
    that keeps a plant running to its rated life, which is a fraction of a
    full rebuild. The defensible relationship between them is therefore an
    ORDERING - maintenance must not cost more than full replacement - plus a
    plausibility band. Both are asserted below. Reading the band as an
    equality claim would be wrong.

MEASURED, staged `data/05_model_input/scenarios.csv`, 2026-09-02 (337,192 rows;
199,081 usable after dropping non-positive lifetime / additions / capital cost):

    provider                    implied rate   implied life   2% / implied
    WITCH 5.0      (conf/full)      3.336%/yr        30.0 y         0.599x
    AIM/CGE 2.2    (conf/base)      2.638%/yr        37.9 y         0.758x
    GEM-E3_V2021                    2.130%/yr        46.9 y         0.939x   <- highest
    TIAM-Grantham 3.2               3.469%/yr        28.8 y         0.577x   <- lowest*
    REMIND-MAgPIE 1.7-3.0          29.560%/yr         3.4 y         0.068x   <- artifact
    whole file, all providers       4.041%/yr        24.7 y         0.495x

    * lowest of the 18 providers with physically plausible lifetimes.

    2% is inside [0.5x, 1.5x] of the implied rate for 18 of the 19 providers
    that have usable rows, and never exceeds it anywhere (max ratio 0.939x).
    So 2% IS defensible as a maintenance-scale charge sitting below
    replacement scale, on every scenario set the model is configured to run.

    The single exception, and the only reason the whole-file aggregate lands
    at 0.495x rather than comfortably inside the band, is a DATA DEFECT, not a
    modelling one - see `test_the_whole_file_aggregate_is_dragged_by_one_provider`.

O&M DOUBLE-COUNT (reported, not asserted - see the last test)
    `include_growth_capex: False` is justified in the parameters file by "IAM
    O&M already bundles annualized capital costs (REMIND/WITCH/POLES)". If
    that is true, the 2% replacement charge is levied on top of an O&M number
    that already contains capital recovery, and is double-counted. Measured
    ratio of `om_cost_usd_per_mw_per_yr` to `0.02 x capital_cost_usd_per_mw`:
    2.103x for WITCH 5.0, 0.966x for AIM/CGE 2.2, median 1.415x across
    providers, max 9.629x (REMIND-MAgPIE 2.1-4.3). O&M is therefore roughly
    the same order as - and usually larger than - the replacement charge, so
    if it does bundle capital recovery the overlap is material rather than
    negligible. Deciding that is an owner call about IAM cost conventions,
    which a test cannot make; the number is reported so the call can be made.
"""

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest
from altr_model.pipelines.calculate_asset_earnings.nodes import REPLACEMENT_CAPEX_RATE

logger = logging.getLogger(__name__)

#: The staged full scenarios. Gitignored (`data/**`), so absent on a fresh
#: clone until `prepare_new_inputs` has run - skip rather than fail, as
#: `test_npv_vectorized_equivalence.py` does for its real-data case.
SCENARIOS = (
    Path(__file__).resolve().parents[3] / "data" / "05_model_input" / "scenarios.csv"
)

pytestmark = pytest.mark.skipif(
    not SCENARIOS.exists(),
    reason=f"staged scenarios not present at {SCENARIOS}",
)

#: Plausibility band around the scenario-implied full-replacement rate. Wide on
#: purpose: the two rates measure different things (see the module docstring),
#: so this asks "same order of magnitude", not "equal".
BAND_LOW, BAND_HIGH = 0.5, 1.5

#: Ratio at which the maintenance charge equals a full replacement per year.
#: Above it the 2% has stopped being maintenance-scale by any reading.
FULL_REPLACEMENT_RATIO = 1.0

#: The scenario pairs the shipped configurations actually run. Whatever the
#: rest of the staged file contains, 2% has to be defensible for THESE.
CONFIGURED_PROVIDERS = {
    "WITCH 5.0": "conf/full",
    "AIM/CGE 2.2": "conf/base",
}

#: Excluded from the per-provider band check, with cause. This provider's
#: `SolarCap - PV` rows carry `lifetime_years` BELOW ONE YEAR (0.478 y is the
#: smallest), which is not a plant life; 52 rows sit under 5 years and 832 more
#: are exactly 0. A sub-year lifetime implies a 117%/yr replacement rate for
#: that technology, which is what drags the provider to 3.4 years overall. It
#: is a defect in the scenario extract, reported to the owners, not evidence
#: about `replacement_capex_rate`.
IMPLAUSIBLE_LIFETIME_PROVIDERS = {"REMIND-MAgPIE 1.7-3.0"}

_COLUMNS = [
    "scenario_provider",
    "technology",
    "lifetime_years",
    "capacity_additions_mw_per_yr",
    "om_cost_usd_per_mw_per_yr",
    "capital_cost_usd_per_mw",
]


@lru_cache(maxsize=1)
def _usable_scenarios() -> pd.DataFrame:
    """The staged scenarios, restricted to rows the ratios are defined on.

    Cached: the file is ~100 MB and every test below reads the same slice.
    Callers must treat the frame as read-only.

    A non-positive `lifetime_years` has no `1 / lifetime`, a non-positive
    `capacity_additions_mw_per_yr` carries no weight, and a non-positive
    `capital_cost_usd_per_mw` has no O&M ratio. Dropping them is arithmetic,
    not judgement - the rows that go are counted in the module docstring.
    """
    raw = pd.read_csv(SCENARIOS, usecols=_COLUMNS)
    usable = raw[
        (raw["lifetime_years"] > 0)
        & (raw["capacity_additions_mw_per_yr"] > 0)
        & (raw["capital_cost_usd_per_mw"] > 0)
    ].copy()
    weight = usable["capacity_additions_mw_per_yr"]
    # Weighted-mean numerators, summed per group below: sum(w/life)/sum(w) is
    # the capacity-weighted 1/lifetime, and sum(w*om/(rate*capex))/sum(w) the
    # capacity-weighted O&M-to-replacement-charge ratio.
    usable["_life_numerator"] = weight / usable["lifetime_years"]
    usable["_om_numerator"] = (
        weight
        * usable["om_cost_usd_per_mw_per_yr"]
        / (REPLACEMENT_CAPEX_RATE * usable["capital_cost_usd_per_mw"])
    )
    return usable


def _implied_rates(by: str | list[str]) -> pd.DataFrame:
    """Capacity-weighted implied replacement rate and O&M ratio, grouped by `by`."""
    grouped = (
        _usable_scenarios()
        .groupby(by)
        .agg(
            _life=("_life_numerator", "sum"),
            _om=("_om_numerator", "sum"),
            capacity_weight_mw=("capacity_additions_mw_per_yr", "sum"),
        )
    )
    return pd.DataFrame(
        {
            "implied_rate": grouped["_life"] / grouped["capacity_weight_mw"],
            "implied_lifetime_years": grouped["capacity_weight_mw"] / grouped["_life"],
            "rate_ratio": REPLACEMENT_CAPEX_RATE
            * grouped["capacity_weight_mw"]
            / grouped["_life"],
            "om_over_replacement_capex": grouped["_om"] / grouped["capacity_weight_mw"],
            "capacity_weight_mw": grouped["capacity_weight_mw"],
        }
    )


def _whole_file_implied_rate() -> float:
    """The single cross-technology, cross-provider implied rate for the file."""
    usable = _usable_scenarios()
    return (
        usable["_life_numerator"].sum() / usable["capacity_additions_mw_per_yr"].sum()
    )


def _table(frame: pd.DataFrame) -> str:
    """Readable measurements for an assertion message."""
    return frame.round(5).sort_values("rate_ratio").to_string()


def test_two_percent_never_exceeds_the_scenario_implied_full_replacement_rate():
    """The ordering claim, and the one that does not depend on a chosen band.

    Annual maintenance cannot cost more than rebuilding the plant once over
    its whole life. If `replacement_capex_rate` ever rises above the implied
    `1 / lifetime`, the model is charging more than a full replacement per
    year and the rate has stopped being maintenance-scale - which is the
    failure mode the owners asked to be warned about, independent of where
    the plausibility band is drawn.
    """
    per_provider = _implied_rates("scenario_provider")
    above = per_provider[per_provider["rate_ratio"] > FULL_REPLACEMENT_RATIO]

    assert above.empty, (
        f"replacement_capex_rate={REPLACEMENT_CAPEX_RATE} exceeds the "
        f"scenario-implied full-replacement rate for {len(above)} provider(s) "
        f"- it is no longer a maintenance-scale charge:\n{_table(above)}"
    )


def test_two_percent_sits_inside_the_plausible_band_for_every_usable_provider():
    """Characterization: 2% is within [0.5x, 1.5x] of every provider's rate.

    Measured 2026-09-02: ratios run 0.577x (TIAM-Grantham 3.2) to 0.939x
    (GEM-E3_V2021) across the 18 providers with physically plausible
    lifetimes. A scenarios drop that shortens lifetimes materially moves
    those ratios down and trips this test with the new numbers in the
    message.
    """
    per_provider = _implied_rates("scenario_provider").drop(
        index=list(IMPLAUSIBLE_LIFETIME_PROVIDERS), errors="ignore"
    )

    missing = set(CONFIGURED_PROVIDERS) - set(per_provider.index)
    assert not missing, (
        f"the configured run providers {sorted(missing)} have no usable rows in "
        f"the staged scenarios, so this check silently skipped the only scenario "
        f"sets the model actually runs ({CONFIGURED_PROVIDERS})"
    )

    outside = per_provider[
        (per_provider["rate_ratio"] < BAND_LOW)
        | (per_provider["rate_ratio"] > BAND_HIGH)
    ]
    assert outside.empty, (
        f"replacement_capex_rate={REPLACEMENT_CAPEX_RATE} is outside "
        f"[{BAND_LOW}x, {BAND_HIGH}x] of the scenario-implied full-replacement "
        f"rate for {len(outside)} provider(s). Either the rate no longer matches "
        f"the scenarios' lifetimes, or those lifetimes are themselves "
        f"implausible - check which before changing the parameter:\n"
        f"{_table(outside)}\n\nAll providers, for context:\n"
        f"{_table(per_provider)}"
    )


def test_the_whole_file_aggregate_is_dragged_by_one_provider():
    """The ask's literal check - and why it is reported, not enforced.

    Pooling all providers gives an implied rate of 4.041%/yr, against which 2%
    is 0.495x: marginally OUTSIDE the band, by half a percentage point of
    ratio. That aggregate is not a quantity any run uses - it weights 19 IAMs'
    views of the same physical world into one number - and it is entirely
    driven by `REMIND-MAgPIE 1.7-3.0`'s sub-year `SolarCap - PV` lifetimes.
    Excluding that one provider's bad rows takes the pooled rate to inside the
    band, and every provider the model is configured to run is comfortably
    inside it on its own.

    Pinned rather than band-checked, so a future scenarios drop that changes
    lifetimes shows up here as a concrete number to look at instead of a
    silent pass.
    """
    pooled = _whole_file_implied_rate()
    per_provider = _implied_rates("scenario_provider")
    clean = per_provider.drop(
        index=list(IMPLAUSIBLE_LIFETIME_PROVIDERS), errors="ignore"
    )
    pooled_clean = (clean["implied_rate"] * clean["capacity_weight_mw"]).sum() / clean[
        "capacity_weight_mw"
    ].sum()

    assert pooled == pytest.approx(0.04041, abs=0.002), (
        f"the pooled cross-provider implied replacement rate moved from the "
        f"pinned 4.041%/yr to {pooled * 100:.3f}%/yr "
        f"(2% is now {REPLACEMENT_CAPEX_RATE / pooled:.3f}x of it). The "
        f"scenarios' lifetimes have changed; re-read the per-provider table "
        f"before trusting replacement_capex_rate={REPLACEMENT_CAPEX_RATE}:\n"
        f"{_table(per_provider)}"
    )
    assert BAND_LOW <= REPLACEMENT_CAPEX_RATE / pooled_clean <= BAND_HIGH, (
        f"dropping {sorted(IMPLAUSIBLE_LIFETIME_PROVIDERS)} no longer brings the "
        f"pooled rate inside the band: {pooled_clean * 100:.3f}%/yr, ratio "
        f"{REPLACEMENT_CAPEX_RATE / pooled_clean:.3f}x. The band miss is then "
        f"NOT attributable to that provider alone and needs a fresh diagnosis."
    )


def test_report_om_against_the_replacement_capex_charge():
    """REPORT ONLY: does IAM O&M already bundle the capital the 2% recharges?

    `include_growth_capex: False` is justified by "IAM O&M already bundles
    annualized capital costs (REMIND/WITCH/POLES)". If that holds, charging
    2% of capital cost per year on top double-counts. This test deliberately
    makes NO claim either way - whether a given IAM's `om_cost` is pure
    operations or operations-plus-capital-recovery is a documented convention
    of that model, not something the numbers can settle. It measures the
    exposure and logs it, and guards only that the ratio remains computable.

    Measured 2026-09-02: WITCH 5.0 2.103x, AIM/CGE 2.2 0.966x, median across
    providers 1.415x, max 9.629x (REMIND-MAgPIE 2.1-4.3). O&M is the same
    order as the replacement charge and usually larger, so any bundling is
    material.
    """
    per_provider = _implied_rates("scenario_provider")
    per_technology = _implied_rates(["scenario_provider", "technology"])

    logger.info(
        "O&M vs %.0f%% replacement CapEx, per provider:\n%s",
        REPLACEMENT_CAPEX_RATE * 100,
        per_provider[["om_over_replacement_capex", "capacity_weight_mw"]]
        .round(4)
        .sort_values("om_over_replacement_capex")
        .to_string(),
    )
    logger.info(
        "Same ratio for the configured run providers, per technology:\n%s",
        per_technology.loc[
            per_technology.index.get_level_values(0).isin(CONFIGURED_PROVIDERS)
        ][["om_over_replacement_capex", "implied_lifetime_years"]]
        .round(4)
        .to_string(),
    )

    ratios = per_provider["om_over_replacement_capex"]
    assert ratios.notna().all() and (ratios > 0).all(), (
        "the O&M / replacement-CapEx ratio stopped being computable, so the "
        f"double-count exposure can no longer be reported:\n{ratios.to_string()}"
    )
