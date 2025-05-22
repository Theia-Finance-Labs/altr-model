import pandas as pd
import os
from pathlib import Path
import glob


def gather_trisk_results(artifacts_dir: str) -> pd.DataFrame:
    """
    Gather TRISK NPV results from downloaded artifacts.

    Args:
        artifacts_dir (str): Directory containing the downloaded artifacts

    Returns:
        pd.DataFrame: Combined NPVs DataFrame
    """
    # Get all NPV files
    npv_files = glob.glob(os.path.join(artifacts_dir, "npvs_*.csv"))

    # Initialize empty DataFrame for combined results
    all_npvs = pd.DataFrame()

    # Process NPV files
    for file in npv_files:
        run_id = os.path.basename(file).replace("npvs_", "").replace(".csv", "")
        df = pd.read_csv(file)
        df["run_id"] = run_id
        all_npvs = pd.concat([all_npvs, df], ignore_index=True)

    return all_npvs


def split_by_ccs_status(
    df: pd.DataFrame, ccs_technologies: list[str] = ["GasCap", "CoalCap", "OilCap"]
) -> dict[str, pd.DataFrame]:
    """
    Split the DataFrame into three groups based on CCS status.

    Args:
        df (pd.DataFrame): Input DataFrame with technology column
        ccs_technologies (list[str], optional): List of technologies that can have CCS.
            Defaults to ['GasCap', 'CoalCap', 'OilCap']

    Returns:
        dict[str, pd.DataFrame]: Dictionary containing three filtered DataFrames:
            - 'with_ccs': Technologies with CCS + other technologies
            - 'without_ccs': Technologies without CCS + other technologies
            - 'other': All technologies except CCS-capable ones
    """
    # Get unique run IDs for each CCS variant
    with_ccs_runs = df[df["technology"].str.contains("w/ CCS", na=False)][
        "run_id"
    ].unique()
    without_ccs_runs = df[df["technology"].str.contains("w/o CCS", na=False)][
        "run_id"
    ].unique()

    # Split technologies by CCS status using run IDs
    with_ccs = df[df["run_id"].isin(with_ccs_runs)]
    without_ccs = df[df["run_id"].isin(without_ccs_runs)]

    # For other technologies, we need to ensure we don't duplicate them
    # We'll take them from the run that has the most complete data
    other_runs = set(df["run_id"].unique()) - set(with_ccs_runs) - set(without_ccs_runs)
    if other_runs:
        other_techs = df[df["run_id"].isin(other_runs)]

    return {"with_ccs": with_ccs, "without_ccs": without_ccs, "other": other_techs}


def save_trisk_results(df: pd.DataFrame, output_dir: str, filename: str):
    """
    Save TRISK NPV results to CSV file.

    Args:
        df (pd.DataFrame): DataFrame to save
        output_dir (str): Directory to save the results
        filename (str): Name of the output file
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Save results
    output_path = os.path.join(output_dir, filename)
    print(f"\nSaving {filename} to: {output_path}")
    df.to_csv(output_path, index=False)
    print(f"Total rows: {len(df)}")


if __name__ == "__main__":
    # Assuming the artifacts are in workspace/mlflow_results/artifacts
    artifacts_dir = "workspace/mlflow_results/artifacts"
    # Save one level up from artifacts directory
    output_dir = "workspace/mlflow_results"

    # Define CCS technologies
    ccs_technologies = ["GasCap", "CoalCap", "OilCap"]

    # Gather the results
    npvs_df = gather_trisk_results(artifacts_dir)

    # Split the results by CCS status
    ccs_split = split_by_ccs_status(npvs_df, ccs_technologies)

    # Save each split
    for ccs_type, df in ccs_split.items():
        save_trisk_results(df, output_dir, f"npvs_{ccs_type}.csv")
