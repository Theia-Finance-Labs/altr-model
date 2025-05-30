library(dplyr)
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
      # Convert boolean strings to actual booleans
      if (value %in% c("TRUE", "true", "True", "1")) {
        value <- TRUE
      } else if (value %in% c("FALSE", "false", "False", "0")) {
        value <- FALSE
      }
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

if (is.null(parsed_args$ccs_status)) {
  stop("Required argument missing. Please provide --ccs_status argument (w/ CCS, w/o CCS, or both).")
}

if (is.null(parsed_args$shock_year)) {
  stop("Required argument missing. Please provide --shock_year argument.")
}

if (is.null(parsed_args$use_age_cutoff)) {
  stop("Required argument missing. Please provide --use_age_cutoff argument (TRUE or FALSE).")
}

if (is.null(parsed_args$use_staggered_shock)) {
  stop("Required argument missing. Please provide --use_staggered_shock argument (TRUE or FALSE).")
}

# Validate CCS status
valid_ccs_statuses <- c("w/ CCS", "w/o CCS", "both")
if (!parsed_args$ccs_status %in% valid_ccs_statuses) {
  stop("Invalid CCS status. Must be one of: ", paste(valid_ccs_statuses, collapse = ", "))
}

# Validate shock year
shock_year <- as.numeric(parsed_args$shock_year)
if (is.na(shock_year)) {
  stop("Invalid shock year. Must be a numeric value.")
}

# Validate boolean parameters
if (!is.logical(parsed_args$use_age_cutoff)) {
  stop("Invalid use_age_cutoff. Must be TRUE or FALSE.")
}

if (!is.logical(parsed_args$use_staggered_shock)) {
  stop("Invalid use_staggered_shock. Must be TRUE or FALSE.")
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
  # In Cloud Run, we use default credentials
  message("GOOGLE_APPLICATION_CREDENTIALS not set, using default credentials")
} else {
  # In local development, verify the credentials file exists
  creds_path <- Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS")
  if (!file.exists(creds_path)) {
    stop("The GCS credentials file does not exist at: ", creds_path)
  }

  # Print GCS credentials info for debugging
  message("GCS Credentials Info:")
  message("Credentials path: ", creds_path)
  message("File exists: ", file.exists(creds_path))
  message("File permissions: ", file.access(creds_path, mode = 4) == 0) # Check if readable
  message("File size: ", file.size(creds_path), " bytes")
}

# Get MLflow tracking URI from environment variable
mlflow_tracking_uri <- Sys.getenv("MLFLOW_TRACKING_URI")
if (mlflow_tracking_uri == "") {
  stop("The MLFLOW_TRACKING_URI environment variable is not set.")
}

# Get experiment name from environment variable
experiment_name <- Sys.getenv("MLFLOW_EXPERIMENT_NAME")
if (experiment_name == "") {
  experiment_name <- "trisk_runs" # Default value if not set
  message("MLFLOW_EXPERIMENT_NAME not set, using default value: ", experiment_name)
} else {
  message("Using experiment name from MLFLOW_EXPERIMENT_NAME: ", experiment_name)
}

# Initialize MLflow with error handling and retry logic
max_retries <- 3
retry_count <- 0
while (retry_count < max_retries) {
  tryCatch(
    {
      # Set MLflow tracking URI
      mlflow_set_tracking_uri(mlflow_tracking_uri)

      # Test the connection by getting the experiment
      experiment <- mlflow_get_experiment(name = "trisk_runs")

      # If we get here, connection is successful
      message("Successfully connected to MLflow server")
      break
    },
    error = function(e) {
      retry_count <<- retry_count + 1
      if (retry_count == max_retries) {
        stop("Failed to connect to MLflow server after ", max_retries, " attempts. Error: ", e$message)
      }
      message("Attempt ", retry_count, " failed. Retrying in 5 seconds...")
      Sys.sleep(5)
    }
  )
}

# Ensure experiment exists with proper error handling
tryCatch(
  {
    expected_artifact_location <- "gs://crispy-mlflow-backend"

    # Try to get the experiment first
    experiment <- mlflow_get_experiment(name = experiment_name)

    if (is.null(experiment)) {
      message(paste0("Experiment '", experiment_name, "' does not exist. Creating it..."))
      experiment <- mlflow_create_experiment(
        name = experiment_name,
        artifact_location = expected_artifact_location
      )
      message(paste0("Successfully created experiment '", experiment_name, "' with ID: ", experiment$experiment_id))
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

      message(paste0(
        "Verifying artifact_location. Current: '", actual_artifact_location_display,
        "', Expected: '", expected_artifact_location, "'"
      ))

      if (!identical(actual_artifact_location_trimmed, expected_artifact_location_trimmed)) {
        error_message <- sprintf(
          "CRITICAL ERROR: Existing MLflow experiment '%s' has an incorrect artifact_location: '%s'. Expected: '%s'. %s",
          experiment_name,
          actual_artifact_location_display,
          expected_artifact_location,
          paste0(
            "This script requires the artifact location to be GCS for proper operation. ",
            "Please delete the existing experiment from your MLflow server (likely at http://localhost:5000) ",
            "and re-run this script. It will be recreated with the correct settings."
          )
        )
        stop(error_message)
      }
    }

    # Set the experiment as active
    mlflow_set_experiment(experiment_name = experiment_name)

    # Verify active experiment
    active_exp <- mlflow_get_experiment()
    message(sprintf(
      "Successfully set up MLflow. Active experiment: '%s' (ID: %s), Artifact Location: '%s'",
      active_exp$name, active_exp$experiment_id,
      ifelse(is.null(active_exp$artifact_location), "Not set", active_exp$artifact_location)
    ))

    # Fetch existing run parameters to avoid re-computation
    message("Fetching existing MLflow runs to check for prior results...")
    existing_run_params_list <- list() # Initialize list to store parameters of relevant runs

    # This tryCatch is for fetching existing runs; errors here shouldn't stop the whole script,
    # but will mean no skipping occurs.
    tryCatch(
      {
        if (!is.null(active_exp) && !is.null(active_exp$experiment_id)) {
          all_run_infos <- mlflow::mlflow_search_runs(experiment_ids = active_exp$experiment_id)

          if (nrow(all_run_infos) > 0) {
            message(paste("Found", nrow(all_run_infos), "existing runs in experiment. Processing their parameters..."))
            for (run_info_idx in 1:nrow(all_run_infos)) {
              run_id <- all_run_infos$run_id[run_info_idx]
              run_data <- mlflow::mlflow_get_run(run_id = run_id)

              # Extract parameters if they exist
              if (!is.null(run_data$data$params) && nrow(run_data$data$params) > 0) {
                # Convert params data_frame to a named list
                # params_df columns are 'key' and 'value'
                params_df <- run_data$data$params
                run_params <- setNames(as.list(params_df$value), params_df$key)

                # Check for the presence of essential parameters for comparison
                required_params_for_check <- c("baseline_scenario", "target_scenario", "scenario_geography", "shock_year", "ccs_status")
                if (all(required_params_for_check %in% names(run_params))) {
                  existing_run_params_list[[run_id]] <- list(
                    baseline_scenario = run_params[["baseline_scenario"]],
                    target_scenario = run_params[["target_scenario"]],
                    scenario_geography = run_params[["scenario_geography"]],
                    shock_year = as.character(run_params[["shock_year"]]), # MLflow stores params as strings
                    ccs_status = run_params[["ccs_status"]], # Add CCS status to parameters
                    had_error = "error" %in% names(run_params) # Check if an 'error' parameter was logged
                  )
                }
              }
            }
            message(paste("Finished processing. Identified", length(existing_run_params_list), "prior runs with comparable parameters."))
          } else {
            message("No existing runs found in the experiment.")
          }
        } else {
          message("Warning: Active experiment or experiment ID is NULL. Cannot fetch existing runs to check for skipping.")
        }
      },
      error = function(e_fetch) {
        message(paste("Warning: Failed to fetch or process existing MLflow runs. Will proceed without skipping. Error:", e_fetch$message))
        # Ensure existing_run_params_list is empty or in a consistent state if error occurs mid-population
        existing_run_params_list <- list()
      }
    )
  },
  error = function(e) {
    message("Error setting up MLflow experiment 'trisk_runs': ", e$message)
    message("Current GOOGLE_APPLICATION_CREDENTIALS: ", Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    stop(paste0("Failed to set up MLflow experiment 'trisk_runs'. Please check your MLflow server (is it running at http://localhost:5000?), GCS credentials, and the 'trisk_runs' experiment configuration. Original error: ", e$message))
  }
)

# Define paths for container environment
data_dir <- "/app/data"
target_dir <- "/app/trisk.model"

# Read input data
assets_data <- readr::read_csv(file.path(data_dir, "assets_data.csv")) %>%
  rename(
    production_year = year,
    plant_age_years = asset_age
  )
message(sprintf("Loaded assets_data: %d rows, %d columns", nrow(assets_data), ncol(assets_data)))
message("Columns in assets_data: ", paste(names(assets_data), collapse = ", "))

# Load discount rates data
discount_rates_data <- readr::read_csv(file.path(data_dir, "countries_discount_rate.csv"))
message(sprintf("Loaded discount_rates_data: %d rows", nrow(discount_rates_data)))

# Group countries by discount rate
discount_rate_groups <- discount_rates_data %>%
  group_by(discount_rate) %>%
  summarise(countries = list(iso2), .groups = "drop")

# Modify technology column based on CCS status
if (parsed_args$ccs_status != "both") {
  assets_data <- assets_data %>%
    mutate(technology = case_when(
      technology %in% c("CoalCap", "GasCap", "OilCap") ~ paste0(technology, "_", parsed_args$ccs_status),
      TRUE ~ technology
    ))
}

scenarios_data <- readr::read_csv(file.path(data_dir, "scenarios_data.csv"))
message(sprintf("Loaded scenarios_data: %d rows, %d columns", nrow(scenarios_data), ncol(scenarios_data)))

financial_data <- readr::read_csv(file.path(data_dir, "financial_data.csv"))
message(sprintf("Loaded financial_data: %d rows, %d columns", nrow(financial_data), ncol(financial_data)))

carbon_data <- readr::read_csv(file.path(data_dir, "ngfs_carbon_price_testdata.csv"))
message(sprintf("Loaded carbon_data: %d rows, %d columns", nrow(carbon_data), ncol(carbon_data)))

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
  total_discount_rates <- nrow(discount_rate_groups)
  total_iterations <- total_scenarios * total_geographies * total_discount_rates
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
  tryCatch(
    {
      # Change to the trisk.model directory
      old_wd <- getwd()
      setwd(target_dir)

      # Get git commit information from environment variables
      git_commit <- Sys.getenv("TRISK_MODEL_COMMIT", "unknown_commit")
      git_commit_short <- Sys.getenv("TRISK_MODEL_COMMIT_SHORT", "unknown")

      devtools::load_all()
      setwd(old_wd)
    },
    error = function(e) {
      stop("Failed to load trisk.model package: ", e$message)
    }
  )

  # Initialize lists to store results for each discount rate
  all_npv_results <- list()
  all_pd_results <- list()
  all_company_trajectories <- list()

  # Loop through discount rates
  for (discount_rate_idx in 1:nrow(discount_rate_groups)) {
    current_discount_rate <- discount_rate_groups$discount_rate[discount_rate_idx]
    current_countries <- unlist(discount_rate_groups$countries[discount_rate_idx])
    
    # Filter assets_data for current countries
    filtered_assets_data <- assets_data %>%
      filter(country_iso2 %in% current_countries)
    
    message(sprintf("Processing discount rate %.3f for %d countries", 
                   current_discount_rate, length(current_countries)))

    for (target_scenario in unique(target_scenarios)) {
      # Get all geographies for this scenario
      scenario_geographies <- scenarios_data %>%
        filter(scenario == target_scenario) %>%
        distinct(scenario_geography) %>%
        pull(scenario_geography)

      # Filter geographies to only those containing countries from current discount rate group
      valid_geographies <- scenarios_data %>%
        filter(scenario == target_scenario,
               scenario_geography %in% scenario_geographies) %>%
        # Split country_iso2_list and check if any of the current countries are in the list
        filter(sapply(strsplit(country_iso2_list, ","), function(x) any(trimws(x) %in% current_countries))) %>%
        distinct(scenario_geography) %>%
        pull(scenario_geography)

      if (length(valid_geographies) == 0) {
        message(sprintf("Skipping target scenario %s - no valid geographies found for discount rate %.3f", 
                       target_scenario, current_discount_rate))
        next
      }

      for (scenario_geography in valid_geographies) {
        # Update progress bar
        current_iteration <- current_iteration + 1
        setTxtProgressBar(pb, current_iteration)

        # --- Check if this combination has already been run successfully ---
        current_params_to_check <- list(
          baseline_scenario = baseline_scenario,
          target_scenario = target_scenario,
          scenario_geography = scenario_geography,
          shock_year = as.character(shock_year),
          ccs_status = parsed_args$ccs_status,
          discount_rate = as.character(current_discount_rate)
        )

        already_ran_successfully <- FALSE
        if (length(existing_run_params_list) > 0) {
          for (existing_run_id in names(existing_run_params_list)) {
            params_from_existing_run <- existing_run_params_list[[existing_run_id]]

            # Compare all relevant parameters including discount rate
            if (identical(params_from_existing_run$baseline_scenario, current_params_to_check$baseline_scenario) &&
                identical(params_from_existing_run$target_scenario, current_params_to_check$target_scenario) &&
                identical(params_from_existing_run$scenario_geography, current_params_to_check$scenario_geography) &&
                identical(params_from_existing_run$shock_year, current_params_to_check$shock_year) &&
                identical(params_from_existing_run$ccs_status, current_params_to_check$ccs_status) &&
                identical(params_from_existing_run$discount_rate, current_params_to_check$discount_rate)) {
              if (!params_from_existing_run$had_error) {
                already_ran_successfully <- TRUE
                message(sprintf(
                  "Skipping: Baseline='%s', Target='%s', Geo='%s', ShockYear='%s', CCS='%s', DiscountRate='%.3f'. Found existing successful run: %s",
                  current_params_to_check$baseline_scenario,
                  current_params_to_check$target_scenario,
                  current_params_to_check$scenario_geography,
                  current_params_to_check$shock_year,
                  current_params_to_check$ccs_status,
                  current_discount_rate,
                  existing_run_id
                ))
                break
              } else {
                message(sprintf("Found existing run %s for parameters, but it had an error. Will re-run.", existing_run_id))
              }
            }
          }
        }

        if (already_ran_successfully) {
          next
        }

        # Sanitize target scenario name for use in filenames
        safe_target_scenario <- gsub("[\\/:*?\"<>|]", "_", target_scenario)
        base_filename <- paste0("npvs_", scenario_geography, "_", safe_target_scenario)
        output_csv <- file.path(base_output_dir, paste0(base_filename, ".csv"))
        output_txt <- file.path(base_output_dir, paste0(base_filename, ".txt"))
        
        params_overwrite <- list(
          baseline_scenario = baseline_scenario,
          target_scenario = target_scenario,
          scenario_geography = scenario_geography,
          shock_year = shock_year,
          discount_rate = current_discount_rate,
          use_age_cutoff = parsed_args$use_age_cutoff,
          use_staggered_shock = parsed_args$use_staggered_shock
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
          mlflow_log_param("shock_year", shock_year)
          mlflow_log_param("scenario_provider", scenario_provider)
          mlflow_log_param("trisk_model_commit", git_commit)
          mlflow_log_param("trisk_model_commit_short", git_commit_short)
          mlflow_log_param("ccs_status", parsed_args$ccs_status)
          mlflow_log_param("discount_rate", current_discount_rate)
          mlflow_log_param("use_age_cutoff", params_overwrite$use_age_cutoff)
          mlflow_log_param("use_staggered_shock", params_overwrite$use_staggered_shock)
          
          # Try to run the model, catch any errors
          tryCatch({
            st_results <- run_trisk_model(
              assets_data = filtered_assets_data,
              scenarios_data = scenarios_data,
              financial_data = financial_data,
              carbon_data = carbon_data,
              baseline_scenario = baseline_scenario,
              target_scenario = target_scenario,
              scenario_geography = scenario_geography,
              shock_year = shock_year,
              discount_rate = current_discount_rate,
              use_age_cutoff = params_overwrite$use_age_cutoff,
              use_staggered_shock = params_overwrite$use_staggered_shock
            )

            npv_results <- st_results$npv_results
            pd_results <- st_results$pd_results
            company_trajectories <- st_results$company_trajectories

            # Add trisk_params to each output dataframe
            npv_results <- npv_results %>%
              dplyr::bind_cols(trisk_params)
            
            pd_results <- pd_results %>%
              dplyr::bind_cols(trisk_params)
            
            # Store results in lists
            all_npv_results[[length(all_npv_results) + 1]] <- npv_results
            all_pd_results[[length(all_pd_results) + 1]] <- pd_results
            all_company_trajectories[[length(all_company_trajectories) + 1]] <- company_trajectories
            
            # Save individual NPV results file
            readr::write_csv(npv_results, output_csv)
            
            # Save company trajectories
            trajectories_csv <- file.path(base_output_dir, paste0(base_filename, "_trajectories.csv"))
            readr::write_csv(company_trajectories, trajectories_csv)
            
            # Log artifacts to MLflow with retry logic
            artifact_retry_count <- 0
            max_artifact_retries <- 3
            
            while (artifact_retry_count < max_artifact_retries) {
              tryCatch({
                # Verify files exist and are readable before logging
                if (!file.exists(output_csv)) {
                  stop("Output file does not exist: ", output_csv)
                }
                if (!file.exists(trajectories_csv)) {
                  stop("Trajectories file does not exist: ", trajectories_csv)
                }
                if (file.access(output_csv, mode = 4) != 0) {
                  stop("Output file is not readable: ", output_csv)
                }
                if (file.access(trajectories_csv, mode = 4) != 0) {
                  stop("Trajectories file is not readable: ", trajectories_csv)
                }
                
                # Get file info for debugging
                file_info <- file.info(output_csv)
                message("File info for ", output_csv, ":")
                message("  Size: ", file_info$size, " bytes")
                message("  Permissions: ", file_info$mode)
                message("  Owner: ", file_info$uname)
                message("  Group: ", file_info$grname)
                
                # Try to log the artifacts
                mlflow_log_artifact(output_csv)
                mlflow_log_artifact(trajectories_csv)
                message("Successfully logged artifacts: ", output_csv, " and ", trajectories_csv)
                
                # Delete the files after successful logging
                if (file.exists(output_csv)) {
                  file.remove(output_csv)
                  message("Successfully deleted local file: ", output_csv)
                }
                if (file.exists(trajectories_csv)) {
                  file.remove(trajectories_csv)
                  message("Successfully deleted local file: ", trajectories_csv)
                }
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
            
            # End the run successfully
            mlflow_end_run()
            message("Successfully ended MLflow run")
          },
          error = function(e) {
            # Save error message to text file
            error_message <- paste0(
              "Error running trisk model for:\n",
              "Scenario geography: ", scenario_geography, "\n",
              "Target scenario: ", target_scenario, "\n",
              "CCS status: ", parsed_args$ccs_status, "\n",
              "Shock year: ", shock_year, "\n",
              "Discount rate: ", current_discount_rate, "\n",
              "Error message: ", e$message, "\n",
              "Timestamp: ", format(Sys.time(), "%Y-%m-%d %H:%M:%S")
            )
            writeLines(error_message, output_txt)
            
            # Log error as a parameter with retry logic
            error_retry_count <- 0
            max_error_retries <- 3
            
            while (error_retry_count < max_error_retries) {
              tryCatch({
                # Log error as a parameter
                mlflow_log_param("error", e$message)
                
                # Log error file as artifact
                mlflow_log_artifact(output_txt)
                
                message("Successfully logged error artifact")
                
                # Delete the error file after successful logging
                if (file.exists(output_txt)) {
                  file.remove(output_txt)
                  message("Successfully deleted local error file: ", output_txt)
                }
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
            
            # End the run with failed status
            mlflow_set_tag("status", "failed")
            mlflow_set_tag("error_message", e$message)
            mlflow_end_run(status = "FAILED")
            message("Successfully marked run as failed")
          })
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
  }
  
  # Combine all results after processing all discount rates
  if (length(all_npv_results) > 0) {
    combined_npv_results <- dplyr::bind_rows(all_npv_results)
    combined_pd_results <- dplyr::bind_rows(all_pd_results)
    combined_company_trajectories <- dplyr::bind_rows(all_company_trajectories)
    
    # Save combined results
    combined_npv_file <- file.path(base_output_dir, paste0("combined_npvs_", safe_target_scenario, ".csv"))
    combined_pd_file <- file.path(base_output_dir, paste0("combined_pd_", safe_target_scenario, ".csv"))
    combined_trajectories_file <- file.path(base_output_dir, paste0("combined_trajectories_", safe_target_scenario, ".csv"))
    
    readr::write_csv(combined_npv_results, combined_npv_file)
    readr::write_csv(combined_pd_results, combined_pd_file)
    readr::write_csv(combined_company_trajectories, combined_trajectories_file)
    
    message(sprintf("Saved combined results for %s with %d discount rates", 
                   safe_target_scenario, length(all_npv_results)))
  }
  
  # Close progress bar
  close(pb)
}
