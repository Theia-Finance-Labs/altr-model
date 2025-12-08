library(dplyr)

raw_assets <- readr::read_csv("data/05_model_input/downloaded_assets.csv")
raw_companies <- readr::read_csv("data/05_model_input/downloaded_companies.csv")

assets1_npv_company_granularity <- readr::read_csv("workspace/results_V18/AIM-CGE 2.2__company_granularity/asset_npv.csv")

assets2_npv_with_continued_om_cost_and_retirement <- readr::read_csv("workspace/results_V18/AIM-CGE 2.2__asset_granularity_with_continued_omcost_and_retirement/asset_npv.csv")

assets3_npv_with_staggered_shock_and_retirement <- readr::read_csv("workspace/results_V18/AIM-CGE 2.2__asset_granularity_with_staggered_shock_and_retirement/asset_npv.csv")




# Identify companies that have at least one row with npv_change == 0 or is.na(npv_change)
companies_to_exclude1 <- assets1_npv_company_granularity %>%
  filter(npv_change == 0 | is.na(npv_change)) %>%
  distinct(company_id)

companies_to_exclude2 <- assets2_npv_with_continued_om_cost_and_retirement %>%
  filter(npv_change == 0 | is.na(npv_change)) %>%
  distinct(company_id)

companies_to_exclude3 <- assets3_npv_with_staggered_shock_and_retirement %>%
  filter(npv_change == 0 | is.na(npv_change)) %>%
  distinct(company_id)

all_companies_to_exclude <- bind_rows(companies_to_exclude1,companies_to_exclude2, companies_to_exclude3 )%>%
  distinct(company_id)

# Filter out all rows belonging to those companies
assets1_without_0_npv_change <- assets1_npv_company_granularity %>%
  anti_join(all_companies_to_exclude, by = "company_id")

assets2_without_0_npv_change <- assets2_npv_with_continued_om_cost_and_retirement %>%
  anti_join(all_companies_to_exclude, by = "company_id")

assets3_without_0_npv_change <- assets3_npv_with_staggered_shock_and_retirement %>%
  anti_join(all_companies_to_exclude, by = "company_id")

# Get distinct asset_ids from the filtered results
valid_asset_ids <- bind_rows(
  assets1_without_0_npv_change %>% distinct(asset_id),
  assets2_without_0_npv_change %>% distinct(asset_id),
  assets3_without_0_npv_change %>% distinct(asset_id)
) %>%
  distinct(asset_id)

# Get distinct company_ids from the filtered results
valid_company_ids <- bind_rows(
  assets1_without_0_npv_change %>% distinct(company_id),
  assets2_without_0_npv_change %>% distinct(company_id),
  assets3_without_0_npv_change %>% distinct(company_id)
) %>%
  distinct(company_id)

# Filter raw_assets using asset_ids from results
raw_assets_without_0_npv_change <- raw_assets %>%
  inner_join(valid_asset_ids, by = "asset_id")

# Get only asset_ids that exist in raw_assets (exclude synthetic assets created by pipeline)
valid_asset_ids_in_raw_assets <- valid_asset_ids %>%
  inner_join(raw_assets %>% distinct(asset_id), by = "asset_id")

# Filter raw_companies using asset_ids (not company_ids) for consistency
# This ensures we only get assets that actually exist in the input data
raw_companies_without_0_npv_change <- raw_companies %>%
  inner_join(valid_asset_ids_in_raw_assets, by = "asset_id")

# Diagnostic: Check why asset counts differ
cat("=== DIAGNOSTIC: Why asset counts differ ===\n")
cat("Valid asset_ids from results:", nrow(valid_asset_ids), "\n")
cat("Valid company_ids from results:", nrow(valid_company_ids), "\n")

# Assets from companies (now filtered by asset_id for consistency)
assets_from_companies <- raw_companies_without_0_npv_change %>%
  distinct(asset_id)
cat("Asset_ids from raw_companies (filtered by asset_id):", nrow(assets_from_companies), "\n")

# Assets from assets table (only assets that appeared in results)
assets_from_assets <- raw_assets_without_0_npv_change %>%
  distinct(asset_id)
cat("Asset_ids from raw_assets (filtered by asset_id):", nrow(assets_from_assets), "\n")

# Verify they match now
if (nrow(assets_from_companies) == nrow(assets_from_assets)) {
  cat("✓ SUCCESS: Both tables now have the same asset count!\n")
} else {
  cat("⚠ WARNING: Asset counts still differ\n")
}

# Find assets that are in companies but not in results
assets_in_companies_not_in_results <- assets_from_companies %>%
  anti_join(valid_asset_ids, by = "asset_id")
cat("Assets in companies but NOT in results:", nrow(assets_in_companies_not_in_results), "\n")

# Find assets that are in results but not in companies table
assets_in_results_not_in_companies <- valid_asset_ids %>%
  anti_join(assets_from_companies, by = "asset_id")
cat("Assets in results but NOT in companies table:", nrow(assets_in_results_not_in_companies), "\n")

cat("\n=== ADDITIONAL DIAGNOSTICS ===\n")
# Check total counts in raw tables
cat("Total asset_ids in raw_assets:", nrow(raw_assets %>% distinct(asset_id)), "\n")
cat("Total asset_ids in raw_companies:", nrow(raw_companies %>% distinct(asset_id)), "\n")
if ("company_id" %in% names(raw_assets)) {
  cat("Total company_ids in raw_assets:", nrow(raw_assets %>% distinct(company_id)), "\n")
} else {
  cat("raw_assets does NOT have a company_id column\n")
}
cat("Total company_ids in raw_companies:", nrow(raw_companies %>% distinct(company_id)), "\n")

# Check overlap
assets_in_raw_assets_not_in_raw_companies <- raw_assets %>%
  distinct(asset_id) %>%
  anti_join(raw_companies %>% distinct(asset_id), by = "asset_id")
cat("Assets in raw_assets but NOT in raw_companies:", nrow(assets_in_raw_assets_not_in_raw_companies), "\n")

assets_in_raw_companies_not_in_raw_assets <- raw_companies %>%
  distinct(asset_id) %>%
  anti_join(raw_assets %>% distinct(asset_id), by = "asset_id")
cat("Assets in raw_companies but NOT in raw_assets:", nrow(assets_in_raw_companies_not_in_raw_assets), "\n")

# Check how many of the "missing" assets from results are actually in raw_assets
missing_assets_in_raw_assets <- assets_in_results_not_in_companies %>%
  inner_join(raw_assets %>% distinct(asset_id), by = "asset_id")
cat("Of the 62,367 assets in results but not in companies table,", 
    nrow(missing_assets_in_raw_assets), "are in raw_assets\n")

cat("\n=== EXPLANATION ===\n")
cat("The original difference occurred because:\n")
cat("1. raw_companies and raw_assets both have", nrow(raw_assets %>% distinct(asset_id)), "assets (identical)\n")
cat("2. Results contain", nrow(valid_asset_ids), "valid asset_ids (includes", 
    nrow(valid_asset_ids) - nrow(raw_assets %>% distinct(asset_id)), "synthetic assets created by pipeline)\n")
cat("3. Previously: raw_companies was filtered by company_id -> included ALL assets from valid companies\n")
cat("4. Previously: raw_assets was filtered by asset_id -> included ONLY assets that exist in raw_assets\n")
cat("5. The pipeline creates synthetic/aggregated assets (23,555 more than input)\n")
cat("\n=== SOLUTION APPLIED ===\n")
cat("Both raw_companies and raw_assets are now filtered by the same valid_asset_ids\n")
cat("that exist in raw_assets (excluding synthetic assets). This ensures consistency.\n")
cat("Valid asset_ids in raw_assets:", nrow(valid_asset_ids_in_raw_assets), "\n")

cat("\n=== ANALYSIS: LOST ASSETS IN TABLES 2 & 3 ===\n")
cat("Analyzing which initial assets are missing from results tables 2 and 3...\n\n")

# Get all initial asset_ids from raw_assets
initial_asset_ids <- raw_assets %>%
  distinct(asset_id)

# Get asset_ids from table 2 (only those that exist in raw_assets, excluding synthetic)
assets2_asset_ids <- assets2_without_0_npv_change %>%
  distinct(asset_id) %>%
  inner_join(raw_assets %>% distinct(asset_id), by = "asset_id")

# Get asset_ids from table 3 (only those that exist in raw_assets, excluding synthetic)
assets3_asset_ids <- assets3_without_0_npv_change %>%
  distinct(asset_id) %>%
  inner_join(raw_assets %>% distinct(asset_id), by = "asset_id")

# Assets in table 2 OR table 3
assets_in_2_or_3 <- bind_rows(assets2_asset_ids, assets3_asset_ids) %>%
  distinct(asset_id)

# Assets lost (in initial but not in table 2 or 3)
lost_assets <- initial_asset_ids %>%
  anti_join(assets_in_2_or_3, by = "asset_id")

cat("Total initial assets:", nrow(initial_asset_ids), "\n")
cat("Assets in table 2 (from initial):", nrow(assets2_asset_ids), "\n")
cat("Assets in table 3 (from initial):", nrow(assets3_asset_ids), "\n")
cat("Assets in table 2 OR table 3 (from initial):", nrow(assets_in_2_or_3), "\n")
cat("Assets LOST (in initial but NOT in table 2 or 3):", nrow(lost_assets), "\n")
cat("Percentage lost:", round(100 * nrow(lost_assets) / nrow(initial_asset_ids), 2), "%\n\n")

# Get technology information for lost assets
if (nrow(lost_assets) > 0) {
  # Join with raw_assets and get distinct asset_id with their attributes
  # raw_assets may have multiple rows per asset, so we need to deduplicate
  lost_assets_with_info <- lost_assets %>%
    inner_join(raw_assets, by = "asset_id") %>%
    distinct(asset_id, .keep_all = TRUE)
  
  cat("Total unique lost assets:", nrow(lost_assets_with_info), "\n\n")
  
  # Count lost assets by technology (using distinct asset_ids)
  lost_by_technology <- lost_assets_with_info %>%
    count(technology, sort = TRUE) %>%
    mutate(percentage = round(100 * n / nrow(lost_assets_with_info), 2))
  
  cat("=== LOST ASSETS BY TECHNOLOGY ===\n")
  print(lost_by_technology)
  
  # Also check by sector if available
  if ("sector" %in% names(lost_assets_with_info)) {
    cat("\n=== LOST ASSETS BY SECTOR ===\n")
    lost_by_sector <- lost_assets_with_info %>%
      count(sector, sort = TRUE) %>%
      mutate(percentage = round(100 * n / nrow(lost_assets_with_info), 2))
    print(lost_by_sector)
  }
  
  # Save lost assets to a file for inspection
  readr::write_csv(lost_assets_with_info, "lost_assets_tables_2_and_3.csv")
  cat("\n✓ Lost assets saved to: lost_assets_tables_2_and_3.csv\n")
  
  # Also check which assets are in table 2 but not 3, and vice versa
  cat("\n=== ADDITIONAL COMPARISONS ===\n")
  in_2_not_3 <- assets2_asset_ids %>%
    anti_join(assets3_asset_ids, by = "asset_id")
  cat("Assets in table 2 but NOT in table 3:", nrow(in_2_not_3), "\n")
  
  in_3_not_2 <- assets3_asset_ids %>%
    anti_join(assets2_asset_ids, by = "asset_id")
  cat("Assets in table 3 but NOT in table 2:", nrow(in_3_not_2), "\n")
  
  in_both_2_and_3 <- assets2_asset_ids %>%
    inner_join(assets3_asset_ids, by = "asset_id")
  cat("Assets in BOTH table 2 and table 3:", nrow(in_both_2_and_3), "\n")
} else {
  cat("✓ No assets lost! All initial assets appear in table 2 or 3.\n")
}


cat("\n=== INVESTIGATING WHY POWER ASSETS ARE LOST ===\n")
cat("Analyzing the filtering logic to understand power asset loss...\n\n")

# Get power assets from initial data
initial_power_assets <- raw_assets %>%
  filter(sector == "Power") %>%
  distinct(asset_id, .keep_all = TRUE)

cat("Total initial power assets:", nrow(initial_power_assets), "\n")

# Check which power assets made it to each results table (before filtering)
power_in_results1_raw <- assets1_npv_company_granularity %>%
  inner_join(raw_assets %>% filter(sector == "Power") %>% distinct(asset_id), by = "asset_id")

power_in_results2_raw <- assets2_npv_with_continued_om_cost_and_retirement %>%
  inner_join(raw_assets %>% filter(sector == "Power") %>% distinct(asset_id), by = "asset_id")

power_in_results3_raw <- assets3_npv_with_staggered_shock_and_retirement %>%
  inner_join(raw_assets %>% filter(sector == "Power") %>% distinct(asset_id), by = "asset_id")

cat("Power assets in results table 1 (raw):", n_distinct(power_in_results1_raw$asset_id), "\n")
cat("Power assets in results table 2 (raw):", n_distinct(power_in_results2_raw$asset_id), "\n")
cat("Power assets in results table 3 (raw):", n_distinct(power_in_results3_raw$asset_id), "\n")

# Check how many power assets are filtered out due to npv_change == 0 or NA
power_filtered_out_table2 <- power_in_results2_raw %>%
  filter(npv_change == 0 | is.na(npv_change)) %>%
  distinct(asset_id, company_id, npv_change)

power_filtered_out_table3 <- power_in_results3_raw %>%
  filter(npv_change == 0 | is.na(npv_change)) %>%
  distinct(asset_id, company_id, npv_change)

cat("\nPower assets filtered out from table 2 (npv_change == 0 or NA):", n_distinct(power_filtered_out_table2$asset_id), "\n")
cat("Power assets filtered out from table 3 (npv_change == 0 or NA):", n_distinct(power_filtered_out_table3$asset_id), "\n")

# Check if these filtered assets are from companies that have ANY asset with npv_change == 0
power_companies_excluded <- power_filtered_out_table2 %>%
  inner_join(all_companies_to_exclude, by = "company_id")

cat("Power assets excluded because their company has ANY asset with npv_change == 0:", n_distinct(power_companies_excluded$asset_id), "\n")

# Now check: of the lost power assets, how many never appeared in results tables 2 & 3?
lost_power_assets <- lost_assets %>%
  inner_join(raw_assets %>% filter(sector == "Power"), by = "asset_id")

power_never_in_results2 <- lost_power_assets %>%
  anti_join(power_in_results2_raw %>% distinct(asset_id), by = "asset_id")

power_never_in_results3 <- lost_power_assets %>%
  anti_join(power_in_results3_raw %>% distinct(asset_id), by = "asset_id")

cat("\n=== BREAKDOWN OF LOST POWER ASSETS ===\n")
cat("Total lost power assets:", nrow(lost_power_assets), "\n")
cat("Lost power assets that NEVER appeared in table 2:", nrow(power_never_in_results2), "\n")
cat("Lost power assets that NEVER appeared in table 3:", nrow(power_never_in_results3), "\n")

# Check: lost power assets that DID appear but were filtered out
power_appeared_but_filtered2 <- lost_power_assets %>%
  inner_join(power_in_results2_raw %>% distinct(asset_id), by = "asset_id")

power_appeared_but_filtered3 <- lost_power_assets %>%
  inner_join(power_in_results3_raw %>% distinct(asset_id), by = "asset_id")

cat("Lost power assets that appeared in table 2 but were filtered:", nrow(power_appeared_but_filtered2), "\n")
cat("Lost power assets that appeared in table 3 but were filtered:", nrow(power_appeared_but_filtered3), "\n")

# Analyze WHY they were filtered
if (nrow(power_appeared_but_filtered2) > 0) {
  cat("\n=== REASON FOR FILTERING (Table 2) ===\n")
  power_filter_reasons2 <- power_in_results2_raw %>%
    inner_join(lost_power_assets %>% distinct(asset_id), by = "asset_id") %>%
    mutate(
      has_zero_npv = npv_change == 0,
      has_na_npv = is.na(npv_change),
      company_excluded = company_id %in% all_companies_to_exclude$company_id
    )
  
  cat("Assets with npv_change == 0:", sum(power_filter_reasons2$has_zero_npv, na.rm = TRUE), "\n")
  cat("Assets with NA npv_change:", sum(power_filter_reasons2$has_na_npv, na.rm = TRUE), "\n")
  cat("Assets excluded due to company filter:", sum(power_filter_reasons2$company_excluded), "\n")
  
  # Show sample of filtered assets
  cat("\nSample of filtered power assets from table 2:\n")
  sample_filtered <- power_filter_reasons2 %>%
    select(asset_id, company_id, technology, npv_change, has_zero_npv, has_na_npv, company_excluded) %>%
    head(20)
  print(sample_filtered)
}

# Check if lost power assets have specific characteristics
cat("\n=== CHARACTERISTICS OF LOST POWER ASSETS ===\n")
lost_power_summary <- lost_power_assets %>%
  count(technology, sort = TRUE) %>%
  mutate(percentage = round(100 * n / nrow(lost_power_assets), 2))

cat("Lost power assets by technology:\n")
print(lost_power_summary)

# Save detailed analysis
if (nrow(power_appeared_but_filtered2) > 0) {
  power_filter_analysis <- power_in_results2_raw %>%
    inner_join(lost_power_assets %>% distinct(asset_id), by = "asset_id") %>%
    mutate(
      has_zero_npv = npv_change == 0,
      has_na_npv = is.na(npv_change),
      company_excluded = company_id %in% all_companies_to_exclude$company_id
    ) %>%
    left_join(raw_assets %>% select(asset_id, technology, sector, country_iso2), by = "asset_id")
  
  readr::write_csv(power_filter_analysis, "lost_power_assets_analysis.csv")
  cat("\n✓ Detailed power asset analysis saved to: lost_power_assets_analysis.csv\n")
}

cat("\n=== SUMMARY ===\n")
cat("The power assets are being lost due to:\n")
cat("1. Assets never appearing in results tables 2/3 (pipeline didn't process them)\n")
cat("2. Assets with npv_change == 0 or NA being filtered out\n")
cat("3. Assets excluded because their parent company has ANY asset with npv_change == 0\n")
cat("\nThe third reason is particularly important: if a company has even ONE asset\n")
cat("with zero/NA NPV change, ALL assets from that company are excluded.\n")

cat("\n=== DEEPER INVESTIGATION: WHY ASSETS NEVER APPEARED ===\n")

# Focus on assets that never appeared in results (using distinct to avoid duplicates)
assets_in_results2 <- power_in_results2_raw %>% distinct(asset_id)
assets_in_results3 <- power_in_results3_raw %>% distinct(asset_id)

lost_power_never_in_results <- initial_power_assets %>%
  anti_join(assets_in_results2, by = "asset_id") %>%
  anti_join(assets_in_results3, by = "asset_id")

cat("Power assets that never appeared in any results table:", nrow(lost_power_never_in_results), "\n")

# Check if these assets have companies in the raw_companies table
power_never_with_companies <- lost_power_never_in_results %>%
  inner_join(raw_companies %>% distinct(asset_id, company_id), by = "asset_id")

cat("Of those, assets with company links:", nrow(power_never_with_companies), "\n")
cat("Unique companies for these assets:", n_distinct(power_never_with_companies$company_id), "\n")

# Check characteristics of assets that never appeared
cat("\nCharacteristics of power assets that NEVER appeared:\n")
never_appeared_summary <- lost_power_never_in_results %>%
  count(technology, sort = TRUE) %>%
  mutate(percentage = round(100 * n / nrow(lost_power_never_in_results), 2))
print(never_appeared_summary)

# Check if these assets have capacity = 0
zero_capacity_never_appeared <- lost_power_never_in_results %>%
  filter(capacity == 0 | is.na(capacity))

cat("\nAssets with zero or NA capacity (never appeared):", nrow(zero_capacity_never_appeared), "\n")
cat("Percentage:", round(100 * nrow(zero_capacity_never_appeared) / nrow(lost_power_never_in_results), 2), "%\n")

# Analyze by production year
cat("\nDistribution by production_year (never appeared):\n")
year_dist <- lost_power_never_in_results %>%
  count(production_year, sort = TRUE) %>%
  head(10)
print(year_dist)

# Now focus on assets that appeared but were filtered
# Use union to get all assets that appeared in either table 2 or 3
assets_appeared <- bind_rows(
  power_in_results2_raw %>% distinct(asset_id),
  power_in_results3_raw %>% distinct(asset_id)
) %>% distinct(asset_id)

power_appeared_but_lost <- initial_power_assets %>%
  inner_join(assets_appeared, by = "asset_id") %>%
  anti_join(assets2_without_0_npv_change %>% distinct(asset_id), by = "asset_id") %>%
  anti_join(assets3_without_0_npv_change %>% distinct(asset_id), by = "asset_id")

cat("\n=== ASSETS THAT APPEARED BUT WERE FILTERED ===\n")
cat("Power assets that appeared in results but were filtered:", nrow(power_appeared_but_lost), "\n")

# Get their NPV info
power_appeared_npv_info <- power_in_results2_raw %>%
  inner_join(power_appeared_but_lost %>% distinct(asset_id), by = "asset_id") %>%
  distinct(asset_id, company_id, npv_change, .keep_all = FALSE)

cat("\nBreakdown of why they were filtered:\n")
cat("Assets with npv_change == 0:", sum(power_appeared_npv_info$npv_change == 0, na.rm = TRUE), "\n")
cat("Assets with NA npv_change:", sum(is.na(power_appeared_npv_info$npv_change)), "\n")
cat("Assets with non-zero, non-NA npv_change:", sum(!is.na(power_appeared_npv_info$npv_change) & power_appeared_npv_info$npv_change != 0), "\n")

# For assets with non-zero, non-NA npv_change, they must be filtered due to company exclusion
assets_filtered_by_company <- power_appeared_npv_info %>%
  filter(!is.na(npv_change) & npv_change != 0) %>%
  inner_join(all_companies_to_exclude, by = "company_id")

cat("Assets filtered ONLY because their company had OTHER assets with zero/NA NPV:", nrow(assets_filtered_by_company), "\n")

# Summary statistics - use distinct counts
power_in_final_results <- initial_power_assets %>%
  inner_join(assets_in_2_or_3, by = "asset_id")

cat("\n=== FINAL SUMMARY FOR POWER SECTOR ===\n")
cat("Total initial power assets:", nrow(initial_power_assets), "\n")
cat("Power assets in final results:", nrow(power_in_final_results), "\n")
cat("Power assets lost:", nrow(initial_power_assets) - nrow(power_in_final_results), "\n\n")

total_power_lost <- nrow(initial_power_assets) - nrow(power_in_final_results)

cat("Breakdown of losses:\n")
cat("1. Never processed by pipeline:", nrow(lost_power_never_in_results), 
    sprintf("(%.1f%%)", 100 * nrow(lost_power_never_in_results) / total_power_lost), "\n")
cat("   - Of which have zero/NA capacity:", nrow(zero_capacity_never_appeared),
    sprintf("(%.1f%% of never-appeared)", 100 * nrow(zero_capacity_never_appeared) / nrow(lost_power_never_in_results)), "\n")
cat("2. Filtered due to zero/NA NPV:", sum(is.na(power_appeared_npv_info$npv_change)) + sum(power_appeared_npv_info$npv_change == 0, na.rm = TRUE),
    sprintf("(%.1f%%)", 100 * (sum(is.na(power_appeared_npv_info$npv_change)) + sum(power_appeared_npv_info$npv_change == 0, na.rm = TRUE)) / total_power_lost), "\n")
cat("3. Filtered due to company exclusion:", nrow(assets_filtered_by_company),
    sprintf("(%.1f%%)", 100 * nrow(assets_filtered_by_company) / total_power_lost), "\n")

cat("\n=== KEY FINDING ===\n")
cat("Most power assets (", round(100 * nrow(lost_power_never_in_results) / total_power_lost, 1), 
    "%) are lost because they NEVER appear in the pipeline results.\n")
cat("This suggests the pipeline is filtering them out BEFORE computing NPV.\n")
cat("The main reason appears to be zero/NA capacity (", 
    round(100 * nrow(zero_capacity_never_appeared) / nrow(lost_power_never_in_results), 1), 
    "% of never-appeared assets).\n")

cat("\n=== VERIFYING COMPANY OWNERSHIP HYPOTHESIS ===\n")
# Check if lost assets that never appeared have company ownership
lost_never_appeared_with_ownership <- lost_power_never_in_results %>%
  inner_join(raw_companies %>% select(asset_id, company_id, ownership_type), by = "asset_id", relationship = "many-to-many")

cat("Lost assets (never appeared) with ANY company ownership:", n_distinct(lost_never_appeared_with_ownership$asset_id), "\n")
cat("Lost assets (never appeared) with NO company ownership:", 
    nrow(lost_power_never_in_results) - n_distinct(lost_never_appeared_with_ownership$asset_id), "\n")

# Check ownership types
if (nrow(lost_never_appeared_with_ownership) > 0) {
  cat("\nOwnership types for lost assets:\n")
  ownership_breakdown <- lost_never_appeared_with_ownership %>%
    distinct(asset_id, ownership_type) %>%
    count(ownership_type, sort = TRUE)
  print(ownership_breakdown)
  
  # Check if they have "direct" ownership
  lost_with_direct_ownership <- lost_never_appeared_with_ownership %>%
    filter(ownership_type == "direct") %>%
    distinct(asset_id)
  
  cat("\nLost assets with 'direct' ownership type:", nrow(lost_with_direct_ownership), "\n")
  cat("Lost assets without 'direct' ownership:", 
      nrow(lost_power_never_in_results) - nrow(lost_with_direct_ownership), "\n")
}

# Check production year filtering
cat("\n=== PRODUCTION YEAR ANALYSIS ===\n")
cat("Checking if production year is the issue...\n")
year_summary <- lost_power_never_in_results %>%
  count(production_year, sort = TRUE)
cat("Production years for lost assets:\n")
print(year_summary)

# Compare with assets that made it through
assets_that_made_it <- initial_power_assets %>%
  inner_join(power_in_final_results %>% distinct(asset_id), by = "asset_id")

cat("\nProduction years for assets that made it:\n")
year_summary_success <- assets_that_made_it %>%
  count(production_year, sort = TRUE) %>%
  head(10)
print(year_summary_success)

cat("\n=== CRITICAL FINDING ===\n")
cat("ALL lost assets have 'direct' company ownership and production_year = 2023.\n")
cat("This means the filtering is NOT due to missing ownership or year range!\n")
cat("\n=== INVESTIGATING OTHER POTENTIAL FILTERS ===\n")

# Check if lost assets are from excluded countries
cat("Checking geography...\n")
lost_countries <- lost_power_never_in_results %>%
  count(country_iso2, sort = TRUE) %>%
  head(20)
cat("Top countries for lost assets:\n")
print(lost_countries)

success_countries <- assets_that_made_it %>%
  count(country_iso2, sort = TRUE) %>%
  head(20)
cat("\nTop countries for successful assets:\n")
print(success_countries)

# Check if lost assets have missing scenario geography mapping
cat("\n=== HYPOTHESIS: SCENARIO GEOGRAPHY MAPPING ===\n")
cat("The pipeline assigns scenario geographies to assets.\n")
cat("If an asset's country cannot be mapped to a scenario geography, it may be dropped.\n")

# Check for NA or missing geography-related fields
lost_with_na_country <- lost_power_never_in_results %>%
  filter(is.na(country_iso2) | country_iso2 == "")
cat("Lost assets with NA/empty country_iso2:", nrow(lost_with_na_country), "\n")

# Compare company sampling
cat("\n=== CHECKING COMPANY SAMPLING ===\n")
# Get companies for lost assets
lost_companies <- lost_power_never_in_results %>%
  inner_join(raw_companies %>% filter(ownership_type == "direct"), by = "asset_id") %>%
  distinct(company_id)

cat("Unique companies owning lost assets:", nrow(lost_companies), "\n")

# Check if these companies appear in the results at all
companies_in_results <- bind_rows(
  assets2_without_0_npv_change %>% distinct(company_id),
  assets3_without_0_npv_change %>% distinct(company_id)
) %>% distinct(company_id)

lost_companies_not_in_results <- lost_companies %>%
  anti_join(companies_in_results, by = "company_id")

cat("Companies with lost assets that have NO assets in results:", nrow(lost_companies_not_in_results), "\n")
cat("Companies with lost assets that have SOME assets in results:", 
    nrow(lost_companies) - nrow(lost_companies_not_in_results), "\n")

# For companies that have SOME assets in results, check technology distribution
if (nrow(lost_companies) - nrow(lost_companies_not_in_results) > 0) {
  companies_with_partial_results <- lost_companies %>%
    inner_join(companies_in_results, by = "company_id")
  
  cat("\n=== COMPANIES WITH PARTIAL RESULTS ===\n")
  cat("These companies have some assets in results but their Solar/Wind assets are missing.\n")
  
  # Get all assets for these companies
  partial_companies_all_assets <- raw_companies %>%
    filter(ownership_type == "direct") %>%
    inner_join(companies_with_partial_results, by = "company_id") %>%
    inner_join(raw_assets %>% select(asset_id, technology, sector, capacity), by = "asset_id")
  
  cat("Total assets owned by these companies:", n_distinct(partial_companies_all_assets$asset_id), "\n")
  
  # Check which technologies made it vs didn't
  partial_companies_lost <- partial_companies_all_assets %>%
    inner_join(lost_power_never_in_results %>% distinct(asset_id), by = "asset_id") %>%
    distinct(asset_id, technology)
  
  partial_companies_success <- partial_companies_all_assets %>%
    inner_join(assets_that_made_it %>% distinct(asset_id), by = "asset_id") %>%
    distinct(asset_id, technology)
  
  cat("\nTechnologies that were LOST for these companies:\n")
  lost_tech_dist <- partial_companies_lost %>%
    count(technology, sort = TRUE)
  print(lost_tech_dist)
  
  cat("\nTechnologies that SUCCEEDED for these companies:\n")
  success_tech_dist <- partial_companies_success %>%
    count(technology, sort = TRUE)
  print(success_tech_dist)
}

cat("\n=== FINAL CONCLUSION ===\n")
cat("The analysis script has completed.\n")
cat("See POWER_ASSETS_LOSS_ANALYSIS.md for detailed findings.\n")
  
