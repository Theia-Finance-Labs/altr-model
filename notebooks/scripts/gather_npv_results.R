library(readr)
library(dplyr)


# Set the results directory
results_dir <- "workspace/results_v5"


# Get all subdirectories in the results directory
subdirs <- list.dirs(results_dir, recursive = FALSE)


# Initialize lists to store dataframes
asset_npv_list <- list()
company_npv_list <- list()
company_technology_npv_list <- list()


# Process each subdirectory
for (subdir in subdirs) {
  # Extract run name from directory path
  run_name <- basename(subdir)
  
  cat("Processing:", run_name, "\n")
  
  # Define file paths
  asset_npv_file <- file.path(subdir, "asset_npv.csv")
  company_npv_file <- file.path(subdir, "company_npv.csv")
  company_technology_npv_file <- file.path(subdir, "company_technology_npv.csv")
  run_params_file <- file.path(subdir, "run_params.csv")
  
  # Check if all required files exist
  if (all(file.exists(asset_npv_file, company_npv_file, company_technology_npv_file, run_params_file))) {
    
    # Load run_params.csv
    run_params <- read_csv(run_params_file)
    
    # Load and process asset_npv.csv
    if (file.exists(asset_npv_file)) {
      asset_npv <- read_csv(asset_npv_file) %>%
        mutate(run_name = run_name) %>%
        left_join(run_params, by = "run_id")
      asset_npv_list[[run_name]] <- asset_npv
    }
    
    # Load and process company_npv.csv
    if (file.exists(company_npv_file)) {
      company_npv <- read_csv(company_npv_file) %>%
        mutate(run_name = run_name) %>%
        left_join(run_params, by = "run_id")
      company_npv_list[[run_name]] <- company_npv
    }
    
    # Load and process company_technology_npv.csv
    if (file.exists(company_technology_npv_file)) {
      company_technology_npv <- read_csv(company_technology_npv_file) %>%
        mutate(run_name = run_name) %>%
        left_join(run_params, by = "run_id")
      company_technology_npv_list[[run_name]] <- company_technology_npv
    }
    
  } else {
    cat("Warning: Some files missing in", run_name, "\n")
  }
}


# Combine all dataframes into single dataframes
asset_npv_combined <- bind_rows(asset_npv_list)
company_npv_combined <- bind_rows(company_npv_list)
company_technology_npv_combined <- bind_rows(company_technology_npv_list)


# Display summary
cat("\nSummary:\n")
cat("Asset NPV: ", nrow(asset_npv_combined), " rows\n")
cat("Company NPV: ", nrow(company_npv_combined), " rows\n")
cat("Company Technology NPV: ", nrow(company_technology_npv_combined), " rows\n")
cat("Number of runs: ", length(unique(asset_npv_combined$run_name)), "\n")


# Display first few rows of each combined dataframe
cat("\nFirst few rows of asset_npv_combined:\n")
print(head(asset_npv_combined))


cat("\nFirst few rows of company_npv_combined:\n")
print(head(company_npv_combined))


cat("\nFirst few rows of company_technology_npv_combined:\n")
print(head(company_technology_npv_combined))


companies_selection <- readr::read_csv("workspace/traj_results/WITCH___asset_production_trajectories.csv") %>% distinct(company_id, technology)

asset_npv_combined %>% 
  filter(stringr::str_detect(run_name, "company_granularity|asset_granularity_with_staggered_shock_and_retirement_scenario")) %>% 
  inner_join(companies_selection, by = c("company_id", "technology")) %>%
  readr::write_csv(file.path(results_dir, "asset_npv_combined.csv"))

company_selection <- asset_npv_combined %>%   
  inner_join(companies_selection, by = c("company_id", "technology")) %>% distinct(company_id)
company_npv_combined %>% 
  filter(stringr::str_detect(run_name, "company_granularity|asset_granularity_with_staggered_shock_and_retirement_scenario")) %>%
  inner_join(company_selection, by = c("company_id")) %>%
  readr::write_csv(file.path(results_dir, "company_npv_combined.csv"))
company_technology_npv_combined %>% 
  filter(stringr::str_detect(run_name, "company_granularity|asset_granularity_with_staggered_shock_and_retirement_scenario")) %>%
  inner_join(company_selection, by = c("company_id")) %>%
  readr::write_csv(file.path(results_dir, "company_technology_npv_combined.csv"))

