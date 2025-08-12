import pandas as pd
import numpy as np
import warnings
from tqdm import tqdm

# ============================ helpers ============================


def _compute_g_weights(
    ages: pd.Series,
    k: float,
    min_active_share: float,
    n_quantiles: int,
    for_decreasing: bool = True,
) -> pd.Series:
    """Compute logistic-sum g(a) weights, clip and normalize.

    Args:
        ages: Asset ages
        k: Steepness parameter for logistic function
        min_active_share: Minimum weight for any asset
        n_quantiles: Number of quantiles to use for age thresholds
        for_decreasing: If True, older assets get higher weights (for decreasing tech).
                       If False, younger assets get higher weights (for increasing tech).
    """
    if ages.empty:
        return pd.Series(dtype=float)
    ages = ages.astype(float)
    med = float(ages.median()) if np.isfinite(ages.median()) else 0.0
    filled = ages.fillna(med)
    qs = np.linspace(0, 1, n_quantiles + 1)[1:-1]
    age_q = np.quantile(filled, qs) if len(qs) else []

    def g(a):
        a = med if pd.isna(a) else a
        base_weight = 1 - sum(1 / (1 + np.exp(-k * (a - q))) for q in age_q)
        # For decreasing tech: older assets should get higher weights, so invert
        # For increasing tech: younger assets should get higher weights, so keep original
        return -base_weight if for_decreasing else base_weight

    raw = filled.map(g)
    clipped = raw.clip(lower=min_active_share)
    s = clipped.sum()
    if not np.isfinite(s) or s <= min_active_share:
        return pd.Series(1.0 / len(clipped), index=clipped.index)
    return clipped / s


def _infer_age_ffill(df: pd.DataFrame) -> pd.Series:
    """Forward-fill asset_age, inferring by year increments where needed."""
    years = df["year"].values
    ages = df["asset_age"].values.astype(float)
    out = np.full_like(ages, np.nan, dtype=float)
    last_age, last_year = np.nan, None
    for i, (y, a) in enumerate(zip(years, ages)):
        if np.isfinite(a):
            out[i], last_age, last_year = a, a, y
        elif np.isfinite(last_age):
            out[i], last_year = last_age + (y - last_year), y
        else:
            out[i] = np.nan
    return pd.Series(out, index=df.index).ffill().fillna(0.0)


def _build_asset_panel_full_horizon(
    assets: pd.DataFrame,
    cid: str,
    geo: str,
    sector: str,
    tech: str,
    min_year: int,
    max_year: int,
) -> pd.DataFrame:
    """
    Build expanding panel from min_year..max_year:
      - asset appears from its first observed year onward (no pre-birth zeros)
      - capacity uses actual forecast values (no forward-filling)
      - age forward-fills / inferred linearly
    Returns: ['asset_id','company_id','scenario_geography','sector','technology','year','capacity','asset_age']
    """
    cols = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "capacity",
        "asset_age",
    ]
    pool = assets.loc[
        (assets["company_id"] == cid)
        & (assets["scenario_geography"] == geo)
        & (assets["sector"] == sector)
        & (assets["technology"] == tech),
        cols,
    ].copy()
    if pool.empty:
        return pd.DataFrame(columns=cols)

    pool["year"] = pool["year"].astype(int)

    # For the staggered shock mechanism, we only want years where we have actual forecast data
    # Don't create artificial years beyond the forecast horizon
    years_with_data = sorted(pool["year"].unique())
    available_years = [y for y in range(min_year, max_year + 1) if y in years_with_data]

    if not available_years:
        return pd.DataFrame(columns=cols)

    # Filter pool to only include the requested year range
    pool = pool[pool["year"].isin(available_years)].copy()

    # Get asset metadata
    meta = pool[
        ["asset_id", "company_id", "scenario_geography", "sector", "technology"]
    ].drop_duplicates()

    # Use actual data without forward-filling capacity
    panel = pool.copy()

    # Only forward-fill/infer asset_age, keep actual capacity values
    panel = panel.sort_values(["asset_id", "year"]).reset_index(drop=True)
    panel["asset_age"] = _infer_age_ffill(panel)

    return panel[
        [
            "asset_id",
            "company_id",
            "scenario_geography",
            "sector",
            "technology",
            "year",
            "capacity",
            "asset_age",
        ]
    ].copy()


def _unique_base(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure 1 row per asset_id with summed capacity_after_shock."""
    if df.empty:
        return df
    if df.index.name == "asset_id":
        df = df.reset_index()
    agg = df.groupby("asset_id", as_index=False).agg(
        company_id=("company_id", "first"),
        scenario_geography=("scenario_geography", "first"),
        sector=("sector", "first"),
        technology=("technology", "first"),
        asset_age=("asset_age", "max"),
        capacity_after_shock=("capacity_after_shock", "sum"),
    )
    return agg.set_index("asset_id")


# ===================== one-year allocators ======================


def _apply_asset_retirements(
    cap0: pd.Series,
    current_year: int,
    retirement_events: list,
) -> pd.Series:
    """
    Apply asset retirements unconditionally, independent of any shocks.
    This mimics the retirement logic from the late & sudden mechanism.

    Args:
        cap0: Current capacity by asset_id
        current_year: The year for which to apply retirements
        retirement_events: List of (retirement_year, asset_id, capacity) tuples

    Returns:
        Updated capacity series after applying retirements
    """
    cap_after_retirement = cap0.copy()

    # Apply retirements for assets scheduled to retire this year
    for retirement_year, asset_id, retirement_capacity in retirement_events:
        if retirement_year == current_year and asset_id in cap_after_retirement.index:
            current_capacity = cap_after_retirement[asset_id]
            if current_capacity > 0:
                # Calculate percentage decrease like in late & sudden mechanism
                percentage_decrease = min(retirement_capacity / current_capacity, 1.0)
                cap_after_retirement[asset_id] *= 1 - percentage_decrease
                # Ensure non-negative
                cap_after_retirement[asset_id] = max(
                    cap_after_retirement[asset_id], 0.0
                )

    return cap_after_retirement


def _allocate_decrease_one_year(
    base_prev: pd.DataFrame,
    ceiling_y: pd.DataFrame,
    shock: float,
    k: float,
    min_active_share: float,
    n_quantiles: int,
    max_depth: int,
):
    """Allocate a negative shock across assets (decreasing tech)."""
    base = _unique_base(base_prev)

    # Use actual forecast capacity from ceiling_y as the starting point
    ceiling_indexed = ceiling_y.set_index("asset_id")
    if not ceiling_indexed.empty:
        # Use actual forecast capacity for current year
        cap0 = ceiling_indexed["capacity"].rename("capacity_before_shock")
        ages = ceiling_indexed["asset_age"]
        # Only consider assets that exist in the forecast for this year
        base = base.reindex(cap0.index).dropna()
    else:
        # Fallback to previous capacity if no current year data
        cap0 = base["capacity_after_shock"].rename("capacity_before_shock")
        ages = (
            ceiling_y.set_index("asset_id")["asset_age"]
            .reindex(cap0.index)
            .fillna(base["asset_age"] + 1)
        )

    g = _compute_g_weights(ages, k, min_active_share, n_quantiles, for_decreasing=True)
    order = ages.sort_values(ascending=False).index.tolist()  # oldest → youngest

    alloc = pd.Series(0.0, index=order)
    rem = shock
    depth = 0
    active = order.copy()

    while rem < -1e-12 and active and depth < max_depth:
        depth += 1
        gw = g.loc[active] / g.loc[active].sum()
        prop = gw * rem  # negative
        changed = False
        for aid in list(active):
            base_cap = float(cap0[aid])
            lower = -base_cap  # floor at zero
            delta = max(float(prop[aid]), lower - alloc[aid])
            if delta != 0.0:
                alloc[aid] += delta
                changed = True
        rem = float(shock - alloc.sum())
        active = [a for a in active if cap0[a] + alloc[a] > 0]
        if not changed:
            break

    out = pd.DataFrame(
        {
            "asset_id": order,
            "capacity_before_shock": cap0.reindex(order).values,
            "allocated_shock": alloc.reindex(order).values,
            "capacity_after_shock": (cap0.reindex(order) + alloc.reindex(order)).values,
            "asset_age": ages.reindex(order).values,
        }
    ).set_index("asset_id")
    return out, rem, depth


def _allocate_increase_one_year(
    base_prev: pd.DataFrame,
    ceiling_y: pd.DataFrame,
    shock: float,
    k: float,
    min_active_share: float,
    n_quantiles: int,
    max_depth: int,
):
    """Allocate a positive shock across assets (increasing tech)."""
    base = _unique_base(base_prev)
    cap0 = base["capacity_after_shock"].rename("capacity_before_shock")
    ceil = ceiling_y.set_index("asset_id")
    ages = ceil["asset_age"].reindex(cap0.index).fillna(base["asset_age"] + 1)

    g = _compute_g_weights(ages, k, min_active_share, n_quantiles, for_decreasing=False)
    order = ages.sort_values(ascending=True).index.tolist()  # newest → oldest

    alloc = pd.Series(0.0, index=order)
    rem = shock
    depth = 0
    active = order.copy()

    while rem > 1e-12 and active and depth < max_depth:
        depth += 1
        gw = g.loc[active] / g.loc[active].sum()
        prop = gw * rem
        changed = False
        for aid in list(active):
            headroom = 0.0
            if aid in ceil.index:
                headroom = max(0.0, float(ceil.at[aid, "capacity"]) - float(cap0[aid]))
            delta = min(float(prop[aid]), headroom - alloc[aid])
            if delta > 0:
                alloc[aid] += delta
                changed = True
        rem = float(shock - alloc.sum())
        active = [
            a
            for a in active
            if a in ceil.index
            and float(cap0[a]) + float(alloc[a]) < float(ceil.at[a, "capacity"])
        ]
        if not changed:
            break

    out = pd.DataFrame(
        {
            "asset_id": order,
            "capacity_before_shock": cap0.reindex(order).values,
            "allocated_shock": alloc.reindex(order).values,
            "capacity_after_shock": (cap0.reindex(order) + alloc.reindex(order)).values,
            "asset_age": ages.reindex(order).values,
        }
    ).set_index("asset_id")
    return out, rem, depth


# =================== allocators by bucket ======================


def allocate_decreasing_tech(
    late_sudden_trajectories: pd.DataFrame,
    assets_forecasts: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
    n_quantiles: int = 3,
    max_recursion_depth: int = 100,
    debug: bool = False,
):
    """
    Distribute **all negative changes** in L&S (full horizon) to assets for decreasing techs.
    Geography-aware (scenario_geography).

    For misaligned_high_carbon companies, asset retirements are applied first to match
    the late & sudden shock mechanism behavior before applying age-based allocation rules.
    """
    group_cols = ["company_id", "scenario_geography", "sector", "technology"]
    d = (
        late_sudden_trajectories[
            group_cols + ["year", "company_trajectory_latesudden", "alignment_type"]
        ]
        .sort_values(group_cols + ["year"])
        .copy()
    )
    d["prev"] = d.groupby(group_cols)["company_trajectory_latesudden"].shift(1)
    d["shock_raw"] = d["company_trajectory_latesudden"] - d["prev"]
    d["shock_eff"] = np.minimum(d["shock_raw"].fillna(0.0), 0.0)

    # Prepare retirement events lookup for misaligned high carbon companies
    # Keep asset-level retirement information for precise asset targeting
    retirement_events = {}
    if not assets_retirement_dates.empty:
        retire_df = assets_retirement_dates.copy()
        retire_key_cols = ["company_id", "scenario_geography", "sector", "technology"]
        retire_df = retire_df.sort_values(retire_key_cols + ["retirement_year"])
        for key, sub in retire_df.groupby(retire_key_cols, sort=False):
            # Store list of (year, asset_id, capacity) tuples for precise targeting
            retirement_events[key] = list(
                zip(
                    sub["retirement_year"].tolist(),
                    sub["asset_id"].tolist(),
                    sub["capacity"].astype(float).tolist(),
                )
            )

    outputs, diags = [], []
    cols_out = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "asset_age",
        "capacity_before_shock",
        "allocated_shock",
        "capacity_after_shock",
        "is_synthetic",
    ]

    groups = list(d.groupby(group_cols, sort=False))
    for key, grp in tqdm(
        groups, desc="Processing companies (decreasing tech)", unit="company"
    ):
        cid, geo, sector, tech = key
        years = sorted(grp["year"].unique())
        y0, yN = int(years[0]), int(years[-1])

        # Check if this is a misaligned high carbon company
        is_misaligned_high_carbon = any(
            grp["alignment_type"] == "misaligned_high_carbon"
        )

        panel = _build_asset_panel_full_horizon(
            assets_forecasts, cid, geo, sector, tech, y0, yN
        )

        # anchor at first L&S year
        ceil0 = panel[panel["year"] == y0].copy()
        out0 = ceil0.assign(
            capacity_before_shock=ceil0["capacity"],
            allocated_shock=0.0,
            capacity_after_shock=ceil0["capacity"],
            is_synthetic=False,
        )[cols_out]
        outputs.append(out0)
        base_prev = out0.set_index("asset_id")[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "asset_age",
                "capacity_after_shock",
            ]
        ]

        for _, row in grp[grp["year"] > y0].iterrows():
            y = int(row["year"])
            shock = float(row["shock_eff"])  # <= 0
            ceil_y = panel[panel["year"] == y].copy()

            # Get the starting capacity (from forecast data)
            ceil_y_indexed = ceil_y.set_index("asset_id")
            if not ceil_y_indexed.empty:
                cap_before_retirement = ceil_y_indexed["capacity"]
                ages = ceil_y_indexed["asset_age"]
            else:
                # Fallback to previous year if no forecast data available
                cap_before_retirement = base_prev["capacity_after_shock"]
                ages = (
                    ceil_y.set_index("asset_id")["asset_age"]
                    .reindex(cap_before_retirement.index)
                    .fillna(base_prev["asset_age"] + 1)
                )

            # Step 1: Apply retirements unconditionally for misaligned high carbon companies
            if is_misaligned_high_carbon:
                cap_after_retirement = _apply_asset_retirements(
                    cap_before_retirement, y, retirement_events.get(key, [])
                )
            else:
                cap_after_retirement = cap_before_retirement.copy()

            # Step 2: Apply shocks on top of post-retirement capacities
            if np.isclose(shock, 0.0) or base_prev.empty:
                # No shock to apply, just use post-retirement capacities
                out = pd.DataFrame(
                    {
                        "asset_id": cap_after_retirement.index,
                        "company_id": cid,
                        "scenario_geography": geo,
                        "sector": sector,
                        "technology": tech,
                        "year": y,
                        "asset_age": ages.values,
                        "capacity_before_shock": cap_before_retirement.values,
                        "allocated_shock": (
                            cap_after_retirement - cap_before_retirement
                        ).values,
                        "capacity_after_shock": cap_after_retirement.values,
                        "is_synthetic": False,
                    }
                )
                outputs.append(out[cols_out])
                base_prev = out.set_index("asset_id")[
                    [
                        "company_id",
                        "scenario_geography",
                        "sector",
                        "technology",
                        "asset_age",
                        "capacity_after_shock",
                    ]
                ]
                diags.append(
                    {
                        "company_id": cid,
                        "technology": tech,
                        "year": y,
                        "residual": 0.0,
                        "iters": 0,
                    }
                )
                continue

            # Apply shocks using post-retirement capacities as the base
            # Create a temporary base_prev that reflects post-retirement state
            temp_base = pd.DataFrame(
                {
                    "asset_id": cap_after_retirement.index,
                    "company_id": cid,
                    "scenario_geography": geo,
                    "sector": sector,
                    "technology": tech,
                    "asset_age": ages.values,
                    "capacity_after_shock": cap_after_retirement.values,
                }
            ).set_index("asset_id")

            # For misaligned high carbon companies, use standard allocation (retirement already applied)
            if is_misaligned_high_carbon:
                out, rem, iters = _allocate_decrease_one_year(
                    temp_base.reset_index(),
                    ceil_y,
                    shock,
                    g_k,
                    min_active_share,
                    n_quantiles,
                    max_recursion_depth,
                )
            else:
                # Use standard allocation for aligned high carbon companies
                out, rem, iters = _allocate_decrease_one_year(
                    temp_base.reset_index(),
                    ceil_y,
                    shock,
                    g_k,
                    min_active_share,
                    n_quantiles,
                    max_recursion_depth,
                )

            # Adjust the output to show retirement + shock effects
            out = out.reset_index()
            out["capacity_before_shock"] = cap_before_retirement.reindex(
                out["asset_id"]
            ).values
            # allocated_shock should include both retirement and shock effects
            out["allocated_shock"] = (
                out["capacity_after_shock"] - out["capacity_before_shock"]
            )

            out = out.assign(
                company_id=cid,
                scenario_geography=geo,
                sector=sector,
                technology=tech,
                year=y,
                is_synthetic=False,
            )
            outputs.append(out[cols_out])
            base_prev = out.set_index("asset_id")[
                [
                    "company_id",
                    "scenario_geography",
                    "sector",
                    "technology",
                    "asset_age",
                    "capacity_after_shock",
                ]
            ]
            diags.append(
                {
                    "company_id": cid,
                    "technology": tech,
                    "year": y,
                    "residual": rem,
                    "iters": iters,
                }
            )

    df = (
        pd.concat(outputs, ignore_index=True)
        if outputs
        else pd.DataFrame(columns=cols_out)
    )
    if debug:
        return df, pd.DataFrame(diags)
    return df


def allocate_increasing_tech(
    late_sudden_trajectories: pd.DataFrame,
    assets_forecasts: pd.DataFrame,
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
    n_quantiles: int = 3,
    max_recursion_depth: int = 100,
    debug: bool = False,
):
    """
    Distribute **all positive changes** in L&S (full horizon) to assets for increasing techs.
    Geography-aware. Uses ONE persistent synthetic asset per (company_id, scenario_geography, sector, technology).
    Ensures the synthetic row is never duplicated (never included in the 'real' block).
    """
    group_cols = ["company_id", "scenario_geography", "sector", "technology"]
    d = (
        late_sudden_trajectories[group_cols + ["year", "company_trajectory_latesudden"]]
        .sort_values(group_cols + ["year"])
        .copy()
    )
    d["prev"] = d.groupby(group_cols)["company_trajectory_latesudden"].shift(1)
    d["shock_raw"] = d["company_trajectory_latesudden"] - d["prev"]
    d["shock_eff"] = np.maximum(d["shock_raw"].fillna(0.0), 0.0)

    outputs, diags = [], []
    cols_out = [
        "asset_id",
        "company_id",
        "scenario_geography",
        "sector",
        "technology",
        "year",
        "asset_age",
        "capacity_before_shock",
        "allocated_shock",
        "capacity_after_shock",
        "is_synthetic",
    ]

    def _get_prev_scalar(
        df: pd.DataFrame, aid: str, col: str, default: float = 0.0
    ) -> float:
        """Safe and fast scalar getter even if df might contain duplicate index rows.
        Tries direct .at access when unique, otherwise falls back to last row selection.
        """
        if df.empty or aid not in df.index:
            return default
        # Fast path when there are no duplicates
        if not df.index.has_duplicates:
            try:
                val = df.at[aid, col]
                return float(val)
            except Exception:
                return default
        # Fallback when duplicates exist
        vals = df.loc[[aid], col]
        try:
            return float(vals.iloc[-1])
        except Exception:
            return default

    groups = list(d.groupby(group_cols, sort=False))
    for key, grp in tqdm(
        groups, desc="Processing companies (increasing tech)", unit="company"
    ):
        cid, geo, sector, tech = key
        synth_id = f"NEW_{cid}_{sector}_{tech}_{geo}"

        years = sorted(grp["year"].unique())
        if not years:
            continue
        y0, yN = int(years[0]), int(years[-1])

        # Build full panel of *real* assets (synthetic never enters this)
        panel = _build_asset_panel_full_horizon(
            assets_forecasts, cid, geo, sector, tech, y0, yN
        )
        # Ensure asset_id is string for stable indexing and comparisons
        if not panel.empty and panel["asset_id"].dtype != object:
            panel["asset_id"] = panel["asset_id"].astype(str)

        # Cache per-year slices and age series to avoid repeated filtering/indexing
        if panel.empty:
            panel_by_year = {y: panel.iloc[0:0].copy() for y in years}
            ages_by_year = {y: pd.Series(dtype=float) for y in years}
        else:
            panel_by_year = {
                int(y): sub.copy() for y, sub in panel.groupby("year", sort=False)
            }
            ages_by_year = {
                int(y): sub.set_index("asset_id")["asset_age"]
                for y, sub in panel_by_year.items()
            }

        # Anchor at first L&S year using panel capacities (real assets only)
        ceil0 = panel_by_year.get(y0, panel.iloc[0:0].copy())
        out0 = ceil0.assign(
            capacity_before_shock=ceil0["capacity"],
            allocated_shock=0.0,
            capacity_after_shock=ceil0["capacity"],
            is_synthetic=False,
        )[cols_out]
        outputs.append(out0)

        base_prev = out0.set_index("asset_id")[
            [
                "company_id",
                "scenario_geography",
                "sector",
                "technology",
                "asset_age",
                "capacity_after_shock",
            ]
        ]
        # Keep index as string, ensure uniqueness only if needed
        if not base_prev.empty and base_prev.index.dtype != object:
            base_prev.index = base_prev.index.map(str)
        if base_prev.index.has_duplicates:
            base_prev = _unique_base(base_prev.reset_index())

        for _, row in grp[grp["year"] > y0].iterrows():
            y = int(row["year"])
            shock = float(row["shock_eff"])  # >= 0
            ceil_y = panel_by_year.get(y, panel.iloc[0:0].copy())

            # De-dup and split base into real vs synthetic parts
            if not base_prev.empty and base_prev.index.has_duplicates:
                base_prev = _unique_base(base_prev.reset_index())
            base_real_prev = base_prev.drop(index=[synth_id], errors="ignore")
            has_synth = synth_id in base_prev.index

            # ---------- Case 1: carry-forward (no positive change) ----------
            if np.isclose(shock, 0.0) and not base_prev.empty:
                # Real block carry-forward (exclude synthetic)
                if base_real_prev.empty:
                    real_out = pd.DataFrame(columns=cols_out)
                else:
                    cap0 = base_real_prev["capacity_after_shock"].rename(
                        "capacity_before_shock"
                    )
                    ages_src = ages_by_year.get(y, pd.Series(dtype=float))
                    ages = ages_src.reindex(cap0.index).fillna(
                        base_real_prev["asset_age"] + 1
                    )
                    real_out = pd.DataFrame(
                        {
                            "asset_id": cap0.index,
                            "company_id": cid,
                            "scenario_geography": geo,
                            "sector": sector,
                            "technology": tech,
                            "year": y,
                            "asset_age": ages.values,
                            "capacity_before_shock": cap0.values,
                            "allocated_shock": np.zeros_like(cap0.values),
                            "capacity_after_shock": cap0.values,
                            "is_synthetic": False,
                        }
                    )

                # Synthetic carry-forward (single row, if exists)
                synth_out = pd.DataFrame(columns=cols_out)
                if has_synth:
                    prev_cap = _get_prev_scalar(
                        base_prev, synth_id, "capacity_after_shock", 0.0
                    )
                    prev_age = (
                        _get_prev_scalar(base_prev, synth_id, "asset_age", 0.0) + 1.0
                    )
                    synth_out = pd.DataFrame(
                        [
                            {
                                "asset_id": synth_id,
                                "company_id": cid,
                                "scenario_geography": geo,
                                "sector": sector,
                                "technology": tech,
                                "year": y,
                                "asset_age": prev_age,
                                "capacity_before_shock": prev_cap,
                                "allocated_shock": 0.0,
                                "capacity_after_shock": prev_cap,
                                "is_synthetic": True,
                            }
                        ]
                    )
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", category=FutureWarning, message=".*all-NA columns.*"
                    )
                    # TODO: remove this warning silencer once synthetic assets are deduplicated properly
                    out = pd.concat([real_out, synth_out], ignore_index=True)

                outputs.append(out[cols_out])

                # chain base to next year
                base_prev = out.set_index("asset_id")[
                    [
                        "company_id",
                        "scenario_geography",
                        "sector",
                        "technology",
                        "asset_age",
                        "capacity_after_shock",
                    ]
                ]
                if not base_prev.empty and base_prev.index.dtype != object:
                    base_prev.index = base_prev.index.map(str)
                if base_prev.index.has_duplicates:
                    base_prev = _unique_base(base_prev.reset_index())
                diags.append(
                    {
                        "company_id": cid,
                        "technology": tech,
                        "year": y,
                        "residual": 0.0,
                        "iters": 0,
                    }
                )
                continue

            # ---------- Case 2: positive change to allocate ----------
            # If we have no *real* base yet (e.g., new fleet), initialize from real assets at y
            if base_real_prev.empty:
                real = ceil_y.copy()
                real["capacity_before_shock"] = real["capacity"]
                real["allocated_shock"] = 0.0
                real["capacity_after_shock"] = real["capacity"]
                real["is_synthetic"] = False
                real_out_init = real[cols_out]
                outputs.append(real_out_init)

                base_real_prev = real_out_init.set_index("asset_id")[
                    [
                        "company_id",
                        "scenario_geography",
                        "sector",
                        "technology",
                        "asset_age",
                        "capacity_after_shock",
                    ]
                ]
                if not base_real_prev.empty and base_real_prev.index.dtype != object:
                    base_real_prev.index = base_real_prev.index.map(str)
                if base_real_prev.index.has_duplicates:
                    base_real_prev = _unique_base(base_real_prev.reset_index())

            if shock <= 1e-12:
                diags.append(
                    {
                        "company_id": cid,
                        "technology": tech,
                        "year": y,
                        "residual": 0.0,
                        "iters": 0,
                    }
                )
                # keep the old base (we already appended init real rows if needed)
                base_prev = pd.concat(
                    [base_real_prev, base_prev.loc[[synth_id]]]
                    if has_synth
                    else [base_real_prev]
                )
                if base_prev.index.has_duplicates:
                    base_prev = _unique_base(base_prev.reset_index())
                continue

            # Allocate to real assets ONLY
            out_real, rem, iters = _allocate_increase_one_year(
                base_real_prev,
                ceil_y,
                shock,
                g_k,
                min_active_share,
                n_quantiles,
                max_recursion_depth,
            )
            out_real = out_real.reset_index().assign(
                company_id=cid,
                scenario_geography=geo,
                sector=sector,
                technology=tech,
                year=y,
                is_synthetic=False,
            )
            outputs.append(out_real[cols_out])

            # If leftover, update/create ONE synthetic row (not included in the real block)
            synth_out = pd.DataFrame(columns=cols_out)
            if rem > 1e-12:
                prev_cap = _get_prev_scalar(
                    base_prev, synth_id, "capacity_after_shock", 0.0
                )
                prev_age = _get_prev_scalar(base_prev, synth_id, "asset_age", 0.0)
                age_y = (prev_age + 1.0) if has_synth else 0.0
                synth_out = pd.DataFrame(
                    [
                        {
                            "asset_id": synth_id,
                            "company_id": cid,
                            "scenario_geography": geo,
                            "sector": sector,
                            "technology": tech,
                            "year": y,
                            "asset_age": age_y,
                            "capacity_before_shock": prev_cap,
                            "allocated_shock": rem,
                            "capacity_after_shock": prev_cap + rem,
                            "is_synthetic": True,
                        }
                    ]
                )
                outputs.append(synth_out[cols_out])
                rem = 0.0

            # chain base to next year: real next + (optional) synthetic next
            base_real_next = out_real.set_index("asset_id")[
                [
                    "company_id",
                    "scenario_geography",
                    "sector",
                    "technology",
                    "asset_age",
                    "capacity_after_shock",
                ]
            ]
            if not synth_out.empty:
                base_prev = pd.concat(
                    [
                        base_real_next,
                        synth_out.set_index("asset_id")[
                            [
                                "company_id",
                                "scenario_geography",
                                "sector",
                                "technology",
                                "asset_age",
                                "capacity_after_shock",
                            ]
                        ],
                    ],
                    axis=0,
                )
            else:
                # keep old synthetic if it existed and we didn't write a new row for it this year
                base_prev = (
                    pd.concat(
                        [base_real_next, base_prev.loc[[synth_id]]],
                        axis=0,
                        join="inner",
                    )
                    if has_synth
                    else base_real_next
                )

            if not base_prev.empty and base_prev.index.dtype != object:
                base_prev.index = base_prev.index.map(str)
            if base_prev.index.has_duplicates:
                base_prev = _unique_base(base_prev.reset_index())

            diags.append(
                {
                    "company_id": cid,
                    "technology": tech,
                    "year": y,
                    "residual": rem,
                    "iters": iters,
                }
            )

    df = (
        pd.concat(outputs, ignore_index=True)
        if outputs
        else pd.DataFrame(columns=cols_out)
    )
    if debug:
        return df, pd.DataFrame(diags)
    return df


# ========================= orchestrator =========================


def apply_staggered_shock_split(
    late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
    assets_retirement_dates: pd.DataFrame,
    shock_year: int,  # unused gating, kept for signature compatibility
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
    n_quantiles: int = 3,
    max_recursion_depth: int = 100,
    debug: bool = False,
):
    """
    Run the decreasing and increasing allocators across the full L&S horizon
    (no gating by shock_year) and concatenate.

    For decreasing technologies (misaligned_high_carbon), asset retirement information
    is used to prioritize specific assets for capacity reduction.
    """
    # Split by alignment type (unchanged behavior)
    dec_mask = late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )
    inc_mask = late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_low_carbon", "aligned_low_carbon"]
    )

    dec = allocate_decreasing_tech(
        late_sudden_trajectories[dec_mask],
        allocated_assets_to_companies,
        assets_retirement_dates,
        g_k,
        min_active_share,
        n_quantiles,
        max_recursion_depth,
        debug,
    )
    inc = allocate_increasing_tech(
        late_sudden_trajectories[inc_mask],
        allocated_assets_to_companies,
        g_k,
        min_active_share,
        n_quantiles,
        max_recursion_depth,
        debug,
    )

    if debug:
        dec_df, dec_diag = dec
        inc_df, inc_diag = inc
        return (
            pd.concat([dec_df, inc_df], ignore_index=True),
            pd.concat([dec_diag, inc_diag], ignore_index=True),
        )

    return pd.concat([dec, inc], ignore_index=True)


def aggregate_late_sudden_trajectories_to_company_level(
    all_assets_late_sudden_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Aggregate late sudden trajectories to company level.
    """

    companies_late_sudden_trajectories = (
        all_assets_late_sudden_trajectories.groupby(
            [
                "company_id",
                "company_name",
                "scenario_geography",
                "sector",
                "technology",
                "alignment_type",
                "late_sudden_phase",
                "year",
            ]
        )
        .agg(
            {
                "asset_activity": "sum",
                "asset_trajectory_baseline": "sum",
                "asset_trajectory_target": "sum",
                "asset_trajectory_latesudden": "sum",
            }
        )
        .rename(
            {
                "asset_activity": "company_activity",
                "asset_trajectory_baseline": "company_trajectory_baseline",
                "asset_trajectory_target": "company_trajectory_target",
                "asset_trajectory_latesudden": "company_trajectory_latesudden",
            },
            axis=1,
        )
        .reset_index()
    )

    return companies_late_sudden_trajectories
