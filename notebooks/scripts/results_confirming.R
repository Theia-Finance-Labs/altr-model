library(dplyr)
library(readr)

# Load datasets
asset_granularity <- readr::read_csv("workspace/results_V19/AIM-CGE 2.2__asset_granularity_with_staggered_shock_and_retirement/company_technology_npv.csv")
company_granularity <- readr::read_csv("workspace/results_V19/AIM-CGE 2.2__company_granularity_with_continued_omcost/company_technology_npv.csv")

# company_granularity <- readr::read_csv("workspace/results_V18/AIM-CGE 2.2__company_granularity/company_technology_npv.csv")
# asset_granularity <- readr::read_csv("workspace/results_V18/AIM-CGE 2.2__asset_granularity_with_staggered_shock_and_retirement/company_technology_npv.csv")


# Merge on company_id, technology, and scenario_geography
merged_data <- asset_granularity %>%
  select(company_id, technology, scenario_geography, npv_change) %>%
  rename(npv_change_asset = npv_change) %>%
  inner_join(
    company_granularity %>%
      select(company_id, technology, scenario_geography, npv_change) %>%
      rename(npv_change_company = npv_change),
    by = c("company_id", "technology", "scenario_geography")
  )

# Display side by side comparison
cat("NPV Change Comparison:\n")
cat("======================\n\n")
cat("Number of matched records:", nrow(merged_data), "\n\n")

# Display the merged dataset with npv_change values side by side
# print(merged_data)


merged_data %>% mutate(npv_change_diff = npv_change_company - npv_change_asset) %>% filter(npv_change_diff != 0, npv_change_asset<0) %>% print(n=100)
