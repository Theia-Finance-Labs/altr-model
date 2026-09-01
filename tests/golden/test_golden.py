"""Golden-run regression gate.

`test_compare_frames_detects_drift` always runs (unit check of the comparator).
`test_outputs_match_golden` is skipped until snapshots are pinned with
`scripts/pin_golden.py` — pinning waits for the full model run to finish.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.golden.compare import compare_frames

SNAP = Path(__file__).parent / "snapshots"


def test_compare_frames_detects_drift():
    a = pd.DataFrame({"x": [1.0, 2.0]})
    b = pd.DataFrame({"x": [1.0, 2.1]})
    assert compare_frames(a, a) == []
    assert compare_frames(a, b) != []

    # NaN turning into 0.0 (or back) is real drift, not a match.
    nan_frame = pd.DataFrame({"x": [1.0, float("nan")]})
    zero_frame = pd.DataFrame({"x": [1.0, 0.0]})
    assert compare_frames(nan_frame, nan_frame) == []
    assert compare_frames(nan_frame, zero_frame) != []
    assert compare_frames(zero_frame, nan_frame) != []


@pytest.mark.skipif(
    not (SNAP / "manifest.json").exists(), reason="golden not pinned yet"
)
def test_outputs_match_golden():
    manifest = json.loads((SNAP / "manifest.json").read_text())
    # Sources are recorded relative to the run directory the manifest names, so
    # a snapshot directory copied into another checkout still resolves.
    run_dir = Path(manifest["run_dir"])
    for entry in manifest["tables"]:
        old = pd.read_parquet(SNAP / entry["snapshot"])
        new = pd.read_csv(run_dir / entry["source"])
        assert compare_frames(old, new) == [], entry["source"]
