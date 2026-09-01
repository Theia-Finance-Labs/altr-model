"""Explicit company-to-asset allocation and reconciliation nodes."""

from __future__ import annotations

import pandas as pd

from altr_model.pipelines.allocate_company_trajectories_to_assets._allocation_nodes import (
    compute_asset_baseline_trajectories,
    flag_phased_out_assets_as_retired,
    melt_asset_staggered_trajectories,
    split_late_sudden_trajectories_by_alignment_type,
    stagger_decreasing_technologies,
    stagger_increasing_technologies,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs._asset_preparation import (
    determine_assets_retirement_dates,
    extend_allocated_assets_to_companies,
)
from altr_model.pipelines.prepare_scenario_asset_and_company_inputs.nodes import (
    FINANCIAL_SURFACE_COLUMNS,
)

ASSET_KEYS = [
    "asset_id",
    "company_id",
    "scenario_geography",
    "sector",
    "technology",
]
COMPANY_YEAR_KEYS = [
    "company_id",
    "scenario_geography",
    "sector",
    "technology",
    "year",
]


def extend_asset_panel_and_attach_retirement(
    asset_forecast_panel: pd.DataFrame,
) -> pd.DataFrame:
    """Extend assets to the scenario horizon and carry retirement on each row."""
    if asset_forecast_panel.empty:
        output = asset_forecast_panel.copy()
        output["retirement_year"] = pd.Series(dtype="float64")
        return output

    scenario_end_year = int(asset_forecast_panel["scenario_end_year"].max())
    extended = extend_allocated_assets_to_companies(
        asset_forecast_panel,
        pd.DataFrame({"year": [scenario_end_year]}),
    )
    group_columns = ASSET_KEYS
    carried_columns = [
        "asset_lifetime_years",
        "increasing",
        "scenario_start_year",
        "scenario_end_year",
    ]
    extended = extended.sort_values(group_columns + ["year"])
    # Extension rows leave carried bool columns as object (bool + NaN); nullable
    # dtypes keep ffill/bfill from object-downcasting (FutureWarning, pandas >=2.2).
    object_columns = [c for c in carried_columns if extended[c].dtype == object]
    for column in object_columns:
        extended[column] = extended[column].convert_dtypes()
    for column in carried_columns:
        extended[column] = extended.groupby(group_columns, sort=False)[
            column
        ].transform(lambda values: values.ffill().bfill())
    for column in object_columns:
        if extended[column].notna().all():
            extended[column] = extended[column].astype(
                asset_forecast_panel[column].dtype
            )

    lifetime_table = (
        extended[["sector", "technology", "asset_lifetime_years"]]
        .dropna(subset=["asset_lifetime_years"])
        .drop_duplicates(["sector", "technology"])
        .rename(columns={"asset_lifetime_years": "lifetime_years"})
    )
    retirement_dates = determine_assets_retirement_dates(
        extended.drop(columns="asset_lifetime_years"),
        lifetime_table,
    )
    extended = extended.merge(
        retirement_dates,
        on=ASSET_KEYS,
        how="left",
        validate="many_to_one",
    )
    return extended.sort_values(ASSET_KEYS + ["year"]).reset_index(drop=True)


def _retirement_lookup(asset_panel: pd.DataFrame) -> pd.DataFrame:
    columns = ASSET_KEYS + ["retirement_year"]
    return asset_panel[columns].dropna(subset=["retirement_year"]).drop_duplicates()


def _legacy_company_pathways(company_pathways: pd.DataFrame) -> pd.DataFrame:
    legacy = company_pathways.copy()
    legacy["trajectory_type"] = legacy["trajectory_type"].replace(
        {"late_sudden_requested": "latesudden"}
    )
    return legacy


def compute_asset_baselines(
    company_pathways_pre_allocation: pd.DataFrame,
    extended_asset_panel: pd.DataFrame,
    apply_retirement_baseline: bool,
    alignment_year: int,
) -> pd.DataFrame:
    """Compute the asset baseline using retirement carried on the asset panel."""
    return compute_asset_baseline_trajectories(
        companies_late_sudden_trajectories=_legacy_company_pathways(
            company_pathways_pre_allocation
        ),
        allocated_assets_to_companies=extended_asset_panel,
        assets_retirement_dates=_retirement_lookup(extended_asset_panel),
        apply_retirement_baseline=apply_retirement_baseline,
        alignment_year=alignment_year,
    )


def split_company_pathways_by_technology_direction(
    company_pathways_pre_allocation: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Expose the decreasing/increasing methodology fork in Kedro Viz."""
    decreasing, increasing = split_late_sudden_trajectories_by_alignment_type(
        _legacy_company_pathways(company_pathways_pre_allocation)
    )
    return {
        "decreasing_company_pathways": decreasing,
        "increasing_company_pathways": increasing,
    }


def allocate_decreasing_company_trajectories_to_assets(
    decreasing_company_pathways: pd.DataFrame,
    assets_with_baseline: pd.DataFrame,
    shock_year: int,
    alignment_year: int,
    apply_retirement_shock: bool,
    apply_decreasing_staggered_shock: bool,
    g_k: float,
    n_quantiles: int,
) -> pd.DataFrame:
    """Allocate decreasing pathways using the selected proportional/staggered mode."""
    decreasing_assets, _ = stagger_decreasing_technologies(
        late_sudden_trajectories=decreasing_company_pathways,
        assets_with_baseline_trajectory=assets_with_baseline,
        assets_retirement_dates=_retirement_lookup(assets_with_baseline),
        shock_year=shock_year,
        alignment_year=alignment_year,
        apply_retirement_shock=apply_retirement_shock,
        apply_decreasing_staggered_shock=apply_decreasing_staggered_shock,
        g_k=g_k,
        n_quantiles=n_quantiles,
    )
    return flag_phased_out_assets_as_retired(decreasing_assets)


def allocate_increasing_company_trajectories_to_assets(
    increasing_company_pathways: pd.DataFrame,
    assets_with_baseline: pd.DataFrame,
    shock_year: int,
) -> pd.DataFrame:
    """Allocate increasing pathways and create the synthetic top-up assets."""
    increasing_assets, _ = stagger_increasing_technologies(
        late_sudden_trajectories=increasing_company_pathways,
        assets_with_baseline_trajectory=assets_with_baseline,
        shock_year=shock_year,
    )
    return increasing_assets


def combine_asset_allocation_branches(
    decreasing_asset_allocation: pd.DataFrame,
    increasing_asset_allocation: pd.DataFrame,
    assets_with_baseline: pd.DataFrame,
) -> pd.DataFrame:
    """Combine both visible allocation branches and restore carried asset metadata."""
    allocation = pd.concat(
        [decreasing_asset_allocation, increasing_asset_allocation], ignore_index=True
    )
    source_metadata = assets_with_baseline.copy()
    source_metadata["asset_id"] = source_metadata["asset_id"].astype(str)
    metadata_columns = ASSET_KEYS + [
        "year",
        "emission_factor",
        "retirement_year",
        "asset_lifetime_years",
    ]
    source_metadata = source_metadata[metadata_columns].drop_duplicates(
        ASSET_KEYS + ["year"]
    )
    allocation["asset_id"] = allocation["asset_id"].astype(str)
    allocation = allocation.merge(
        source_metadata,
        on=ASSET_KEYS + ["year"],
        how="left",
        validate="many_to_one",
    )
    renewable_synthetic = allocation["is_synthetic"].fillna(False) & allocation[
        "technology"
    ].isin(
        {
            "SolarCap - CSP",
            "SolarCap - PV",
            "WindCap - Offshore",
            "WindCap - Onshore",
            "HydroCap",
            "NuclearCap",
            "GeothermalCap",
        }
    )
    allocation.loc[
        renewable_synthetic & allocation["emission_factor"].isna(),
        "emission_factor",
    ] = 0.0
    return allocation


def build_canonical_asset_trajectories(
    asset_allocation_wide: pd.DataFrame,
    company_pathways_pre_allocation: pd.DataFrame,
) -> pd.DataFrame:
    """Melt the combined allocation once and attach active financial assumptions."""
    asset_trajectories = melt_asset_staggered_trajectories(asset_allocation_wide)
    allocation_metadata = asset_allocation_wide[
        ASSET_KEYS
        + ["year", "emission_factor", "retirement_year", "asset_lifetime_years"]
    ].drop_duplicates(ASSET_KEYS + ["year"])
    asset_trajectories = asset_trajectories.merge(
        allocation_metadata,
        on=ASSET_KEYS + ["year"],
        how="left",
        validate="many_to_one",
    )

    surface_rows = company_pathways_pre_allocation[
        company_pathways_pre_allocation["trajectory_type"].isin(
            ["baseline", "late_sudden_requested"]
        )
    ].copy()
    surface_rows["trajectory_type"] = surface_rows["trajectory_type"].replace(
        {"late_sudden_requested": "latesudden"}
    )
    surface_columns = list(
        dict.fromkeys(
            [
                "trajectory_type",
                *COMPANY_YEAR_KEYS,
                "scenario_type",
                *FINANCIAL_SURFACE_COLUMNS,
                "increasing",
                "aligned",
            ]
        )
    )
    asset_trajectories = asset_trajectories.merge(
        surface_rows[surface_columns].drop_duplicates(
            ["trajectory_type", *COMPANY_YEAR_KEYS]
        ),
        on=["trajectory_type", *COMPANY_YEAR_KEYS],
        how="left",
        validate="many_to_one",
    )
    asset_sort = [
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "asset_id",
        "year",
        "trajectory_type",
    ]
    return asset_trajectories.sort_values(asset_sort).reset_index(drop=True)


FROZEN_CAPACITY_COLUMNS = ASSET_KEYS + ["year", "frozen_capacity_at_retirement"]


def create_frozen_capacity_at_retirement(
    asset_allocation_wide: pd.DataFrame,
    alignment_year: int | None = None,
) -> pd.DataFrame:
    """Capacity each retiring asset last stood at, carried through its retirement.

    For every asset with a retirement year, take its capacity in the year
    BEFORE retirement — at the retirement year itself the retirement logic has
    already zeroed it — and extend that level across every year from retirement
    onward.

    Retirement here means the EFFECTIVE retirement year, not the raw one:
    allocation never retires an asset before `alignment_year + 1`
    (`_allocation_nodes.py`), so anchoring on the raw `retirement_year` of an
    asset due to retire on or before the alignment year would read a year the
    asset is still running and freeze the wrong capacity.

    This is a lookup table, not a cost driver: fixed costs use first-year
    capacity (``compute_ops_block``'s ``initial_capacity``), so nothing in the
    earnings maths reads this column today. It is carried because the handover
    branch carries it and the 2026-09-01 owner ruling ports Q4 — it is the
    surface a stranded-capacity view would be built on.
    """
    if asset_allocation_wide.empty or "capacity_after_shock" not in (
        asset_allocation_wide.columns
    ):
        return pd.DataFrame(columns=FROZEN_CAPACITY_COLUMNS)

    # retirement_year is carried on every row of the wide panel, so the retiring
    # assets are a filter rather than a join.
    assets = asset_allocation_wide.dropna(subset=["retirement_year"])
    if assets.empty:
        return pd.DataFrame(columns=FROZEN_CAPACITY_COLUMNS)

    effective_retirement = assets["retirement_year"].astype(int)
    if alignment_year is not None:
        effective_retirement = effective_retirement.clip(lower=int(alignment_year) + 1)
    assets = assets.assign(_eff_retirement_year=effective_retirement)

    last_active = assets.loc[assets["year"].eq(assets["_eff_retirement_year"] - 1)]
    if last_active.empty:
        return pd.DataFrame(columns=FROZEN_CAPACITY_COLUMNS)

    frozen = (
        last_active.assign(
            frozen_capacity_at_retirement=last_active["capacity_after_shock"]
        )[ASSET_KEYS + ["_eff_retirement_year", "frozen_capacity_at_retirement"]]
        .drop_duplicates()
        .merge(
            pd.DataFrame({"year": sorted(asset_allocation_wide["year"].unique())}),
            how="cross",
        )
    )
    frozen = frozen.loc[frozen["year"].ge(frozen["_eff_retirement_year"])]
    return (
        frozen[FROZEN_CAPACITY_COLUMNS]
        .sort_values(ASSET_KEYS + ["year"])
        .reset_index(drop=True)
    )


def reconcile_realized_company_trajectories(
    asset_trajectories: pd.DataFrame,
    company_pathways_pre_allocation: pd.DataFrame,
) -> pd.DataFrame:
    """Derive the realized company path explicitly from allocated asset capacity."""
    requested = company_pathways_pre_allocation[
        company_pathways_pre_allocation["trajectory_type"].eq("late_sudden_requested")
    ].copy()
    realized_values = (
        asset_trajectories[asset_trajectories["trajectory_type"].eq("latesudden")]
        .groupby(COMPANY_YEAR_KEYS, as_index=False)["asset_trajectory"]
        .sum()
        .rename(columns={"asset_trajectory": "company_trajectory"})
    )
    realized = requested.drop(columns="company_trajectory").merge(
        realized_values,
        on=COMPANY_YEAR_KEYS,
        how="inner",
        validate="one_to_one",
    )
    realized["trajectory_type"] = "late_sudden_realized"
    return (
        pd.concat([company_pathways_pre_allocation, realized], ignore_index=True)
        .sort_values(COMPANY_YEAR_KEYS + ["trajectory_type"])
        .reset_index(drop=True)
    )
