"""Reproduce what `kedro viz` does at startup: bootstrap project, build the
pipeline registry (register_pipelines -> find_pipelines -> sum), and load the
catalog config. Prints the first exception that would crash viz boot."""
import sys, traceback
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))

try:
    from kedro.framework.startup import bootstrap_project
    bootstrap_project(Path(".").resolve())
    print("[ok] bootstrap_project")

    from kedro.framework.project import pipelines
    keys = list(pipelines.keys())
    print(f"[ok] register_pipelines -> {keys}")
    default = pipelines["__default__"]
    print(f"[ok] __default__ built: {len(default.nodes)} nodes")
    # toposort, like viz does to draw the graph
    _ = default.grouped_nodes
    print("[ok] grouped_nodes (toposort) succeeded")
except Exception:
    print("[CRASH] during project/registry load:")
    traceback.print_exc()
    sys.exit(2)

print("ALL_OK")
