"""Every model-parameter check, in one place, run before any pipeline.

Review of #60 (2026-10-08): allowed values and range checks used to sit in
the node modules that read each switch, so they were scattered across six
files and ran only when that node ran. They live here instead, and
`ParameterChecksHook` runs `check_parameters` once from `before_pipeline_run`
- before the first node of ANY pipeline, including a single stage run on its
own. Nodes no longer re-check their switches.

Each choice selects between behaviours that move published numbers. A typo
used to fall through an `if x == "a": ... else: ...` and silently take the
other arm, so an unknown value is rejected here, naming the conf key and every
legal value.
"""

import logging
from typing import Any

from kedro.framework.hooks import hook_impl

from altr_model._validation import validate_choice

logger = logging.getLogger(__name__)

#: How a NATURAL retirement - age past the technology's lifetime - is dated.
#: The two pathways must use the SAME rule, or natural retirement stops
#: cancelling out of the shock-minus-baseline difference.
RETIREMENT_TIMING_DEFERRED = "deferred_to_window"
RETIREMENT_TIMING_NATURAL = "natural"

#: What decides that an asset is "brown", for the discount spread AND the
#: terminal growth rate alike (owner ruling 13 tied both to one carrier).
SPREAD_CARRIER_TECHNOLOGY = "technology"
SPREAD_CARRIER_ALIGNMENT = "alignment_type"

#: conf key (dotted for nested blocks) -> legal values, the shipped default
#: first where the docs list it first.
CHOICES: dict[str, tuple[str, ...]] = {
    "ownership_aggregation": ("tier_filter", "sum"),
    "carbon_price_fill": ("none", "peer_scenario_median"),
    "capture_price.method": ("none", "hirth2013"),
    "price_floor.method": ("none", "lrmc"),
    "retirement_timing": (RETIREMENT_TIMING_DEFERRED, RETIREMENT_TIMING_NATURAL),
    "carbon_cost_method": ("full_ef", "differential_ef"),
    "dispatch_floor": ("none", "own_variable_cost"),
    "dcf.terminal_value.method": ("none", "perpetuity"),
    "dcf.negative_tv_method": ("perpetuity", "bounded_annuity"),
    "dcf.tv_anchor_policy": ("raw", "operating"),
    "dcf.spread_carrier": (SPREAD_CARRIER_TECHNOLOGY, SPREAD_CARRIER_ALIGNMENT),
}

#: conf key -> (low, high, closed). A closed range accepts its edges.
BOUNDS: dict[str, tuple[float, float, bool]] = {
    "decom_cost_fraction_of_capex": (0.0, 1.0, True),
    "price_floor.discount_rate": (0.0, 1.0, False),
}

#: Ranged keys where null is legal and switches the feature off.
NULLABLE = frozenset({"decom_cost_fraction_of_capex"})

#: On/off switches worth naming in the run log next to the choices.
LOGGED_SWITCHES = (
    "price_ramp",
    "dcf.stranding_aware_tv",
    "company_npv_floor",
)

_MISSING = object()


def _lookup(params: dict, dotted: str) -> Any:
    node: Any = params
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _check_bounds(name: str, value: Any, low: float, high: float, closed: bool) -> None:
    if value is None and name in NULLABLE:
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    inside = low <= number <= high if closed else low < number < high
    if not inside:
        interval = f"[{low}, {high}]" if closed else f"({low}, {high})"
        raise ValueError(f"{name} must lie in {interval}; got {value!r}.")


def check_parameters(params: dict) -> None:
    """Validate the run's parameters and log the active model options.

    A key absent from `params` is skipped: the node that needs it fails on the
    missing key itself. Raises ValueError on the first bad value.
    """
    for name, allowed in CHOICES.items():
        value = _lookup(params, name)
        if value is not _MISSING:
            validate_choice(name, value, allowed)

    for name, (low, high, closed) in BOUNDS.items():
        value = _lookup(params, name)
        if value is not _MISSING:
            _check_bounds(name, value, low, high, closed)

    if _lookup(params, "price_floor.method") == "lrmc" and (
        _lookup(params, "price_floor.discount_rate") is _MISSING
    ):
        raise ValueError(
            "price_floor.discount_rate is required when price_floor.method is "
            "'lrmc' (a real rate within (0, 1), e.g. 0.08)."
        )

    shock_year = _lookup(params, "shock_year")
    alignment_year = _lookup(params, "alignment_year")
    if _MISSING not in (shock_year, alignment_year) and alignment_year < shock_year:
        raise ValueError(
            f"alignment_year ({alignment_year}) cannot be earlier than "
            f"shock_year ({shock_year})."
        )

    active = [
        f"{name}={_lookup(params, name)}"
        for name in (*CHOICES, *LOGGED_SWITCHES)
        if _lookup(params, name) is not _MISSING
    ]
    logger.info("Model options: %s", ", ".join(active))


class ParameterChecksHook:
    """Runs `check_parameters` before the first node of any pipeline."""

    @hook_impl
    def before_pipeline_run(self, catalog: Any) -> None:
        check_parameters(catalog.load("parameters"))
