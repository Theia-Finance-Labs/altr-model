# run kedro run --tags=legacy to get the data
library(readxl)
library(dplyr)
library(yaml)

# Define CCS status
CCS_STATUS <- "both"  # "w/ CCS" or "w/o CCS" or "both"

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

# Create output directory
output_dir <- file.path(dirname(script_dir), "data", "reporting", "trisk_r_results")
if (!dir.exists(output_dir)) {
  dir.create(output_dir, recursive = TRUE)
}

# Load baseline-target pairs from YAML
baseline_target_pairs_path <- file.path(dirname(script_dir), "workspace", "trisk_R", "baseline_target_pairs.yaml")
if (!file.exists(baseline_target_pairs_path)) {
  stop("Baseline-target pairs YAML file not found at: ", baseline_target_pairs_path, 
       "\nPlease run generate_scenario_pairs.R first to generate this file.")
}
BASELINE_TARGET_PAIR <- yaml::read_yaml(baseline_target_pairs_path)

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

# Load the trisk.model package from the correct location
trisk_model_path <- file.path(dirname(dirname(dirname(script_dir))), "packages", "crispy-kedro", "pkg", "trisk.model")
if (!dir.exists(trisk_model_path)) {
  stop("Could not find trisk.model package at: ", trisk_model_path)
}
devtools::load_all(trisk_model_path)

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

  # Create experiment output directory
  experiment_dir <- file.path(output_dir, gsub("[\\/:*?\"<>|]", "_", baseline_scenario))
  if (!dir.exists(experiment_dir)) {
    dir.create(experiment_dir, recursive = TRUE)
  }

  for (target_scenario in unique(target_scenarios)) {  
    for (scenario_geography in unique(available_scenario_geographies$scenario_geography)) {
      # Update progress bar
      current_iteration <- current_iteration + 1
      setTxtProgressBar(pb, current_iteration)
      
      # Sanitize target scenario name for use in filenames
      safe_target_scenario <- gsub("[\\/:*?\"<>|]", "_", target_scenario)
      base_filename <- paste0("npvs_", scenario_geography, "_", safe_target_scenario)
      output_csv <- file.path(experiment_dir, paste0(base_filename, ".csv"))
      output_txt <- file.path(experiment_dir, paste0(base_filename, ".txt"))
      
      params_overwrite <- list(
        baseline_scenario = baseline_scenario,
        target_scenario = target_scenario,
        scenario_geography = scenario_geography,
        shock_year = SHOCK_YEAR
      )
      trisk_params <- do.call(trisk.model::process_params, c(list(fun = trisk.model::run_trisk_model), params_overwrite))

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
        
        # Save results
        readr::write_csv(npv_results, output_csv)
        message("NPV results for ", scenario_geography, " - ", target_scenario, " saved to: ", output_csv)
      },
      error = function(e) {
        # Save error message to text file
        error_message <- paste0(
          "Error running trisk model for:\n",
          "Scenario geography: ", scenario_geography, "\n",
          "Target scenario: ", target_scenario, "\n",
          "CCS status: ", CCS_STATUS, "\n",
          "Error message: ", e$message, "\n",
          "Timestamp: ", format(Sys.time(), "%Y-%m-%d %H:%M:%S")
        )
        writeLines(error_message, output_txt)
        message("ERROR for ", scenario_geography, " - ", target_scenario, ". Error saved to: ", output_txt)
      })
    }
  }
  # Close progress bar
  close(pb)
}

