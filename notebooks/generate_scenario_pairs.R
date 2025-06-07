library(dplyr)
library(yaml)
library(readr)

FORCED_BASELINE <- "AR6_WITCH 5.0_EN_NoPolicy" # or null

# Get the script's directory and normalize paths
script_dir <- normalizePath(dirname(sys.frame(1)$ofile), mustWork = FALSE)
if (script_dir == ".") {
  # If running interactively or from RStudio, get the current working directory
  script_dir <- getwd()
}

# Define data paths relative to the script directory
data_dir <- file.path(dirname(script_dir), "data", "08_reporting")
data_dir <- normalizePath(data_dir, mustWork = FALSE)

if (!dir.exists(data_dir)) {
  stop("Data directory does not exist: ", data_dir, "\nPlease ensure you have run 'kedro run --tags=legacy' first.")
}

# Read scenario data
scenarios_data <- readr::read_csv(file.path(data_dir, "scenarios_data.csv"))

# Function to generate baseline-target pairs
generate_baseline_target_pairs <- function(scenarios_data, forced_baseline = NULL) {
  if (!is.null(forced_baseline)) {
    # Verify that the forced baseline exists
    if (!forced_baseline %in% scenarios_data$scenario) {
      stop("Forced baseline scenario '", forced_baseline, "' not found in the data")
    }
    
    # Get all target scenarios regardless of provider
    target_scenarios <- scenarios_data %>%
      filter(scenario_type == "target") %>%
      pull(scenario) %>%
      unique()
    
    # Create a single pair with the forced baseline
    return(list(list(
      baseline = forced_baseline,
      targets = target_scenarios
    )))
  } else {
    # Original logic for provider-based pairs
    # Analyze scenario providers and their types
    provider_analysis <- scenarios_data %>%
      group_by(scenario_provider) %>%
      summarise(
        n_scenarios = n_distinct(scenario),
        n_baseline = n_distinct(scenario[scenario_type == "baseline"]),
        n_target = n_distinct(scenario[scenario_type == "target"]),
        n_sectors = n_distinct(sector),
        n_geographies = n_distinct(scenario_geography)
      ) %>%
      arrange(desc(n_scenarios))
    
    # Print provider analysis
    cat("Scenario Provider Analysis:\n")
    print(provider_analysis)
    
    # Filter providers that have both baseline and target scenarios
    valid_providers <- provider_analysis %>%
      filter(n_baseline > 0, n_target > 0) %>%
      filter(scenario_provider %in% c(
        "NGFS2024_GCAM", 
        "NGFS2024_MESSAGE",
        "NGFS2024_REMIND",
        "WEO2023",
        "AR6_WITCH 5.0",
        "AR6_IMAGE 3.2",
        "AR6_COFFEE 1.1",
        "mission_possible"
      ))  %>%
      pull(scenario_provider) 
    
    cat("\nValid providers (with both baseline and target scenarios):\n")
    print(valid_providers)
    
    # Generate pairs for each provider
    BASELINE_TARGET_PAIR <- list()
    for (provider in valid_providers) {
      # Filter scenarios for the given provider
      provider_scenarios <- scenarios_data %>%
        filter(scenario_provider == !!provider)
      
      # Get baseline scenarios
      baseline_scenarios <- provider_scenarios %>%
        filter(scenario_type == "baseline") %>%
        pull(scenario) %>%
        unique()
      
      # Get target scenarios
      target_scenarios <- provider_scenarios %>%
        filter(scenario_type == "target") %>%
        pull(scenario) %>%
        unique()
      
      # Skip if no baseline or target scenarios
      if (length(baseline_scenarios) == 0 || length(target_scenarios) == 0) {
        next
      }
      
      # Generate pairs for each baseline scenario
      for (baseline in baseline_scenarios) {
        BASELINE_TARGET_PAIR[[length(BASELINE_TARGET_PAIR) + 1]] <- list(
          baseline = baseline,
          targets = target_scenarios
        )
      }
    }
    
    return(BASELINE_TARGET_PAIR)
  }
}

# Generate baseline-target pairs
# To force a specific baseline scenario, uncomment and modify the following line:
# BASELINE_TARGET_PAIR <- generate_baseline_target_pairs(scenarios_data, forced_baseline = "your_baseline_scenario")
BASELINE_TARGET_PAIR <- generate_baseline_target_pairs(scenarios_data, forced_baseline=FORCED_BASELINE)

# Create output directory for YAML file
output_dir <- file.path(dirname(script_dir), "workspace", "trisk_R")
if (!dir.exists(output_dir)) {
  dir.create(output_dir, recursive = TRUE)
}

# Save baseline-target pairs to YAML
yaml_path <- file.path(output_dir, "baseline_target_pairs.yaml")
yaml::write_yaml(BASELINE_TARGET_PAIR, yaml_path)
message("Saved baseline-target pairs to: ", yaml_path)

# Print summary of generated pairs
cat("\nGenerated baseline-target pairs:\n")
for (pair in BASELINE_TARGET_PAIR) {
  cat(sprintf("\nBaseline: %s\n", pair$baseline))
  cat(sprintf("Number of target scenarios: %d\n", length(pair$targets)))
  cat("Target scenarios:\n")
  print(pair$targets)
}


