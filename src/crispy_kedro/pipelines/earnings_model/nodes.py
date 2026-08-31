"""Back-compat re-exports; implementation lives in the sibling modules."""

from .capacity import (  # noqa: F401
    assemble_asset_panel,
    compute_capacity_flows,
    compute_flow_based_capex,
)
from .mcpr import (  # noqa: F401
    apply_mcpr_adjustment,
    build_scenario_surfaces,
    compute_scenario_vre_share,
)
from .ops import (  # noqa: F401
    compute_fcff,
    compute_ops_block,
    write_asset_earnings_series,
)
from .validation import (  # noqa: F401
    validate_and_standardize_inputs,
    validate_capacity_flow_identity,
)
