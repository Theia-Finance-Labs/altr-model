library(readxl)

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

assets_data <- readxl::read_excel(file.path("..", "..", "data", "08_reporting", "assets_data.xslx"))
scenarios_data <- readxl::read_excel(file.path("..", "..", "data", "08_reporting", "scenarios_data.xlsx"))
financial_data <- readxl::read_excel(file.path("..", "..", "data", "08_reporting", "financial_data.xlsx"))
carbon_data <- readr::read_csv(file.path("inst", "testdata", "ngfs_carbon_price_testdata.csv"))

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

