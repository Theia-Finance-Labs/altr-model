"""Tolerance-based DataFrame comparison for golden-run pinning."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compare_frames(old: pd.DataFrame, new: pd.DataFrame, rtol: float = 1e-9) -> list[str]:
    """Return a list of difference descriptions; empty list == match."""
    diffs: list[str] = []
    if list(old.columns) != list(new.columns):
        diffs.append(f"columns differ: {set(old.columns) ^ set(new.columns)}")
        return diffs
    if len(old) != len(new):
        diffs.append(f"row count {len(old)} -> {len(new)}")
        return diffs
    for col in old.columns:
        o, n = old[col].reset_index(drop=True), new[col].reset_index(drop=True)
        if pd.api.types.is_numeric_dtype(o) and pd.api.types.is_numeric_dtype(n):
            # NaN drift first: filling NaN with 0 would hide a column that
            # silently turned missing into zero (or the reverse).
            mask_diff = int((o.isna() != n.isna()).sum())
            if mask_diff:
                diffs.append(f"{col}: NaN mask differs in {mask_diff} row(s)")
                continue
            # Masks align, so equal_nan=True compares only the real values.
            if not np.allclose(o, n, rtol=rtol, equal_nan=True):
                worst = (o - n).abs().max()
                diffs.append(f"{col}: numeric drift, max abs diff {worst}")
        elif not o.astype(str).equals(n.astype(str)):
            diffs.append(f"{col}: value mismatch")
    return diffs
