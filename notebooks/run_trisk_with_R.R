# run kedro run --tags=legacy to get the data
library(readxl)
library(dplyr)

# Check current working directory
current_dir <- getwd()
target_dir <- file.path("pkg", "trisk.model")

# Normalize for comparison
normalized_current <- normalizePath(current_dir, winslash = "/", mustWork = FALSE)
normalized_target <- normalizePath(target_dir, winslash = "/", mustWork = FALSE)

# If not already in pkg/trisk.model, set it
if (!grepl(paste0("/?", target_dir, "$"), normalized_current)) {
    setwd(target_dir)
    message("Working directory set to: ", getwd())
  }


assets_data <- readr::read_csv(file.path("..", "..", "data", "08_reporting", "assets_data.csv")) %>% 
  rename(
    production_year=year,
    plant_age_years=asset_age
  )
scenarios_data <- readr::read_csv(file.path("..", "..", "data", "08_reporting", "scenarios_data.csv"))
financial_data <- readr::read_csv(file.path("..", "..", "data", "08_reporting", "financial_data.csv"))
carbon_data <- readr::read_csv(file.path("inst", "testdata", "ngfs_carbon_price_testdata.csv"))

SHOCK_YEAR = 2030

SCENARIO_PROVIDER <- 'AR6_REMIND-MAgPIE 2.1-4.2'

available_baseline_scenarios <- scenarios_data %>% filter(scenario_type=="baseline", SCENARIO_PROVIDER==SCENARIO_PROVIDER) %>% distinct(scenario)
print(available_baseline_scenarios, n=1000)
available_target_scenarios <- scenarios_data %>% filter(scenario_type=="target", SCENARIO_PROVIDER==SCENARIO_PROVIDER) %>% distinct(scenario)
print(available_target_scenarios, n=1000)


BASELINE_SCENARIO <- "AR6_REMIND-MAgPIE 2.1-4.2_NGFS2_Current Policies - IPD-95th"


available_scenario_geographies <- scenarios_data %>% 
  filter(scenario %in% c(BASELINE_SCENARIO)) %>%
  distinct(scenario_geography)
print(available_scenario_geographies)



# Set up progress bar
total_scenarios <- nrow(available_target_scenarios)
total_geographies <- nrow(available_scenario_geographies)
total_iterations <- total_scenarios * total_geographies
pb <- txtProgressBar(min = 0, max = total_iterations, style = 3)
current_iteration <- 0

# Create base output directory if it doesn't exist
base_output_dir <- file.path("..", "..", "data", "08_reporting", "trisk_results", SCENARIO_PROVIDER)
if (!dir.exists(base_output_dir)) {
  dir.create(base_output_dir, recursive = TRUE)
}

devtools::load_all()
for (target_scenario in unique(available_target_scenarios$scenario)) {  
  for (scenario_geography in unique(available_scenario_geographies$scenario_geography)) {
    # Update progress bar
    current_iteration <- current_iteration + 1
    setTxtProgressBar(pb, current_iteration)
    
    # Sanitize target scenario name for use in filenames
    safe_target_scenario <- gsub("[\\/:*?\"<>|]", "_", target_scenario)
    base_filename <- paste0("npvs_", scenario_geography, "_", safe_target_scenario)
    output_csv <- file.path(base_output_dir, paste0(base_filename, ".csv"))
    output_txt <- file.path(base_output_dir, paste0(base_filename, ".txt"))
    
    # Try to run the model, catch any errors
    tryCatch({
      st_results <- run_trisk_model(
        assets_data = assets_data,
        scenarios_data = scenarios_data,
        financial_data = financial_data,
        carbon_data = carbon_data,
        baseline_scenario = BASELINE_SCENARIO,
        target_scenario = target_scenario,
        scenario_geography = scenario_geography,
        shock_year = SHOCK_YEAR
      )

      npv_results <- st_results$npv_results
      pd_results <- st_results$pd_results
      company_trajectories <- st_results$company_trajectories
      
      # Save individual NPV results file
      readr::write_csv(npv_results, output_csv)
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
      message("ERROR for ", scenario_geography, " - ", target_scenario, ". Error saved to: ", output_txt)
    })
  }
}

# Close progress bar
close(pb)

