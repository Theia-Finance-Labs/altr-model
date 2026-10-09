"""Central parameter checks (review of #60, 2026-10-08).

Every allowed-value list, numeric range and cross-parameter rule lives in
`altr_model.parameter_checks` and runs once, from a `before_pipeline_run`
hook, before any node - whichever pipeline is run.
"""

import copy
from pathlib import Path

import pytest
from altr_model.parameter_checks import (
    BOUNDS,
    CHOICES,
    ParameterChecksHook,
    check_parameters,
)
from kedro.config import OmegaConfigLoader

CONF = Path(__file__).resolve().parents[2] / "conf"


@pytest.fixture(scope="module")
def shipped() -> dict:
    loader = OmegaConfigLoader(str(CONF), base_env="base", default_run_env="base")
    return loader["parameters"]


def _with(params: dict, dotted: str, value) -> dict:
    out = copy.deepcopy(params)
    node = out
    *parents, leaf = dotted.split(".")
    for part in parents:
        node = node[part]
    node[leaf] = value
    return out


def test_shipped_defaults_pass(shipped):
    check_parameters(shipped)


def test_every_checked_key_exists_in_the_shipped_conf(shipped):
    for dotted in [*CHOICES, *BOUNDS, "shock_year", "alignment_year"]:
        node = shipped
        for part in dotted.split("."):
            assert part in node, f"{dotted} is checked but absent from conf/base"
            node = node[part]


@pytest.mark.parametrize("name", sorted(CHOICES))
def test_an_unknown_choice_raises_naming_the_key(shipped, name):
    with pytest.raises(ValueError, match=name.replace(".", r"\.")):
        check_parameters(_with(shipped, name, "typo"))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("decom_cost_fraction_of_capex", 1.5),
        ("decom_cost_fraction_of_capex", -0.1),
        ("price_floor.discount_rate", 0.0),
        ("price_floor.discount_rate", 1.0),
    ],
)
def test_out_of_range_values_raise(shipped, name, value):
    with pytest.raises(ValueError, match=name.replace(".", r"\.")):
        check_parameters(_with(shipped, name, value))


def test_null_switches_a_ranged_feature_off(shipped):
    check_parameters(_with(shipped, "decom_cost_fraction_of_capex", None))


def test_lrmc_needs_a_discount_rate():
    with pytest.raises(ValueError, match=r"price_floor\.discount_rate"):
        check_parameters({"price_floor": {"method": "lrmc"}})


def test_a_null_rate_is_not_a_switch_off(shipped):
    with pytest.raises(ValueError, match=r"price_floor\.discount_rate"):
        check_parameters(_with(shipped, "price_floor.discount_rate", None))


def test_a_non_numeric_rate_raises(shipped):
    with pytest.raises(ValueError, match=r"price_floor\.discount_rate"):
        check_parameters(_with(shipped, "price_floor.discount_rate", "eight"))


def test_closed_range_accepts_its_edges(shipped):
    check_parameters(_with(shipped, "decom_cost_fraction_of_capex", 0.0))
    check_parameters(_with(shipped, "decom_cost_fraction_of_capex", 1.0))


def test_alignment_year_before_shock_year_raises(shipped):
    params = _with(shipped, "alignment_year", shipped["shock_year"] - 1)
    with pytest.raises(ValueError, match="alignment_year"):
        check_parameters(params)


def test_one_log_line_lists_the_active_options(shipped, caplog):
    with caplog.at_level("INFO", logger="altr_model.parameter_checks"):
        check_parameters(shipped)
    assert "dcf.negative_tv_method=bounded_annuity" in caplog.text
    assert "company_npv_floor=False" in caplog.text


def test_the_hook_checks_the_run_parameters(shipped):
    class Catalog:
        def load(self, name):
            assert name == "parameters"
            return _with(shipped, "retirement_timing", "typo")

    with pytest.raises(ValueError, match="retirement_timing"):
        ParameterChecksHook().before_pipeline_run(catalog=Catalog())


def test_the_hook_is_registered():
    from altr_model import settings

    assert any(isinstance(h, ParameterChecksHook) for h in settings.HOOKS)
