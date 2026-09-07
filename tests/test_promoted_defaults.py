"""Constants promoted from code to conf on 2026-09-06 must keep bit-identical
behaviour: every promoted conf value equals the function default it replaced,
and every `params:` reference in the pipelines resolves."""
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from crispy_kedro.pipelines.distribute_impacts_to_asset_level import nodes as dist
from crispy_kedro.pipelines.earnings_model import nodes as earn
from crispy_kedro.pipelines.inputs_processing import nodes as inp
from crispy_kedro.pipelines.valuation_model import nodes as val

CONF = Path(__file__).resolve().parents[1] / "conf" / "base"


def _params():
    merged = {}
    for f in sorted(CONF.glob("parameters*.yml")):
        merged.update(yaml.safe_load(f.read_text()) or {})
    return merged


def _default(fn, name):
    return inspect.signature(fn).parameters[name].default


@pytest.mark.parametrize(
    "fn, arg, key",
    [
        (earn.compute_flow_based_capex, "replacement_capex_rate", "replacement_capex_rate"),
        (earn.build_scenario_surfaces, "decom_cost_share_of_capex", "decom_cost_share_of_capex"),
        (earn.build_scenario_surfaces, "default_capacity_factor", "default_capacity_factor"),
        (earn.apply_mcpr_adjustment, "mcpr_floor_at_iam_price", "mcpr_floor_at_iam_price"),
        (earn.compute_ops_block, "market_passthrough", "market_passthrough"),
        (dist.compute_asset_baseline_trajectories, "retirement_floor_offset_years", "retirement_floor_offset_years"),
        (dist.stagger_decreasing_technologies, "retirement_floor_offset_years", "retirement_floor_offset_years"),
    ],
)
def test_conf_value_equals_function_default(fn, arg, key):
    assert _params()[key] == _default(fn, arg)


def test_dcf_shock_rate_default_matches_conf():
    assert _params()["dcf"]["discount_rate_shock"] == _default(val.compute_yearly_npv_trajectories, "discount_rate_shock")


def test_excluded_countries_match_historical_list():
    assert _params()["excluded_country_iso2"] == inp.DEFAULT_EXCLUDED_COUNTRY_ISO2
    assert len(inp.DEFAULT_EXCLUDED_COUNTRY_ISO2) == 22


def test_mcpr_defaults_match_in_code_fallbacks():
    """apply_mcpr_adjustment builds fallback dicts when passed None; conf must equal them."""
    import re
    src = inspect.getsource(earn.apply_mcpr_adjustment)
    p = _params()
    code_vf = dict(re.findall(r'"([^"]+)": ([0-9.]+),', src.split("mcpr_value_factors = {")[1].split("}")[0]))
    assert {k: float(v) for k, v in code_vf.items()} == {k: float(v) for k, v in p["mcpr_value_factors"].items()}
    code_techs = re.findall(r'"(\w+)",', src.split("mcpr_marginal_technologies = [")[1].split("]")[0])
    assert code_techs == p["mcpr_marginal_technologies"]


def test_null_capacity_factor_fails_fast():
    df = pd.DataFrame({
        "scenario": ["s"], "scenario_geography": ["g"], "scenario_type": ["baseline"],
        "sector": ["Power"], "technology": ["GasCap"], "year": [2030],
        "scenario_price": [50.0], "fuel_price": [10.0], "scenario_capacity_factor": [np.nan],
        "capital_cost_usd_per_mw": [1e6], "om_cost_usd_per_mw_per_yr": [1e4],
        "carbon_price_usd_per_tco2": [0.0], "lifetime_years": [30], "scenario_pathway": [1.0],
        "efficiency_decimal": [0.5], "capacity_additions_mw_per_yr": [0.0], "scrap_usd_per_mw": [0.0],
    })
    with pytest.raises(ValueError, match="capacity factor"):
        earn.build_scenario_surfaces(df, default_capacity_factor=None)
    out = earn.build_scenario_surfaces(df)  # default 1.0 keeps historical behaviour
    assert out["capacity_factor"].iloc[0] == 1.0
    assert out["scrap_usd_per_mw"].iloc[0] == -5e5


def test_every_params_reference_resolves():
    from kedro.framework.project import pipelines
    from kedro.framework.startup import bootstrap_project
    bootstrap_project(Path(__file__).resolve().parents[1])
    p = _params()
    missing = []
    for name, pl in pipelines.items():
        for node in pl.nodes:
            for i in node.inputs:
                if i.startswith("params:"):
                    cur = p
                    for part in i[len("params:"):].split("."):
                        if not isinstance(cur, dict) or part not in cur:
                            missing.append((name, node.name, i)); break
                        cur = cur[part]
    assert not missing, missing


def test_run_stamp_flattens_nested_params():
    from crispy_kedro.pipelines.reporting.nodes import _flatten_parameters
    df = _flatten_parameters({"dcf": {"discount_rate_shock": 0.07, "terminal_value": {"method": "perpetuity"}}, "company_ids": [], "enable_mcpr": True})
    got = dict(zip(df["parameter"], df["value"]))
    assert got == {"company_ids": "[]", "dcf.discount_rate_shock": 0.07, "dcf.terminal_value.method": "perpetuity", "enable_mcpr": True}
