"""The evidence behind dropping replacement CapEx (owner ruling, 2026-09-04).

Until 2026-09-04 the model charged `replacement_capex_rate` (2%/yr) of a real
asset's standing capacity, priced at the year's new-build cost, as roll-over
CapEx. The parameters file justified keeping growth CapEx OFF with "IAM O&M
already bundles annualized capital costs" -- and that argument applies to the
replacement charge just as much. The measured exposure on the staged scenarios
(this file's predecessor, `test_replacement_rate_scenario_alignment.py`, kept
in git history) was O&M at 2.1x the replacement charge for WITCH 5.0 and 1.4x
median across providers, so the overlap was material. The owner's ruling: drop
it, rather than carry a per-technology rate the data cannot support.

This file keeps the data-side half of that reasoning alive as a
characterization: delivered O&M is itself maintenance-scale or larger relative
to build cost for the configured providers, which is what makes "O&M covers
capital upkeep" a defensible reading. It makes no claim about IAM cost
conventions -- that remains a documented convention of each model, and the
owner's call.
"""

import logging
from pathlib import Path

import pandas as pd
import pytest

logger = logging.getLogger(__name__)

SCENARIOS = (
    Path(__file__).resolve().parents[3] / "data" / "05_model_input" / "scenarios.csv"
)

pytestmark = pytest.mark.skipif(
    not SCENARIOS.exists(),
    reason=f"staged scenarios not present at {SCENARIOS}",
)

#: The scenario providers the shipped configurations actually run.
CONFIGURED_PROVIDERS = {"WITCH 5.0": "conf/full", "AIM/CGE 2.2": "conf/base"}

#: Below this share of build cost per year, delivered O&M would be too small to
#: plausibly contain any capital upkeep (pure fixed O&M for most technologies
#: sits at 1-3% of capex per year in utility benchmarks).
MAINTENANCE_SCALE_FLOOR = 0.01

_COLUMNS = [
    "scenario_provider",
    "technology",
    "capacity_additions_mw_per_yr",
    "om_cost_usd_per_mw_per_yr",
    "capital_cost_usd_per_mw",
]


def _om_share_of_capex_by_provider() -> pd.Series:
    """Capacity-weighted om_cost / capital_cost per provider, per year."""
    raw = pd.read_csv(SCENARIOS, usecols=_COLUMNS)
    usable = raw[
        (raw["capacity_additions_mw_per_yr"] > 0) & (raw["capital_cost_usd_per_mw"] > 0)
    ]
    weight = usable["capacity_additions_mw_per_yr"]
    numer = (
        weight * usable["om_cost_usd_per_mw_per_yr"] / usable["capital_cost_usd_per_mw"]
    )
    return (
        numer.groupby(usable["scenario_provider"]).sum()
        / weight.groupby(usable["scenario_provider"]).sum()
    )


def test_delivered_om_is_at_least_maintenance_scale_for_the_configured_providers():
    share = _om_share_of_capex_by_provider()
    logger.info(
        "Delivered O&M as a share of build cost per year, per provider:\n%s",
        share.round(4).sort_values().to_string(),
    )

    missing = set(CONFIGURED_PROVIDERS) - set(share.index)
    assert not missing, (
        f"the configured run providers {sorted(missing)} have no usable rows in "
        f"the staged scenarios ({CONFIGURED_PROVIDERS})"
    )
    configured = share.loc[list(CONFIGURED_PROVIDERS)]
    assert (configured >= MAINTENANCE_SCALE_FLOOR).all(), (
        "delivered O&M has fallen below maintenance scale for a configured "
        "provider, which undercuts the reading that it bundles capital upkeep "
        f"(the basis for dropping replacement CapEx):\n{configured.to_string()}"
    )
