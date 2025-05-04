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
  base_output_dir <- file.path("..", "..", "data", "08_reporting", "trisk_results", scenario_provider)
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
  }
# Close progress bar
close(pb)

