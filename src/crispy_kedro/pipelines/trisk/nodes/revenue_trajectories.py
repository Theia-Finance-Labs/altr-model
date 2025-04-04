import pandas as pd
import numpy as np
import ibis


def build_price_trajectory(
    traj_scenario: pd.DataFrame, shock_year: int
) -> pd.DataFrame:

    # Part 1: years > shock_year -1 (i.e., years >= shock_year)
    after_shock_target = traj_scenario.loc[
        (traj_scenario["scenario_year"] >= shock_year)
        & (traj_scenario["scenario_type"] == "target"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_target"}
    )

    after_shock_baseline = traj_scenario.loc[
        (traj_scenario["scenario_year"] >= shock_year)
        & (traj_scenario["scenario_type"] == "baseline"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_baseline"}
    )
    after_shock = pd.merge(
        after_shock_target,
        after_shock_baseline,
        how="inner",
        on=["sector", "technology", "year"],
    )

    after_shock_sorted = after_shock.sort_values(["sector", "technology", "year"])

    # Group and summarize to get baseline and target prices
    summary = (
        after_shock_sorted.groupby(["sector", "technology"])
        .agg(
            baseline_price_at_shock=("scenario_price_baseline", "first"),
            target_price_end_shockperiod=("scenario_price_target", "last"),
            first_year=("year", "min"),
            last_year=("year", "max"),
        )
        .reset_index()
    )

    # Function to interpolate prices
    def interpolate_prices(row):
        first_year = row["first_year"] + 1
        last_year = row["last_year"]
        if first_year > last_year:
            return pd.DataFrame(
                columns=[
                    "sector",
                    "technology",
                    "year",
                    "scenario_price_late_sudden",
                ]
            )
        years = list(range(int(first_year), int(last_year) + 1))
        baseline = row["baseline_price_at_shock"]
        target = row["target_price_end_shockperiod"]
        if first_year == last_year:
            prices = [target]
        else:
            prices = np.linspace(
                baseline, target, num=(int(last_year) - int(first_year) + 1)
            )
        df = pd.DataFrame(
            {
                "sector": row["sector"],
                "technology": row["technology"],
                "year": years,
                "scenario_price_late_sudden": prices,
            }
        )
        return df

    # Apply interpolation
    interpolated_prices = summary.apply(interpolate_prices, axis=1).tolist()
    interpolated_prices = (
        pd.concat(interpolated_prices, ignore_index=True)
        if interpolated_prices
        else pd.DataFrame()
    )
    # Part 2: years <= shock_year
    before_shock = traj_scenario.loc[
        (traj_scenario["scenario_year"] <= shock_year)
        & (traj_scenario["scenario_type"] == "baseline"),
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={
            "scenario_year": "year",
            "scenario_price": "scenario_price_late_sudden",
        }
    )

    # Combine both parts
    final_result = pd.concat([before_shock, interpolated_prices], ignore_index=True)

    # Select relevant columns
    traj_price_late_sudden = final_result[
        ["sector", "technology", "year", "scenario_price_late_sudden"]
    ]

    # Add baseline price
    traj_price_baseline = traj_scenario.loc[
        traj_scenario["scenario_type"] == "baseline",
        ["sector", "technology", "scenario_year", "scenario_price"],
    ].rename(
        columns={"scenario_year": "year", "scenario_price": "scenario_price_baseline"}
    )

    traj_price_late_sudden = pd.merge(
        traj_price_late_sudden,
        traj_price_baseline,
        on=["sector", "technology", "year"],
        how="inner",
    )

    return traj_price_late_sudden


def filter_companies(
    plant_ownerships: ibis.expr.types.Table, filtered_plant_detail: pd.DataFrame
) -> pd.DataFrame:
    filtered_assets = filtered_plant_detail["asset_id"].unique()
    plant_ownership_df = plant_ownerships.filter(
        plant_ownerships.asset_id.isin(filtered_assets)
    ).execute()

    # TODO : APPLY OWNERSHIP TREE ACCORDING TO EVENTS
    # Step 1: aggregate ownership by asset and company
    companies_ownership_tree = plant_ownership_df.groupby(
        ["asset_id", "owner_name", "company_id"], as_index=False
    ).agg({"ownership_percentage": "sum"})

    # Step 2: normalize ownership per asset
    companies_ownership_tree["normalized_ownership"] = (
        companies_ownership_tree["ownership_percentage"]
        / companies_ownership_tree.groupby("asset_id")[
            "ownership_percentage"
        ].transform("sum")
    ).astype(float)

    return companies_ownership_tree[
        ["asset_id", "owner_name", "company_id", "normalized_ownership"]
    ]


def allocate_production_to_companies(
    companies_ownership_tree: pd.DataFrame,
    traj_assets_baseline: pd.DataFrame,
    traj_assets_shocked: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    def allocate_trajectory(asset_df, asset_col, output_col):
        """
        Merges asset-level trajectories with company ownership info,
        allocates the asset trajectory based on normalized ownership,
        and aggregates by company, sector, technology, and year.

        Parameters:
            asset_df: DataFrame with asset trajectories.
            asset_col: The column name in asset_df to allocate (e.g.
                       "asset_trajectory_baseline" or "asset_trajectory_shock").
            output_col: The name for the resulting allocated column
                        (e.g. "company_trajectory_baseline" or
                        "company_trajectory_shock").

        Returns:
            A DataFrame aggregated to the company level.
        """
        merged = asset_df.merge(
            companies_ownership_tree[
                ["asset_id", "company_id", "normalized_ownership"]
            ],
            on="asset_id",
            how="inner",
        )
        merged[f"allocated_{asset_col}"] = (
            merged[asset_col] * merged["normalized_ownership"]
        )
        allocated = (
            merged.groupby(
                ["company_id", "sector", "technology", "year"], as_index=False
            )[f"allocated_{asset_col}"]
            .sum()
            .rename(columns={f"allocated_{asset_col}": output_col})
        )
        return allocated

    # Allocate baseline trajectories. Assumes traj_assets_baseline has a column named
    # "asset_trajectory_baseline".
    traj_companies_baseline = allocate_trajectory(
        traj_assets_baseline, "asset_trajectory_baseline", "company_trajectory_baseline"
    )

    # Allocate shock trajectories. Assumes traj_assets_shocked has a column named
    # "asset_trajectory_shock".
    traj_companies_shock = allocate_trajectory(
        traj_assets_shocked, "asset_trajectory_shock", "company_trajectory_shock"
    )

    return traj_companies_baseline, traj_companies_shock


def calculate_net_profits(
    financial_averages: ibis.expr.types.Table,
    traj_companies_baseline: pd.DataFrame,
    traj_companies_shock: pd.DataFrame,
    traj_technology_prices: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Execute the financial averages query and ensure margin is float
    financial_averages_df = financial_averages.execute()
    financial_averages_df["net_profit_margin"] = financial_averages_df[
        "net_profit_margin"
    ].astype(float)

    # Calculate net profits for the baseline scenario
    traj_companies_revenue_baseline = traj_companies_baseline.merge(
        traj_technology_prices, on=["sector", "technology", "year"], how="inner"
    ).merge(financial_averages_df, on=["sector", "technology"], how="inner")
    traj_companies_revenue_baseline["net_profits_baseline"] = (
        traj_companies_revenue_baseline["company_trajectory_baseline"]
        * traj_companies_revenue_baseline["scenario_price_baseline"]
        * traj_companies_revenue_baseline["net_profit_margin"]
    )

    # Calculate net profits for the shock (target) scenario
    traj_companies_revenue_shock = traj_companies_shock.merge(
        traj_technology_prices, on=["sector", "technology", "year"], how="inner"
    ).merge(financial_averages_df, on=["sector", "technology"], how="inner")
    traj_companies_revenue_shock["net_profits_shock"] = (
        traj_companies_revenue_shock["company_trajectory_shock"]
        * traj_companies_revenue_shock["scenario_price_late_sudden"]
        * traj_companies_revenue_shock["net_profit_margin"]
    )

    traj_companies_revenue_baseline = traj_companies_revenue_baseline[
        [
            "company_id",
            "sector",
            "technology",
            "year",
            "company_trajectory_baseline",
            "net_profits_baseline",
        ]
    ]

    traj_companies_revenue_shock = traj_companies_revenue_shock[
        [
            "company_id",
            "sector",
            "technology",
            "year",
            "company_trajectory_shock",
            "net_profits_shock",
        ]
    ]

    return traj_companies_revenue_baseline, traj_companies_revenue_shock


def calculate_discounted_net_profits(
    traj_companies_revenue_baseline: pd.DataFrame,
    traj_companies_revenue_shock: pd.DataFrame,
    discount_rate: float,
    growth_rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Processes the baseline and shock revenue data to compute annual
    discounted net profits and append terminal value rows.

    Parameters:
      companies_revenue_baseline : DataFrame with columns including
                                   'company_id', 'sector', 'technology', 'year',
                                   'net_profits_baseline', etc.
      companies_revenue_shock    : DataFrame with columns including
                                   'company_id', 'sector', 'technology', 'year',
                                   'net_profits_shock', etc.
      discount_rate              : Annual discount rate.
      growth_rate                : Long-run growth rate for terminal value.

    Returns:
      A tuple (traj_companies_net_profits_baseline, traj_companies_net_profits_shock)
      where each is a DataFrame with annual discounted profits and a terminal row.
    """
    # Process baseline
    baseline_processed = discount_dividend_model(
        traj_companies_revenue_baseline,
        discount_rate,
        profit_col="net_profits_baseline",
        discounted_col="discounted_net_profit_baseline",
    )
    end_year_baseline = baseline_processed["year"].max()
    traj_companies_net_profits_baseline = calculate_terminal_value(
        baseline_processed,
        end_year_baseline,
        growth_rate,
        discount_rate,
        profit_col="net_profits_baseline",
        discounted_col="discounted_net_profit_baseline",
    )

    # Process shock (target)
    shock_processed = discount_dividend_model(
        traj_companies_revenue_shock,
        discount_rate,
        profit_col="net_profits_shock",
        discounted_col="discounted_net_profit_shock",
    )
    end_year_shock = shock_processed["year"].max()
    traj_companies_net_profits_shock = calculate_terminal_value(
        shock_processed,
        end_year_shock,
        growth_rate,
        discount_rate,
        profit_col="net_profits_shock",
        discounted_col="discounted_net_profit_shock",
    )

    return traj_companies_net_profits_baseline, traj_companies_net_profits_shock


def discount_dividend_model(
    data: pd.DataFrame, discount_rate: float, profit_col: str, discounted_col: str
) -> pd.DataFrame:
    """
    For each company group, sort by year, assign a time index t_calc,
    and compute the discounted profit.

    Parameters:
      data         : DataFrame with company-level annual net profits.
      discount_rate: Annual discount rate (e.g. 0.05 for 5%).
      profit_col   : Name of the profit column (e.g. 'net_profits_baseline'
                     or 'net_profits_shock').
      discounted_col: Name of the new column to store discounted profits.

    Returns:
      DataFrame with a new discounted profits column.
    """
    data = data.sort_values(by=["company_id", "sector", "technology", "year"]).copy()

    def apply_discount(group):
        group = group.copy()
        group["t_calc"] = range(len(group))
        group[discounted_col] = group[profit_col] / (
            (1 + discount_rate) ** group["t_calc"]
        )
        return group

    data = data.groupby(["company_id", "sector", "technology"], group_keys=False).apply(
        apply_discount
    )
    data = data.drop(columns=["t_calc"])
    return data


def calculate_terminal_value(
    data: pd.DataFrame,
    end_year: int,
    growth_rate: float,
    discount_rate: float,
    profit_col: str,
    discounted_col: str,
) -> pd.DataFrame:
    """
    Append a terminal value row for each company group. The terminal row
    represents the next period (end_year + 1) where profit is grown by
    (1 + growth_rate) and discounted using a perpetuity formula.

    Parameters:
      data         : DataFrame that has been processed with discount_dividend_model.
      end_year     : The last year in the data.
      growth_rate  : The long-run growth rate for terminal value calculation.
      discount_rate: The discount rate.
      profit_col   : Name of the profit column (baseline or shock).
      discounted_col: Name of the discounted profit column.

    Returns:
      DataFrame with an appended terminal value row.
    """
    # Filter for rows corresponding to the end year
    terminal_data = data[data["year"] == end_year].copy()
    # Prepare terminal rows for year end_year+1
    terminal_data["year"] = terminal_data["year"] + 1
    terminal_data[profit_col] = terminal_data[profit_col] * (1 + growth_rate)
    # Apply the perpetuity formula for terminal discounted value:
    # discounted_terminal = profit / (discount_rate - growth_rate)
    terminal_data[discounted_col] = terminal_data[profit_col] / (
        discount_rate - growth_rate
    )

    # Append the terminal rows back to the original data and sort
    data_with_terminal = pd.concat([data, terminal_data], ignore_index=True)
    data_with_terminal = data_with_terminal.sort_values(
        by=["company_id", "sector", "technology", "year"]
    ).reset_index(drop=True)
    return data_with_terminal


def compute_npvs(
    traj_companies_net_profits_baseline: pd.DataFrame,
    traj_companies_net_profits_shock: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute total NPV without terminal value

    Parameters:
      traj_companies_net_profits_baseline: DataFrame with discounted baseline profits
      traj_companies_net_profits_shock: DataFrame with discounted shock profits

    Returns:
      DataFrame with NPV calculations including baseline, shock, difference and change
    """

    companies_net_profits_baseline = (
        traj_companies_net_profits_baseline[
            traj_companies_net_profits_baseline["year"]
            < traj_companies_net_profits_baseline["year"].max()
        ]
        .groupby(["company_id", "sector", "technology"])
        .agg({"discounted_net_profit_baseline": "sum"})
        .rename(
            columns={"discounted_net_profit_baseline": "net_present_value_baseline"}
        )
        .reset_index()
    )

    companies_net_profits_shock = (
        traj_companies_net_profits_shock[
            traj_companies_net_profits_shock["year"]
            < traj_companies_net_profits_shock["year"].max()
        ]
        .groupby(["company_id", "sector", "technology"])
        .agg({"discounted_net_profit_shock": "sum"})
        .rename(columns={"discounted_net_profit_shock": "net_present_value_shock"})
        .reset_index()
    )

    companies_net_profits = pd.merge(
        companies_net_profits_baseline,
        companies_net_profits_shock,
        on=["company_id", "sector", "technology"],
    )

    companies_npvs = companies_net_profits.assign(
        net_present_value_difference=lambda x: x["net_present_value_shock"]
        - x["net_present_value_baseline"],
        net_present_value_change=lambda x: x["net_present_value_difference"]
        / x["net_present_value_baseline"],
    )

    return companies_npvs
