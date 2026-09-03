"""
Valuation model pipeline nodes for converting earnings to NPV using DCF methodology.
"""

import logging

import numpy as np
import pandas as pd

from altr_model._validation import validate_choice

logger = logging.getLogger(__name__)


CARBONTECH_ALIGNMENTS = {"misaligned_high_carbon", "aligned_high_carbon"}

#: What decides that an asset is "brown", for the discount spread AND the
#: terminal growth rate alike — owner ruling 13 tied both to one carrier.
SPREAD_CARRIER_TECHNOLOGY = "technology"
SPREAD_CARRIER_ALIGNMENT = "alignment_type"
SPREAD_CARRIERS = (SPREAD_CARRIER_TECHNOLOGY, SPREAD_CARRIER_ALIGNMENT)

#: What a non-stranded group with a negative terminal FCFF is worth.
NEGATIVE_TV_METHODS = ("perpetuity", "bounded_annuity")

#: What the terminal anchor is allowed to see.
TV_ANCHOR_POLICIES = ("raw", "operating")

#: The asset-series grain `asset_horizon_attributes` is keyed on — the same
#: `ASSET_SERIES_KEYS` the earnings stage writes it at. The valuation group keys
#: add name and classification columns, all functionally dependent on these six,
#: so one horizon row serves one valuation group.
HORIZON_ATTRIBUTE_KEYS = [
    "company_id",
    "asset_id",
    "scenario_geography",
    "sector",
    "technology",
    "trajectory_type",
]


def _horizon_attributes_per_group(
    npv_data: pd.DataFrame,
    last_idx: np.ndarray,
    asset_horizon_attributes: pd.DataFrame | None,
) -> pd.DataFrame | None:
    """`asset_horizon_attributes` re-indexed to one row per valuation group.

    Returns None when the table is absent, empty, or does not carry the join
    keys — every caller then falls back exactly as a frame without the table
    always has (no exit floor, the tier-2 annuity horizon). A group with no
    matching row gets NaN across the merge and takes the same fallbacks.

    A table carrying MORE than one row per asset series raises instead: there
    is no defensible way to choose between two different horizons for the same
    asset, and picking one quietly would mis-price the exit.
    """
    if asset_horizon_attributes is None or asset_horizon_attributes.empty:
        return None
    missing = [
        column
        for column in HORIZON_ATTRIBUTE_KEYS
        if column not in asset_horizon_attributes.columns
        or column not in npv_data.columns
    ]
    if missing:
        logger.warning(
            "asset_horizon_attributes cannot be joined — missing key column(s) "
            "%s; the terminal-value fallbacks apply",
            missing,
        )
        return None

    group_keys = npv_data.iloc[last_idx][HORIZON_ATTRIBUTE_KEYS].reset_index(drop=True)
    # ONE mechanism, and it is the one that raises. A `drop_duplicates` here
    # would silently keep whichever duplicate came first — and it also made
    # `validate="many_to_one"` unreachable, so the guard that looked like the
    # protection could never fire. The earnings stage emits exactly one row per
    # asset series (`tail(1)` over `ASSET_SERIES_KEYS`), so a duplicate key is a
    # broken input, not a case to paper over: the merge raises and names it.
    merged = group_keys.merge(
        asset_horizon_attributes,
        on=HORIZON_ATTRIBUTE_KEYS,
        how="left",
        validate="many_to_one",
    )
    unmatched = int(merged.drop(columns=HORIZON_ATTRIBUTE_KEYS).isna().all(axis=1).sum())
    if unmatched:
        logger.warning(
            "%d of %d valuation groups have no asset_horizon_attributes row; "
            "they take the terminal-value fallbacks",
            unmatched,
            len(merged),
        )
    return merged


def compute_yearly_npv_trajectories(
    asset_earnings: pd.DataFrame,
    asset_horizon_attributes: pd.DataFrame | None = None,
    discount_rate_baseline: float = 0.07,
    discount_rate_shock: float = 0.08,
    terminal_growth_rate: float = 0.02,
    terminal_method: str = "perpetuity",
    terminal_growth_rate_brown: float | None = None,
    terminal_growth_rate_green: float | None = None,
    terminal_normalization_window: int = 1,
    brown_discount_spread: float = 0.0,
    green_discount_spread: float = 0.0,
    brown_technologies: list[str] | None = None,
    spread_carrier: str = "technology",
    stranding_aware_tv: bool = False,
    stranding_consecutive_years: int = 3,
    brown_remaining_life_years: int = 10,
    negative_tv_method: str = "perpetuity",
    tv_anchor_policy: str = "raw",
) -> pd.DataFrame:
    """
    Node 1: Compute yearly NPV trajectories with all financial components.

    Returns yearly trajectories for each asset-trajectory_type combination with:
    - Present value calculations for each year
    - All financial components (FCFF, EBITDA, revenue, costs)
    - Terminal value calculation in final year

    Args:
        asset_horizon_attributes: One row per asset series carrying its
            lifetime, age, scrap price and capacity in the LAST forecast year —
            what the bounded negative branch below prices its remaining life and
            its exit off. Optional: without it every group falls back to the
            tier-2 annuity horizon and takes no exit floor.
        terminal_growth_rate_brown / terminal_growth_rate_green: Terminal growth
            rate for a `brown_technologies` member / everything else. Either
            falling back to terminal_growth_rate when None. A declining fossil
            asset does not grow into perpetuity, and a clean one may. Owner
            ruling 13 put this on the SAME carrier as the discount spread —
            membership of the list, not `alignment_type`, which had offshore
            wind and nuclear growing at the fossil rate whenever a scenario
            classed them `misaligned_high_carbon`.
        terminal_normalization_window: Number of final years averaged into the
            terminal FCFF. 1 is the last year alone; 3-5 is the Damodaran /
            McKinsey / CFA practice, and stops a single transition-period CapEx
            spike from erasing an asset's whole terminal value.
        brown_discount_spread: Carbon risk PREMIUM added to the assets named in
            `brown_technologies`. Bolton & Kacperczyk (2021, 2023) measure
            ~1.5-2.5% higher equity returns for high-emission firms, and no
            corresponding discount for clean ones — so there is a penalty leg
            and no greenium leg. 0 gives a uniform rate; a negative value is
            rejected rather than silently applied as a discount.
        green_discount_spread: The GREENIUM — a discount subtracted from every
            asset the carrier does not call brown. Live only under
            `spread_carrier="alignment_type"`; under the shipped "technology"
            carrier it is retired and ignored with a warning, because Bolton &
            Kacperczyk measure a penalty on high emitters and NO corresponding
            discount for clean firms. Kept as a parameter so the pre-ruling-12
            behaviour is reachable and measurable, not merely described.
        brown_technologies: The technologies that pay the premium under the
            "technology" carrier.
        spread_carrier: WHAT decides that an asset is brown — and it decides it
            for BOTH the discount spread (ruling 12) and the terminal growth
            rate (ruling 13), which the owner tied to one carrier.
            "technology" — membership of `brown_technologies`. What a lender
                prices is what the plant burns. Shipped.
            "alignment_type" — membership of `CARBONTECH_ALIGNMENTS`, the
                pre-ruling behaviour. Alignment describes an asset's trajectory
                against its scenario, not what it burns, so it misfired in both
                directions: offshore wind and nuclear classed
                `misaligned_high_carbon` paid the fossil penalty AND grew at the
                fossil rate, while oil classed `misaligned_low_carbon` collected
                the greenium. Kept reachable for the ablation batch so the
                ruling's effect can be measured rather than asserted.
            NOTE the tier-2 carbontech annuity below is NOT governed by this
            switch — it still selects on `alignment_type` under either carrier,
            pending its own ruling.
        stranding_aware_tv: Three-tier terminal value instead of a single
            perpetuity (Gourdel 2024):
            1. STRANDED — FCFF <= 0 for the last N years: TV = 0. A rational
               owner exercises the abandonment option rather than funding
               perpetual losses.
            2. DECLINING BUT PROFITABLE CARBONTECH — TV = a finite annuity over
               brown_remaining_life_years, not a perpetuity, because a fossil
               asset in transition has a finite remaining economic life.
            3. EVERYTHING ELSE — the standard Gordon Growth perpetuity.
        stranding_consecutive_years: How many consecutive loss-making years at
            the end of the horizon count as stranded. A company can weather one
            or two bad years; N in a row is a closure.
        brown_remaining_life_years: Annuity horizon for tier 2, and the
            fallback horizon for the bounded negative branch below.
        negative_tv_method: What a NON-stranded group with a negative terminal
            FCFF is worth.
            "perpetuity" — Gordon Growth on the negative cash flow, which is
                unbounded below: the asset is valued at less than nothing,
                forever.
            "bounded_annuity" — the least bad of the two choices an owner
                actually has: run the remaining life out at a loss
                (`final_fcff * annuity_factor(r, N_remaining)`) or pay to
                decommission now (`-decom_cost`). Both are negative, so the
                larger is the smaller loss. A loss-maker does not run at a
                loss forever — it exits.
                Where `N_remaining <= 0` and capacity is still standing, the
                run-out arm does NOT exist — there is no life left to run out —
                so the exit arm binds and TV = `-decom_cost` (owner ruling C2).
                Where neither arm is available (past its lifetime AND no scrap
                price to quote an exit at) the group takes no terminal value.
        tv_anchor_policy: What the terminal anchor is allowed to see.
            "raw" — the anchor is the mean FCFF of the last
                `terminal_normalization_window` years, whatever those years
                contain, and a group standing at zero capacity is valued like
                any other. The pre-proposal behaviour, kept for the ablation.
            "operating" — two corrections, both about the anchor describing a
                PERPETUITY:
                1. A group whose capacity at the horizon is zero has no
                   terminal value at all. There is no plant to run: whatever
                   the anchor says, TV = 0.
                2. The anchor excludes decommissioning charges. Decom is a
                   one-off exit cost booked into `capex_total`; capitalising it
                   into a perpetuity charges it every year forever.
    """

    logger.info("Computing yearly NPV trajectories...")

    # Each of these selects between behaviours that move published numbers, and
    # each was reached by an `if x == "a": ... else: ...`, so a misspelling did
    # not raise — it silently took the other arm. Reject at the top of the node
    # instead, naming the conf key and every legal value.
    validate_choice("dcf.negative_tv_method", negative_tv_method, NEGATIVE_TV_METHODS)
    validate_choice("dcf.tv_anchor_policy", tv_anchor_policy, TV_ANCHOR_POLICIES)
    validate_choice("dcf.spread_carrier", spread_carrier, SPREAD_CARRIERS)

    if stranding_aware_tv:
        logger.info(
            "Stranding-aware TV ENABLED (Gourdel 2024): "
            "stranded (>=%d consecutive loss years) -> TV=0; "
            "declining carbontech (profitable) -> %d-year finite annuity; "
            "greentech -> standard Gordon Growth perpetuity",
            stranding_consecutive_years,
            brown_remaining_life_years,
        )

    if negative_tv_method == "bounded_annuity":
        logger.info(
            "Bounded negative TV ENABLED: a non-stranded group with a negative "
            "terminal FCFF takes max(run-out annuity, -decommissioning cost) "
            "instead of an unbounded negative perpetuity"
        )

    if tv_anchor_policy == "operating":
        logger.info(
            "Operating terminal anchor ENABLED: zero capacity at the horizon "
            "means TV=0, and decommissioning charges are excluded from the "
            "anchor years' FCFF"
        )

    g_brown = (
        terminal_growth_rate_brown
        if terminal_growth_rate_brown is not None
        else terminal_growth_rate
    )
    g_green = (
        terminal_growth_rate_green
        if terminal_growth_rate_green is not None
        else terminal_growth_rate
    )

    npv_data = asset_earnings.copy()

    unresolved_mask = npv_data["scenario_type"].isna()
    if unresolved_mask.any():
        unresolved_asset_ids = sorted(npv_data.loc[unresolved_mask, "asset_id"].unique())
        raise ValueError(
            f"{len(unresolved_asset_ids)} asset(s) have no scenario_type resolved "
            f"and cannot be included in NPV: {unresolved_asset_ids}"
        )

    def get_discount_rate(scenario_type):
        if scenario_type == "baseline":
            return discount_rate_baseline
        elif scenario_type == "target":
            return discount_rate_shock
        else:
            raise ValueError(f"Invalid scenario type: {scenario_type}")

    # map() over the column instead of a row-wise apply: same per-value
    # semantics (including the raise above), one Python call per row instead
    # of one Series construction per row.
    base_rate = npv_data["scenario_type"].map(get_discount_rate).to_numpy(dtype=float)

    # Carbon risk premium on top of the scenario base rate, charged by
    # TECHNOLOGY. There is no green leg: the literature the spread rests on
    # measures a penalty on high emitters and no discount for clean firms.
    if brown_discount_spread < 0:
        raise ValueError(
            "dcf.brown_discount_spread is a risk PREMIUM and cannot be "
            f"negative (got {brown_discount_spread}). A negative value would "
            "make carbon-intensive assets cheaper to finance than everything "
            "else; use 0 for a uniform rate."
        )

    if green_discount_spread < 0:
        raise ValueError(
            "dcf.green_discount_spread is a DISCOUNT expressed as a positive "
            f"number of rate points (got {green_discount_spread}). The old "
            "greenium was -50 bps, entered as 0.005; a negative value here "
            "would be silently ignored by the selection below, so it is "
            "rejected instead."
        )

    brown_set = set(brown_technologies or ())

    # WHICH assets count as brown, for the spread here AND for the terminal
    # growth rate far below — owner ruling 13 tied the two to one carrier, so
    # they must not be able to disagree.
    if spread_carrier == SPREAD_CARRIER_ALIGNMENT:
        if "alignment_type" in npv_data.columns:
            is_brown_row = (
                npv_data["alignment_type"].isin(CARBONTECH_ALIGNMENTS).to_numpy()
            )
        else:
            is_brown_row = np.zeros(len(npv_data), dtype=bool)
    elif "technology" in npv_data.columns:
        is_brown_row = npv_data["technology"].isin(brown_set).to_numpy()
    else:
        is_brown_row = np.zeros(len(npv_data), dtype=bool)

    if spread_carrier == SPREAD_CARRIER_ALIGNMENT and brown_set:
        logger.warning(
            "dcf.brown_technologies has %d entries but spread_carrier is "
            "'alignment_type', so the list is ignored — brown selection runs "
            "on alignment_type for both the spread and terminal growth",
            len(brown_set),
        )
    if (
        brown_discount_spread > 0
        and spread_carrier == SPREAD_CARRIER_TECHNOLOGY
        and not brown_set
    ):
        logger.warning(
            "dcf.brown_discount_spread is %.1f bps but dcf.brown_technologies "
            "is empty, so no asset pays it and the rate is uniform",
            brown_discount_spread * 10000,
        )

    # The GREENIUM leg exists only under the alignment carrier. Under the
    # shipped technology carrier it is retired: Bolton & Kacperczyk measure a
    # penalty on high emitters and no discount for clean firms, so a non-zero
    # value here would be subsidising every non-fossil asset's valuation off
    # evidence that does not exist. Ignored loudly rather than quietly.
    greenium = green_discount_spread
    if greenium and spread_carrier != SPREAD_CARRIER_ALIGNMENT:
        logger.warning(
            "dcf.green_discount_spread is %.1f bps but dcf.spread_carrier is "
            "'%s', under which the greenium is retired (Bolton & Kacperczyk "
            "find no discount for clean firms); it is IGNORED. Set "
            "spread_carrier: 'alignment_type' to reach the pre-ruling-12 "
            "behaviour.",
            green_discount_spread * 10000,
            spread_carrier,
        )
        greenium = 0.0

    if brown_discount_spread > 0 and is_brown_row.any():
        logger.info(
            "Carbon risk premium: +%.1f bps on %d of %d asset-year rows, by "
            "%s — Bolton & Kacperczyk 2021/2023",
            brown_discount_spread * 10000,
            int(is_brown_row.sum()),
            len(npv_data),
            (
                "technology (" + ", ".join(sorted(brown_set)) + ")"
                if spread_carrier == SPREAD_CARRIER_TECHNOLOGY
                else "alignment_type"
            ),
        )
    green_rate = base_rate - greenium if greenium > 0 else base_rate
    npv_data["discount_rate"] = np.where(
        is_brown_row, base_rate + brown_discount_spread, green_rate
    )

    # Guard: need trajectory_type and FCFF
    need_cols = ["asset_id", "year", "FCFF", "trajectory_type"]
    missing = [c for c in need_cols if c not in npv_data.columns]
    if missing:
        raise ValueError(f"asset_earnings missing required columns for NPV: {missing}")

    # Ensure we have the financial components we want to include
    financial_cols = [
        "FCFF",
        "EBITDA",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "capex_total",
    ]
    available_financial_cols = [
        col for col in financial_cols if col in npv_data.columns
    ]
    if not available_financial_cols:
        logger.warning("No financial component columns found in asset_earnings")

    group_keys = [
        "asset_name",
        "asset_id",
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "is_synthetic",
        "alignment_type",
        "trajectory_type",
    ]

    # Collapse CapEx flow-split rows to ONE row per asset-year before any
    # row-indexed logic runs. Upstream, compute_capacity_flows emits separate
    # component rows per (asset, year) — operating, decommissioning, rollover —
    # and their FCFFs sum correctly for present value, but the terminal-value
    # anchor (the group's last ROW) assumes one row per year. In the 2026-08
    # WITCH audit 38% of asset-trajectories carried duplicate years in the
    # anchor zone, corrupting 3,414 nonzero terminal values.
    agg_map = {col: "sum" for col in available_financial_cols}
    agg_map["discount_rate"] = "first"
    # A cell whose FCFF rows are ALL missing sums to 0.0 -- pandas' default
    # min_count=0 -- and a 0.0 reads as a loss year in the stranding test far
    # below, so a data gap could write off an asset's whole terminal value.
    # Carry the observation count through the collapse so a filled zero can be
    # told apart from a measured one. ONLY the stranding test reads it: every
    # present-value number keeps the summed 0.0 it has always had.
    npv_data = npv_data.assign(_fcff_observed=npv_data["FCFF"].notna())
    agg_map["_fcff_observed"] = "sum"
    # The decommissioning charge booked inside capex_total. A genuine flow, so
    # it sums across the flow-split rows exactly as its parent does. Internal to
    # this node: it feeds the terminal anchor and never reaches the output.
    has_decom = "decom_cost" in npv_data.columns
    if has_decom:
        agg_map["decom_cost"] = "sum"
    pre_rows = len(npv_data)
    npv_data = npv_data.groupby(
        group_keys + ["year"], dropna=False, as_index=False
    ).agg(agg_map)
    if len(npv_data) != pre_rows:
        logger.info(
            "Collapsed %d flow-split rows into %d unique asset-year rows "
            "before terminal-value computation",
            pre_rows,
            len(npv_data),
        )

    # ------------------------------------------------------------------
    # Vectorised trajectory + terminal-value computation.
    #
    # This replaces a per-group Python loop measured at ~1.55 ms/group, i.e.
    # ~60 s per production run at ~40k groups. Semantics are unchanged and
    # pinned by tests/.../test_npv_vectorized_equivalence.py, which
    # re-implements the old loop and asserts frame equality.
    # ------------------------------------------------------------------

    # Group ids in the order the old groupby(sort=True) iterated, then sort rows
    # by (group, year) so every group is one contiguous, year-ordered block.
    # dropna=False keeps assets whose group keys contain NaN: the downstream
    # nodes keep them, and pandas' default silently discarded them here.
    gid = npv_data.groupby(group_keys, dropna=False, sort=True).ngroup().to_numpy()
    npv_data = npv_data.assign(_gid=gid).sort_values(
        ["_gid", "year"], kind="stable", ignore_index=True
    )
    gid = npv_data["_gid"].to_numpy()

    n_rows = len(npv_data)
    n_groups = int(gid.max()) + 1 if n_rows else 0
    sizes = np.bincount(gid, minlength=n_groups)
    starts = np.zeros(n_groups, dtype=np.int64)
    if n_groups:
        starts[1:] = np.cumsum(sizes)[:-1]
    last_idx = starts + sizes - 1
    # Distance from the end of each group — the trailing windows below.
    pos_from_end = sizes[gid] - 1 - (np.arange(n_rows) - starts[gid])

    # NaN years must fail loudly: the int casts below would silently wrap
    # NaN to INT64_MIN and produce astronomically wrong terminal values.
    n_nan_year = int(npv_data["year"].isna().sum())
    if n_nan_year:
        raise ValueError(
            f"asset_earnings contains {n_nan_year} rows with NaN year; "
            "cannot compute NPV trajectories"
        )
    years = npv_data["year"].to_numpy()
    discount_rate = npv_data["discount_rate"].to_numpy(dtype=np.float64)
    fcff = npv_data["FCFF"].to_numpy(dtype=np.float64)
    # True where this collapsed asset-year had at least one measured FCFF.
    fcff_observed = npv_data["_fcff_observed"].to_numpy() > 0

    # Rows are year-sorted, so the group's first row carries its minimum year.
    base_year_per_group = years[starts].astype(np.int64)
    base_year = base_year_per_group[gid]
    years_from_base = years - base_year
    discount_factor = (1.0 + discount_rate) ** (-years_from_base)

    npv_data["base_year"] = base_year
    npv_data["terminal_method"] = terminal_method
    npv_data["years_from_base"] = years_from_base
    npv_data["discount_factor"] = discount_factor
    npv_data["pv_fcff"] = fcff * discount_factor
    npv_data["terminal_value"] = 0.0
    npv_data["yearly_npv"] = npv_data["pv_fcff"]  # Only FCFF for forecast years

    # Per-group terminal anchors, all taken from the last (highest-year) row.
    final_year = years[last_idx].astype(np.int64)
    final_discount_rate = discount_rate[last_idx]
    years_to_terminal = (final_year + 1) - base_year_per_group
    if "alignment_type" in npv_data.columns:
        is_carbontech = (
            npv_data["alignment_type"]
            .iloc[last_idx]
            .isin(CARBONTECH_ALIGNMENTS)
            .to_numpy()
        )
    else:
        is_carbontech = np.zeros(n_groups, dtype=bool)
    # The terminal GROWTH rate rides the SAME carrier as the discount spread
    # (owner ruling 13) — one carrier, one answer, so an asset cannot be brown
    # for its rate and green for its growth. Recomputed here at GROUP grain
    # rather than reused from `is_brown_row`, which was measured on the
    # pre-collapse frame and is not row-aligned with `last_idx`. Both
    # `technology` and `alignment_type` are group keys, so the group's last row
    # speaks for the whole group either way.
    if spread_carrier == SPREAD_CARRIER_ALIGNMENT:
        is_brown_group = is_carbontech
    elif "technology" in npv_data.columns:
        is_brown_group = npv_data["technology"].iloc[last_idx].isin(brown_set).to_numpy()
    else:
        is_brown_group = np.zeros(n_groups, dtype=bool)

    horizon = _horizon_attributes_per_group(
        npv_data, last_idx, asset_horizon_attributes
    )

    def anchor(column: str) -> np.ndarray | None:
        """A horizon attribute as one value per group, or None if unavailable."""
        if horizon is None or column not in horizon.columns:
            return None
        return pd.to_numeric(horizon[column], errors="coerce").to_numpy(
            dtype=np.float64
        )

    # Normalized terminal FCFF: mean of the last min(window, group_size) rows.
    # A single transition-period CapEx spike in the final year must not decide
    # the whole terminal value.
    if terminal_normalization_window > 1:
        logger.info(
            "Terminal FCFF normalization: averaging the last %s years "
            "(Damodaran/McKinsey practice)",
            terminal_normalization_window,
        )
    window_mask = pos_from_end < terminal_normalization_window

    # A perpetuity capitalises whatever the anchor holds, so the anchor has to
    # be OPERATING cash flow. Decommissioning is a one-off charge for leaving,
    # and an asset shedding capacity every year of the transition books one
    # every year: left in, r-g turns a single exit bill into an infinite series
    # of them. Adding the charge back is exact — capex_total contains it as a
    # positive outflow, so FCFF + decom_cost is the FCFF of an asset that did
    # not retire. A missing charge is no charge, hence fillna(0.0) rather than
    # a NaN that would silently drop the year from the window mean.
    anchor_fcff = fcff
    if tv_anchor_policy == "operating" and has_decom:
        anchor_fcff = fcff + npv_data["decom_cost"].fillna(0.0).to_numpy(
            dtype=np.float64
        )

    final_fcff = (
        pd.Series(anchor_fcff[window_mask])
        .groupby(gid[window_mask])
        .mean()  # NaN-skipping
        .reindex(np.arange(n_groups))
        .to_numpy()
    )

    # Technology-appropriate terminal growth rate, written onto every row of the
    # group whether or not a terminal row is ultimately added.
    if terminal_method == "perpetuity":
        g_effective = np.where(is_brown_group, g_brown, g_green).astype(np.float64)
    else:
        g_effective = np.full(n_groups, float(terminal_growth_rate))
    npv_data["terminal_growth_rate"] = g_effective[gid] if n_groups else 0.0

    terminal_value = np.zeros(n_groups, dtype=np.float64)
    if terminal_method == "perpetuity" and n_groups:
        # NaN != 0 is True — a group whose terminal FCFF is missing is treated
        # as having one, exactly as a raw float comparison would.
        has_terminal_fcff = final_fcff != 0
        terminal_cf = final_fcff * (1.0 + g_effective)

        if stranding_aware_tv:
            # Stranded: loss-making for N consecutive years at the horizon end
            # (Gourdel 2024) — a rational owner shuts down, so TV = 0.
            # A group with FEWER than N observed years cannot show N
            # consecutive loss years: its whole history is shorter than the
            # test. Scoring it stranded off 1-2 observations writes off the
            # asset's entire terminal value on evidence the criterion does not
            # have. A MISSING year is not a loss either, so both the history
            # length and the loss run count measured values, never the 0.0 the
            # collapse above puts in a gap's place.
            # NOTE the deliberate asymmetry with the anchor above: stranding
            # reads the AS-BOOKED FCFF, decom included. The anchor asks "what
            # does this asset earn from here?" and a one-off exit charge is no
            # part of the answer; stranding asks "is it burning cash?", and an
            # asset paying a decommissioning bill it cannot cover is. Stranded
            # pays zero, which is strictly less negative than the raw anchor's
            # value, so the ordering is conservative either way.
            observed_per_group = np.bincount(gid[fcff_observed], minlength=n_groups)
            has_full_history = observed_per_group >= stranding_consecutive_years
            window = pos_from_end < stranding_consecutive_years
            strand_mask = window & fcff_observed
            is_stranded = (
                pd.Series(fcff[strand_mask] <= 0)
                .groupby(gid[strand_mask])
                .all()
                .reindex(np.arange(n_groups), fill_value=False)
                .to_numpy()
                .astype(bool)
            )
            # Every year of the trailing window must actually be measured:
            # "loss, gap, loss" is not a run of three consecutive loss years.
            window_is_complete = np.bincount(
                gid[strand_mask], minlength=n_groups
            ) == np.minimum(sizes, stranding_consecutive_years)
            stranded = (
                has_terminal_fcff & is_stranded & has_full_history & window_is_complete
            )
            # Declining but still profitable carbontech: a finite annuity over
            # the remaining economic life instead of a perpetuity.
            annuity = (
                has_terminal_fcff & ~is_stranded & is_carbontech & (final_fcff > 0)
            )
            annuity_factor = np.zeros(n_groups, dtype=np.float64)
            for t in range(1, brown_remaining_life_years + 1):
                annuity_factor = annuity_factor + 1.0 / (1.0 + final_discount_rate) ** t
            # The annuity factor already discounts t=1..N back to final_year, so
            # discount from final_year (not final_year + 1) to base_year.
            annuity_tv = (
                terminal_cf
                * annuity_factor
                * (1.0 + final_discount_rate) ** (-(final_year - base_year_per_group))
            )
            terminal_value = np.where(annuity, annuity_tv, terminal_value)
        else:
            stranded = np.zeros(n_groups, dtype=bool)
            annuity = np.zeros(n_groups, dtype=bool)

        # BOUNDED NEGATIVE — a non-stranded group losing money at the horizon.
        # Gordon Growth on a negative terminal FCFF is unbounded below: the
        # asset is valued at less than nothing, forever. No owner makes that
        # choice. Bound it by the least bad of the two they actually have —
        # run the remaining life out at a loss, or pay to exit now. Both
        # candidates are negative, so the larger is the smaller loss.
        if negative_tv_method == "bounded_annuity":
            negative = has_terminal_fcff & ~stranded & (final_fcff < 0)

            # Remaining economic life at the horizon. Where the asset carries
            # no lifetime, fall back to the tier-2 annuity's own horizon.
            n_remaining = np.full(n_groups, float(brown_remaining_life_years))
            lifetime, age = anchor("lifetime_years"), anchor("asset_age")
            past_lifetime = np.zeros(n_groups, dtype=bool)
            if lifetime is not None and age is not None:
                measured = lifetime - age
                past_lifetime = np.isfinite(measured) & (measured <= 0)
                n_remaining = np.where(
                    np.isfinite(measured), np.maximum(measured, 0.0), n_remaining
                )

            # The tier-2 annuity factor as a closed form, at the group's OWN
            # rate (technology spreads included) over its own remaining life.
            with np.errstate(divide="ignore", invalid="ignore"):
                negative_annuity_factor = np.where(
                    final_discount_rate != 0,
                    (1.0 - (1.0 + final_discount_rate) ** (-n_remaining))
                    / final_discount_rate,
                    n_remaining,
                )
            run_out_tv = final_fcff * negative_annuity_factor

            # The exit quote: decommissioning whatever capacity is still
            # standing at the horizon, priced off the same scrap rate the
            # include_decom_costs charge uses. Where scrap or capacity is
            # unavailable there is no quote, so there is no floor and the
            # annuity stands alone.
            scrap, capacity = anchor("scrap_usd_per_mw"), anchor("asset_trajectory")
            if scrap is None or capacity is None:
                exit_tv = np.full(n_groups, -np.inf)
            else:
                decom_cost = np.abs(scrap) * capacity
                exit_tv = np.where(np.isfinite(decom_cost), -decom_cost, -np.inf)

            # PAST ITS LIFETIME AND STILL STANDING — the run-out arm does not
            # exist for it. There is no remaining life to run out, so the owner
            # is not choosing between running on and exiting: exiting is the
            # only thing left, and the exit arm binds.
            #
            # Clamping `n_remaining` to zero and leaving the arm in place is
            # what produced the degeneracy this corrects: a zero-year annuity
            # factor makes `run_out_tv` exactly 0, 0 beats every negative
            # `-decom_cost`, and the asset walks away from its decommissioning
            # bill. That is a FREE EXIT, and it is not a rare corner —
            # `lifetime - age <= 0` with capacity still standing holds for
            # 20.5% of the fixture's asset series. Owner ruling C2 (2026-09-04)
            # reads decision #5 the other way: no life left to run out means
            # the exit arm is the one that prices the group.
            #
            # The capacity COLUMN is absent (not "capacity is zero"): with no
            # quote available the exit arm is unavailable too, and both arms
            # missing resolves to 0 below - the same answer either way. There is
            # no plant to decommission either, so both arms are 0 and the
            # `tv_anchor_policy="operating"` zeroing below agrees.
            if capacity is None:
                still_standing = np.zeros(n_groups, dtype=bool)
            else:
                still_standing = np.isfinite(capacity) & (capacity > 0)
            run_out_tv = np.where(
                past_lifetime & still_standing, -np.inf, run_out_tv
            )

            # BOTH arms unavailable — past its lifetime, still standing, and no
            # scrap price to quote the exit at. There is no number to put on
            # the group, so it takes no terminal value rather than an infinite
            # one: the same "no quote, no floor" reading as the branch above,
            # applied when the annuity is the arm that is missing.
            least_bad = np.maximum(run_out_tv, exit_tv)
            least_bad = np.where(np.isneginf(least_bad), 0.0, least_bad)

            # The annuity factor already discounts t = 1..N back to final_year,
            # so discount from final_year (not final_year + 1) to base_year —
            # the same convention the tier-2 annuity uses.
            bounded_tv = least_bad * (1.0 + final_discount_rate) ** (
                -(final_year - base_year_per_group)
            )
            terminal_value = np.where(negative, bounded_tv, terminal_value)
        else:
            negative = np.zeros(n_groups, dtype=bool)

        # Gordon Growth perpetuity for everything else, only where r > g.
        with np.errstate(divide="ignore", invalid="ignore"):
            perpetuity_tv = (terminal_cf / (final_discount_rate - g_effective)) * (
                1.0 + final_discount_rate
            ) ** (-years_to_terminal)
        perpetuity = (
            has_terminal_fcff
            & ~stranded
            & ~annuity
            & ~negative
            & (final_discount_rate > g_effective)
        )
        terminal_value = np.where(perpetuity, perpetuity_tv, terminal_value)

        # WHICH TIER CLAIMED WHAT. The tiers are mutually exclusive and the
        # counts sum to n_groups EXCEPT groups where r <= g (no perpetuity is
        # defined; they carry no terminal value and are counted separately
        # below). NOTE: these are tier ASSIGNMENTS logged before the
        # operating-anchor retired-at-horizon override; a group counted here
        # can still be zeroed by that override afterwards.
        # A census is the cheapest way for a reader
        # to see whether the perpetuity is the common case or the exception in
        # their own run — the handover page quotes the fixture's, and this is
        # how to reproduce it on any other input.
        logger.info(
            "Terminal-value tier census of %d groups: %d stranded (TV=0), "
            "%d carbontech annuity, %d bounded negative, %d perpetuity, "
            "%d with no terminal anchor, %d with r <= g (no perpetuity "
            "defined, no terminal value) — assignments before the "
            "operating-anchor retirement override",
            n_groups,
            int(stranded.sum()),
            int(annuity.sum()),
            int(negative.sum()),
            int(perpetuity.sum()),
            int((~has_terminal_fcff).sum()),
            int(
                (
                    has_terminal_fcff
                    & ~stranded
                    & ~annuity
                    & ~negative
                    & ~perpetuity
                ).sum()
            ),
        )

        # RETIRED AT THE HORIZON — the hard case, and it outranks every tier
        # above. A group standing at zero capacity has no plant: there is
        # nothing to run out, nothing to decommission a second time, and
        # nothing to grow into perpetuity. Whatever its final cash flows say,
        # the terminal value is zero.
        #
        # The tiers cannot reach this on their own, because the anchor is a
        # WINDOW: with `terminal_normalization_window: 3` a plant that retired
        # two years before the horizon still has two live years inside the
        # window, so it is handed a terminal value off cash flows it can no
        # longer earn. Zeroing on capacity is what stops the window from
        # resurrecting a retired asset.
        if tv_anchor_policy == "operating":
            capacity_at_horizon = anchor("asset_trajectory")
            if capacity_at_horizon is None:
                logger.warning(
                    "tv_anchor_policy='operating' has no capacity at the "
                    "horizon to read; a retired group keeps the terminal value "
                    "its tier gave it"
                )
            else:
                retired_at_horizon = np.isfinite(capacity_at_horizon) & (
                    capacity_at_horizon <= 0
                )
                logger.info(
                    "Retired at the horizon: %d of %d groups stand at zero "
                    "capacity and take TV=0",
                    int(retired_at_horizon.sum()),
                    n_groups,
                )
                terminal_value = np.where(retired_at_horizon, 0.0, terminal_value)

    # One terminal row per group with a non-zero terminal value, built as a
    # single frame (the old per-group Series.to_frame().T forced object dtype).
    add_groups = np.flatnonzero(terminal_value != 0)
    if len(add_groups):
        anchors = last_idx[add_groups]
        group_years_to_terminal = years_to_terminal[add_groups]
        terminal_rows = npv_data.iloc[anchors].copy()
        terminal_rows["year"] = final_year[add_groups] + 1
        terminal_rows["years_from_base"] = group_years_to_terminal
        terminal_rows["discount_factor"] = (
            1.0 + final_discount_rate[add_groups]
        ) ** (-group_years_to_terminal)
        terminal_rows["pv_fcff"] = 0.0  # No FCFF in terminal year
        terminal_rows["terminal_value"] = terminal_value[add_groups]
        terminal_rows["yearly_npv"] = terminal_value[add_groups]
        # Financial components are 0 in the terminal year (it's just the TV)
        for fin_col in available_financial_cols:
            terminal_rows[fin_col] = 0.0
        npv_data = pd.concat([npv_data, terminal_rows], ignore_index=True).sort_values(
            ["_gid", "year"], kind="stable", ignore_index=True
        )

    logger.info(
        "Computed %d asset-trajectory groups, %d with a terminal-value row",
        n_groups,
        len(add_groups),
    )

    # Select columns for output - ensure all financial components are included
    output_cols = (
        group_keys
        + [
            "year",
            "discount_rate",
            "base_year",
            "terminal_method",
            "terminal_growth_rate",
            "years_from_base",
            "discount_factor",
            "pv_fcff",
            "terminal_value",
            "yearly_npv",
        ]
        + available_financial_cols
    )
    yearly_df = npv_data[[col for col in output_cols if col in npv_data.columns]].copy()

    logger.info(
        f"Computed yearly NPV trajectories for {len(yearly_df)} asset-year-trajectory combinations"
    )

    return yearly_df


def calculate_npv_per_asset(
    yearly_npv_trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """
    Node 2: Aggregate yearly NPV trajectories to asset level, pivoting by trajectory_type.

    Returns one row per asset x scenario with columns:
      - baseline_npv
      - latesudden_npv
      - npv_change
    """

    logger.info("Aggregating yearly NPV trajectories to asset level...")

    data = yearly_npv_trajectories.copy()

    # Group keys (everything except trajectory_type and year)
    group_keys = [
        "asset_id",
        "asset_name",
        "company_id",
        "company_name",
        "scenario_geography",
        "sector",
        "technology",
        "is_synthetic",
        "alignment_type",
    ]

    # Sum yearly NPV by trajectory type
    agg_dict = {
        "yearly_npv": "sum",
        "discount_rate": "mean",  # changes over time depending on scenario type
        "base_year": "first",
        "terminal_method": "first",
        "terminal_growth_rate": "first",
    }

    # Sum financial components across years as well
    financial_cols = [
        "FCFF",
        "EBITDA",
        "revenue",
        "var_cost",
        "fixed_cost",
        "carbon_cost_net",
        "capex_total",
    ]
    for col in financial_cols:
        if col in data.columns:
            agg_dict[col] = "sum"

    # Aggregate by asset and trajectory type. dropna=False: the trajectory
    # groupby upstream keeps NaN group keys, so dropping them here would make
    # those assets disappear between two nodes with no warning.
    aggregated = (
        data.groupby(group_keys + ["trajectory_type"], dropna=False)
        .agg(agg_dict)
        .reset_index()
    )

    # Rename yearly_npv to NPV for clarity
    aggregated = aggregated.rename(columns={"yearly_npv": "NPV"})

    # Pivot to wide format by trajectory_type
    pivot_values = ["NPV", "discount_rate"] + [
        col for col in financial_cols if col in aggregated.columns
    ]

    npv_wide = aggregated.pivot(
        index=group_keys,
        columns="trajectory_type",
        values=pivot_values,
    ).reset_index()

    # Flatten multi-level columns and rename
    npv_wide.columns = npv_wide.columns.to_flat_index()
    rename_map = {}
    for col in npv_wide.columns:
        if isinstance(col, tuple) and len(col) == 2:
            value_name, trajectory_type = col
            # Handle single-level columns (they become ('column_name', ''))
            if trajectory_type == "":
                rename_map[col] = value_name
            # Handle multi-level columns
            elif value_name == "NPV":
                if trajectory_type == "baseline":
                    rename_map[col] = "baseline_npv"
                elif trajectory_type == "latesudden":
                    rename_map[col] = "latesudden_npv"
            elif value_name == "discount_rate":
                if trajectory_type == "baseline":
                    rename_map[col] = "baseline_discount_rate"
                elif trajectory_type == "latesudden":
                    rename_map[col] = "latesudden_discount_rate"
            else:
                # Handle financial components
                if trajectory_type == "baseline":
                    rename_map[col] = f"baseline_{value_name}"
                elif trajectory_type == "latesudden":
                    rename_map[col] = f"latesudden_{value_name}"

    npv_wide = npv_wide.rename(columns=rename_map)

    # Calculate NPV change (robust to division by zero and object dtypes)
    if "baseline_npv" in npv_wide.columns and "latesudden_npv" in npv_wide.columns:
        with np.errstate(divide="ignore", invalid="ignore"):
            baseline_arr = npv_wide["baseline_npv"].to_numpy(dtype=np.float64)
            shock_arr = npv_wide["latesudden_npv"].to_numpy(dtype=np.float64)
            change_arr = np.true_divide((shock_arr - baseline_arr), abs(baseline_arr))
        # A zero baseline yields inf/-inf; that is "undefined", not "infinitely
        # worse", and it poisons every downstream mean.
        change_arr = np.where(np.isfinite(change_arr), change_arr, np.nan)
        npv_wide["npv_change"] = change_arr

    logger.info(f"Calculated NPV (wide) for {len(npv_wide)} assets")

    return npv_wide


def aggregate_to_company_technology_npv(asset_npv: pd.DataFrame) -> pd.DataFrame:
    """
    Node 2: Aggregate asset-level NPV to company-technology level.
    """

    logger.info("Aggregating NPV to company-technology level...")

    # Group by company, technology and scenario dimensions
    groupby_cols = [
        "company_id",
        "company_name",
        "sector",
        "technology",
        "scenario_geography",
    ]

    # Define aggregation functions
    agg_funcs = {
        # Sum NPV components (already wide)
        "baseline_npv": "sum",
        "latesudden_npv": "sum",
        "baseline_discount_rate": "mean",
        "latesudden_discount_rate": "mean",
        # Count assets
        "asset_id": "count",
    }

    company_tech_npv = (
        asset_npv.groupby(groupby_cols, dropna=False).agg(agg_funcs).reset_index()
    )

    # Rename asset count column
    company_tech_npv = company_tech_npv.rename(columns={"asset_id": "asset_count"})

    with np.errstate(divide="ignore", invalid="ignore"):
        base_ct = company_tech_npv["baseline_npv"].to_numpy(dtype=np.float64)
        shock_ct = company_tech_npv["latesudden_npv"].to_numpy(dtype=np.float64)
        change_ct = np.true_divide((shock_ct - base_ct), abs(base_ct))
    change_ct = np.where(np.isfinite(change_ct), change_ct, np.nan)
    company_tech_npv["npv_change"] = change_ct
    logger.info(
        f"Aggregated to {len(company_tech_npv)} company-technology-scenario_geography combinations"
    )

    return company_tech_npv


def aggregate_to_company_npv(company_technology_npv: pd.DataFrame) -> pd.DataFrame:
    """
    Node 3: Aggregate company-technology NPV to company level.
    """

    logger.info("Aggregating NPV to company level...")

    # Group by company and scenario dimensions only
    groupby_cols = ["company_id", "company_name"]

    # Define aggregation functions
    agg_funcs = {
        # Sum NPV components across all technologies
        "baseline_npv": "sum",
        "latesudden_npv": "sum",
        "baseline_discount_rate": "mean",
        "latesudden_discount_rate": "mean",
        # Sum asset counts
        "asset_count": "sum",
    }

    company_npv = (
        company_technology_npv.groupby(groupby_cols, dropna=False)
        .agg(agg_funcs)
        .reset_index()
    )

    with np.errstate(divide="ignore", invalid="ignore"):
        base_c = company_npv["baseline_npv"].to_numpy(dtype=np.float64)
        shock_c = company_npv["latesudden_npv"].to_numpy(dtype=np.float64)
        change_c = np.true_divide((shock_c - base_c), abs(base_c))
    change_c = np.where(np.isfinite(change_c), change_c, np.nan)
    company_npv["npv_change"] = change_c

    logger.info(f"Aggregated to {len(company_npv)} company-level records")

    return company_npv
