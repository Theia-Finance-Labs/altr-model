# ALTR Model

ALTR is an asset-level transition-risk valuation model. It answers one question:
**how much company value moves when a late-and-sudden climate-policy shock forces
companies off their current-policy pathway onto a climate-aligned one?** The unit
of analysis is the physical asset — a power plant, with a capacity, a technology,
a country and an age. Every asset is valued twice, once along a *baseline*
pathway and once along a *late & sudden* shock pathway, and the difference is the
transition-risk signal.

The mechanism runs bottom-up. Two IAM scenarios (one baseline, one target) supply
production pathways, prices, capacity factors and cost assumptions. Company-level
baseline and target trajectories are built from them, the shock is imposed at
`shock_year` and must be completed by `alignment_year`, and the resulting
company-level capacity change is *staggered* down onto the company's individual
assets rather than applied uniformly. Each asset's physical trajectory is then
turned into money — production, revenue at the market clearing price, fuel and
carbon costs, fixed O&M, growth/replacement CapEx and decommissioning — netting
to EBITDA and free cash flow to the firm. Finally the cash flows are discounted
(with an optional terminal value) into an NPV per asset, and rolled up to
company-technology and company level.

The comparison is *marginal*: the baseline is a current-policy pathway that
already carries its own transition costs, not a costless "no additional
headwinds" world. So ALTR measures the extra loss (or, occasionally, the avoided
loss) caused by policy that is stricter than current policy — a framing closer to
economy-wide current-policy stress tests than to a zero-carbon-cost
counterfactual. This matters when reading the results and is spelled out under
[Reading the sign of `npv_change`](user_guide.md#reading-the-sign-of-npv_change).

## What is in this package

| Piece | Where |
| --- | --- |
| Model code, as eight ordered Kedro pipeline stages | `src/crispy_kedro/pipelines/` |
| Run configuration — every knob you normally touch | `conf/base/parameters.yml` |
| Advanced / methodology-internal knobs | `conf/base/parameters_<pipeline>.yml` |
| Dataset declarations (where each table is read and written) | `conf/base/catalog.yml` |
| A tiny committed input slice + the regression test that runs on it | `tests/fixtures/data/`, `tests/integration/` |
| Methodology reference (PDF) | [ALTR Model User Guide](altr_documentation.pdf) |
| This site | `docs/handover/`, built with `mkdocs` |

!!! warning "Where the PDF names tooling this package does not have"
    The PDF documents the *methodology*, and was written against the internal
    setup: it refers in places to a Docker Compose configuration and to a
    `notebooks/run_kedro_batch.py` batch runner, neither of which ships here.
    The equivalents in this package are `scripts/prepare_inputs.py` to stage
    the delivered data and `kedro run` to run the model — both exactly as the
    [quickstart](quickstart.md) gives them.

The eight stages, in the order they run:

1. `inputs_processing` — filter and interpolate scenarios, assets and ownership
2. `inputs_postproc` — post-process those inputs for the trajectory stages
3. `create_baseline_and_target_trajectories` — company-level baseline/target paths
4. `create_late_sudden_trajectories` — impose the late & sudden shock on the paths
5. `distribute_impacts_to_asset_level` — stagger company impacts down onto assets
6. `earnings_model` — prices, carbon costs, capex/opex and FCFF per asset
7. `valuation_model` — DCF and NPV per asset, technology and company
8. `reporting` — reporting views, plots and export tables

Stages 1–7 carry the `altrisk` tag and produce the numbers; stage 8 carries the
`reporting` tag and turns those numbers into tables and charts.

## Where to start

* **[Quickstart](quickstart.md)** — clean machine to completed run. Follow it
  verbatim; it is the supported path.
* **[User guide](user_guide.md)** — one worked example end to end: choose a
  scenario pair, set three parameters, run, and read the two headline output
  tables.
* **[Scenario catalog](scenario_catalog.md)** — candidate baseline/target
  scenario pairs to copy into `conf/base/parameters.yml`.
* **[Troubleshooting](troubleshooting.md)** — the failure modes you are most
  likely to hit, with the exact error text.

!!! note "The PDF and this site"
    [ALTR Model User Guide](altr_documentation.pdf) is the methodology
    reference: what each stage does conceptually, the input data dictionaries,
    and the modelling notes (scenario viability, geography matching, asset
    retirement, synthetic assets) in its *Additional notes* section. Where the
    PDF and this site disagree on **mechanics** — file layout, pipeline names,
    commands — this site describes the package you actually have, and wins.
