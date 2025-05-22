# Full end-to-end script: compute capacity coverage per region & technology,
# sum across technologies for “All”, plot each tech + All with discrete legend steps,
# and export raw data to Excel

# ---- 0. Libraries & parameters ----
library(dplyr)
library(tidyr)
library(readr)
library(sf)
library(rnaturalearth)
library(ggplot2)
library(viridis)
library(writexl)
library(purrr)
library(scales)
library(grid)

SCENARIO_REF <- "AR6_WITCH 5.0_EN_NoPolicy"
YEAR_REF     <- 2025
OUTPUT_DIR   <- "workspace/statdesc/Percentage of production per region/"

if (!dir.exists(OUTPUT_DIR)) dir.create(OUTPUT_DIR, recursive = TRUE)

# ---- 1. Read & parse data ----
assets_data <- readr::read_csv(
  "packages/crispy-kedro/data/08_reporting/assets_data.csv",
  show_col_types = FALSE
) %>%
  mutate(asset_trajectory_gw = as.numeric(asset_trajectory) / 1000) %>%
  select(asset_id, country_iso2, technology, year, asset_trajectory_gw)

scenarios_data <- readr::read_csv(
  "packages/crispy-kedro/data/08_reporting/scenarios_data.csv",
  show_col_types = FALSE
) %>%
  mutate(scenario_pathway = parse_number(scenario_pathway)) %>%
  select(
    scenario, scenario_year, scenario_geography,
    technology, scenario_pathway, country_iso2_list
  )

# ---- 2. Filter to our scenario & year ----
scenarios_filtered <- scenarios_data %>%
  filter(
    scenario      == SCENARIO_REF,
    scenario_year == YEAR_REF,
    technology   %in% unique(assets_data$technology)
  )

assets_filtered <- assets_data %>%
  filter(year == YEAR_REF) %>%
  select(-year)

# ---- 3. Build region ↔ country lookup ----
region_lookup <- scenarios_filtered %>%
  separate_rows(country_iso2_list, sep = ",") %>%
  rename(country_iso2 = country_iso2_list) %>%
  distinct(scenario_geography, country_iso2)

# ---- 4. Sum asset capacity by region × technology ----
coverage_long <- assets_filtered %>%
  inner_join(region_lookup, by = "country_iso2") %>%
  group_by(scenario_geography, technology) %>%
  summarise(
    region_asset_gw = sum(asset_trajectory_gw, na.rm = TRUE),
    .groups = "drop"
  )

# ---- 5. Merge in scenario targets and compute % coverage ----
coverage_long <- coverage_long %>%
  inner_join(
    scenarios_filtered %>%
      select(scenario_geography, technology, scenario_pathway),
    by = c("scenario_geography", "technology")
  ) %>%
  mutate(
    coverage_pct = 100 * region_asset_gw / scenario_pathway
  )

# ---- 6. Compute “All technologies” summary per region ----
# a) sum actual assets across technologies
all_assets <- coverage_long %>%
  group_by(scenario_geography) %>%
  summarise(
    region_asset_gw = sum(region_asset_gw, na.rm = TRUE),
    .groups = "drop"
  )
# b) sum scenario pathways across technologies
all_pathways <- scenarios_filtered %>%
  group_by(scenario_geography) %>%
  summarise(
    scenario_pathway = sum(scenario_pathway, na.rm = TRUE),
    .groups = "drop"
  )
# c) build the “All” table
coverage_all <- all_assets %>%
  left_join(all_pathways, by = "scenario_geography") %>%
  mutate(
    coverage_pct = 100 * region_asset_gw / scenario_pathway,
    technology   = "All"
  ) %>%
  select(
    scenario_geography,
    technology,
    scenario_pathway,
    region_asset_gw,
    coverage_pct
  )

# ---- 7. Combine into one table ----
coverage_full <- bind_rows(
  coverage_long %>% select(
    scenario_geography, technology,
    scenario_pathway, region_asset_gw, coverage_pct
  ),
  coverage_all
)

# ---- 8. Load world map & region→country lookup for plotting ----
world <- rnaturalearth::ne_countries(returnclass = "sf")
region_country <- region_lookup

# ---- 9. Plot & save a map per technology (plus “All”) with discrete legend ----
for (tech in unique(coverage_full$technology)) {
  df <- coverage_full %>%
    filter(technology == tech)
  
  map_df <- region_country %>%
    inner_join(df, by = "scenario_geography")
  
  shp <- world %>%
    inner_join(
      map_df,
      by = c("iso_a2" = "country_iso2")
    )
  
  # number of distinct regions = legend steps
  n_steps <- n_distinct(df$scenario_geography)
  
  p <- ggplot(shp) +
    geom_sf(aes(fill = coverage_pct), colour = "grey30") +
    scale_fill_stepsn(
      colours = viridis(n_steps, option = "magma"),
      breaks  = sort(unique(shp$coverage_pct)),
      labels  = label_percent(scale = 1, accuracy = 1),
      name    = "Coverage (%)"
    ) +
    labs(title = paste0("Capacity Coverage (%) — ", tech)) +
    theme_minimal(base_size = 14) +
    theme(
      plot.title        = element_text(hjust = 0.5, face = "bold"),
      legend.position   = "right",
      legend.key.height = unit(1.2, "cm"),
      legend.title      = element_text(size = 12),
      legend.text       = element_text(size = 10)
    )
  
  ggsave(
    filename = paste0(
      OUTPUT_DIR,
      "map_coverage_",
      gsub(" ", "_", tech),
      ".png"
    ),
    plot   = p,
    width  = 10,
    height = 6
  )
  cat(paste("saved map of", tech, "to", paste0(OUTPUT_DIR, "map_coverage_", gsub(" ", "_", tech), ".png")))
}

# ---- 10. Export raw coverage data to Excel ----
sheets <- coverage_full %>%
  arrange(technology, scenario_geography) %>%
  split(.$technology) %>%
  map(~ select(
    .x,
    scenario_geography,
    technology,
    scenario_pathway,
    region_asset_gw,
    coverage_pct
  ))

write_xlsx(sheets, path = paste0(OUTPUT_DIR, "coverage_by_region.xlsx"))
 

cat(paste("saved coverage by region to", paste0(OUTPUT_DIR, "coverage_by_region.xlsx")))