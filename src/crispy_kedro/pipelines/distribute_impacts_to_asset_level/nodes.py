import pandas as pd
import numpy as np

# ============================ helpers ============================


def _compute_g_weights(
    ages: pd.Series, k: float, min_active_share: float, n_quantiles: int
) -> pd.Series:
    """Compute logistic-sum g(a) weights, clip and normalize."""
    if ages.empty:
        return pd.Series(dtype=float)
    ages = ages.astype(float)
    med = float(ages.median()) if np.isfinite(ages.median()) else 0.0
    filled = ages.fillna(med)
    qs = np.linspace(0, 1, n_quantiles + 1)[1:-1]
    age_q = np.quantile(filled, qs) if len(qs) else []

    def g(a):
        a = med if pd.isna(a) else a
        return 1 - sum(1 / (1 + np.exp(-k * (a - q))) for q in age_q)

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
    assets: pd.DataFrame, cid: str, tech: str, min_year: int, max_year: int
) -> pd.DataFrame:
    """
    Build expanding panel from min_year..max_year:
      - asset appears from its first observed year onward (no pre-birth zeros)
      - capacity forward-fills
      - age forward-fills / inferred linearly
    Returns: ['asset_id','company_id','technology','year','capacity','asset_age']
    """
    cols = ["asset_id", "company_id", "technology", "year", "capacity", "asset_age"]
    pool = assets.loc[
        (assets["company_id"] == cid) & (assets["technology"] == tech), cols
    ].copy()
    if pool.empty:
        return pd.DataFrame(columns=cols)

    pool["year"] = pool["year"].astype(int)

    first = (
        pool.groupby("asset_id", as_index=False)["year"]
        .min()
        .rename(columns={"year": "first_year"})
    )
    meta = first.merge(
        pool[["asset_id", "company_id", "technology"]].drop_duplicates(),
        on="asset_id",
        how="left",
    )

    horizon = pd.DataFrame({"year": np.arange(min_year, max_year + 1, dtype=int)})
    grid = (
        meta.assign(_=1)
        .merge(horizon.assign(_=1), on="_")
        .query("year >= first_year")
        .drop(columns=["_", "first_year"])
    )

    panel = grid.merge(pool, on=["asset_id", "year"], how="left").sort_values(
        ["asset_id", "year"]
    )
    panel["capacity"] = panel.groupby("asset_id")["capacity"].ffill()
    panel["asset_age"] = _infer_age_ffill(panel)
    panel = panel.merge(
        meta[["asset_id", "company_id", "technology"]], on="asset_id", how="left"
    )

    return panel[cols].copy()


def _unique_base(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure 1 row per asset_id with summed capacity_after_shock."""
    if df.empty:
        return df
    if df.index.name == "asset_id":
        df = df.reset_index()
    agg = df.groupby("asset_id", as_index=False).agg(
        company_id=("company_id", "first"),
        technology=("technology", "first"),
        asset_age=("asset_age", "max"),
        capacity_after_shock=("capacity_after_shock", "sum"),
    )
    return agg.set_index("asset_id")


# ===================== one-year allocators ======================


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
    cap0 = base["capacity_after_shock"].rename("capacity_before_shock")
    ages = (
        ceiling_y.set_index("asset_id")["asset_age"]
        .reindex(cap0.index)
        .fillna(base["asset_age"] + 1)
    )

    g = _compute_g_weights(ages, k, min_active_share, n_quantiles)
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

    g = _compute_g_weights(ages, k, min_active_share, n_quantiles)
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
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
    n_quantiles: int = 3,
    max_recursion_depth: int = 100,
    debug: bool = False,
):
    """
    Distribute **all negative changes** in L&S (full horizon) to assets for decreasing techs.
    """
    d = late_sudden_trajectories[
        ["company_id", "technology", "year", "company_trajectory_latesudden"]
    ].sort_values(["company_id", "technology", "year"])
    d["prev"] = d.groupby(["company_id", "technology"])[
        "company_trajectory_latesudden"
    ].shift(1)
    d["shock_raw"] = d["company_trajectory_latesudden"] - d["prev"]
    # NO SHOCK-YEAR GATE: allocate every decrease across the horizon
    d["shock_eff"] = np.minimum(d["shock_raw"].fillna(0.0), 0.0)

    outputs, diags = [], []
    cols_out = [
        "asset_id",
        "company_id",
        "technology",
        "year",
        "asset_age",
        "capacity_before_shock",
        "allocated_shock",
        "capacity_after_shock",
        "is_synthetic",
    ]

    for (cid, tech), grp in d.groupby(["company_id", "technology"], sort=False):
        years = sorted(grp["year"].unique())
        y0, yN = int(years[0]), int(years[-1])
        panel = _build_asset_panel_full_horizon(assets_forecasts, cid, tech, y0, yN)

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
            ["company_id", "technology", "asset_age", "capacity_after_shock"]
        ]

        for _, row in grp[grp["year"] > y0].iterrows():
            y = int(row["year"])
            shock = float(row["shock_eff"])  # <= 0
            ceil_y = panel[panel["year"] == y].copy()

            if np.isclose(shock, 0.0) or base_prev.empty:
                # carry forward unchanged
                cap0 = base_prev["capacity_after_shock"].rename("capacity_before_shock")
                ages = (
                    ceil_y.set_index("asset_id")["asset_age"]
                    .reindex(cap0.index)
                    .fillna(base_prev["asset_age"] + 1)
                )
                out = pd.DataFrame(
                    {
                        "asset_id": cap0.index,
                        "company_id": cid,
                        "technology": tech,
                        "year": y,
                        "asset_age": ages.values,
                        "capacity_before_shock": cap0.values,
                        "allocated_shock": np.zeros_like(cap0.values),
                        "capacity_after_shock": cap0.values,
                        "is_synthetic": False,
                    }
                )
                outputs.append(out[cols_out])
                base_prev = out.set_index("asset_id")[
                    ["company_id", "technology", "asset_age", "capacity_after_shock"]
                ]
                diags.append(
                    {
                        "company_id": cid,
                        "technology": tech,
                        "year": y,
                        "residual": shock,
                        "iters": 0,
                    }
                )
                continue

            out, rem, iters = _allocate_decrease_one_year(
                base_prev,
                ceil_y,
                shock,
                g_k,
                min_active_share,
                n_quantiles,
                max_recursion_depth,
            )
            out = out.reset_index().assign(
                company_id=cid, technology=tech, year=y, is_synthetic=False
            )
            outputs.append(out[cols_out])
            base_prev = out.set_index("asset_id")[
                ["company_id", "technology", "asset_age", "capacity_after_shock"]
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
    """
    d = late_sudden_trajectories[
        ["company_id", "technology", "year", "company_trajectory_latesudden"]
    ].sort_values(["company_id", "technology", "year"])
    d["prev"] = d.groupby(["company_id", "technology"])[
        "company_trajectory_latesudden"
    ].shift(1)
    d["shock_raw"] = d["company_trajectory_latesudden"] - d["prev"]
    # NO SHOCK-YEAR GATE: allocate every increase across the horizon
    d["shock_eff"] = np.maximum(d["shock_raw"].fillna(0.0), 0.0)

    outputs, diags = [], []
    cols_out = [
        "asset_id",
        "company_id",
        "technology",
        "year",
        "asset_age",
        "capacity_before_shock",
        "allocated_shock",
        "capacity_after_shock",
        "is_synthetic",
    ]

    for (cid, tech), grp in d.groupby(["company_id", "technology"], sort=False):
        years = sorted(grp["year"].unique())
        y0, yN = int(years[0]), int(years[-1])
        panel = _build_asset_panel_full_horizon(assets_forecasts, cid, tech, y0, yN)

        # anchor
        ceil0 = panel[panel["year"] == y0].copy()
        out0 = ceil0.assign(
            capacity_before_shock=ceil0["capacity"],
            allocated_shock=0.0,
            capacity_after_shock=ceil0["capacity"],
            is_synthetic=False,
        )[cols_out]
        outputs.append(out0)
        base_prev = out0.set_index("asset_id")[
            ["company_id", "technology", "asset_age", "capacity_after_shock"]
        ]

        for _, row in grp[grp["year"] > y0].iterrows():
            y = int(row["year"])
            shock = float(row["shock_eff"])  # >= 0
            ceil_y = panel[panel["year"] == y].copy()
            synth = None

            if np.isclose(shock, 0.0) and not base_prev.empty:
                # carry forward unchanged
                cap0 = base_prev["capacity_after_shock"].rename("capacity_before_shock")
                ages = (
                    ceil_y.set_index("asset_id")["asset_age"]
                    .reindex(cap0.index)
                    .fillna(base_prev["asset_age"] + 1)
                )
                out = pd.DataFrame(
                    {
                        "asset_id": cap0.index,
                        "company_id": cid,
                        "technology": tech,
                        "year": y,
                        "asset_age": ages.values,
                        "capacity_before_shock": cap0.values,
                        "allocated_shock": np.zeros_like(cap0.values),
                        "capacity_after_shock": cap0.values,
                        "is_synthetic": False,
                    }
                )
                outputs.append(out[cols_out])
                base_prev = out.set_index("asset_id")[
                    ["company_id", "technology", "asset_age", "capacity_after_shock"]
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

            if base_prev.empty:
                # no existing base → emit whatever real assets exist at y (they’ll be 1st year capacity)
                real = ceil_y.copy()
                real["capacity_before_shock"] = real["capacity"]
                real["allocated_shock"] = 0.0
                real["capacity_after_shock"] = real["capacity"]
                real["is_synthetic"] = False
                outputs.append(real[cols_out])
                base_prev = real.set_index("asset_id")[
                    ["company_id", "technology", "asset_age", "capacity_after_shock"]
                ]

            if shock <= 1e-12:
                # nothing to allocate
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

            out, rem, iters = _allocate_increase_one_year(
                base_prev,
                ceil_y,
                shock,
                g_k,
                min_active_share,
                n_quantiles,
                max_recursion_depth,
            )
            out = out.reset_index().assign(
                company_id=cid, technology=tech, year=y, is_synthetic=False
            )
            outputs.append(out[cols_out])

            if rem > 1e-12:
                synth = pd.DataFrame(
                    [
                        {
                            "asset_id": f"NEW_{cid}_{tech}_{y}",
                            "company_id": cid,
                            "technology": tech,
                            "year": y,
                            "asset_age": 0.0,
                            "capacity_before_shock": 0.0,
                            "allocated_shock": rem,
                            "capacity_after_shock": rem,
                            "is_synthetic": True,
                        }
                    ]
                )
                outputs.append(synth[cols_out])
                rem = 0.0
                # include synthetic in base for chaining
                base_prev = pd.concat(
                    [
                        out.set_index("asset_id")[
                            [
                                "company_id",
                                "technology",
                                "asset_age",
                                "capacity_after_shock",
                            ]
                        ],
                        synth.set_index("asset_id")[
                            [
                                "company_id",
                                "technology",
                                "asset_age",
                                "capacity_after_shock",
                            ]
                        ],
                    ]
                )
            else:
                base_prev = out.set_index("asset_id")[
                    ["company_id", "technology", "asset_age", "capacity_after_shock"]
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


# ========================= orchestrator =========================


def apply_staggered_shock_split(
    late_sudden_trajectories: pd.DataFrame,
    allocated_assets_to_companies: pd.DataFrame,
    shock_year: int,  # kept for signature compatibility; not gating shocks anymore
    g_k: float = 6.0,
    min_active_share: float = 1e-12,
    n_quantiles: int = 3,
    max_recursion_depth: int = 100,
    debug: bool = False,
):
    """
    Run the decreasing and increasing allocators across the full L&S horizon
    (no gating by shock_year) and concatenate.
    """
    dec_mask = late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_high_carbon", "aligned_high_carbon"]
    )
    inc_mask = late_sudden_trajectories["alignment_type"].isin(
        ["misaligned_low_carbon", "aligned_low_carbon"]
    )

    dec = allocate_decreasing_tech(
        late_sudden_trajectories[dec_mask],
        allocated_assets_to_companies,
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
        return pd.concat([dec_df, inc_df], ignore_index=True), pd.concat(
            [dec_diag, inc_diag], ignore_index=True
        )

    return pd.concat([dec, inc], ignore_index=True)
