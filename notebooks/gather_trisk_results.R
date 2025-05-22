library(tidyverse)

#' Gather TRISK NPV results from downloaded artifacts.
#'
#' @param artifacts_dir Character. Directory containing the downloaded artifacts
#' @return Data frame. Combined NPVs data frame
gather_trisk_results <- function(artifacts_dir) {
  # Get all NPV files
  npv_files <- list.files(
    path = artifacts_dir,
    pattern = "npvs_.*\\.csv$",
    full.names = TRUE
  )
  
  # Initialize empty list for results
  all_npvs_list <- list()
  
  # Process NPV files
  for (file in npv_files) {
    run_id <- gsub("npvs_|\\.csv$", "", basename(file))
    df <- read.csv(file)
    df$run_id <- run_id
    all_npvs_list[[length(all_npvs_list) + 1]] <- df
  }
  
  # Combine all data frames
  all_npvs <- bind_rows(all_npvs_list)
  return(all_npvs)
}

#' Split the data frame into three groups based on CCS status.
#'
#' @param df Data frame. Input data frame with technology column
#' @param ccs_technologies Character vector. List of technologies that can have CCS.
#'   Defaults to c('GasCap', 'CoalCap', 'OilCap')
#' @return List. List containing three filtered data frames:
#'   - 'with_ccs': Technologies with CCS + other technologies
#'   - 'without_ccs': Technologies without CCS + other technologies
#'   - 'other': All technologies except CCS-capable ones
split_by_ccs_status <- function(df, ccs_technologies = c("GasCap", "CoalCap", "OilCap")) {
  # Get unique run IDs for each CCS variant
  with_ccs_runs <- unique(df[grepl("w/ CCS", df$technology), "run_id"])
  without_ccs_runs <- unique(df[grepl("w/o CCS", df$technology), "run_id"])
  
  # Split technologies by CCS status using run IDs
  with_ccs <- df[df$run_id %in% with_ccs_runs, ]
  without_ccs <- df[df$run_id %in% without_ccs_runs, ]
  
  # For other technologies, we need to ensure we don't duplicate them
  # We'll take them from the run that has the most complete data
  other_runs <- setdiff(unique(df$run_id), union(with_ccs_runs, without_ccs_runs))
  if (length(other_runs) > 0) {
    other_techs <- df[df$run_id %in% other_runs, ]
  }
  
  return(list(
    with_ccs = with_ccs,
    without_ccs = without_ccs,
    other = other_techs
  ))
}

#' Save TRISK NPV results to CSV file.
#'
#' @param df Data frame. Data frame to save
#' @param output_dir Character. Directory to save the results
#' @param filename Character. Name of the output file
save_trisk_results <- function(df, output_dir, filename) {
  # Create output directory if it doesn't exist
  dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)
  
  # Save results
  output_path <- file.path(output_dir, filename)
  cat(sprintf("\nSaving %s to: %s\n", filename, output_path))
  write.csv(df, output_path, row.names = FALSE)
  cat(sprintf("Total rows: %d\n", nrow(df)))
}

# Main execution
if (interactive()) {
  # Assuming the artifacts are in workspace/mlflow_results/artifacts
  artifacts_dir <- "workspace/mlflow_results/artifacts"
  # Save one level up from artifacts directory
  output_dir <- "workspace/mlflow_results"
  
  # Define CCS technologies
  ccs_technologies <- c("GasCap", "CoalCap", "OilCap")
  
  # Gather the results
  npvs_df <- gather_trisk_results(artifacts_dir)
  
  # Split the results by CCS status
  ccs_split <- split_by_ccs_status(npvs_df, ccs_technologies)
  
  # Save each split
  for (ccs_type in names(ccs_split)) {
    save_trisk_results(
      ccs_split[[ccs_type]],
      output_dir,
      sprintf("npvs_%s.csv", ccs_type)
    )
  }
} 