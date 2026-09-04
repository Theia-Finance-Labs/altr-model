"""Low-level scenario, company, and asset input transformations."""

import logging
from typing import List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def check_input_parameters(
    shock_year: int,
    alignment_year: int,
) -> None:
    if alignment_year < shock_year:
        raise ValueError("Alignment year cannot be earlier than shock year")


def filter_scenarios(
    scenarios_pathways: pd.DataFrame, target_scenario: str, baseline_scenario: str
) -> pd.DataFrame:
    # NOTE: Removed WindCap transformation - keeping WindCap - Onshore and WindCap - Offshore
    # as-is to match with asset data

    # Bypassing scenario_type column for filtering - determining baseline/target on the fly
    # based on the baseline_scenario and target_scenario parameters. This is more practical
    # than relying on the scenario_type column which can be heavy to maintain. However, we
    # still set the scenario_type column to the proper values because it's used elsewhere.
    assert (
        target_scenario in scenarios_pathways.scenario.unique()
    ), f"Target scenario '{target_scenario}' not found in scenarios pathways"
    assert (
        baseline_scenario in scenarios_pathways.scenario.unique()
    ), f"Baseline scenario '{baseline_scenario}' not found in scenarios pathways"

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
    sector_technology_index = pd.MultiIndex.from_frame(
        scenarios_pathways[["sector", "technology"]]
    )
    scenarios_pathways = scenarios_pathways[
        sector_technology_index.isin(common_sector_tech)
    ]

    scenarios_pathways_filtered = scenarios_pathways.loc[
        scenarios_pathways.scenario.isin([target_scenario, baseline_scenario]), :
    ].reset_index(drop=True)

    scenarios_pathways_filtered = scenarios_pathways_filtered.reset_index(drop=True)

    # Set scenario_type column on the fly based on which scenario is baseline and which is target
    scenarios_pathways_filtered.loc[
        scenarios_pathways_filtered["scenario"] == baseline_scenario, "scenario_type"
    ] = "baseline"
    scenarios_pathways_filtered.loc[
        scenarios_pathways_filtered["scenario"] == target_scenario, "scenario_type"
    ] = "target"

    scenarios_pathways_filtered.loc[
        :, "scenario_pathway"
    ] = scenarios_pathways_filtered.loc[:, "scenario_pathway"].astype(float)

    return scenarios_pathways_filtered


def _consolidate_ownership_stakes(companies_ownerships: pd.DataFrame) -> pd.DataFrame:
    """Roll up multiple ownership_type stakes in the same asset into one row.

    A company can hold more than one stake in the same asset (e.g. "direct"
    and "equity"), recorded as separate rows for the same
    (company_id, asset_id, year). Total ownership is direct + equity, so
    those rows are summed here into a single row per
    (company_id, asset_id, sector, technology, year) - otherwise the
    duplicate rows survive into the per-company asset pivot later in the
    pipeline and it fails with "Index contains duplicate entries".

    ``company_name`` and ``asset_name`` are NOT group keys. They are labels
    nothing computes on, and keying on them broke the roll-up in both
    directions: pandas' default drops every row with NaN in a key, so a blank
    name deleted that company's stake and its capacity with it; and
    ``dropna=False`` alone then SPLIT one stake into two whenever sibling rows
    disagreed about a name (typically one blank, one filled), reinstating the
    duplicate key this function exists to remove. Carried as ``first``
    instead, they cannot do either - ``first`` skips NaN, so a name blank on
    one row of a stake is taken from the row that has it, and a stake with no
    name anywhere keeps its row with a NaN label.

    ``dropna=False`` stays for the load-bearing keys: a NaN there is a real
    data defect that must reach the run, not vanish from it. This is a
    roll-up, not a filter; it must return the same total ownership it was
    handed. The company-grain aggregations downstream
    (``aggregate_assets_to_company_level``,
    ``apply_reduce_granularity_from_asset_to_company_level``) carry the names
    the same way, so an unnamed company survives to the company projection
    inputs rather than being dropped one stage later.
    """
    group_cols = [
        "company_id",
        "asset_id",
        "sector",
        "technology",
        "year",
    ]
    consolidated = companies_ownerships.groupby(
        group_cols, as_index=False, dropna=False
    ).agg(
        company_name=("company_name", "first"),
        asset_name=("asset_name", "first"),
        ownership_percentage=("ownership_percentage", "sum"),
    )
    # Column order as callers have always seen it (names beside their ids).
    return consolidated[
        [
            "company_id",
            "company_name",
            "asset_id",
            "asset_name",
            "sector",
            "technology",
            "year",
            "ownership_percentage",
        ]
    ]


#: Configured `ownership_type` values the NUMBERED (`ownership_level`) schema
#: understands, mapped to the rung they select. These are the two names the
#: NAMED schema uses plus "indirect", the numbered schema's own word for 2+.
#: A bare integer ("2") selects that level exactly. ANYTHING ELSE RAISES: the
#: previous `level >= 2` fallback turned every typo into a silent request for
#: the indirect rungs, so "dirct" quietly reported on the wrong tier.
_NUMBERED_DIRECT = frozenset({"direct"})
_NUMBERED_INDIRECT = frozenset({"indirect", "equity"})


def _normalize_tier(value: object) -> str:
    """Case- and whitespace-insensitive form of one tier label."""
    return str(value).strip().casefold()


def _select_ownership_tier(
    companies_ownerships: pd.DataFrame, ownership_type: str
) -> pd.DataFrame:
    """Keep one rung of the ownership tree.

    A company's stake in an asset is recorded at several tiers - a direct
    holding and the equity stakes that roll up through subsidiaries. They are
    alternative views of the same capacity, not additive ones, so a run picks
    the tier it reports on. Summing across tiers would allocate the same plant
    to the same company twice.

    Two schemas are in circulation: `ownership_type`, which names the rungs
    ("direct" and "equity" in the marts export), and the newer
    `ownership_level`, which numbers them (1 = direct, 2+ = indirect).

    A tier the data does not carry is a configuration error, not an empty
    result: silently returning an empty panel takes every company out of the
    run and the failure only surfaces as zero rows several stages later. Both
    schemas therefore raise `ValueError` naming the configured value and what
    the frame actually offers.

    Matching is case- and whitespace-insensitive on BOTH sides, and the
    selection uses the same normalized comparison the validation does - a
    check that accepted "Direct" and then filtered on `== "Direct"` would
    hand back the empty panel this exists to prevent. Under the numbered
    schema only the labels in `_NUMBERED_DIRECT` / `_NUMBERED_INDIRECT` and a
    bare integer are accepted; a typo raises instead of falling through to
    "level >= 2".

    Neither path can return zero rows without raising first. Two silent
    reductions remain OUTSIDE this function, and both are handled where they
    happen: the no-tier-column branch below keeps every row (and
    `scripts/prepare_inputs.py` refuses a delivered file that reaches it), and
    `_consolidate_ownership_stakes` keeps the cosmetic name columns out of its
    group keys (and groups with `dropna=False`) so a blank name cannot delete
    a stake.
    """
    if "ownership_type" in companies_ownerships.columns:
        column = companies_ownerships["ownership_type"]
        available = sorted(str(v) for v in column.dropna().unique())
        wanted = _normalize_tier(ownership_type)
        matches = column.map(_normalize_tier).eq(wanted) & column.notna()
        if not matches.any():
            raise ValueError(
                f"ownership_type {ownership_type!r} is not present in the "
                f"companies input; its 'ownership_type' column holds "
                f"{available}. Set `ownership_type` in "
                "conf/base/parameters_prepare_scenario_asset_and_company_inputs"
                ".yml to one of those (matching ignores case and surrounding "
                "whitespace)."
            )
        selected = companies_ownerships.loc[matches]
    elif "ownership_level" in companies_ownerships.columns:
        level = pd.to_numeric(companies_ownerships["ownership_level"], errors="coerce")
        rungs = sorted(str(v) for v in level.dropna().unique())
        wanted = _normalize_tier(ownership_type)
        if wanted in _NUMBERED_DIRECT:
            mask = level.eq(1)
        elif wanted in _NUMBERED_INDIRECT:
            mask = level.ge(2)
        elif wanted.isdigit():
            mask = level.eq(int(wanted))
        else:
            raise ValueError(
                f"ownership_type {ownership_type!r} means nothing under the "
                f"'ownership_level' schema, whose column holds {rungs}. Use "
                f"{sorted(_NUMBERED_DIRECT)} for level 1, "
                f"{sorted(_NUMBERED_INDIRECT)} for level 2+, or a bare level "
                "number. It is NOT taken as 'some indirect rung': that "
                "fallback reported a typo on the wrong tier without saying so."
            )
        selected = companies_ownerships.loc[mask]
        if selected.empty:
            raise ValueError(
                f"ownership_type {ownership_type!r} selects no rung of the "
                f"'ownership_level' column, which holds {rungs} "
                "('direct' selects level 1, 'indirect'/'equity' select level "
                "2+, a bare number selects that level)."
            )
    else:
        logger.warning(
            "Neither 'ownership_type' nor 'ownership_level' is present in the "
            "companies input; keeping every ownership row. Capacity may be "
            "allocated more than once per company."
        )
        return companies_ownerships

    logger.info(
        "Ownership tier '%s': kept %s of %s ownership rows",
        ownership_type,
        len(selected),
        len(companies_ownerships),
    )
    return selected


#: Accepted values of the `ownership_aggregation` parameter, in the order the
#: error message lists them; the first is the default.
OWNERSHIP_AGGREGATIONS = ("tier_filter", "sum")


def filter_companies(
    companies_ownerships: pd.DataFrame,
    company_ids: List[str],
    ownership_type: str = "direct",
    ownership_aggregation: str = OWNERSHIP_AGGREGATIONS[0],
) -> pd.DataFrame:
    """Reduce the ownership table to one stake row per company-asset-year.

    `ownership_aggregation` decides how a company's several stakes in one asset
    combine - see the annotated key in
    `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`.
    """
    if ownership_aggregation not in OWNERSHIP_AGGREGATIONS:
        raise ValueError(
            f"ownership_aggregation must be one of {OWNERSHIP_AGGREGATIONS}, "
            f"got {ownership_aggregation!r}. Use 'tier_filter' to report on one "
            "ownership tier (the validated default) or 'sum' to total every "
            "holding a company has in an asset-year."
        )

    # Tier first, then consolidate: consolidation sums the stakes it is given,
    # so under "tier_filter" it must only ever see one rung of the tree. Under
    # "sum" it is handed every rung deliberately.
    if ownership_aggregation == "tier_filter":
        companies_ownerships = _select_ownership_tier(
            companies_ownerships, ownership_type
        )
    companies_ownerships = _consolidate_ownership_stakes(companies_ownerships)

    if company_ids:
        filtered_companies_ownerships = companies_ownerships.loc[
            companies_ownerships.company_id.isin(company_ids), :
        ].reset_index(drop=True)
    else:
        filtered_companies_ownerships = companies_ownerships

    return filtered_companies_ownerships


def apply_ccs_suffix(
    assets_forecasts: pd.DataFrame,
    companies_ownerships: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
    ccs_on: bool | None,
) -> pd.DataFrame:
    if (
        not any(
            " - w/ CCS" in tech for tech in scenarios_pathways["technology"].unique()
        )
        and not any(
            " - w/o CCS" in tech for tech in scenarios_pathways["technology"].unique()
        )
    ) or ccs_on is None:
        logger.warning("No CCS technologies are present in the assets forecasts")
        return assets_forecasts, companies_ownerships

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
    ccs_technologies_mask_companies = companies_ownerships["technology"].isin(
        ["BiomassCap", "CoalCap", "GasCap", "OilCap"]
    )
    if ccs_on:
        assets_forecasts.loc[ccs_technologies_mask_assets, "technology"] = (
            assets_forecasts.loc[ccs_technologies_mask_assets, "technology"]
            + " - w/ CCS"
        )
        companies_ownerships.loc[ccs_technologies_mask_companies, "technology"] = (
            companies_ownerships.loc[ccs_technologies_mask_companies, "technology"]
            + " - w/ CCS"
        )
    else:
        assets_forecasts.loc[ccs_technologies_mask_assets, "technology"] = (
            assets_forecasts.loc[ccs_technologies_mask_assets, "technology"]
            + " - w/o CCS"
        )
        companies_ownerships.loc[ccs_technologies_mask_companies, "technology"] = (
            companies_ownerships.loc[ccs_technologies_mask_companies, "technology"]
            + " - w/o CCS"
        )
    return assets_forecasts, companies_ownerships


def filter_assets(
    assets_forecasts: pd.DataFrame,
    companies_ownerships: pd.DataFrame,
    scenarios_pathways: pd.DataFrame,
    max_forecast_horizon: int,
) -> pd.DataFrame:
    # TODO REMOVE HARDFIX FOR NGFS
    assets_forecasts = assets_forecasts.loc[
        ~assets_forecasts.country_iso2.isna()
        & ~assets_forecasts.country_iso2.isin(
            [
                "AS",
                "BM",
                "AW",
                "SZ",
                "FO",
                "CW",
                "DM",
                "GF",
                "PS",
                "KN",
                "MK",
                "IM",
                "PM",
                "XK",
                "SC",
                "SS",
                "AX",
                "KY",
                "BQ",
                "GG",
                "MS",
                "JE",
            ]
        ),
        :,
    ]

    # NOTE: Removed WindCap transformation - keeping WindCap - Onshore and WindCap - Offshore
    # as-is to match with scenario data which has WindCap - Onshore

    owned_assets = companies_ownerships["asset_id"].unique().tolist()
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
        (scenario_start_year <= filtered_assets_forecasts.year)
        & (filtered_assets_forecasts.year <= forecast_end_year),
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
            assets_with_geography.loc[
                unassigned_mask, "scenario_geography"
            ] = global_geography

    assert (
        assets_with_geography["scenario_geography"].isna().sum() == 0
    ), "Some assets are not assigned to a scenario geography"

    return assets_with_geography


def allocate_assets_to_companies(
    assets_forecasts: pd.DataFrame,
    companies_ownerships: pd.DataFrame,
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
        companies_ownerships: DataFrame with company ownership information
        scenarios_pathways: DataFrame with scenario data to determine start year

    Returns:
        DataFrame with allocated asset capacities to companies
    """

    # Get scenario start year for backfilling
    scenario_start_year = scenarios_pathways.year.min()

    # Prepare assets data
    assets_prepared = assets_forecasts.copy()

    # Prepare companies data. Drop asset_name: it's also on assets_prepared, and
    # duplicating it would make pandas suffix both copies (asset_name_x/_y)
    # instead of keeping a plain asset_name column.
    companies_prepared = companies_ownerships.copy().drop(columns=["asset_name"])

    # Merge assets with ownership data on asset_id, sector, technology, and year
    merged_data = pd.merge(
        assets_prepared,
        companies_prepared,
        on=["asset_id", "sector", "technology", "year"],
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
    # selected upstream sums to ~100 per asset-year, which
    # `check_ownership_allocation` in scripts/prepare_inputs.py warns about when
    # the delivered rows do not -- so divide by 100 to get the fraction.
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
        merged_data["capacity"].sum() / raw_capacity_total
        if raw_capacity_total
        else float("nan"),
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


# Share of new-build cost charged at retirement: 0 = free exit, 1 = a full rebuild.
DECOM_FRACTION_BOUNDS = (0.0, 1.0)


def apply_decom_cost_fraction(
    scenarios: pd.DataFrame, fraction: float | None
) -> pd.DataFrame:
    """Recalibrate ``scrap_usd_per_mw`` as ``-fraction * capex_usd_per_mw``.

    The marts drop delivers scrap at ``-capital_cost / 2``: retiring a plant is
    charged half its build cost. ``None`` keeps the delivered column. A number
    rewrites it for every scenario row, so both consumers -- the in-window
    decommissioning charge and the terminal value's decommissioning floor --
    price retirement at the same share of new-build cost. Kept negative: the
    charge site takes ``abs()``.
    """
    if fraction is None:
        return scenarios
    lo, hi = DECOM_FRACTION_BOUNDS
    if not (lo <= float(fraction) <= hi):
        raise ValueError(
            "decom_cost_fraction_of_capex must be within [0, 1] or null "
            f"(share of capex_usd_per_mw charged at retirement); got {fraction!r}"
        )
    if "capex_usd_per_mw" not in scenarios.columns:
        raise ValueError(
            "decom_cost_fraction_of_capex needs the capex_usd_per_mw column, "
            "which prepare_scenario_pathways derives from capital_cost_usd_per_mw"
        )
    return scenarios.assign(
        scrap_usd_per_mw=-float(fraction) * scenarios["capex_usd_per_mw"]
    )


# Capture-price factors after Hirth (2013), "The market value of variable
# renewables", Energy Economics 38. Hirth measures the VALUE FACTOR of wind and
# solar (generation-weighted capture price / average system price) and finds
# it falling with market share: wind from ~1.1 at zero share to 0.5-0.8 at 30%,
# solar reaching the same by ~15%. The model otherwise pays every technology the
# regional annual-average price. Dispatchable plant takes the residual so that
# generation-weighted capture prices still average to the system price.
CAPTURE_PRICE_METHODS = ("none", "hirth2013")
CAPTURE_WIND_TECHNOLOGIES = ("WindCap - Onshore", "WindCap - Offshore")
CAPTURE_SOLAR_TECHNOLOGIES = ("SolarCap - PV",)
_REGION_YEAR_KEYS = ["scenario", "scenario_geography", "year"]
# Below this residual generation share the dispatchable factor is undefined (all-VRE).
_CAPTURE_MIN_RESIDUAL_SHARE = 1e-9


def compute_capture_price_factor(
    scenarios: pd.DataFrame, params: dict | None
) -> pd.DataFrame:
    """Add ``capture_price_factor`` per scenario row (1.0 under ``method: none``).

    Shares are computed on LEAF technologies only: the extract also carries
    aggregate parents (``CoalCap`` = ``CoalCap - w/o CCS`` + ``CoalCap - w/ CCS``),
    which would double-count generation. Wind and PV take Hirth's linear
    value-factor-in-share form (floored); every other technology, CSP and the
    parents included, takes the dispatchable residual (capped).
    """
    params = params or {}
    method = params.get("method", "none")
    if method not in CAPTURE_PRICE_METHODS:
        raise ValueError(
            f"capture_price.method must be one of {CAPTURE_PRICE_METHODS}; got {method!r}"
        )
    if method == "none":
        return scenarios.assign(capture_price_factor=1.0)

    techs = set(scenarios["technology"].unique())
    parents = {t for t in techs if any(o.startswith(t + " - ") for o in techs)}
    leaf = scenarios[~scenarios["technology"].isin(parents)]
    total = leaf.groupby(_REGION_YEAR_KEYS)["scenario_pathway"].sum().rename("total")
    wind = (
        leaf[leaf["technology"].isin(CAPTURE_WIND_TECHNOLOGIES)]
        .groupby(_REGION_YEAR_KEYS)["scenario_pathway"]
        .sum()
        .rename("wind")
    )
    solar = (
        leaf[leaf["technology"].isin(CAPTURE_SOLAR_TECHNOLOGIES)]
        .groupby(_REGION_YEAR_KEYS)["scenario_pathway"]
        .sum()
        .rename("solar")
    )
    sh = pd.concat([total, wind, solar], axis=1).fillna(0.0)
    positive = sh["total"] > 0
    s_w = (sh["wind"] / sh["total"]).where(positive, 0.0)
    s_s = (sh["solar"] / sh["total"]).where(positive, 0.0)
    floor, cap = float(params["vre_floor"]), float(params["dispatchable_cap"])
    vf_w = (params["wind_intercept"] + params["wind_slope"] * s_w).clip(lower=floor)
    vf_s = (params["solar_intercept"] + params["solar_slope"] * s_s).clip(lower=floor)
    residual_share = 1.0 - s_w - s_s
    vf_d = (
        (
            (1.0 - s_w * vf_w - s_s * vf_s)
            / residual_share.where(residual_share > _CAPTURE_MIN_RESIDUAL_SHARE)
        )
        .fillna(1.0)
        .clip(upper=cap)
    )
    factors = pd.DataFrame({"_vf_w": vf_w, "_vf_s": vf_s, "_vf_d": vf_d})
    out = scenarios.merge(
        factors, left_on=_REGION_YEAR_KEYS, right_index=True, how="left"
    )
    is_wind = out["technology"].isin(CAPTURE_WIND_TECHNOLOGIES)
    is_solar = out["technology"].isin(CAPTURE_SOLAR_TECHNOLOGIES)
    out["capture_price_factor"] = np.where(
        is_wind, out["_vf_w"], np.where(is_solar, out["_vf_s"], out["_vf_d"])
    )
    return out.drop(columns=["_vf_w", "_vf_s", "_vf_d"])


# Long-run-marginal-cost price floor. IAM electricity prices are annual
# marginal-cost shadow prices; under WITCH, MESSAGE and REMIND they sit below
# the full cost of the plants those pathways keep building. In long-run
# equilibrium the average price must at least cover the levelised cost of the
# price-setting entrant, or nothing gets built (peak-load pricing, Boiteux).
PRICE_FLOOR_METHODS = ("none", "lrmc")
#: Technologies that can set the price: the region-year's largest thermal
#: generator by scenario pathway. Nuclear and hydro are price-takers in practice.
PRICE_SETTING_TECHNOLOGY_PREFIXES = ("CoalCap", "GasCap", "OilCap", "BiomassCap")
HOURS_PER_YEAR = 8760
#: A real cost of capital must be a rate strictly between these bounds.
DISCOUNT_RATE_BOUNDS = (0.0, 1.0)


def capital_recovery_factor(rate: float, lifetime_years) -> float:
    """Annuity factor: the equal yearly payment that repays one unit of capital
    over ``lifetime_years`` at ``rate`` -- r(1+r)^L / ((1+r)^L - 1)."""
    growth = (1.0 + rate) ** lifetime_years
    return rate * growth / (growth - 1.0)


def apply_lrmc_price_floor(
    scenarios: pd.DataFrame, params: dict | None
) -> pd.DataFrame:
    """Lift ``power_price_excarbon_usd_per_mwh`` to the price-setter's LRMC.

    Per scenario x region x year, the price-setting technology is the LEAF
    thermal technology with the largest ``scenario_pathway`` (aggregate parents
    such as ``CoalCap`` are excluded). Its levelised cost per MWh is
    ``fuel_price / efficiency + om / hours + capex x CRF(rate, lifetime) / hours``
    with ``hours = capacity_factor x 8760``, all from that technology's own row.
    The floor is ONE market price: every technology in the region-year receives
    ``max(price, floor)``. ``scenario_price`` keeps the raw IAM value for audit;
    ``price_floor_lrmc`` reports the floor (0.0 where none applies: method
    ``none``, no thermal generation, or a setter whose cost inputs are not
    usable) and ``price_setter_technology`` names the setter.
    """
    params = params or {}
    method = params.get("method", "none")
    if method not in PRICE_FLOOR_METHODS:
        raise ValueError(
            f"price_floor.method must be one of {PRICE_FLOOR_METHODS}; got {method!r}"
        )
    if method == "none":
        return scenarios.assign(price_floor_lrmc=0.0, price_setter_technology=None)
    rate = float(params.get("discount_rate", float("nan")))
    lo, hi = DISCOUNT_RATE_BOUNDS
    if not (lo < rate < hi):
        raise ValueError(
            "price_floor.discount_rate must be a real rate within (0, 1), e.g. 0.08; "
            f"got {params.get('discount_rate')!r}"
        )

    techs = set(scenarios["technology"].unique())
    parents = {t for t in techs if any(o.startswith(t + " - ") for o in techs)}
    thermal = scenarios[
        ~scenarios["technology"].isin(parents)
        & scenarios["technology"].str.startswith(PRICE_SETTING_TECHNOLOGY_PREFIXES)
    ]
    setter = thermal.sort_values("scenario_pathway", ascending=False).drop_duplicates(
        _REGION_YEAR_KEYS
    )
    hours = (setter["scenario_capacity_factor"] * HOURS_PER_YEAR).where(
        setter["scenario_capacity_factor"] > 0
    )
    efficiency = setter["efficiency_decimal"].where(setter["efficiency_decimal"] > 0)
    lifetime = setter["lifetime_years"].where(setter["lifetime_years"] > 0)
    lrmc = (
        setter["fuel_price"] / efficiency
        + setter["om_cost_usd_per_mw_per_yr"] / hours
        + setter["capital_cost_usd_per_mw"]
        * capital_recovery_factor(rate, lifetime)
        / hours
    )
    floors = pd.DataFrame(
        {
            "price_floor_lrmc": lrmc.fillna(0.0),
            "price_setter_technology": setter["technology"],
        }
    ).join(setter[_REGION_YEAR_KEYS])
    out = scenarios.merge(floors, on=_REGION_YEAR_KEYS, how="left")
    out["price_floor_lrmc"] = out["price_floor_lrmc"].fillna(0.0)
    out["power_price_excarbon_usd_per_mwh"] = np.maximum(
        out["power_price_excarbon_usd_per_mwh"], out["price_floor_lrmc"]
    )
    return out
