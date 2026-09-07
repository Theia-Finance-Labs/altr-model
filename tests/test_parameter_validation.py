"""validate_parameters must accept the shipped conf and reject the silent-fallthrough cases."""
import copy
from pathlib import Path

import pytest
import yaml

from crispy_kedro.pipelines.inputs_processing.nodes import PARAMETER_SPEC, validate_parameters

CONF = Path(__file__).resolve().parents[1] / "conf" / "base"


def _conf():
    merged = {}
    for f in sorted(CONF.glob("parameters*.yml")):
        merged.update(yaml.safe_load(f.read_text()) or {})
    return merged


def test_shipped_conf_is_valid():
    validate_parameters(_conf())


def test_spec_covers_every_declared_non_reporting_key():
    def leaves(d, pre=""):
        for k, v in d.items():
            if isinstance(v, dict) and k not in ("mcpr_value_factors", "mcpr_regional_value_factors"):
                yield from leaves(v, pre + k + ".")
            else:
                yield pre + k
    declared = {k for k in leaves(_conf()) if not k.startswith("reporting") and not k.startswith("plot_")}
    declared -= {k for k in declared if k.startswith("mcpr_regional_value_factors")}
    assert declared <= set(PARAMETER_SPEC), sorted(declared - set(PARAMETER_SPEC))


@pytest.mark.parametrize(
    "path, bad, fragment",
    [
        ("carbon_cost_method", "full_EF", "carbon_cost_method"),
        ("dcf.terminal_value.method", "perpetual", "terminal_value.method"),
        ("ownership_type", "Direct", "ownership_type"),
        ("market_passthrough", 1.5, "outside"),
        ("dcf.discount_rate_shock", "7%", "expected"),
        ("shock_year", 2040, "alignment_year"),
        ("staggered_shock.n_quantiles", 0, "outside"),
    ],
)
def test_bad_value_names_the_key(path, bad, fragment):
    p = copy.deepcopy(_conf())
    cur = p
    parts = path.split(".")
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = bad
    with pytest.raises(ValueError, match=fragment):
        validate_parameters(p)


def test_missing_key_is_reported():
    p = copy.deepcopy(_conf())
    del p["enable_mcpr"]
    with pytest.raises(ValueError, match="enable_mcpr: missing"):
        validate_parameters(p)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda p: p["mcpr_value_factors"].__setitem__("WindCap - Onshore", 2.0), "mcpr_value_factors.WindCap - Onshore"),
        (lambda p: p["mcpr_regional_value_factors"]["EU"].__setitem__("SolarCap - PV", 0), "mcpr_regional_value_factors.EU.SolarCap - PV"),
        (lambda p: p["excluded_country_iso2"].append(42), "excluded_country_iso2\\[22\\]"),
        (lambda p: p.__setitem__("mcpr_marginal_technologies", []), "at least one"),
        (lambda p: p.__setitem__("default_capacity_factor", 0), "outside \\(0"),
        (lambda p: p.__setitem__("default_capacity_factor", True), "bool"),
        (lambda p: p.__setitem__("mcpr_markup_factor", 0), "outside \\(0"),
    ],
)
def test_collection_and_open_bound_checks(mutate, fragment):
    p = copy.deepcopy(_conf())
    mutate(p)
    with pytest.raises(ValueError, match=fragment):
        validate_parameters(p)


def test_legitimate_edge_values_accepted():
    p = copy.deepcopy(_conf())
    p["company_ids"] = None
    p["dcf"]["terminal_value"]["g_real_brown"] = None
    p["dcf"]["brown_discount_spread"] = -0.005
    p["max_forecast_horizon"] = 5  # int for a numeric spec
    validate_parameters(p)


def test_hook_runs_validation_before_any_node():
    from crispy_kedro.hooks import ParameterValidationHooks
    from crispy_kedro.settings import HOOKS

    assert any(isinstance(h, ParameterValidationHooks) for h in HOOKS)

    class _Catalog:
        def load(self, name):
            assert name == "parameters"
            p = copy.deepcopy(_conf()); p["carbon_cost_method"] = "typo"; return p

    with pytest.raises(ValueError, match="carbon_cost_method"):
        ParameterValidationHooks().before_pipeline_run({}, None, _Catalog())
