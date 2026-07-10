# AGENTS.md — crispy-kedro

## Purpose
Kedro pipeline for CRISPY climate risk / transaction cost minimizer (TCM) modelling.

## Team context
Board: Theia Team Board (org project #5). Issues carry Status/Priority/Size/Product/Project/Review/Sprint fields; TCM issues carry Product=`TCM`.
Conventions: theia-ops/docs/operating-manual.md. Technical review: Bertrand first.

## Layout
- src/        Kedro pipelines and nodes
- conf/       Kedro configuration (base/local)
- docs/       research notes, superpowers specs+plans, source docs
- notebooks/  exploratory analysis
- tests/      pytest suite
- MCPR/, pkg/, workspace/  model-specific workstreams

## Commands
- poetry install
- poetry run kedro run
- poetry run pytest tests/

## Rules
- Methodology docs live in docs/; never delete files — archive instead.
- ALTR/MCPR changes need Bertrand's review before merge.
