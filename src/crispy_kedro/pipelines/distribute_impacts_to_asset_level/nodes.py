"""Back-compat re-exports; implementation lives in the sibling modules."""
from ._shared import (  # noqa: F401
    _allocate_reduction_with_caps_array,
    _index_assets_by_group,
)
from .assembly import (  # noqa: F401
    concatenate_staggered_shock_results,
    melt_asset_staggered_trajectories,
    split_late_sudden_trajectories_by_alignment_type,
)
from .baseline import (  # noqa: F401
    _compute_g_weights_array,
    _index_company_by_year,
    compute_asset_baseline_trajectories,
)
from .retirement import (  # noqa: F401
    _build_retirement_map,
    create_frozen_capacity_at_retirement,
    flag_phased_out_assets_as_retired,
)
from .staggering_decrease import (  # noqa: F401
    _prop_scale_decreasing_fast,
    _stagger_decreasing_fast,
    stagger_decreasing_technologies,
)
from .staggering_increase import stagger_increasing_technologies  # noqa: F401
