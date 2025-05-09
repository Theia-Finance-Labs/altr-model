# Parse command line arguments
args <- commandArgs(trailingOnly = TRUE)

# Function to parse named arguments
parse_args <- function(args) {
  args_list <- list()
  for (arg in args) {
    split_arg <- strsplit(arg, "=")[[1]]
    if (length(split_arg) == 2) {
      name <- gsub("^--", "", split_arg[1])
      value <- split_arg[2]
      # Remove surrounding quotes if they exist
      value <- gsub("^\"|\"$", "", value)
      args_list[[name]] <- value
    }
  }
  return(args_list)
}

# Parse the arguments
parsed_args <- parse_args(args)

if (is.null(parsed_args$config)) {
  stop("Required argument missing. Please provide --config argument with baseline-target pairs JSON.")
}

# Parse the JSON configuration
library(jsonlite)
json_data <- fromJSON(parsed_args$config)
if (!is.data.frame(json_data)) {
  # Convert list to data frame if necessary
  json_data <- as.data.frame(do.call(rbind, json_data))
}

# run kedro run --tags=legacy to get the data
library(readxl)
library(dplyr)
library(mlflow)

# Check if GCS credentials environment variable is set
if (Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS") == "") {
  stop("The GOOGLE_APPLICATION_CREDENTIALS environment variable is not set. \nPlease set it to the path of your GCS credentials JSON file.")
}

# Verify the credentials file exists and is readable
creds_path <- Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if (!file.exists(creds_path)) {
  stop("The GCS credentials file does not exist at: ", creds_path)
}

# Print GCS credentials info for debugging
message("GCS Credentials Info:")
message("Credentials path: ", creds_path)
message("File exists: ", file.exists(creds_path))
message("File permissions: ", file.access(creds_path, mode = 4) == 0)  # Check if readable
message("File size: ", file.size(creds_path), " bytes")

# Get MLflow tracking URI from environment variable
mlflow_tracking_uri <- Sys.getenv("MLFLOW_TRACKING_URI")
if (mlflow_tracking_uri == "") {
  stop("The MLFLOW_TRACKING_URI environment variable is not set.")
}

# Initialize MLflow with error handling and retry logic
max_retries <- 3
retry_count <- 0
while (retry_count < max_retries) {
  tryCatch({
    # Set MLflow tracking URI
    mlflow_set_tracking_uri(mlflow_tracking_uri)
    
    # Test the connection by getting the experiment
    experiment <- mlflow_get_experiment(name = "trisk_runs")
    
    # If we get here, connection is successful
    message("Successfully connected to MLflow server")
    break
  }, error = function(e) {
    retry_count <<- retry_count + 1
    if (retry_count == max_retries) {
      stop("Failed to connect to MLflow server after ", max_retries, " attempts. Error: ", e$message)
    }
    message("Attempt ", retry_count, " failed. Retrying in 5 seconds...")
    Sys.sleep(5)
  })
}

# Ensure experiment exists with proper error handling
tryCatch({
  experiment_name <- "trisk_runs"
  expected_artifact_location <- "gs://crispy-mlflow-backend"
  
  # Try to get the experiment first
  experiment <- mlflow_get_experiment(name = experiment_name)
  
  if (is.null(experiment)) {
    message(paste0("Experiment '", experiment_name, "' does not exist. Creating with artifact location: '", expected_artifact_location, "' and setting as active."))
    mlflow_set_experiment(experiment_name = experiment_name, artifact_location = expected_artifact_location)
  } else {
    message(paste0("Experiment '", experiment_name, "' already exists with ID: ", experiment$experiment_id))
    
    # Handle cases where artifact_location might be NULL or needs trimming
    actual_artifact_location_val <- experiment$artifact_location
    if (is.null(actual_artifact_location_val)) {
        actual_artifact_location_trimmed <- ""
        actual_artifact_location_display <- "Not set"
    } else {
        actual_artifact_location_trimmed <- trimws(actual_artifact_location_val)
        actual_artifact_location_display <- actual_artifact_location_val
    }
    expected_artifact_location_trimmed <- trimws(expected_artifact_location)

    message(paste0("Verifying artifact_location. Current: '", actual_artifact_location_display, 
                   "', Expected: '", expected_artifact_location, "'"))

    if (!identical(actual_artifact_location_trimmed, expected_artifact_location_trimmed)) {
      error_message <- sprintf(
        "CRITICAL ERROR: Existing MLflow experiment '%s' has an incorrect artifact_location: '%s'. Expected: '%s'. %s",
        experiment_name, 
        actual_artifact_location_display,
        expected_artifact_location,
        paste0("This script requires the artifact location to be GCS for proper operation. ",
               "Please delete the existing experiment from your MLflow server (likely at http://localhost:5000) ",
               "and re-run this script. It will be recreated with the correct settings.")
      )
      stop(error_message)
    }
    
    # If artifact location is correct, set experiment as active
    message(paste0("Existing experiment '", experiment_name, "' has the correct artifact location. Setting as active."))
    mlflow_set_experiment(experiment_name = experiment_name)
  }
  
  # Verify active experiment (optional but good for sanity check)
  active_exp <- mlflow_get_experiment()
  message(sprintf("Successfully set up MLflow. Active experiment: '%s' (ID: %s), Artifact Location: '%s'", 
                  active_exp$name, active_exp$experiment_id, 
                  ifelse(is.null(active_exp$artifact_location), "Not set", active_exp$artifact_location)))

}, error = function(e) {
  message("Error setting up MLflow experiment 'trisk_runs': ", e$message)
  message("Current GOOGLE_APPLICATION_CREDENTIALS: ", Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
  stop(paste0("Failed to set up MLflow experiment 'trisk_runs'. Please check your MLflow server (is it running at http://localhost:5000?), GCS credentials, and the 'trisk_runs' experiment configuration. Original error: ", e$message))
})

# Define paths for container environment
data_dir <- "/app/data"
target_dir <- "/app/trisk.model"

# Read input data
assets_data <- readr::read_csv(file.path(data_dir, "assets_data.csv")) %>% 
  rename(
    production_year=year,
    plant_age_years=asset_age
  )
scenarios_data <- readr::read_csv(file.path(data_dir, "scenarios_data.csv"))
financial_data <- readr::read_csv(file.path(data_dir, "financial_data.csv"))
carbon_data <- readr::read_csv(file.path(data_dir, "ngfs_carbon_price_testdata.csv"))

SHOCK_YEAR = 2030

# Process each baseline-target pair
for (i in 1:nrow(json_data)) {
  baseline_scenario <- json_data$baseline[i]
  target_scenarios <- unlist(json_data$targets[i])

  available_scenario_geographies <- scenarios_data %>% 
    filter(scenario %in% c(baseline_scenario, target_scenarios)) %>%
    distinct(scenario_geography)
  print(available_scenario_geographies)

  # Set up progress bar
  total_scenarios <- length(target_scenarios)
  total_geographies <- nrow(available_scenario_geographies)
  total_iterations <- total_scenarios * total_geographies
  pb <- txtProgressBar(min = 0, max = total_iterations, style = 3)
  current_iteration <- 0

  # Create base output directory if it doesn't exist
  # Get scenario provider from scenarios dataframe
  scenario_provider <- scenarios_data %>%
    filter(scenario == baseline_scenario) %>%
    pull(scenario_provider) %>%
    unique()
  base_output_dir <- file.path(data_dir, "trisk_results", scenario_provider)
  if (!dir.exists(base_output_dir)) {
    dir.create(base_output_dir, recursive = TRUE)
  }

  # Load the trisk.model package
  tryCatch({
    # Change to the trisk.model directory
    old_wd <- getwd()
    setwd(target_dir)
    devtools::load_all()
    setwd(old_wd)
  }, error = function(e) {
    stop("Failed to load trisk.model package: ", e$message)
  })

  for (target_scenario in unique(target_scenarios)) {  
    for (scenario_geography in unique(available_scenario_geographies$scenario_geography)) {
      # Update progress bar
      current_iteration <- current_iteration + 1
      setTxtProgressBar(pb, current_iteration)
      
      # Sanitize target scenario name for use in filenames
      safe_target_scenario <- gsub("[\\/:*?\"<>|]", "_", target_scenario)
      base_filename <- paste0("npvs_", scenario_geography, "_", safe_target_scenario)
      output_csv <- file.path(base_output_dir, paste0(base_filename, ".csv"))
      output_txt <- file.path(base_output_dir, paste0(base_filename, ".txt"))
      
      params_overwrite <- list(
        baseline_scenario = baseline_scenario,
        target_scenario = target_scenario,
        scenario_geography = scenario_geography,
        shock_year = SHOCK_YEAR
      )
      trisk_params <- do.call(trisk.model::process_params, c(list(fun = trisk.model::run_trisk_model), params_overwrite))

      # Start MLflow run with error handling
      tryCatch({
        # Start a new run with nested=TRUE to handle potential existing runs
        run <- mlflow_start_run(nested = TRUE)
        
        # Log parameters
        mlflow_log_param("baseline_scenario", baseline_scenario)
        mlflow_log_param("target_scenario", target_scenario)
        mlflow_log_param("scenario_geography", scenario_geography)
        mlflow_log_param("shock_year", SHOCK_YEAR)
        mlflow_log_param("scenario_provider", scenario_provider)
        
        # Try to run the model, catch any errors
        tryCatch({
          st_results <- run_trisk_model(
            assets_data = assets_data,
            scenarios_data = scenarios_data,
            financial_data = financial_data,
            carbon_data = carbon_data,
            baseline_scenario = baseline_scenario,
            target_scenario = target_scenario,
            scenario_geography = scenario_geography,
            shock_year = SHOCK_YEAR
          )

          npv_results <- st_results$npv_results
          pd_results <- st_results$pd_results
          company_trajectories <- st_results$company_trajectories

          # Add trisk_params to each output dataframe
          npv_results <- npv_results %>%
            dplyr::bind_cols(trisk_params)
          
          pd_results <- pd_results %>%
            dplyr::bind_cols(trisk_params)
          
          company_trajectories <- company_trajectories %>%
            dplyr::bind_cols(trisk_params)
          
          # Save individual NPV results file
          readr::write_csv(npv_results, output_csv)
          
          # Log artifacts to MLflow with retry logic
          artifact_retry_count <- 0
          max_artifact_retries <- 3
          
          while (artifact_retry_count < max_artifact_retries) {
            tryCatch({
              # Verify file exists and is readable before logging
              if (!file.exists(output_csv)) {
                stop("Output file does not exist: ", output_csv)
              }
              if (file.access(output_csv, mode = 4) != 0) {
                stop("Output file is not readable: ", output_csv)
              }
              
              # Get file info for debugging
              file_info <- file.info(output_csv)
              message("File info for ", output_csv, ":")
              message("  Size: ", file_info$size, " bytes")
              message("  Permissions: ", file_info$mode)
              message("  Owner: ", file_info$uname)
              message("  Group: ", file_info$grname)
              
              # Try to log the artifact
              mlflow_log_artifact(output_csv)
              message("Successfully logged artifact: ", output_csv)
              break
            }, error = function(e) {
              artifact_retry_count <<- artifact_retry_count + 1
              if (artifact_retry_count == max_artifact_retries) {
                message("Warning: Failed to log artifact after ", max_artifact_retries, " attempts: ", e$message)
                message("Full error details:")
                message("  Error message: ", e$message)
                message("  Error class: ", class(e)[1])
                message("  Call stack: ", paste(capture.output(sys.calls()), collapse = "\n"))
              } else {
                message("Attempt ", artifact_retry_count, " to log artifact failed. Retrying in 5 seconds...")
                message("Error details: ", e$message)
                Sys.sleep(5)
              }
            })
          }
          
          # Log some summary metrics
          mlflow_log_metric("total_assets", nrow(npv_results))
          mlflow_log_metric("total_companies", length(unique(npv_results$company_name)))
          
          message("NPV results for ", scenario_geography, " - ", target_scenario, " saved to: ", output_csv)
        },
        error = function(e) {
          # Save error message to text file
          error_message <- paste0(
            "Error running trisk model for:\n",
            "Scenario geography: ", scenario_geography, "\n",
            "Target scenario: ", target_scenario, "\n",
            "Error message: ", e$message, "\n",
            "Timestamp: ", format(Sys.time(), "%Y-%m-%d %H:%M:%S")
          )
          writeLines(error_message, output_txt)
          
          # Log error as a parameter with retry logic
          error_retry_count <- 0
          max_error_retries <- 3
          
          while (error_retry_count < max_error_retries) {
            tryCatch({
              mlflow_log_param("error", e$message)
              mlflow_log_artifact(output_txt)
              message("Successfully logged error artifact")
              break
            }, error = function(e2) {
              error_retry_count <<- error_retry_count + 1
              if (error_retry_count == max_error_retries) {
                message("Warning: Failed to log error artifact after ", max_error_retries, " attempts: ", e2$message)
                message("Full error details:")
                message("  Error message: ", e2$message)
                message("  Error class: ", class(e2)[1])
                message("  Call stack: ", paste(capture.output(sys.calls()), collapse = "\n"))
              } else {
                message("Attempt ", error_retry_count, " to log error artifact failed. Retrying in 5 seconds...")
                message("Error details: ", e2$message)
                Sys.sleep(5)
              }
            })
          }
          
          message("ERROR for ", scenario_geography, " - ", target_scenario, ". Error saved to: ", output_txt)
        })
        
        # End the run explicitly with retry logic
        end_run_retry_count <- 0
        max_end_run_retries <- 3
        
        while (end_run_retry_count < max_end_run_retries) {
          tryCatch({
            mlflow_end_run()
            message("Successfully ended MLflow run")
            break
          }, error = function(e) {
            end_run_retry_count <<- end_run_retry_count + 1
            if (end_run_retry_count == max_end_run_retries) {
              message("Warning: Failed to end MLflow run after ", max_end_run_retries, " attempts: ", e$message)
            } else {
              message("Attempt ", end_run_retry_count, " to end run failed. Retrying in 5 seconds...")
              Sys.sleep(5)
            }
          })
        }
      }, error = function(e) {
        message("Error in MLflow run: ", e$message)
        message("Current GOOGLE_APPLICATION_CREDENTIALS: ", Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        # Try to end any active run if there is one
        tryCatch({
          mlflow_end_run()
        }, error = function(e) {
          message("Warning: Could not end MLflow run: ", e$message)
        })
        # Continue with next iteration even if MLflow fails
      })
    }
  }
  # Close progress bar
  close(pb)
}

