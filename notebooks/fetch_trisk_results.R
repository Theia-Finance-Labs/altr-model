library(mlflow)
library(jsonlite)
library(dplyr)
library(purrr)
library(fs)

# Resolve namespace conflicts
# The flatten function from purrr is masked by jsonlite
flatten <- purrr::flatten

# MLflow configuration
mlflow_tracking_uri <- "https://mlflow.1in1000.com:443"
experiment_name <- "age_impact_v1"
# Define the target scenario value for filtering
TARGET_SCENARIO_VALUE <- "AR6_IMAGE 3.2_SSP1_SPA1_19I_RE_LB"

#' Fetch all successful runs from MLflow that match a specific target_scenario parameter.
#' @return A list of successful runs with their parameters and metrics.
fetch_successful_runs_for_target_scenario <- function(target_scenario_filter_value) {
  # Set tracking URI
  mlflow::mlflow_set_tracking_uri(mlflow_tracking_uri)
  
  # Get experiment
  experiment <- mlflow::mlflow_get_experiment(name = experiment_name)
  if (is.null(experiment)) {
    stop(sprintf("Experiment '%s' not found", experiment_name))
  }
  
  # Construct the filter string for the target_scenario parameter
  # Assumes target_scenario is logged as a parameter, accessible via "params.target_scenario"
  filter_string <- sprintf("params.target_scenario = '%s' AND attributes.status = 'FINISHED'", target_scenario_filter_value)
  
  cat(sprintf("Searching runs with filter: %s\n", filter_string))
  
  # Search for runs matching the filter
  # mlflow_search_runs returns a tibble where 'params' and 'metrics' are list-columns
  runs_df <- mlflow::mlflow_search_runs(
    experiment_ids = experiment$experiment_id,
    filter = filter_string
  )
  
  successful_runs <- list()
  
  cat(sprintf("Total runs found by mlflow_search_runs with filter: %d\n", nrow(runs_df)))
  
  if (nrow(runs_df) > 0) {
      cat("Column names from mlflow_search_runs output (filtered data):\n")
      print(names(runs_df))
      cat("Class of the 'params' column: ", class(runs_df$params), "\n")
      if (length(runs_df$params) > 0 && !is.null(runs_df$params[[1]])){
        cat("Class of the first element of 'params' column: ", class(runs_df$params[[1]]), "\n")
        cat("Names of parameters in the first filtered run's param list:\n")
        print(names(runs_df$params[[1]]))
        cat("Value of 'target_scenario' in the first filtered run's param list:\n")
        print(runs_df$params[[1]]$target_scenario)
      } else {
        cat("'params' column is empty or its first element is NULL.\n")
      }
  }
  
  for (i in seq_len(nrow(runs_df))) {
    run_row <- runs_df[i, ]
    run_id <- run_row$run_id
    
    # Parameters and metrics are directly available as list-columns in runs_df
    # Each element of the list-column 'params' is itself a list of key-value pairs
    params <- if(length(run_row$params) > 0 && !is.null(run_row$params[[1]])) run_row$params[[1]] else list()
    metrics <- if(length(run_row$metrics) > 0 && !is.null(run_row$metrics[[1]])) run_row$metrics[[1]] else list()
    
    # The filter should have already ensured these are successful and match the scenario.
    # We double check for an error parameter just in case.
    if (is.list(params) && !("error" %in% names(params))) {
      successful_runs[[length(successful_runs) + 1]] <- list(
        run_id = run_id,
        parameters = params, # params should be a named list
        metrics = metrics,   # metrics should be a named list
        status = run_row$status,
        start_time = run_row$start_time,
        end_time = run_row$end_time %||% NA
      )
    }
  }
  
  cat(sprintf("Total runs processed after filtering (and passing 'error' check): %d\n", length(successful_runs)))
  return(successful_runs)
}

# This function is now less critical if filtering happens in fetch_successful_runs_for_target_scenario
# but kept for displaying all runs if needed or for other scenarios.
filter_runs_by_target_scenario <- function(runs, target_scenario_val) {
  cat(sprintf("\nFiltering %d runs for target scenario: '%s' (client-side)\n", length(runs), target_scenario_val))
  
  filtered_runs <- Filter(function(run) {
    if (is.list(run$parameters) && !is.null(run$parameters$target_scenario)) {
      return(run$parameters$target_scenario == target_scenario_val)
    } else {
      return(FALSE)
    }
  }, runs)
  
  cat(sprintf("Found %d runs matching the exact target scenario (client-side).\n", length(filtered_runs)))
  return(filtered_runs)
}

#' Download artifacts for a specific run and rename them with run ID
#' @param run_id Run ID to download artifacts for
#' @param output_dir Directory to save artifacts to
#' @return List of downloaded file paths
download_run_artifacts <- function(run_id, output_dir) {
  fs::dir_create(output_dir, recurse = TRUE)
  artifacts <- mlflow::mlflow_list_artifacts(run_id = run_id)
  downloaded_files <- list()
  
  if (is.null(artifacts) || nrow(artifacts) == 0) {
    cat(sprintf("No artifacts found for run %s\n", run_id))
    return(downloaded_files)
  }
  
  for (i in seq_len(nrow(artifacts))) {
    artifact_row <- artifacts[i, ]
    if (endsWith(artifact_row$path, ".csv")) {
      temp_path <- mlflow::mlflow_download_artifacts(
        run_id = run_id,
        path = artifact_row$path
      )
      new_filename <- if (grepl("trajectories", tolower(artifact_row$path))) {
        sprintf("trajectories_%s.csv", run_id)
      } else {
        sprintf("npvs_%s.csv", run_id)
      }
      new_path <- file.path(output_dir, new_filename)
      fs::file_move(temp_path, new_path)
      downloaded_files[[artifact_row$path]] <- new_path
      cat(sprintf("Downloaded and renamed %s to %s\n", artifact_row$path, new_filename))
    }
  }
  return(downloaded_files)
}

#' Display the runs and their parameters in a readable format
#' @param runs List of runs to display
#' @param title Optional title for the display
display_runs <- function(runs, title = "") {
  if (title != "") cat(sprintf("\n%s\n", title))
  cat(sprintf("Found %d runs to display:\n\n", length(runs)))
  
  for (i in seq_along(runs)) {
    run <- runs[[i]]
    cat(sprintf("Run %d:\n  Run ID: %s\n  Status: %s\n  Start Time: %s\n  End Time: %s\n", 
              i, run$run_id, run$status, run$start_time, run$end_time %||% "NA"))
    
    cat("\n  Parameters:\n")
    if (is.list(run$parameters) && length(run$parameters) > 0) {
      for (key in names(run$parameters)) cat(sprintf("    %s: %s\n", key, run$parameters[[key]]))
    } else cat("    No parameters found or parameters not in expected list format.\n")
    
    cat("\n  Metrics:\n")
    if (is.list(run$metrics) && length(run$metrics) > 0) {
      for (key in names(run$metrics)) cat(sprintf("    %s: %s\n", key, run$metrics[[key]]))
    } else cat("    No metrics found or metrics not in expected list format.\n")
    cat("\n", paste(rep("-", 80), collapse = ""), "\n\n")
  }
}

#' Null-coalescing operator similar to %||% in purrr
`%||%` <- function(x, y) if (is.null(x)) y else x

#' Main function to fetch and download MLflow runs and artifacts
#' @param output_path Base directory for output files
main <- function(output_path) {
  tryCatch({
    output_dir <- fs::path(output_path)
    fs::dir_create(output_dir, recurse = TRUE)
    cat(sprintf("Created output directory: %s\n", fs::path_abs(output_dir)))
    
    artifacts_dir <- fs::path(output_dir, "artifacts")
    fs::dir_create(artifacts_dir, recurse = TRUE)
    cat(sprintf("Created artifacts directory: %s\n", fs::path_abs(artifacts_dir)))
    
    # Fetch runs already filtered by target_scenario at the server level
    filtered_runs <- fetch_successful_runs_for_target_scenario(TARGET_SCENARIO_VALUE)
    
    if (length(filtered_runs) > 0) {
        display_runs(filtered_runs, sprintf("Runs matching '%s' (fetched via server-side filter)", TARGET_SCENARIO_VALUE))
        
        cat("\nDownloading artifacts for filtered runs...\n")
        for (run_to_download in filtered_runs) {
          run_id <- run_to_download$run_id
          scenario_geo <- if(is.list(run_to_download$parameters)) run_to_download$parameters$scenario_geography %||% "unknown" else "unknown"
          cat(sprintf("\nDownloading artifacts for run %s (Geography: %s)\n", run_id, scenario_geo))
          
          downloaded_files <- download_run_artifacts(run_id, as.character(artifacts_dir))
          cat(sprintf("Downloaded %d files for run %s:\n", length(downloaded_files), run_id))
          for (artifact_path in names(downloaded_files)) {
            cat(sprintf("  - %s -> %s\n", artifact_path, downloaded_files[[artifact_path]]))
          }
        }
    } else {
        cat(sprintf("\nNo runs found matching '%s' using server-side filter.\n", TARGET_SCENARIO_VALUE))
    }
    
    # As a fallback or for comparison, fetch all runs and filter client-side (optional, can be commented out)
    # cat("\n--- Fetching all successful runs for client-side filtering comparison ---\n")
    # all_successful_runs <- fetch_all_successful_runs() # You would need to define this function similar to the Python version
    # if (length(all_successful_runs) > 0) {
    #    client_filtered_runs <- filter_runs_by_target_scenario(all_successful_runs, TARGET_SCENARIO_VALUE)
    #    display_runs(client_filtered_runs, sprintf("Runs matching '%s' (client-side filter)", TARGET_SCENARIO_VALUE))
    # } else {
    #    cat("No successful runs found by fetch_all_successful_runs.\n")
    # }

    # Save run information to JSON (now primarily for server-filtered runs)
    # It might be useful to save all runs separately if you uncomment the block above.
    json_path <- fs::path(output_dir, "successful_runs.json")
    # For now, saving only the server-filtered runs.
    # If you want all_runs too, you'd fetch them and include them here.
    jsonlite::write_json(
      list(filtered_runs_by_server = filtered_runs), 
      json_path,
      pretty = TRUE,
      auto_unbox = TRUE
    )
    cat(sprintf("\nSaved detailed run information (server-filtered) to '%s'\n", json_path))
    
  }, error = function(e) {
    cat(sprintf("Error in main: %s\n", e$message))
    print(e) 
  })
}

# Run the main function
output_path <- "workspace/mlflow_results"
main(output_path)
