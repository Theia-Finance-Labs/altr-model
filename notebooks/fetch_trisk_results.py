import mlflow
import pandas as pd
from typing import List, Dict
import json
import os
from pathlib import Path
import shutil

# MLflow configuration
mlflow_tracking_uri = "https://mlflow.1in1000.com:443"
experiment_name = "age_impact_v1"


def fetch_successful_runs() -> List[Dict]:
    """
    Fetch all successful runs from MLflow and their parameters.
    A run is considered successful if it doesn't have an 'error' parameter.
    """
    # Set tracking URI
    mlflow.set_tracking_uri(mlflow_tracking_uri)

    # Get experiment
    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"Experiment '{experiment_name}' not found")

    # Search for all runs in the experiment
    runs = mlflow.search_runs(experiment_ids=[experiment.experiment_id])

    # Filter for successful runs (no error parameter)
    successful_runs = []
    for _, run in runs.iterrows():
        # Get run details
        run_data = mlflow.get_run(run.run_id)
        params = run_data.data.params

        # Check if run has an error parameter
        if "error" not in params:
            successful_runs.append(
                {
                    "run_id": run.run_id,
                    "parameters": params,
                    "metrics": run_data.data.metrics,
                    "status": run_data.info.status,
                    "start_time": run_data.info.start_time,
                    "end_time": run_data.info.end_time,
                }
            )

    return successful_runs


def filter_runs_by_target_scenario(
    runs: List[Dict], target_scenario: str
) -> List[Dict]:
    """
    Filter runs by target scenario.
    """
    return [
        run
        for run in runs
        if run["parameters"].get("target_scenario") == target_scenario
    ]


def download_run_artifacts(run_id: str, output_dir: str) -> Dict[str, str]:
    """
    Download artifacts for a specific run and rename them with run ID.
    Returns a dictionary with paths to the downloaded files.
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Get the run
    run = mlflow.get_run(run_id)

    # List all artifacts in the run
    artifacts = mlflow.artifacts.list_artifacts(run_id=run_id)

    downloaded_files = {}

    for artifact in artifacts:
        if artifact.path.endswith(".csv"):
            # Download the artifact to a temporary location
            temp_path = mlflow.artifacts.download_artifacts(
                run_id=run_id,
                artifact_path=artifact.path,
                dst_path=output_dir,
            )

            # Determine the new filename based on the artifact type
            if "trajectories" in artifact.path.lower():
                new_filename = f"trajectories_{run_id}.csv"
            else:
                new_filename = f"npvs_{run_id}.csv"

            # Create the new file path
            new_path = os.path.join(output_dir, new_filename)

            # Move the file to its new name
            shutil.move(temp_path, new_path)

            downloaded_files[artifact.path] = new_path
            print(f"Downloaded and renamed {artifact.path} to {new_filename}")

    return downloaded_files


def display_runs(runs: List[Dict], title: str = ""):
    """
    Display the runs and their parameters in a readable format.
    """
    if title:
        print(f"\n{title}")
    print(f"Found {len(runs)} successful runs:\n")

    for i, run in enumerate(runs, 1):
        print(f"Run {i}:")
        print(f"  Run ID: {run['run_id']}")
        print(f"  Status: {run['status']}")
        print(f"  Start Time: {run['start_time']}")
        print(f"  End Time: {run['end_time']}")
        print("\n  Parameters:")
        for key, value in run["parameters"].items():
            print(f"    {key}: {value}")

        print("\n  Metrics:")
        for key, value in run["metrics"].items():
            print(f"    {key}: {value}")
        print("\n" + "-" * 80 + "\n")


def main(output_path: str):
    """
    Main function to fetch and download MLflow runs and artifacts.

    Args:
        output_path (str): Base directory for output files. Will create:
            - {output_path}/artifacts/ for downloaded artifacts
            - {output_path}/successful_runs.json for run information
    """
    try:
        # Create output directory structure
        output_dir = Path(output_path)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created output directory: {output_dir.absolute()}")
        except Exception as e:
            raise Exception(f"Failed to create output directory {output_dir}: {str(e)}")

        artifacts_dir = output_dir / "artifacts"
        try:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created artifacts directory: {artifacts_dir.absolute()}")
        except Exception as e:
            raise Exception(
                f"Failed to create artifacts directory {artifacts_dir}: {str(e)}"
            )

        # Fetch successful runs
        successful_runs = fetch_successful_runs()

        # Display all runs
        display_runs(successful_runs, "All Successful Runs")

        # Filter and display runs for specific target scenario
        target_scenario = "AR6_IMAGE 3.2_SSP1_SPA1_19I_RE_LB"
        filtered_runs = filter_runs_by_target_scenario(successful_runs, target_scenario)
        display_runs(filtered_runs, f"Runs with target scenario: {target_scenario}")

        # Download artifacts for each filtered run
        print("\nDownloading artifacts for filtered runs...")
        for run in filtered_runs:
            run_id = run["run_id"]
            scenario_geo = run["parameters"].get("scenario_geography", "unknown")
            print(
                f"\nDownloading artifacts for run {run_id} (Geography: {scenario_geo})"
            )
            downloaded_files = download_run_artifacts(run_id, str(artifacts_dir))

            # Print summary of downloaded files
            print(f"Downloaded {len(downloaded_files)} files:")
            for artifact_path, local_path in downloaded_files.items():
                print(f"  - {artifact_path} -> {local_path}")

        # Save run information to JSON
        json_path = output_dir / "successful_runs.json"
        with open(json_path, "w") as f:
            json.dump(
                {"all_runs": successful_runs, "filtered_runs": filtered_runs},
                f,
                indent=2,
                default=str,
            )
        print(f"\nSaved detailed run information to '{json_path}'")

    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    output_path = "workspace/mlflow_results"
    main(output_path)
