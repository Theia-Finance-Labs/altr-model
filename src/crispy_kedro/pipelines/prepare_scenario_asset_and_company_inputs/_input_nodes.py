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
        raise ValueError("Alignment year must be greater than shock year")


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


def filter_companies(
    companies_ownership_tree: pd.DataFrame,
    company_ids: List[str],
    ownership_type: str,
) -> pd.DataFrame:
    companies_owners = companies_ownership_tree[
        companies_ownership_tree["ownership_type"] == ownership_type
    ]

    if company_ids:
        filtered_companies_ownership_tree = companies_owners.loc[
            companies_owners.company_id.isin(company_ids), :
        ].reset_index(drop=True)
    else:
        filtered_companies_ownership_tree = companies_owners

    return filtered_companies_ownership_tree


def apply_ccs_suffix(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
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
    ccs_technologies_mask_companies = companies_ownership_tree["technology"].isin(
        ["BiomassCap", "CoalCap", "GasCap", "OilCap"]
    )
    if ccs_on:
        assets_forecasts.loc[ccs_technologies_mask_assets, "technology"] = (
            assets_forecasts.loc[ccs_technologies_mask_assets, "technology"]
            + " - w/ CCS"
        )
        companies_ownership_tree.loc[ccs_technologies_mask_companies, "technology"] = (
            companies_ownership_tree.loc[ccs_technologies_mask_companies, "technology"]
            + " - w/ CCS"
        )
    else:
        assets_forecasts.loc[ccs_technologies_mask_assets, "technology"] = (
            assets_forecasts.loc[ccs_technologies_mask_assets, "technology"]
            + " - w/o CCS"
        )
        companies_ownership_tree.loc[ccs_technologies_mask_companies, "technology"] = (
            companies_ownership_tree.loc[ccs_technologies_mask_companies, "technology"]
            + " - w/o CCS"
        )
    return assets_forecasts, companies_ownership_tree


def filter_assets(
    assets_forecasts: pd.DataFrame,
    companies_ownership_tree: pd.DataFrame,
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

    # Prepare companies data. Drop asset_name: it's also on assets_prepared, and
    # duplicating it would make pandas suffix both copies (asset_name_x/_y)
    # instead of keeping a plain asset_name column.
    companies_prepared = companies_ownership_tree.copy().drop(columns=["asset_name"])

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

    # Calculate owned asset capacity (allocated capacity based on ownership percentage)
    merged_data["capacity"] = (
        merged_data["capacity"] * merged_data["ownership_percentage"]
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


def scale_electricity_price(
    scenarios_pathways: pd.DataFrame, theta: float = 1.0
) -> pd.DataFrame:
    # """
    # Adjust electricity prices per technology and year so that:
    #   - each tech covers SRMC + θ*(FOM/MWh + α*CapAnn/MWh)
    #   - energy-weighted mean price equals the original average price

    # Parameters
    # ----------
    # scenarios_pathways : pd.DataFrame
    #     Must include:
    #     ['scenario', 'year', 'scenario_geography',
    #      'scenario_price', 'fuel_price', 'efficiency_decimal',
    #      'om_cost_usd_per_mw_per_yr', 'capital_cost_usd_per_mw',
    #      'scenario_capacity_factor', 'scenario_pathway',   # in MW!
    #      'capacity_additions_mw_per_yr', 'lifetime_years']
    # theta : float, optional
    #     Fraction of fixed + capex recovery via energy (default = 1.0)

    # Returns
    # -------
    # pd.DataFrame
    #     Same as input, with new column 'scenario_price_scaled'.
    # """

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
