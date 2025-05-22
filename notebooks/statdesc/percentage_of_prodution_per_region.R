library(dplyr)
library(tidyr)
library(readr)
library(sf)
library(rnaturalearth)
library(ggplot2)
library(viridis)
# Parameters
SCENARIO_REF <- "AR6_WITCH 5.0_EN_NoPolicy"
YEAR_REF     <- 2025

# Read & parse data (no library() calls; use ::)
assets_data <- readr::read_csv(
  "data/08_reporting/assets_data.csv",
  show_col_types = FALSE
) %>%
  dplyr::mutate(
    asset_trajectory_gw = as.numeric(.data$asset_trajectory) / 1000
  )

scenarios_data <- readr::read_csv(
  "data/08_reporting/scenarios_data.csv",
  show_col_types = FALSE
) %>%
  dplyr::mutate(
    # strip non‐digits (commas, units) if any
    scenario_pathway = readr::parse_number(.data$scenario_pathway)
  )

# Filter to our scenario, year, and matching technologies
scenarios_filtered <- scenarios_data %>%
  dplyr::filter(
    .data$scenario       == SCENARIO_REF,
    .data$scenario_year  == YEAR_REF,
    .data$technology    %in% unique(assets_data$technology)
  )

assets_filtered <- assets_data %>%
  dplyr::filter(.data$year == YEAR_REF)

# Build a region ⇢ country map from the scenario file
region_country <- scenarios_filtered %>%
  dplyr::select(
    region = .data$scenario_geography,
    country_iso2_list = .data$country_iso2_list
  ) %>%
  dplyr::filter(!is.na(.data$country_iso2_list)) %>%
  dplyr::distinct() %>%
  tidyr::separate_rows(.data$country_iso2_list, sep = ",") %>%
  dplyr::rename(country_iso2 = .data$country_iso2_list)

# Also include Global → every country in the world
world <- rnaturalearth::ne_countries(scale = "medium", returnclass = "sf")

# Sum scenario pathways by region & tech
region_tech_scenario <- scenarios_filtered %>%
  dplyr::group_by(
    region     = .data$scenario_geography,
    technology = .data$technology
  ) %>%
  dplyr::summarise(
    scenario_pathway = sum(.data$scenario_pathway, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  # add a Global‐across‐all‐tech entry too
  dplyr::bind_rows(
    scenarios_filtered %>%
      dplyr::group_by(technology = .data$technology) %>%
      dplyr::summarise(
        scenario_pathway = sum(.data$scenario_pathway, na.rm = TRUE),
        .groups = "drop"
      ) %>%
      dplyr::mutate(region = "Global")
  )

# Sum asset trajectories by region & tech
region_tech_assets <- region_country %>%
  dplyr::inner_join(
    assets_filtered %>% 
      dplyr::select(
        country_iso2    = .data$country_iso2,
        technology      = .data$technology,
        asset_trajectory = .data$asset_trajectory_gw
      ),
    by = "country_iso2"
  ) %>%
  dplyr::group_by(.data$region, .data$technology) %>%
  dplyr::summarise(
    asset_trajectory = sum(.data$asset_trajectory, na.rm = TRUE),
    .groups = "drop"
  )

# Combine to get coverage by region & tech
region_tech_cov <- region_tech_scenario %>%
  dplyr::inner_join(region_tech_assets, by = c("region", "technology")) %>%
  dplyr::mutate(
    coverage = .data$asset_trajectory / .data$scenario_pathway
  )

# Expand region–tech coverage to country–tech coverage
final_coverage <- region_country %>%
  dplyr::inner_join(region_tech_cov, by = "region") %>%
  dplyr::select(
    country_iso2,
    .data$region,
    .data$technology,
    .data$scenario_pathway,
    .data$asset_trajectory,
    .data$coverage
  )

# Compute total (all‐tech) coverage per region & country
region_totals <- final_coverage %>%
  dplyr::group_by(.data$region, .data$country_iso2) %>%
  dplyr::summarise(
    asset_trajectory   = sum(.data$asset_trajectory),
    scenario_pathway   = sum(.data$scenario_pathway),
    .groups            = "drop"
  ) %>%
  dplyr::mutate(
    technology = "Total",
    coverage   = .data$asset_trajectory / .data$scenario_pathway
  )

# Bind individual‐tech & total
final_coverage_all <- dplyr::bind_rows(final_coverage, region_totals)

# Join to the world map
map_sf <- world %>%
  dplyr::left_join(final_coverage_all,
                   by = c("iso_a2" = "country_iso2"))

# Plot function
plot_coverage_map <- function(sf_data, tech, outdir) {
  df <- sf_data %>% dplyr::filter(.data$technology == tech)
  p <- ggplot2::ggplot(df) +
    ggplot2::geom_sf(
      ggplot2::aes(fill = .data$coverage),
      na.rm = FALSE
    ) +
    ggplot2::scale_fill_viridis_c(
      name   = "Coverage",
      labels = scales::percent,
      limits = c(0, 1),
      na.value = "grey90"
    ) +
    ggplot2::labs(
      title    = paste("Coverage for", tech),
      subtitle = paste("Scenario:", SCENARIO_REF, "| Year:", YEAR_REF)
    ) +
    ggplot2::theme_minimal() +
    ggplot2::theme(
      plot.title    = ggplot2::element_text(hjust = 0.5),
      plot.subtitle = ggplot2::element_text(hjust = 0.5)
    )
  ggplot2::ggsave(
    filename = file.path(outdir, paste0("coverage_map_", gsub(" ", "_", tech), ".png")),
    plot     = p,
    width    = 12,
    height   = 8,
    dpi      = 300
  )
}

# Create output directory
output_dir <- "workspace/statdesc/Percentage of production per region"
if (!dir.exists(output_dir)) {
  dir.create(output_dir, recursive = TRUE)
}

# Plot each technology
for (tech in unique(final_coverage$technology)) {
  plot_coverage_map(map_sf, tech, output_dir)
}

# Plot the Total coverage map
plot_coverage_map(map_sf, "Total", output_dir)

# Save the combined data
readr::write_csv(
  final_coverage_all %>% distinct(region,    technology,    scenario_pathway ,asset_trajectory, coverage),
  file.path(output_dir, "coverage_data.csv")
)
readr::write_csv(
  sf::st_drop_geometry(world),
  file.path(output_dir, "world_map_data.csv")
)
