library(readr)
library(dplyr)

# Function to gather shock and trajectory data from results directories
gather_shock_and_trajectories <- function(results_dir) {
  # Get all subdirectories in the results directory
  subdirs <- list.dirs(results_dir, recursive = FALSE)

  # Initialize lists to store dataframes
  asset_shock_list <- list()
  yearly_trajectories_list <- list()

  # Process each subdirectory
  for (subdir in subdirs) {
    # Extract run name from directory path
    run_name <- basename(subdir)

    cat("Processing:", run_name, "\n")

    # Define file paths for the main files
    asset_shock_file <- file.path(subdir, "asset_level_staggered_shock.csv")
    yearly_trajectories_file <- file.path(subdir, "yearly_npv_trajectories.csv")

    # Define run_params file path
    run_params_file <- file.path(subdir, "run_params.csv")

    # Check if run_params exists (required for joining)
    if (!file.exists(run_params_file)) {
      cat("Warning: run_params.csv not found in", run_name, "\n")
      next
    }

    # Load run_params.csv
    tryCatch({
      run_params <- read_csv(run_params_file, show_col_types = FALSE)
    }, error = function(e) {
      cat("Error reading run_params.csv in", run_name, ":", e$message, "\n")
      next
    })

    # Load and process asset_level_staggered_shock.csv
    if (file.exists(asset_shock_file)) {
      tryCatch({
        asset_shock <- read_csv(asset_shock_file, show_col_types = FALSE) %>%
          mutate(run_name = run_name) %>%
          left_join(run_params, by = "run_id")
        asset_shock_list[[run_name]] <- asset_shock
      }, error = function(e) {
        cat("Error reading asset_level_staggered_shock.csv in", run_name, ":", e$message, "\n")
      })
    } else {
      cat("Warning: asset_level_staggered_shock.csv not found in", run_name, "\n")
    }

    # Load and process yearly_npv_trajectories.csv
    if (file.exists(yearly_trajectories_file)) {
      tryCatch({
        yearly_trajectories <- read_csv(yearly_trajectories_file, show_col_types = FALSE) %>%
          mutate(run_name = run_name) %>%
          left_join(run_params, by = "run_id")
        yearly_trajectories_list[[run_name]] <- yearly_trajectories
      }, error = function(e) {
        cat("Error reading yearly_npv_trajectories.csv in", run_name, ":", e$message, "\n")
      })
    } else {
      cat("Warning: yearly_npv_trajectories.csv not found in", run_name, "\n")
    }
  }

  # Combine all dataframes into single dataframes
  asset_shock_combined <- bind_rows(asset_shock_list)
  yearly_trajectories_combined <- bind_rows(yearly_trajectories_list)

  # Calculate number of runs more safely
  run_names <- c()
  if (nrow(asset_shock_combined) > 0) {
    run_names <- c(run_names, unique(asset_shock_combined$run_name))
  }
  if (nrow(yearly_trajectories_combined) > 0) {
    run_names <- c(run_names, unique(yearly_trajectories_combined$run_name))
  }
  unique_runs <- unique(run_names)

  # Return results as a list
  results <- list(
    asset_shock = asset_shock_combined,
    yearly_trajectories = yearly_trajectories_combined,
    summary = list(
      asset_shock_rows = nrow(asset_shock_combined),
      trajectories_rows = nrow(yearly_trajectories_combined),
      num_runs = length(unique_runs)
    )
  )

  return(results)
}

# Example usage:
# Set the results directory (you can change this)
results_dir <- "workspace/results_v4"

# Gather the data
results_data <- gather_shock_and_trajectories(results_dir)

# Display summary
cat("\nSummary for", results_dir, ":\n")
cat("Asset Shock Data: ", results_data$summary$asset_shock_rows, " rows\n")
cat("Yearly Trajectories Data: ", results_data$summary$trajectories_rows, " rows\n")
cat("Number of runs processed: ", results_data$summary$num_runs, "\n")

# Display first few rows of each combined dataframe
if (nrow(results_data$asset_shock) > 0) {
  cat("\nFirst few rows of asset_level_staggered_shock_combined:\n")
  print(head(results_data$asset_shock))
} else {
  cat("\nNo asset shock data found.\n")
}

if (nrow(results_data$yearly_trajectories) > 0) {
  cat("\nFirst few rows of yearly_npv_trajectories_combined:\n")
  print(head(results_data$yearly_trajectories))
} else {
  cat("\nNo yearly trajectories data found.\n")
}

# You can access the combined dataframes like this:
# asset_shock_combined <- results_data$asset_shock
# yearly_trajectories_combined <- results_data$yearly_trajectories






if (results_dir == "workspace/results_v3") {
  results_data$asset_shock %>% 
  filter(stringr::str_detect(run_name, "company_granularity|asset_granularity_with_staggered_shock_and_retirement_scenario")) %>%
  inner_join(results_data$asset_shock %>% distinct(asset_id, technology) %>% sample_n(1000), by = c("asset_id", "technology")) %>%
  readr::write_csv("workspace/traj_results/WITCH___asset_production_trajectories.csv")
}if (results_dir == "workspace/results_v4") {
  assets_selection <- readr::read_csv("workspace/traj_results/WITCH___asset_production_trajectories.csv") %>% distinct(asset_id, technology)
  results_data$asset_shock %>% 
    inner_join(assets_selection, by = c("asset_id", "technology")) %>%
    readr::write_csv("workspace/traj_results/COFFEE___asset_production_trajectories.csv")

  results_data$yearly_trajectories %>% 
    inner_join(assets_selection, by = c("asset_id", "technology")) %>%
    readr::write_csv("workspace/traj_results/COFFEE___financial_yearly_trajectories.csv")    
}
