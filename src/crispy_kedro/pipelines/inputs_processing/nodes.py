"""
This is a boilerplate pipeline 'inputs_processing'
generated using Kedro 0.19.12
"""

import pandas as pd
from typing import List, Tuple
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter validation (run by ParameterValidationHooks.before_pipeline_run in
# src/crispy_kedro/hooks.py, i.e. before any node under any runner).
# One entry per parameter that has a constrained domain. Allowed is either a
# set of legal values, a (lo, hi) inclusive numeric range (None = unbounded),
# or None (type check only). Dotted keys address nested blocks.
# ---------------------------------------------------------------------------
_NUM = (int, float)
# Static VRE value factors above 1 are legitimate at low penetration (Hirth 2013;
# the dynamic formula itself starts at 1.10), so the cap is loose, not 1.0.
VALUE_FACTOR_MAX = 1.5
PARAMETER_SPEC: dict[str, tuple[type | tuple[type, ...], object]] = {
    "baseline_scenario": (str, None),
    "target_scenario": (str, None),
    "company_ids": ((list, type(None)), None),
    "ownership_type": (str, {"direct", "indirect"}),
    "ccs_on": ((bool, type(None)), None),
    "max_forecast_horizon": (int, (1, None)),
    "shock_year": (int, (2000, 2100)),
    "alignment_year": (int, (2000, 2100)),
    "enable_mcpr": (bool, None),
    "mcpr_mode": (str, {"auto", "carbon_explicit", "merit_order_decline"}),
    "mcpr_method": (str, {"marginal_technology"}),
    "mcpr_markup_factor": (_NUM, (0, None, "open")),
    "mcpr_merit_order_alpha": (_NUM, (0, 1)),
    "mcpr_merit_order_floor": (_NUM, (0, 1)),
    "mcpr_floor_at_iam_price": (bool, None),
    "mcpr_marginal_technologies": (list, None),
    "mcpr_value_factors": (dict, None),
    "enable_dynamic_capture_ratios": (bool, None),
    "enable_regional_mcpr_vf": (bool, None),
    "carbon_cost_method": (str, {"full_ef", "differential_ef"}),
    "market_passthrough": (_NUM, (0, 1)),
    "price_ramp": (bool, None),
    "include_growth_capex": (bool, None),
    "include_replacement_capex": (bool, None),
    "include_decom_costs": (bool, None),
    "replacement_capex_rate": (_NUM, (0, 1)),
    "decom_cost_share_of_capex": (_NUM, (0, None)),
    "default_capacity_factor": ((float, int, type(None)), (0, 1, "open")),
    "apply_continued_om_baseline": (bool, None),
    "apply_continued_om_shock": (bool, None),
    "dynamic_marginal_ef": (bool, None),
    "excluded_country_iso2": (list, None),
    "apply_retirement_baseline": (bool, None),
    "apply_retirement_shock": (bool, None),
    "apply_decreasing_staggered_shock": (bool, None),
    "staggered_shock.g_k": (_NUM, (0, None)),
    "staggered_shock.n_quantiles": (int, (1, None)),
    "retirement_floor_offset_years": (int, (0, None)),
    "reduce_granularity_from_asset_to_company_level": (bool, None),
    "dcf.discount_rate_baseline": (_NUM, (0, 1)),
    "dcf.discount_rate_shock": (_NUM, (0, 1)),
    "dcf.brown_discount_spread": (_NUM, (-1, 1)),
    "dcf.green_discount_spread": (_NUM, (-1, 1)),
    "dcf.terminal_value.method": (str, {"perpetuity", "none"}),
    "dcf.terminal_value.g_real_default": (_NUM, (-1, 1)),
    "dcf.terminal_value.g_real_brown": ((*_NUM, type(None)), (-1, 1)),
    "dcf.terminal_value.g_real_green": ((*_NUM, type(None)), (-1, 1)),
    "dcf.terminal_value.normalization_window": (int, (1, None)),
    "dcf.stranding_aware_tv": (bool, None),
    "dcf.stranding_consecutive_years": (int, (1, None)),
    "dcf.brown_remaining_life_years": (int, (1, None)),
}


def _lookup(params: dict, dotted: str):
    cur = params
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def _range_errors(key: str, value, allowed: tuple) -> list[str]:
    """Range check; a third element "open" makes the lower bound exclusive."""
    lo, hi = allowed[0], allowed[1]
    open_lo = len(allowed) > 2 and allowed[2] == "open"
    bad_lo = lo is not None and (value <= lo if open_lo else value < lo)
    bad_hi = hi is not None and value > hi
    if bad_lo or bad_hi:
        return [f"{key}: {value!r} outside {'(' if open_lo else '['}{lo}, {hi}]"]
    return []


def _collection_errors(parameters: dict) -> list[str]:
    """Element-level checks for the list/dict parameters (type checks alone
    would let mcpr_value_factors.X = 2.0 or a non-string country code through)."""
    errors: list[str] = []
    for key in ("mcpr_marginal_technologies", "excluded_country_iso2"):
        for i, item in enumerate(parameters.get(key) or []):
            if not isinstance(item, str) or not item:
                errors.append(f"{key}[{i}]: expected a non-empty string, got {item!r}")
    if not parameters.get("mcpr_marginal_technologies"):
        errors.append("mcpr_marginal_technologies: must name at least one technology")
    for tech, vf in (parameters.get("mcpr_value_factors") or {}).items():
        if isinstance(vf, bool) or not isinstance(vf, _NUM):
            errors.append(f"mcpr_value_factors.{tech}: expected a number, got {vf!r}")
        else:
            errors.extend(_range_errors(f"mcpr_value_factors.{tech}", vf, (0, VALUE_FACTOR_MAX, "open")))
    for geo, techs in (parameters.get("mcpr_regional_value_factors") or {}).items():
        if not isinstance(techs, dict):
            errors.append(f"mcpr_regional_value_factors.{geo}: expected a mapping, got {techs!r}")
            continue
        for tech, vf in techs.items():
            if isinstance(vf, bool) or not isinstance(vf, _NUM):
                errors.append(f"mcpr_regional_value_factors.{geo}.{tech}: expected a number, got {vf!r}")
            else:
                errors.extend(_range_errors(f"mcpr_regional_value_factors.{geo}.{tech}", vf, (0, VALUE_FACTOR_MAX, "open")))
    ids = parameters.get("company_ids")
    if ids and any(not isinstance(c, str) for c in ids):
        errors.append("company_ids: every entry must be a string")
    return errors


def validate_parameters(parameters: dict) -> None:
    """Fail fast on a missing, mistyped or out-of-range parameter.

    Every enum in the model otherwise falls through silently (a typo in
    carbon_cost_method selects the other methodology; a typo in
    terminal_value.method zeroes terminal value; a typo in ownership_type
    empties the universe), so this is the only place a bad value is caught.
    """
    errors: list[str] = []
    for key, (typ, allowed) in PARAMETER_SPEC.items():
        try:
            value = _lookup(parameters, key)
        except KeyError:
            errors.append(f"{key}: missing")
            continue
        if isinstance(value, bool) and bool not in (typ if isinstance(typ, tuple) else (typ,)):
            errors.append(f"{key}: expected a number, got bool {value!r}")
            continue
        if not isinstance(value, typ):
            errors.append(f"{key}: expected {typ}, got {type(value).__name__} {value!r}")
            continue
        if allowed is None or value is None:
            continue
        if isinstance(allowed, set):
            if value not in allowed:
                errors.append(f"{key}: {value!r} not in {sorted(allowed)}")
        else:
            errors.extend(_range_errors(key, value, allowed))
    errors.extend(_collection_errors(parameters))
    if not errors and parameters["alignment_year"] <= parameters["shock_year"]:
        errors.append(
            f"alignment_year ({parameters['alignment_year']}) must be greater than "
            f"shock_year ({parameters['shock_year']})"
        )
    if errors:
        raise ValueError("Invalid parameters:\n  " + "\n  ".join(errors))
    logger.info("Parameters validated: %d keys checked", len(PARAMETER_SPEC))


def check_input_parameters(
    shock_year: int,
    alignment_year: int,
) -> None:
    """Superseded by validate_parameters (run via ParameterValidationHooks.before_pipeline_run
    since 2026-09-06); kept for direct callers, no longer wired in any pipeline."""

    if alignment_year < shock_year:
        raise ValueError("Alignment year must be greater than shock year")


def filter_scenarios(
    scenarios_pathways: pd.DataFrame, target_scenario: str, baseline_scenario: str
) -> pd.DataFrame:
    """
    Keep only the baseline and target scenario rows, tagging each as its trajectory type.

    Parameters
    ----------
    scenarios_pathways : pd.DataFrame
        Raw downloaded AR6 scenario pathways (catalog input, not a conf key).
    target_scenario : str
        IAM scenario the late-sudden shock converges to; exact scenario name as
        "AR6_<provider>_<scenario>" (the "AR6_<provider>_" prefix is prepended if
        missing, no match raises). Must share provider, geographies and
        sector/technology coverage with the baseline. Conf key
        `params:target_scenario` (conf/base/parameters.yml).
    baseline_scenario : str
        IAM scenario used as the no-transition reference pathway; same naming rule as
        target_scenario. Conf key `params:baseline_scenario` (conf/base/parameters.yml).

    Returns
    -------
    pd.DataFrame
        The two selected scenarios with harmonised names.
    """

    # Standardize scenario naming
    # TODO: remove after integration of scenario data in DBT
    # Only add prefix to rows that don't already have it (idempotent)
    needs_prefix = ~scenarios_pathways["scenario"].astype(str).str.startswith("AR6_")
    if needs_prefix.any():
        scenarios_pathways.loc[needs_prefix, "scenario"] = (
            "AR6_"
            + scenarios_pathways.loc[needs_prefix, "scenario_provider"].astype(str).str.strip()
            + "_"
            + scenarios_pathways.loc[needs_prefix, "scenario"].astype(str).str.strip()
        )

    scenarios_pathways.loc[
        scenarios_pathways["scenario_geography"] == "Global", "country_iso2_list"
    ] = np.nan

    # NOTE: Removed WindCap transformation - keeping WindCap - Onshore and WindCap - Offshore
    # as-is to match with asset data

    assert (
        target_scenario
        in scenarios_pathways[
            scenarios_pathways["scenario_type"] == "target"
        ].scenario.unique()
    ), "Target scenario not found in scenarios pathways"
    assert (
        baseline_scenario
        in scenarios_pathways[
            scenarios_pathways["scenario_type"] == "baseline"
        ].scenario.unique()
    ), "Baseline scenario not found in scenarios pathways"

    baseline_geographies = set(
        scenarios_pathways[scenarios_pathways["scenario"] == baseline_scenario][
            "scenario_geography"
        ].unique()
    )
    target_geographies = set(
        scenarios_pathways[scenarios_pathways["scenario"] == target_scenario][
            "scenario_geography"
        ].unique()
    )

    # Find common geographies between baseline and target scenarios
    common_geographies = baseline_geographies.intersection(target_geographies)

    # Check if there are any differences and warn if so
    if baseline_geographies != target_geographies:
        baseline_only = baseline_geographies - target_geographies
        target_only = target_geographies - baseline_geographies

        logger.warning(
            f"Geographies in baseline scenario ({baseline_geographies}) do not match "
            f"geographies in target scenario ({target_geographies}). "
            f"Baseline-only geographies: {baseline_only}. "
            f"Target-only geographies: {target_only}. "
            f"Filtering to common geographies: {common_geographies}"
        )

    # Filter scenarios_pathways to only include common geographies
    scenarios_pathways = scenarios_pathways[
        scenarios_pathways["scenario_geography"].isin(common_geographies)
    ]

    # Create sector+technology combinations for baseline and target scenarios
    baseline_sector_tech = set(
        scenarios_pathways[scenarios_pathways["scenario"] == baseline_scenario].apply(
            lambda row: (row["sector"], row["technology"]), axis=1
        )
    )
    target_sector_tech = set(
        scenarios_pathways[scenarios_pathways["scenario"] == target_scenario].apply(
            lambda row: (row["sector"], row["technology"]), axis=1
        )
    )

    # Find common sector+technology combinations
    common_sector_tech = baseline_sector_tech.intersection(target_sector_tech)

    # Check if there are any differences and warn if so
    if baseline_sector_tech != target_sector_tech:
        baseline_only = baseline_sector_tech - target_sector_tech
        target_only = target_sector_tech - baseline_sector_tech

        logger.warning(
            f"Sector+Technology combinations in baseline scenario do not match "
            f"those in target scenario. "
            f"Baseline-only combinations: {baseline_only}. "
            f"Target-only combinations: {target_only}. "
            f"Filtering to common combinations: {common_sector_tech}"
        )

    # Filter scenarios_pathways to only include common sector+technology combinations
    scenarios_pathways = scenarios_pathways[
        scenarios_pathways.apply(
            lambda row: (row["sector"], row["technology"]) in common_sector_tech, axis=1
        )
    ]

    scenarios_pathways_filtered = scenarios_pathways.loc[
        scenarios_pathways.scenario.isin([target_scenario, baseline_scenario]), :
    ].reset_index(drop=True)

    scenarios_pathways_filtered = scenarios_pathways_filtered.reset_index(drop=True)

    scenarios_pathways_filtered.loc[:, "scenario_pathway"] = (
        scenarios_pathways_filtered.loc[:, "scenario_pathway"].astype(float)
    )

    scenarios_pathways_filtered = scenarios_pathways_filtered.rename(
        columns={"scenario_year": "year"}
    )
    return scenarios_pathways_filtered


def filter_companies(
    companies_ownership_tree: pd.DataFrame,
    company_ids: List[str],
    ownership_type: str,
) -> pd.DataFrame:
    """
    Restrict the ownership tree to the requested companies and ownership links.

    Parameters
    ----------
    companies_ownership_tree : pd.DataFrame
        Raw downloaded plant-ownership links (catalog input, not a conf key).
    company_ids : List[str]
        Restrict the run to these company ids; list of company_id strings, empty list
        = all companies. Conf key `params:company_ids` (conf/base/parameters.yml).
    ownership_type : str
        Which ownership links attach assets to companies: "direct" (ownership_level 1)
        or "indirect" (level >= 2); anything else silently yields an empty universe.
        Conf key `params:ownership_type` (conf/base/parameters.yml).

    Returns
    -------
    pd.DataFrame
        The filtered ownership tree.
    """

    # Filter by ownership type/level.
    # The BigQuery schema changed: 'ownership_type' (str: "direct"/"indirect")
    # was replaced by 'ownership_level' (int: 1=direct, 2+=indirect).
    # Handle both schemas gracefully.
    if "ownership_type" in companies_ownership_tree.columns:
        companies_owners = companies_ownership_tree[
            companies_ownership_tree["ownership_type"] == ownership_type
        ]
    elif "ownership_level" in companies_ownership_tree.columns:
        # Map ownership_type string to level: "direct" → 1, "indirect" → 2+
        level = 1 if ownership_type == "direct" else 2
        if ownership_type == "direct":
            companies_owners = companies_ownership_tree[
                companies_ownership_tree["ownership_level"] == level
            ]
        else:
            companies_owners = companies_ownership_tree[
                companies_ownership_tree["ownership_level"] >= level
            ]
        logger.info(
            "Using ownership_level=%s for ownership_type='%s' (%s rows)",
            level, ownership_type, len(companies_owners),
        )
    else:
        logger.warning(
            "Neither 'ownership_type' nor 'ownership_level' found in companies data. "
            "Using all rows."
        )
        companies_owners = companies_ownership_tree

    # Rename production_year → year for downstream consistency
    companies_owners = companies_owners.rename(columns={"production_year": "year"})

    if company_ids:
        filtered_companies_ownership_tree = companies_owners.loc[
            companies_owners.company_id.isin(company_ids), :
        ].reset_index(drop=True)
    else:
        filtered_companies_ownership_tree = companies_owners

    # Consolidate multiple ownership paths through different subsidiaries.
    # The new BigQuery schema has one row per (asset, company, year, child_company),
    # so the same parent company can appear multiple times for the same asset-year.
    # Sum ownership_percentage across paths to get the parent's total ownership.
    group_keys = ["asset_id", "company_id", "company_name", "year"]
    if "ownership_level" in filtered_companies_ownership_tree.columns:
        group_keys.append("ownership_level")
    elif "ownership_type" in filtered_companies_ownership_tree.columns:
        group_keys.append("ownership_type")

    available_keys = [
        k for k in group_keys if k in filtered_companies_ownership_tree.columns
    ]
    pre_count = len(filtered_companies_ownership_tree)
    filtered_companies_ownership_tree = (
        filtered_companies_ownership_tree.groupby(available_keys, as_index=False)
        .agg(ownership_percentage=("ownership_percentage", "sum"))
    )
    post_count = len(filtered_companies_ownership_tree)
    if pre_count != post_count:
        logger.info(
            "Consolidated %s ownership paths → %s unique (asset, company, year) rows",
            pre_count,
            post_count,
        )

    return filtered_companies_ownership_tree


def apply_ccs_suffix(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
    ccs_on: bool | None,
) -> pd.DataFrame:
    """
    Suffix asset and ownership technologies with the requested CCS variant.

    Parameters
    ----------
    assets_forecasts : pd.DataFrame
        Raw downloaded asset-level forecasts (catalog input, not a conf key).
    companies_ownership_tree : pd.DataFrame
        Filtered ownership tree (catalog input, not a conf key).
    scenarios_pathways : pd.DataFrame
        Filtered scenario pathways, used to detect whether CCS variants exist
        (catalog input, not a conf key).
    ccs_on : bool or None
        Which CCS variant of coal/gas/biomass/oil scenarios to use: True = "w/ CCS",
        False = "w/o CCS", None = no distinction (returns the inputs unchanged).
        Conf key `params:ccs_on` (conf/base/parameters.yml).

    Returns
    -------
    tuple of pd.DataFrame
        (assets_forecasts, companies_ownership_tree) with CCS suffixes applied.
    """
    if (
        not any(
            " - w/ CCS" in tech for tech in scenarios_pathways["technology"].unique()
        )
        and not any(
            " - w/o CCS" in tech for tech in scenarios_pathways["technology"].unique()
        )
    ) or ccs_on is None:
        logger.warning("No CCS technologies are present in the assets forecasts")
        return assets_forecasts, companies_ownership_tree

    if (
        not any(
            " - w/ CCS" in tech for tech in scenarios_pathways["technology"].unique()
        )
        and ccs_on
    ):
        raise ValueError(
            "With CCS technologies are not present in the scenarios pathways"
        )
    if (
        not any(
            " - w/o CCS" in tech for tech in scenarios_pathways["technology"].unique()
        )
        and not ccs_on
    ):
        raise ValueError(
            "Without CCS technologies are not present in the scenarios pathways"
        )

    ccs_technologies_mask_assets = assets_forecasts["technology"].isin(
        ["BiomassCap", "CoalCap", "GasCap", "OilCap"]
    )
    # Apply CCS suffix to assets
    suffix = " - w/ CCS" if ccs_on else " - w/o CCS"
    assets_forecasts.loc[ccs_technologies_mask_assets, "technology"] = (
        assets_forecasts.loc[ccs_technologies_mask_assets, "technology"] + suffix
    )

    # Apply CCS suffix to companies if technology column exists
    # (newer BigQuery schema may not include technology on the ownership table)
    if "technology" in companies_ownership_tree.columns:
        ccs_technologies_mask_companies = companies_ownership_tree["technology"].isin(
            ["BiomassCap", "CoalCap", "GasCap", "OilCap"]
        )
        companies_ownership_tree.loc[ccs_technologies_mask_companies, "technology"] = (
            companies_ownership_tree.loc[ccs_technologies_mask_companies, "technology"]
            + suffix
        )

    return assets_forecasts, companies_ownership_tree


DEFAULT_EXCLUDED_COUNTRY_ISO2 = ['AS', 'BM', 'AW', 'SZ', 'FO', 'CW', 'DM', 'GF', 'PS', 'KN', 'MK', 'IM', 'PM', 'XK', 'SC', 'SS', 'AX', 'KY', 'BQ', 'GG', 'MS', 'JE']


def filter_assets(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
    max_forecast_horizon: int,
    excluded_country_iso2: list[str] | None = None,
) -> pd.DataFrame:
    """
    Drop assets outside the modelled universe, horizon and country scope.

    Parameters
    ----------
    assets_forecasts : pd.DataFrame
        Asset-level forecasts after the CCS suffixing (catalog input, not a conf key).
    companies_ownership_tree : pd.DataFrame
        Ownership tree defining which assets are owned (catalog input, not a conf key).
    scenarios_pathways : pd.DataFrame
        Filtered scenario pathways, used for the technology/geography scope
        (catalog input, not a conf key).
    max_forecast_horizon : int
        Years of asset-level GEM forecast kept before scenario pathways take over;
        integer years >= 1. Conf key `params:max_forecast_horizon`
        (conf/base/parameters.yml).
    excluded_country_iso2 : list[str] or None
        Assets whose country_iso2 is in this list are dropped (as are assets with no
        country); list of ISO 3166-1 alpha-2 codes, [] disables the filter. None falls
        back to DEFAULT_EXCLUDED_COUNTRY_ISO2 (the historical NGFS hard-fix). Conf key
        `params:excluded_country_iso2` (conf/base/parameters_inputs_processing.yml).

    Returns
    -------
    pd.DataFrame
        The filtered asset forecasts.
    """

    # Assets in excluded_country_iso2 are dropped (conf key; the default list
    # is the historical NGFS hard-fix, kept for direct callers).
    if excluded_country_iso2 is None:
        excluded_country_iso2 = DEFAULT_EXCLUDED_COUNTRY_ISO2
    assets_forecasts = assets_forecasts.loc[
        ~assets_forecasts.country_iso2.isna()
        & ~assets_forecasts.country_iso2.isin(excluded_country_iso2),
        :,
    ]

    # NOTE: Removed WindCap transformation - keeping WindCap - Onshore and WindCap - Offshore
    # as-is to match with scenario data which has WindCap - Onshore

    owned_assets = companies_ownership_tree["asset_id"].unique().tolist()
    filtered_assets_forecasts = assets_forecasts.loc[
        assets_forecasts["asset_id"].isin(owned_assets), :
    ]

    both_scenario_start_year = (
        scenarios_pathways.groupby("scenario_type")["year"].min().to_dict()
    )
    assert (
        both_scenario_start_year["baseline"] == both_scenario_start_year["target"]
    ), "Baseline and target scenarios start at different years"
    scenario_start_year = both_scenario_start_year["baseline"]
    forecast_end_year = scenario_start_year + max_forecast_horizon

    filtered_assets_forecasts = filtered_assets_forecasts.loc[
        (scenario_start_year <= filtered_assets_forecasts.production_year)
        & (filtered_assets_forecasts.production_year <= forecast_end_year),
        :,
    ]

    # Log how many unique assets we have
    unique_assets = len(filtered_assets_forecasts["asset_id"].unique())
    print(
        f"Found {unique_assets:,} unique assets after filtering by ownership and time range"
    )

    # Check that we have assets remaining
    if filtered_assets_forecasts.empty:
        raise ValueError("No assets remaining after filtering")

    filtered_assets_forecasts = filtered_assets_forecasts.rename(
        {"production_year": "year"}, axis=1
    )
    filtered_assets_forecasts.loc[:, "capacity"] = filtered_assets_forecasts.loc[
        :, "capacity"
    ].astype(float)

    return filtered_assets_forecasts


def assign_scenario_geographies_to_assets(
    assets_forecasts: pd.DataFrame, scenarios_pathways: pd.DataFrame
) -> pd.DataFrame:
    """Assign scenario geographies to assets based on country mapping.

    If a country maps to multiple scenario geographies, pick the geography with the
    smallest number of countries (most granular). If there is a tie for smallest,
    raise an error listing the conflicting geographies and the asset+country pair(s).
    """
    # Build mapping of scenario geographies to individual countries
    geographies_to_countries_mapping = (
        scenarios_pathways[["scenario_geography", "country_iso2_list"]]
        .drop_duplicates()
        .assign(
            country_iso2_list=lambda x: x.country_iso2_list.astype(str).str.split(",")
        )
        .explode("country_iso2_list")
        .rename(columns={"country_iso2_list": "country_iso2"})
    )

    geographies_to_countries_mapping.loc[
        geographies_to_countries_mapping["country_iso2"] == "nan", "country_iso2"
    ] = None

    # Count how many countries each geography contains (NaNs are excluded from the count)
    geography_sizes = (
        geographies_to_countries_mapping.groupby("scenario_geography", as_index=False)[
            "country_iso2"
        ]
        .count()
        .rename(columns={"country_iso2": "geography_country_count"})
    )

    # Determine best (most granular) geography per asset+country pair
    asset_country_pairs = assets_forecasts[
        ["asset_id", "country_iso2"]
    ].drop_duplicates()

    asset_country_candidates = asset_country_pairs.merge(
        geographies_to_countries_mapping, on="country_iso2", how="left"
    ).merge(geography_sizes, on="scenario_geography", how="left")

    # For each asset+country, find the minimum country count among candidate geographies
    min_counts = asset_country_candidates.groupby(["asset_id", "country_iso2"])[
        "geography_country_count"
    ].transform("min")

    is_min = asset_country_candidates["geography_country_count"].eq(min_counts)

    # Detect ties: more than one candidate with the same minimum count for a given asset+country
    tie_counts = (
        asset_country_candidates[is_min]
        .groupby(["asset_id", "country_iso2"], as_index=False)
        .size()
        .rename(columns={"size": "num_min_candidates"})
    )

    ambiguous_pairs = tie_counts.query("num_min_candidates > 1")
    if not ambiguous_pairs.empty:
        conflict_messages = []
        for _, row in ambiguous_pairs.iterrows():
            aid = row["asset_id"]
            ctry = row["country_iso2"]
            candidates = asset_country_candidates[
                (asset_country_candidates["asset_id"] == aid)
                & (asset_country_candidates["country_iso2"] == ctry)
                & is_min
            ][["scenario_geography", "geography_country_count"]]
            candidates_list = candidates.apply(
                lambda r: f"{r['scenario_geography']} (n={int(r['geography_country_count'])})",
                axis=1,
            ).tolist()
            conflict_messages.append(
                f"asset_id={aid}, country={ctry}: conflicting geographies {candidates_list}"
            )
        conflict_text = "\n".join(conflict_messages)
        raise ValueError(
            "Ambiguous scenario geography assignment detected. "
            "Multiple geographies tie for most granular: \n" + conflict_text
        )

    # Select the unique most granular geography per asset+country
    selected_geographies = (
        asset_country_candidates[is_min]
        .drop_duplicates(["asset_id", "country_iso2"])  # ensure one per pair
        .loc[:, ["asset_id", "country_iso2", "scenario_geography"]]
    )

    # Merge the chosen geography back to all asset rows
    assets_with_geography = assets_forecasts.merge(
        selected_geographies, on=["asset_id", "country_iso2"], how="left"
    )

    # Fallback: Assign unassigned assets to a global geography (if defined with NaN country list)
    unassigned_mask = assets_with_geography["scenario_geography"].isna()

    if unassigned_mask.sum() > 0:
        global_geographies = geographies_to_countries_mapping[
            geographies_to_countries_mapping["country_iso2"].isna()
        ]["scenario_geography"].unique()

        if len(global_geographies) > 0:
            global_geography = global_geographies[0]
            print(
                f"Assigning {unassigned_mask.sum()} unassigned assets to global geography: {global_geography}"
            )
            assets_with_geography.loc[unassigned_mask, "scenario_geography"] = (
                global_geography
            )

    assert (
        assets_with_geography["scenario_geography"].isna().sum() == 0
    ), "Some assets are not assigned to a scenario geography"

    return assets_with_geography


def allocate_assets_to_companies(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:
    """
    Allocate asset capacities to companies based on ownership percentages.

    For company-asset combinations that start after the scenario start year,
    backfill their capacity with zeros back to the scenario start year.

    This function joins assets with company ownership data and calculates
    the owned asset capacity based on ownership percentages.

    Args:
        assets_forecasts: DataFrame with asset information and capacities
        companies_ownership_tree: DataFrame with company ownership information
        scenarios_pathways: DataFrame with scenario data to determine start year

    Returns:
        DataFrame with allocated asset capacities to companies
    """

    # Get scenario start year for backfilling
    scenario_start_year = scenarios_pathways.year.min()

    # Prepare assets data
    assets_prepared = assets_forecasts.copy()

    # Prepare companies data
    companies_prepared = companies_ownership_tree.copy()

    # Merge assets with ownership data.
    # The join keys depend on which columns exist in the companies table.
    # Newer BigQuery schema only has: asset_id, company_id, company_name,
    # ownership_level, production_year, ownership_percentage.
    possible_keys = ["asset_id", "sector", "technology", "year"]
    actual_keys = [k for k in possible_keys if k in companies_prepared.columns]
    if not actual_keys:
        raise ValueError("No common columns between assets and companies for merge")
    logger.info("Merging assets with companies on: %s", actual_keys)

    merged_data = pd.merge(
        assets_prepared,
        companies_prepared,
        on=actual_keys,
        how="inner",
    )

    # Identify company-asset-technology combinations that need backfilling
    company_asset_tech_first_years = merged_data.groupby(
        ["company_id", "asset_id", "technology"]
    )["year"].min()

    combinations_needing_backfill = company_asset_tech_first_years[
        company_asset_tech_first_years > scenario_start_year
    ]

    # Create backfill records for company-asset combinations that start after scenario start
    backfill_records = []

    for (
        company_id,
        asset_id,
        technology,
    ), first_year in combinations_needing_backfill.items():
        # Get a template record for this company-asset-technology combination
        template_record = (
            merged_data[
                (merged_data["company_id"] == company_id)
                & (merged_data["asset_id"] == asset_id)
                & (merged_data["technology"] == technology)
            ]
            .iloc[0]
            .copy()
        )

        # Create records for missing years with zero capacity
        for year in range(scenario_start_year, int(first_year)):
            backfill_record = template_record.copy()
            backfill_record["year"] = year
            backfill_record["capacity"] = 0.0
            backfill_records.append(backfill_record)

    if backfill_records:
        backfill_df = pd.DataFrame(backfill_records)
        merged_data = pd.concat([merged_data, backfill_df], ignore_index=True)
        print(
            f"Backfilled {len(backfill_records)} company-asset-year records with zero capacity"
        )

    # Calculate owned asset capacity (allocated capacity based on ownership
    # percentage). ownership_percentage is on the 0-100 scale -- the tier
    # selected upstream sums to ~100 per asset-year (see check_ownership_tier in
    # notebooks/prepare_new_inputs.py) -- so divide by 100 to get the fraction.
    max_ownership = merged_data["ownership_percentage"].max()
    if pd.notna(max_ownership) and max_ownership <= 1.5:
        raise ValueError(
            f"ownership_percentage looks like a 0-1 fraction (max={max_ownership}), "
            "not the expected 0-100 percent scale; dividing by 100 would shrink "
            "allocated capacity ~100x. Check the ownership extract's scale convention."
        )

    raw_capacity_total = merged_data["capacity"].sum()
    merged_data["capacity"] = (
        merged_data["capacity"] * merged_data["ownership_percentage"] / 100.0
    )
    logger.info(
        "Ownership allocation: raw capacity total %.1f -> allocated %.1f (ratio %.3f)",
        raw_capacity_total,
        merged_data["capacity"].sum(),
        merged_data["capacity"].sum() / raw_capacity_total if raw_capacity_total else float("nan"),
    )

    merged_data = merged_data.rename(columns={"capacity": "asset_activity"})

    return merged_data


def determine_increasing_or_decreasing_techs(
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    # 1) Compute which techs are “increasing” (low‑carbon) vs “decreasing”:
    target_only = scenarios_pathways.query("scenario_type == 'target'")
    sorted_by_year = target_only.sort_values("year")
    tech_first_last = sorted_by_year.groupby(["technology", "scenario_geography"])[
        "scenario_pathway"
    ].agg(first="first", last="last")
    tech_first_last.loc[:, "increasing"] = (
        tech_first_last["last"] > tech_first_last["first"]
    )

    tech_trend = tech_first_last.loc[:, ["increasing"]].reset_index()

    return tech_trend


def determine_lifetime_per_technology(
    scenarios_pathways: pd.DataFrame,
) -> pd.DataFrame:

    unique_combinations = (
        scenarios_pathways.loc[
            scenarios_pathways["scenario_type"] == "target",
            ["sector", "technology", "lifetime_years"],
        ]
        .dropna(subset=["lifetime_years"])
        .groupby(["sector", "technology"])
        .agg({"lifetime_years": lambda x: np.ceil(x.mean()).astype(int)})
        .reset_index()
    )

    return unique_combinations


def interpolate_scenarios_annually(scenarios_pathways: pd.DataFrame) -> pd.DataFrame:
    """
    Interpolate scenario data to fill missing years with linear interpolation and extend
    to the maximum year across the entire dataset using constant values.

    This is a temporary fix to handle the fact that downloaded_scenarios.csv contains
    5-year interval data but the late_sudden trajectory algorithms expect annual data.

    Args:
        scenarios_pathways: DataFrame with scenario data (potentially sparse years)

    Returns:
        DataFrame with annually interpolated scenario data extended to max year
    """

    # Main grouping columns for interpolation (keeping it simple)
    group_cols = [
        "scenario",
        "scenario_type",
        "scenario_geography",
        "sector",
        "technology",
    ]

    # Numeric columns that should be interpolated
    numeric_cols = [
        "scenario_price",
        "fuel_price",
        "scenario_pathway",
        "scenario_capacity_factor",
        "lifetime_years",
        "carbon_price_usd_per_tco2",
    ]
    existing_numeric_cols = [
        col for col in numeric_cols if col in scenarios_pathways.columns
    ]

    # Get the maximum year across the entire dataset
    global_max_year = int(scenarios_pathways["year"].max())

    interpolated_scenarios = []

    # Group by main identifiers and interpolate within each group
    for _, group_df in scenarios_pathways.groupby(group_cols, dropna=False):
        group_df = group_df.sort_values("year").copy()

        # Get the year range for this group
        min_year = int(group_df["year"].min())
        group_max_year = int(group_df["year"].max())

        # Create annual year range extending to global max year
        annual_years = list(range(min_year, global_max_year + 1))

        # Create base template with first row's non-numeric values
        template_row = group_df.iloc[0].copy()

        # Create rows for each year
        annual_data = []
        for year in annual_years:
            row = template_row.copy()
            row["year"] = year
            annual_data.append(row)

        annual_df = pd.DataFrame(annual_data)

        # Merge with original data to get actual values where they exist
        merged_df = annual_df.merge(
            group_df[group_cols + ["year"] + existing_numeric_cols],
            on=group_cols + ["year"],
            how="left",
            suffixes=("", "_actual"),
        )

        # Replace interpolated numeric columns with actual values
        for col in existing_numeric_cols:
            actual_col = f"{col}_actual"
            if actual_col in merged_df.columns:
                merged_df[col] = merged_df[actual_col]
                merged_df.drop(columns=[actual_col], inplace=True)

        # Interpolate missing values within the original range
        for col in existing_numeric_cols:
            if col in merged_df.columns:
                merged_df[col] = pd.to_numeric(merged_df[col], errors="coerce")
                # Only interpolate within the original data range
                original_range_mask = (merged_df["year"] >= min_year) & (
                    merged_df["year"] <= group_max_year
                )
                merged_df.loc[original_range_mask, col] = merged_df.loc[
                    original_range_mask, col
                ].interpolate(method="linear")

                # For years beyond the group's max year, extend with the last known value
                if group_max_year < global_max_year:
                    last_known_value = merged_df.loc[
                        merged_df["year"] == group_max_year, col
                    ].iloc[0]
                    if not pd.isna(last_known_value):
                        extension_mask = merged_df["year"] > group_max_year
                        merged_df.loc[extension_mask, col] = last_known_value

        interpolated_scenarios.append(merged_df)

    # Combine all groups
    if interpolated_scenarios:
        result = pd.concat(interpolated_scenarios, ignore_index=True)
        result["year"] = result["year"].astype(int)
        return result
    else:
        return scenarios_pathways  # Return original if no interpolation was possible


def scale_electricity_price(
    scenarios_pathways: pd.DataFrame, theta: float = 1.0
) -> pd.DataFrame:
    """
    Adjust electricity prices per technology and year so that:
      - each tech covers SRMC + θ*(FOM/MWh + α*CapAnn/MWh)
      - energy-weighted mean price equals the original average price

    NOTE: the body below is commented out — this node is a pass-through and
    returns `scenarios_pathways` unchanged (no `scenario_price_scaled` column).

    Parameters
    ----------
    scenarios_pathways : pd.DataFrame
        Must include:
        ['scenario', 'year', 'scenario_geography',
         'scenario_price', 'fuel_price', 'efficiency_decimal',
         'om_cost_usd_per_mw_per_yr', 'capital_cost_usd_per_mw',
         'scenario_capacity_factor', 'scenario_pathway',   # in MW!
         'capacity_additions_mw_per_yr', 'lifetime_years']
    theta : float, optional
        Fraction of fixed + capex recovery via energy (default = 1.0)

    Returns
    -------
    pd.DataFrame
        Same as input, with new column 'scenario_price_scaled'.
    """

    # df = scenarios_pathways.copy()
    # hours_per_year = 8760

    # # --- Core costs per MWh ---
    # df["srmc"] = df["fuel_price"] / df["efficiency_decimal"]
    # # df["srmc"] = df["fuel_intensity"]

    # df["fom_per_mwh"] = df["om_cost_usd_per_mw_per_yr"] / (
    #     hours_per_year * df["scenario_capacity_factor"]
    # )

    # df["capann_per_mwh"] = (df["capital_cost_usd_per_mw"] / df["lifetime_years"]) / (
    #     hours_per_year * df["scenario_capacity_factor"]
    # )

    # # --- Build share α = ΔK / K ---
    # df["fleet_capacity_mw"] = df["scenario_pathway"]  # already MW
    # df["alpha_build"] = (
    #     df["capacity_additions_mw_per_yr"].fillna(0) / df["fleet_capacity_mw"]
    # )
    # df["alpha_build"] = df["alpha_build"].clip(lower=0, upper=1)

    # # --- Breakeven target price ---
    # df["target_price"] = (
    #     df["srmc"] + theta * df["fom_per_mwh"]  # + theta * df["capann_per_mwh"]
    # )
    # # + theta * df["capann_per_mwh"]

    # # --- Energy weights (now in MWh) ---
    # df["E"] = df["scenario_pathway"] * df["scenario_capacity_factor"] * hours_per_year

    # # --- Normalize per (scenario, year, geography) ---
    # def normalize_group(g):
    #     w = g["E"] / g["E"].sum()
    #     P_avg = g["scenario_price"].mean()
    #     P = g["target_price"]

    #     r = P_avg / (w * P).sum()
    #     P_scaled = r * P

    #     pinned = P_scaled < g["target_price"]
    #     if pinned.any():
    #         P_scaled[pinned] = g.loc[pinned, "target_price"]
    #         free = ~pinned
    #         if free.any():
    #             r = (P_avg - (w[pinned] * P_scaled[pinned]).sum()) / (
    #                 w[free] * P_scaled[free]
    #             ).sum()
    #             P_scaled[free] *= r

    #     g["scenario_price_scaled"] = P_scaled
    #     return g

    # df = (
    #     df.groupby(["scenario", "year", "scenario_geography"], group_keys=False)
    #     .apply(normalize_group)
    #     .reset_index(drop=True)
    # )
    # df["scenario_price_scaled"] = np.where(
    #     df["scenario_capacity_factor"] == 0,
    #     0,  # df["scenario_price"],
    #     df["scenario_price_scaled"],
    # )
    # return df

    return scenarios_pathways


def inject_carbon_prices(
    scenarios_pathways: pd.DataFrame,
    ar6_carbon_prices: pd.DataFrame,
) -> pd.DataFrame:
    """
    Inject carbon prices from the AR6 scenario database into the scenario pathways.

    Carbon price treatment depends on the IAM:
    - IAMs that report explicit carbon prices (e.g., WITCH 5.0): these are merged
      directly. The ALTR earnings model applies them as a DIFFERENTIAL carbon cost
      (excess above the marginal generator's emission factor) to avoid double-counting
      with the AR6 electricity price, which already includes carbon effects per the
      IAMC variable template.
    - IAMs that do NOT report carbon prices (e.g., AIM/CGE 2.2): carbon_price stays
      at 0. Their electricity prices already embed carbon effects through general
      equilibrium dynamics (CGE models capture fuel price shifts, capital composition
      changes, and demand response endogenously).

    Parameters
    ----------
    scenarios_pathways : pd.DataFrame
        Scenario data with columns including scenario, scenario_geography, year,
        and carbon_price_usd_per_tco2 (possibly all NaN).
    ar6_carbon_prices : pd.DataFrame
        AR6 scenario database extract with columns: scenario_provider, scenario,
        scenario_geography, scenario_year, carbon_price_usd_per_tco2.

    Returns
    -------
    pd.DataFrame
        scenarios_pathways with carbon_price_usd_per_tco2 populated where available.
    """
    df = scenarios_pathways.copy()

    # Ensure column exists
    if "carbon_price_usd_per_tco2" not in df.columns:
        df["carbon_price_usd_per_tco2"] = np.nan

    # Check if carbon prices are already populated
    existing_cp = df["carbon_price_usd_per_tco2"].notna().sum()
    if existing_cp > 0:
        logger.info(
            "Carbon prices already populated for %s/%s rows (%.1f%%) — skipping injection",
            existing_cp, len(df), 100 * existing_cp / len(df),
        )
        return df

    # Extract matching carbon prices from AR6 database
    ar6_cp = ar6_carbon_prices.copy()
    if "scenario_year" in ar6_cp.columns:
        ar6_cp = ar6_cp.rename(columns={"scenario_year": "year"})

    # Deduplicate: take mean carbon price per (scenario_provider, scenario, geography, year)
    # across technologies (carbon price is technology-independent)
    cp_lookup = (
        ar6_cp[ar6_cp["carbon_price_usd_per_tco2"].notna()]
        .groupby(["scenario_provider", "scenario", "scenario_geography", "year"])[
            "carbon_price_usd_per_tco2"
        ]
        .mean()
        .reset_index()
    )

    if cp_lookup.empty:
        logger.warning("No carbon prices found in AR6 reference data")
        df["carbon_price_usd_per_tco2"] = 0.0
        return df

    # Build composite scenario key to match pathways format: "AR6_<provider>_<scenario>"
    cp_lookup["scenario_key"] = (
        "AR6_" + cp_lookup["scenario_provider"] + "_" + cp_lookup["scenario"]
    )

    cp_for_merge = cp_lookup[
        ["scenario_key", "scenario_geography", "year", "carbon_price_usd_per_tco2"]
    ].rename(
        columns={
            "scenario_key": "scenario",
            "carbon_price_usd_per_tco2": "_ar6_carbon_price",
        }
    )

    df = df.merge(
        cp_for_merge,
        on=["scenario", "scenario_geography", "year"],
        how="left",
    )

    # Fill carbon_price from AR6 data where available
    injected = df["_ar6_carbon_price"].notna().sum()
    df["carbon_price_usd_per_tco2"] = df["_ar6_carbon_price"].fillna(0.0)
    df = df.drop(columns=["_ar6_carbon_price"])

    logger.info(
        "Carbon price injection: %s/%s rows populated from AR6 data (%.1f%%)",
        injected,
        len(df),
        100 * injected / len(df) if len(df) > 0 else 0,
    )

    # Log summary by scenario
    for scen in df["scenario"].unique():
        sub = df[df["scenario"] == scen]
        cp = sub["carbon_price_usd_per_tco2"]
        nonzero = (cp > 0).sum()
        if nonzero > 0:
            logger.info(
                "  %s: %s/%s rows with carbon price, mean=$%.0f/tCO2, max=$%.0f/tCO2",
                scen,
                nonzero,
                len(sub),
                cp[cp > 0].mean(),
                cp.max(),
            )
        else:
            logger.info(
                "  %s: no carbon prices (price signal carries transition effect)",
                scen,
            )

    return df
