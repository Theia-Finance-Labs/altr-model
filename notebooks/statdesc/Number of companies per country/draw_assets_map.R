library(dplyr)
library(sf)
library(ggplot2)
library(rnaturalearth)
library(viridis)

unique_power_assets_loc <- readr::read_csv(file.path("data", "08_reporting", "assets_data.csv")) %>%
  distinct(asset_id, sector, latitude, longitude)

unique_power_assets_loc %>% readr::write_csv(file.path(getwd(), "notebooks", "statdesc", "Number of companies per country", "unique_power_assets_loc.csv"))

# Read the power assets data
power_assets <- asset_data %>%
  dplyr::filter(
    !is.na(.data$latitude),
    !is.na(.data$longitude)
  )

# Get world map data as an sf object
world <- rnaturalearth::ne_countries(
  scale       = "medium",
  returnclass = "sf"
)

# Convert power assets to sf points
assets_sf <- sf::st_as_sf(
  power_assets,
  coords = c("longitude", "latitude"),
  crs    = 4326
)

# Count assets per country
country_counts <- sf::st_join(assets_sf, world) %>%
  dplyr::group_by(.data$name) %>%
  dplyr::summarise(n_assets = dplyr::n()) %>%
  sf::st_drop_geometry()

# Join counts back to world map and create discrete bins
world_with_counts <- world %>%
  dplyr::left_join(country_counts, by = "name") %>%
  tidyr::replace_na(list(n_assets = 0)) %>%
  dplyr::mutate(
    asset_bin = cut(
      .data$n_assets,
      breaks = c(0, 1, 10, 100, 1000, Inf),
      labels = c("0", "1–10", "11–100", "101–1000", ">1000"),
      include.lowest = TRUE
    )
  )

# Define custom colors: grey for "0", viridis for the rest
viridis_colors <- viridis::viridis(4, option = "C")  # 4 colors for non-zero bins
custom_colors <- c("0" = "grey80",
                   "1–10" = viridis_colors[1],
                   "11–100" = viridis_colors[2],
                   "101–1000" = viridis_colors[3],
                   ">1000" = viridis_colors[4])

# Plot with manual colors
p <- ggplot2::ggplot() +
  ggplot2::geom_sf(
    data = world_with_counts,
    aes(fill = .data$asset_bin),
    color = "white",
    size  = 0.1
  ) +
  ggplot2::scale_fill_manual(
    values = custom_colors,
    name   = "Assets per Country"
  ) +
  ggplot2::guides(
    fill = ggplot2::guide_legend(
      title.position = "top",
      nrow           = 1,
      byrow          = TRUE,
      keywidth       = grid::unit(2, "cm")
    )
  ) +
  ggplot2::theme_minimal() +
  ggplot2::theme(
    legend.position   = "bottom",
    legend.title      = ggplot2::element_text(size = 12, face = "bold"),
    legend.text       = ggplot2::element_text(size = 10),
    plot.title        = ggplot2::element_text(size = 16, face = "bold"),
    plot.subtitle     = ggplot2::element_text(size = 12)
  ) +
  ggplot2::labs(
    title    = "Distribution of Power Assets by Country",
    subtitle = "Grey indicates countries with zero assets"
  )


ggplot2::ggsave(file.path(getwd(), "notebooks", "statdesc", "Number of companies per country", "power_assets_map.png"), plot = p, width = 12, height = 6, dpi = 300)

print(paste("saved power assets map to", file.path(getwd(), "notebooks", "statdesc", "Number of companies per country", "power_assets_map.png")))
