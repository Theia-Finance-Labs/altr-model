def split_assets_per_proximity_to_target(
    truncated_traj_assets_raw, traj_assets_target_prod
):
    return assets_to_compensate, assets_to_simple_shock


def apply_compensation_shock(
    assets_to_compensate, traj_assets_baseline_prod, traj_assets_target_prod
):
    return assets_compensated_shocked


def apply_simple_shock(
    assets_to_simple_shock, traj_assets_baseline_prod, traj_assets_target_prod
):
    return assets_simply_shocked


def gather_shock_trajectories(assets_compensated_shocked, assets_simply_shocked):
    return traj_assets_shocked
