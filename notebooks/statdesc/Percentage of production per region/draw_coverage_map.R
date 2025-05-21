library(dplyr)
library(readr)
library(ggplot2)
library(sf)
library(rnaturalearth)

assets_data  <-  read_csv("data/08_reporting/assets_data.csv")
scenarios_data  <-  read_csv("data/08_reporting/scenarios_data.csv")

SCENARIO_REF = "AR6_WITCH 5.0_EN_NoPolicy"
YEAR_REF = 2025

scenarios_data_filtered <- scenarios_data %>%
  dplyr::filter(
    scenario == SCENARIO_REF,
    technology %in% unique(assets_data$technology),
    scenario_year == YEAR_REF
  )

assets_data_filtered <- assets_data %>%
  dplyr::filter(
    year == YEAR_REF
  )

unique_regions_countries <- scenarios_data_filtered %>%
  dplyr::select(
    scenario_geography,
    country_iso2_list
  ) %>%
  filter(scenario_geography != "Global") %>%
  distinct()

# Initialize empty list to store results
coverage_results <- list()

for (region in unique_regions_countries$scenario_geography) {
    countries <- unique_regions_countries %>%
        dplyr::filter(
            scenario_geography == region
        ) %>%
        dplyr::pull(country_iso2_list)
    # Split countries string into vector
    country_list <- strsplit(countries, ",")[[1]]
    
    # Filter assets for countries in this region
    region_assets <- assets_data_filtered %>%
        dplyr::filter(country_iso2 %in% country_list)

    region_assets_production <- region_assets %>% 
        distinct(asset_id, technology, asset_trajectory) %>%
        group_by(technology) %>%
        summarise(
            asset_trajectory = sum(asset_trajectory)
        ) %>%
        ungroup() 
    
    region_scenario_production <- scenarios_data_filtered %>%
        dplyr::filter(scenario_geography == region) %>%
        dplyr::select(technology, scenario_pathway)
        
    production_comparison <- region_scenario_production %>%
        dplyr::inner_join(region_assets_production, by = "technology") %>%
        dplyr::mutate(
            coverage = as.numeric(asset_trajectory) / as.numeric(scenario_pathway),
            region = region
        )
    
    coverage_results[[region]] <- production_comparison
}

# Combine all results
all_coverage <- do.call(rbind, coverage_results)

# Calculate global totals
global_coverage <- all_coverage %>%
    group_by(technology) %>%
    summarise(
        coverage = sum(as.numeric(asset_trajectory)) / sum(as.numeric(scenario_pathway)),
        region = "Global",
        asset_trajectory = sum(as.numeric(asset_trajectory)),
        scenario_pathway = sum(as.numeric(scenario_pathway))
    )

# Combine regional and global results
final_coverage <- rbind(all_coverage, global_coverage)

# Get world map data
world <- ne_countries(scale = "medium", returnclass = "sf")

# Create a function to plot coverage map
plot_coverage_map <- function(data, tech) {
    # Filter data for specific technology
    tech_data <- data %>%
        filter(technology == tech)
    
    # Join with world map data
    map_data <- world %>%
        left_join(tech_data, by = c("iso_a2" = "region"))
    
    # Create the plot
    ggplot() +
        geom_sf(data = map_data, aes(fill = coverage)) +
        scale_fill_viridis_c(
            name = "Coverage",
            labels = scales::percent,
            limits = c(0, 1)
        ) +
        labs(
            title = paste("Coverage Map for", tech),
            subtitle = paste("Year:", YEAR_REF)
        ) +
        theme_minimal() +
        theme(
            plot.title = element_text(hjust = 0.5),
            plot.subtitle = element_text(hjust = 0.5)
        )
}

# Plot individual technology maps
tech_list <- unique(final_coverage$technology)

# Create directory if it doesn't exist
output_dir <- "notebooks/statdesc/Percentage of production per region/plots"
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

# Save individual technology maps
for (tech in tech_list) {
    p <- plot_coverage_map(final_coverage, tech)
    # Save plot
    ggsave(
        filename = file.path(output_dir, paste0("coverage_map_", gsub(" ", "_", tech), ".png")),
        plot = p,
        width = 12,
        height = 8,
        dpi = 300
    )
}

# Plot and save total coverage map
total_coverage <- final_coverage %>%
    group_by(region) %>%
    summarise(
        coverage = mean(as.numeric(coverage)),
        technology = "Total",
        asset_trajectory = sum(as.numeric(asset_trajectory)),
        scenario_pathway = sum(as.numeric(scenario_pathway))
    )

p_total <- plot_coverage_map(total_coverage, "Total")
ggsave(
    filename = file.path(output_dir, "coverage_map_total.png"),
    plot = p_total,
    width = 12,
    height = 8,
    dpi = 300
)

# Also save the data
write_csv(final_coverage, file.path(output_dir, "coverage_data.csv"))

# Save raw data for each technology map
for (tech in tech_list) {
    tech_data <- final_coverage %>%
        filter(technology == tech)
    
    # Join with world map data
    map_data <- world %>%
        left_join(tech_data, by = c("iso_a2" = "region"))
    
    # Save the map data
    write_csv(
        as.data.frame(map_data),
        file.path(output_dir, paste0("map_data_", gsub(" ", "_", tech), ".csv"))
    )
}

# Save total coverage map data
total_map_data <- world %>%
    left_join(total_coverage, by = c("iso_a2" = "region"))

write_csv(
    as.data.frame(total_map_data),
    file.path(output_dir, "map_data_total.csv")
)

# Save the world map data for reference
write_csv(
    as.data.frame(world),
    file.path(output_dir, "world_map_data.csv")
)
