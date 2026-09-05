"""Run one full-universe altrisk arm via the KedroSession API.

Bypasses `kedro run --params`, whose comma-splitting cannot express nested
dicts or lists. Nested dcf overrides MUST arrive as a whole block -- see the
runbook's --params replacement trap.

Usage: bench_run.py <label> <params.json|->
"""

import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("ALTR_BENCH_RUNS", PROJECT / "data" / "09_benchmarks"))


def main() -> int:
    label = sys.argv[1]
    raw = sys.argv[2]
    extra = json.loads(raw) if raw != "-" else {}

    rundir = OUT / label
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "params.json").write_text(json.dumps(extra, indent=2))

    logfile = rundir / "run.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(logfile, mode="w"), logging.StreamHandler()],
        force=True,
    )

    sys.path.insert(0, str(PROJECT / "src"))
    from kedro.framework.session import KedroSession
    from kedro.framework.startup import bootstrap_project

    bootstrap_project(PROJECT)

    # Free disk before the run; outputs from the previous arm are regenerable.
    outdir = PROJECT / "data/07_model_output"
    if outdir.exists():
        for p in outdir.iterdir():
            if p.name != ".gitkeep":
                p.unlink() if p.is_file() else shutil.rmtree(p)

    free_gb = shutil.disk_usage(PROJECT).free / 1e9
    print(f"[bench] {label}: {free_gb:.2f} GB free before run", flush=True)
    if free_gb < 2.5:
        print(f"[bench] ABORT {label}: only {free_gb:.2f} GB free", flush=True)
        return 2

    t0 = time.time()
    status = "ok"
    node_count = None
    try:
        from kedro.framework.project import pipelines

        with KedroSession.create(PROJECT, env="full", extra_params=extra) as session:
            session.load_context()
            node_count = len(
                pipelines["__default__"].only_nodes_with_tags("altrisk").nodes
            )
            print(f"[bench] {label}: {node_count} tagged nodes", flush=True)
            session.run(tags=["altrisk"])
    except Exception as exc:  # noqa: BLE001 -- the failure IS the measurement
        status = f"FAILED: {type(exc).__name__}: {exc}"
        logging.exception("run failed")
    runtime = time.time() - t0

    summary = {
        "label": label,
        "status": status,
        "runtime_s": round(runtime, 1),
        "node_count": node_count,
        "free_gb_after": round(shutil.disk_usage(PROJECT).free / 1e9, 2),
    }
    (rundir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[bench] {json.dumps(summary)}", flush=True)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
