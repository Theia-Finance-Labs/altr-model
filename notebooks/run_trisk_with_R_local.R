# run kedro run --tags=legacy to get the data
library(readxl)
library(dplyr)
library(mlflow)

# Define CCS status
CCS_STATUS <- "w/ CCS"  # or "w/o CCS" or "both"

# Check if GCS credentials environment variable is set
if (Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS") == "") {
  stop("The GOOGLE_APPLICATION_CREDENTIALS environment variable is not set. \nPlease set it to the path of your GCS credentials JSON file.")
}

# Verify the credentials file exists and is readable
creds_path <- Sys.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if (!file.exists(creds_path)) {
  stop("The GCS credentials file does not exist at: ", creds_path)
}

# Initialize MLflow with error handling and retry logic
max_retries <- 3
retry_count <- 0
while (retry_count < max_retries) {
  tryCatch({
    # Set MLflow tracking URI
    mlflow_set_tracking_uri("http://localhost:5000")
    
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

# Get the script's directory and normalize paths
script_dir <- normalizePath(dirname(sys.frame(1)$ofile), mustWork = FALSE)
if (script_dir == ".") {
  # If running interactively or from RStudio, get the current working directory
  script_dir <- getwd()
}

# Define the target directory relative to the script
target_dir <- file.path(dirname(script_dir), "pkg", "trisk.model")

# Normalize the target directory path
target_dir <- normalizePath(target_dir, mustWork = FALSE)

# If not already in pkg/trisk.model, set it
if (!grepl(paste0("/?", basename(target_dir), "$"), normalizePath(getwd(), mustWork = FALSE))) {
  if (dir.exists(target_dir)) {
    setwd(target_dir)
    message("Working directory set to: ", getwd())
  } else {
    stop("Target directory does not exist: ", target_dir, "\nPlease ensure you are running this script from the correct location.")
  }
}

# Define data paths relative to the script directory
data_dir <- file.path(dirname(script_dir), "data", "08_reporting")
data_dir <- normalizePath(data_dir, mustWork = FALSE)

if (!dir.exists(data_dir)) {
  stop("Data directory does not exist: ", data_dir, "\nPlease ensure you have run 'kedro run --tags=legacy' first.")
}

assets_data <- readr::read_csv(file.path(data_dir, "assets_data.csv")) %>% 
  rename(
    production_year=year,
    plant_age_years=asset_age
  )

# Modify technology column based on CCS status
if (CCS_STATUS != "both") {
  assets_data <- assets_data %>%
    mutate(technology = case_when(
      technology %in% c("CoalCap", "GasCap", "OilCap") ~ paste0(technology, "_", CCS_STATUS),
      TRUE ~ technology
    ))
}

scenarios_data <- readr::read_csv(file.path(data_dir, "scenarios_data.csv"))
financial_data <- readr::read_csv(file.path(data_dir, "financial_data.csv"))
carbon_data <- readr::read_csv(file.path(target_dir, "inst", "testdata", "ngfs_carbon_price_testdata.csv"))

SHOCK_YEAR = 2030

BASELINE_TARGET_PAIR <- list(
  list(baseline='AR6_WITCH 5.0_EN_NoPolicy',
  targets=c(
"AR6_WITCH 5.0_EN_INDCi2030_1000", 
"AR6_WITCH 5.0_EN_INDCi2030_1000_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1000f", 
"AR6_WITCH 5.0_EN_INDCi2030_1000f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1200", 
"AR6_WITCH 5.0_EN_INDCi2030_1200_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1200f", 
"AR6_WITCH 5.0_EN_INDCi2030_1200f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1400", 
"AR6_WITCH 5.0_EN_INDCi2030_1400_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1400f", 
"AR6_WITCH 5.0_EN_INDCi2030_1400f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1600", 
"AR6_WITCH 5.0_EN_INDCi2030_1600_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1600f", 
"AR6_WITCH 5.0_EN_INDCi2030_1600f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1800", 
"AR6_WITCH 5.0_EN_INDCi2030_1800_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_1800f", 
"AR6_WITCH 5.0_EN_INDCi2030_1800f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_2000", 
"AR6_WITCH 5.0_EN_INDCi2030_2000_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_2000f", 
"AR6_WITCH 5.0_EN_INDCi2030_2000f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_2500", 
"AR6_WITCH 5.0_EN_INDCi2030_2500_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_2500f", 
"AR6_WITCH 5.0_EN_INDCi2030_2500f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_3000", 
"AR6_WITCH 5.0_EN_INDCi2030_3000_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_3000f", 
"AR6_WITCH 5.0_EN_INDCi2030_3000f_NDCp", "AR6_WITCH 5.0_EN_INDCi2030_500f", 
"AR6_WITCH 5.0_EN_INDCi2030_600f", "AR6_WITCH 5.0_EN_INDCi2030_600f_NDCp", 
"AR6_WITCH 5.0_EN_INDCi2030_700f", "AR6_WITCH 5.0_EN_INDCi2030_700f_NDCp", 
"AR6_WITCH 5.0_EN_INDCi2030_800", "AR6_WITCH 5.0_EN_INDCi2030_800_NDCp", 
"AR6_WITCH 5.0_EN_INDCi2030_800f", "AR6_WITCH 5.0_EN_INDCi2030_800f_NDCp", 
"AR6_WITCH 5.0_EN_INDCi2030_900", "AR6_WITCH 5.0_EN_INDCi2030_900_NDCp", 
"AR6_WITCH 5.0_EN_INDCi2030_900f", "AR6_WITCH 5.0_EN_INDCi2030_900f_NDCp", 
"AR6_WITCH 5.0_EN_INDCi2100", "AR6_WITCH 5.0_EN_INDCi2100_NDCp", 
"AR6_WITCH 5.0_EN_NPi2020_1000", "AR6_WITCH 5.0_EN_NPi2020_1000f", 
"AR6_WITCH 5.0_EN_NPi2020_1200", "AR6_WITCH 5.0_EN_NPi2020_1200f", 
"AR6_WITCH 5.0_EN_NPi2020_1400", "AR6_WITCH 5.0_EN_NPi2020_1400f", 
"AR6_WITCH 5.0_EN_NPi2020_1600", "AR6_WITCH 5.0_EN_NPi2020_1600f", 
"AR6_WITCH 5.0_EN_NPi2020_1800", "AR6_WITCH 5.0_EN_NPi2020_1800f", 
"AR6_WITCH 5.0_EN_NPi2020_2000", "AR6_WITCH 5.0_EN_NPi2020_2000f", 
"AR6_WITCH 5.0_EN_NPi2020_2500", "AR6_WITCH 5.0_EN_NPi2020_2500f", 
"AR6_WITCH 5.0_EN_NPi2020_3000", "AR6_WITCH 5.0_EN_NPi2020_3000f", 
"AR6_WITCH 5.0_EN_NPi2020_400f", "AR6_WITCH 5.0_EN_NPi2020_450", 
"AR6_WITCH 5.0_EN_NPi2020_450f", "AR6_WITCH 5.0_EN_NPi2020_500", 
"AR6_WITCH 5.0_EN_NPi2020_500f", "AR6_WITCH 5.0_EN_NPi2020_600", 
"AR6_WITCH 5.0_EN_NPi2020_600f", "AR6_WITCH 5.0_EN_NPi2020_700", 
"AR6_WITCH 5.0_EN_NPi2020_700f", "AR6_WITCH 5.0_EN_NPi2020_800", 
"AR6_WITCH 5.0_EN_NPi2020_800f", "AR6_WITCH 5.0_EN_NPi2020_900", 
"AR6_WITCH 5.0_EN_NPi2020_900f", "AR6_WITCH 5.0_EN_NPi2100"
  )),
  list(baseline='AR6_IMAGE 3.2_SSP1-baseline',
  targets=c(

"AR6_IMAGE 3.2_SSP1_SPA1_19I_RE_LB", "AR6_IMAGE 3.2_SSP1_SPA1_26I_D", 
"AR6_IMAGE 3.2_SSP1_SPA1_26I_LI", "AR6_IMAGE 3.2_SSP1_SPA1_26I_LIRE", 
"AR6_IMAGE 3.2_SSP1_SPA1_26I_RE", "AR6_IMAGE 3.2_SSP1_SPA1_34I_D", 
"AR6_IMAGE 3.2_SSP1_SPA1_34I_LI", "AR6_IMAGE 3.2_SSP1_SPA1_34I_LIRE", 
"AR6_IMAGE 3.2_SSP1_SPA1_34I_RE"

  )),
  list(baseline='AR6_IMAGE 3.2_SSP2-baseline',
  targets=c(

"AR6_IMAGE 3.2_SSP2_SPA0_26I_D", 
"AR6_IMAGE 3.2_SSP2_SPA1_19I_D_LB", "AR6_IMAGE 3.2_SSP2_SPA1_19I_LIRE_LB", 
"AR6_IMAGE 3.2_SSP2_SPA1_19I_RE_LB", "AR6_IMAGE 3.2_SSP2_SPA2_19I_D", 
"AR6_IMAGE 3.2_SSP2_SPA2_19I_LI", "AR6_IMAGE 3.2_SSP2_SPA2_19I_LIRE", 
"AR6_IMAGE 3.2_SSP2_SPA2_19I_RE", "AR6_IMAGE 3.2_SSP2_SPA2_26I_D", 
"AR6_IMAGE 3.2_SSP2_SPA2_26I_LI", "AR6_IMAGE 3.2_SSP2_SPA2_26I_LIRE", 
"AR6_IMAGE 3.2_SSP2_SPA2_26I_RE", "AR6_IMAGE 3.2_SSP2_SPA2_34I_D", 
"AR6_IMAGE 3.2_SSP2_SPA2_34I_LI", "AR6_IMAGE 3.2_SSP2_SPA2_34I_LIRE", 
"AR6_IMAGE 3.2_SSP2_SPA2_34I_RE", "AR6_IMAGE 3.2_SSP2_SPA2_45I_D", 
"AR6_IMAGE 3.2_SSP2_SPA2_45I_LI", "AR6_IMAGE 3.2_SSP2_SPA2_45I_LIRE", 
"AR6_IMAGE 3.2_SSP2_SPA2_45I_RE"

  ))
)

for (baseline_target_pairs in BASELINE_TARGET_PAIR) {
  baseline_scenario <- baseline_target_pairs$baseline
  target_scenarios <- baseline_target_pairs$targets

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

  devtools::load_all()
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
        mlflow_log_param("ccs_status", CCS_STATUS)  # Log CCS status
        
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
              mlflow_log_artifact(output_csv)
              message("Successfully logged artifact: ", output_csv)
              break
            }, error = function(e) {
              artifact_retry_count <<- artifact_retry_count + 1
              if (artifact_retry_count == max_artifact_retries) {
                message("Warning: Failed to log artifact after ", max_artifact_retries, " attempts: ", e$message)
              } else {
                message("Attempt ", artifact_retry_count, " to log artifact failed. Retrying in 5 seconds...")
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
            "CCS status: ", CCS_STATUS, "\n",  # Add CCS status to error message
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
              } else {
                message("Attempt ", error_retry_count, " to log error artifact failed. Retrying in 5 seconds...")
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
}
# Close progress bar
close(pb)

