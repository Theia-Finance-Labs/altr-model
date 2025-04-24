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

devtools::load_all()

assets_data <- readxl::read_excel(file.path("..", "..", "data", "08_reporting", "assets_data.xlsx"))
scenarios_data <- readr::read_csv(file.path("..", "..", "data", "08_reporting", "scenarios_data.csv"))
financial_data <- readxl::read_excel(file.path("..", "..", "data", "08_reporting", "financial_data.xlsx"))
carbon_data <- readr::read_csv(file.path("inst", "testdata", "ngfs_carbon_price_testdata.csv"))


available_baseline_scenarios <- scenarios_data %>% filter(scenario_type=="baseline") %>% distinct(scenario)
print(available_baseline_scenarios, n=1000)
available_target_scenarios <- scenarios_data %>% filter(scenario_type=="target") %>% distinct(scenario)
print(available_target_scenarios, n=1000)

baseline_scenario <- "KAPSARC_GCAM 5.3_NGFS2_Current Policies"
target_scenario <- "KAPSARC_GCAM 5.3_NGFS2_Below 2°C"

available_scenario_geographies <- scenarios_data %>% 
  filter(scenario %in% c(baseline_scenario, target_scenario)) %>%
  distinct(scenario_geography)
print(available_scenario_geographies)

scenario_geography = "R10AFRICA"

st_results <- run_trisk_model(
  assets_data = assets_data,
  scenarios_data = scenarios_data,
  financial_data = financial_data,
  carbon_data = carbon_data,
  baseline_scenario = baseline_scenario,
  target_scenario = target_scenario,
  scenario_geography = scenario_geography
)

npv_results <- st_results$npv_results
pd_results <- st_results$pd_results
company_trajectories <- st_results$company_trajectories

