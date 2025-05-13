# Define arguments
ARGS <- list(
  BASELINE_SCENARIO = NULL,  # Set to NULL to include all baseline scenarios
  TARGET_SCENARIO = NULL,    # Set to NULL to include all target scenarios
  SCENARIO_GEOGRAPHY = NULL, # Set to NULL to include all geographies
  SHOCK_YEAR = NULL,        # Set to NULL to include all shock years
  CCS_STATUS = NULL,        # Set to NULL to include all CCS statuses
  SCENARIO_PROVIDER = NULL  # Set to NULL to include all providers
)

# Define valid arguments
VALID_ARGS <- names(ARGS)

# Load required libraries
library(mlflow)
library(dplyr)
library(readr)
library(purrr)

# Hardcoded MLflow tracking URI and experiment name
mlflow_tracking_uri <- "https://mlflow.1in1000.com:443"
experiment_name <- "age_impact_v1"

# Initialize MLflow
mlflow_set_tracking_uri(mlflow_tracking_uri)
mlflow_set_experiment(experiment_name)

# Function to check if a run matches the filter parameters
matches_filters <- function(run_data, filters) {
  if (length(filters) == 0) return(TRUE)
  
  # Get run parameters
  params <- run_data$data$params
  if (is.null(params) || nrow(params) == 0) return(FALSE)
  
  # Convert params to named list
  param_list <- setNames(params$value, params$key)
  
  # Check if all filters match
  all(sapply(names(filters), function(param_name) {
    param_value <- filters[[param_name]]
    !is.null(param_list[[param_name]]) && param_list[[param_name]] == param_value
  }))
}

# Function to download and combine artifacts from a run
download_run_artifacts <- function(run_id, output_dir) {
  # Create run-specific directory
  run_dir <- file.path(output_dir, run_id)
  dir.create(run_dir, recursive = TRUE, showWarnings = FALSE)
  
  # Get run info
  run_data <- mlflow_get_run(run_id)
  
  # Download artifacts
  tryCatch({
    # Start a new run context
    mlflow_start_run(run_id = run_id)
    
    message(sprintf("Listing artifacts for run %s...", run_id))
    artifacts <- mlflow_list_artifacts(run_id)
    
    if (nrow(artifacts) == 0) {
      message(sprintf("No artifacts found for run %s", run_id))
      return(FALSE)
    }
    
    message(sprintf("Found %d artifacts for run %s", nrow(artifacts), run_id))
    
    for (i in 1:nrow(artifacts)) {
      artifact_path <- artifacts$path[i]
      message(sprintf("Processing artifact: %s", artifact_path))
      
      if (grepl("\\.csv$", artifact_path)) {
        # Download CSV file
        local_path <- file.path(run_dir, basename(artifact_path))
        message(sprintf("Attempting to download to: %s", normalizePath(local_path)))
        
        tryCatch({
          mlflow_download_artifacts(run_id, artifact_path, local_path)
          message(sprintf("Successfully downloaded artifact to: %s", normalizePath(local_path)))
          
          # Read and add run parameters
          data <- read_csv(local_path)
          params <- run_data$data$params
          if (!is.null(params) && nrow(params) > 0) {
            param_list <- setNames(params$value, params$key)
            for (param_name in names(param_list)) {
              data[[param_name]] <- param_list[[param_name]]
            }
          }
          
          # Save enriched data
          write_csv(data, local_path)
          message(sprintf("Successfully processed and saved data to: %s", normalizePath(local_path)))
        }, error = function(e) {
          message(sprintf("Error processing artifact %s: %s", artifact_path, e$message))
        })
      } else {
        message(sprintf("Skipping non-CSV artifact: %s", artifact_path))
      }
    }
    
    # End the run
    mlflow_end_run()
    return(TRUE)
  }, error = function(e) {
    message(sprintf("Error downloading artifacts for run %s: %s", run_id, e$message))
    # Make sure to end the run even if there's an error
    tryCatch(mlflow_end_run(), error = function(e) {})
    return(FALSE)
  })
}

# Main execution
main <- function() {
  # Create output directory
  output_dir <- "trisk_results"
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  
  # Get all runs from the experiment
  runs <- mlflow_search_runs(experiment_ids = list(mlflow_get_experiment()$experiment_id))
  
  # Convert arguments to filters
  filters <- list()
  
  for (param in VALID_ARGS) {
    if (!is.null(ARGS[[param]])) {
      # Convert parameter name to lowercase for MLflow comparison
      filters[[tolower(param)]] <- ARGS[[param]]
    }
  }
  
  # Filter and process runs
  successful_downloads <- 0
  failed_downloads <- 0
  
  for (i in 1:nrow(runs)) {
    run_id <- runs$run_uuid[i]
    run_data <- mlflow_get_run(run_id)
    
    if (matches_filters(run_data, filters)) {
      message(sprintf("Processing run %s", run_id))
      if (download_run_artifacts(run_id, output_dir)) {
        successful_downloads <- successful_downloads + 1
      } else {
        failed_downloads <- failed_downloads + 1
      }
    }
  }
  
  # Print summary
  message("\nDownload Summary:")
  message(sprintf("Total runs found: %d", nrow(runs)))
  message(sprintf("Runs matching filters: %d", successful_downloads + failed_downloads))
  message(sprintf("Successful downloads: %d", successful_downloads))
  message(sprintf("Failed downloads: %d", failed_downloads))
  message(sprintf("\nResults saved in: %s", normalizePath(output_dir)))
}

# Run the main function
main() 