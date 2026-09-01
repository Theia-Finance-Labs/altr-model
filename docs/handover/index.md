# ALTR Model

ALTR is an asset-level transition-risk valuation model, and it exists to answer
one question: how much company value moves when a late-and-sudden climate-policy
shock forces companies off their current-policy pathway onto a climate-aligned
one? The unit of analysis is the physical asset - a power plant with a capacity,
a technology, a country and an age - and every asset is valued twice, once along
a *baseline* pathway and once along a *late & sudden* shock pathway. The
difference between the two valuations is the transition-risk signal.

The mechanism runs bottom-up. Two IAM scenarios (one baseline, one target)
supply production pathways, prices, capacity factors and cost assumptions -
company-level baseline and target trajectories are built from them, the shock is
imposed at `shock_year` and must be completed by `alignment_year`, and the
resulting company-level capacity change is *allocated* down onto the company's
individual assets rather than applied uniformly. Each asset's physical
trajectory is then turned into money: production, revenue at the scenario power
price, fuel and carbon costs, fixed O&M, growth/replacement CapEx and
decommissioning, netting to EBITDA and free cash flow to the firm. The cash
flows are discounted (with an optional terminal value) into an NPV per asset and
rolled up to company-technology and company level.

One framing choice matters before you read any number. The comparison is
*marginal* - the baseline is a current-policy pathway that already carries its
own transition costs, not a costless "no additional headwinds" world. ALTR
therefore measures the extra loss (or, occasionally, the avoided loss) caused by
policy stricter than current policy, which puts it closer to economy-wide
current-policy stress tests than to a zero-carbon-cost counterfactual. The full
consequences for interpretation are spelled out under
[Reading the sign of `npv_change`](user_guide.md#reading-the-sign-of-npv_change) -
read that section before you present results to anyone.

Everything the model does is in this package, in code you can read and run. That
is deliberate: where the number comes from should never be a matter of trust.

## What is in this package

| Piece | Where |
| --- | --- |
| Model code, as six ordered Kedro pipeline stages | `src/altr_model/pipelines/` |
| Run configuration - scenario pair and run scope | `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml` |
| The other five per-pipeline parameter files | `conf/base/parameters_<pipeline>.yml` |
| Dataset declarations (where each table is read and written) | `conf/base/catalog.yml` |
| A tiny committed input slice + the regression test that runs on it | `tests/fixtures/data/`, `tests/integration/` |
| Methodology reference (PDF) | [ALTR Model User Guide](altr_documentation.pdf) |
| This site | `docs/handover/`, built with `mkdocs` |

!!! danger "This site supersedes the PDF wherever the two disagree"
    [`altr_documentation.pdf`](altr_documentation.pdf) is a **delivered binary
    that cannot be edited**, and parts of it describe the internal setup rather
    than the package in your hands. Where it and this site differ on
    mechanics - commands, file names, pipeline names, the clone URL - **this
    site is correct and the PDF is not**. Four places specifically:

    * It names a Docker Compose configuration and a
      `notebooks/run_kedro_batch.py` batch runner. Both exist in this
      repository, but as **maintainer tooling** left out of the sanitized
      copies `scripts/build_export.py` produces for delivery
      ([batch runs and the app](batch_runs.md) documents them and says
      exactly which pieces a copy carries). In a sanitized copy, the
      equivalents are `scripts/prepare_inputs.py` to stage the delivered
      data and `uv run kedro run` to run the model - both exactly as the
      [quickstart](quickstart.md) gives them.
    * It refers to a Poetry install and a `conf/base/parameters.yml`. This
      package installs with **uv** (`uv sync`) and has **no consolidated
      parameters file**: the namespace is split across six per-pipeline files
      ([parameters reference](parameters.md)).
    * Its worked examples carry identifiers from the full internal run. They
      illustrate the format; they are not the data you were delivered.

The six stages, in the order they run:

1. `prepare_scenario_asset_and_company_inputs` - filter and enrich scenarios,
   build the asset panel and the company projection inputs
2. `calculate_company_trajectories` - company baseline/target paths and the four
   alignment-case late & sudden transitions
3. `allocate_company_trajectories_to_assets` - allocate company impacts onto
   assets and reconcile the realised company path
4. `calculate_asset_earnings` - capacity flows, CapEx, operating earnings and
   FCFF per asset
5. `calculate_asset_and_company_npv` - DCF and NPV per asset, technology and
   company
6. `plot_transition_risk_results` - trajectory and financial figure packs

Stages 1-5 carry the `altrisk` tag and produce the numbers (29 nodes); stage 6
carries the `reporting` tag and turns those numbers into figures (3 nodes).

## Where to start

* **[Quickstart](quickstart.md)** - clean machine to completed run. Follow it
  verbatim; it is the supported path.
* **[User guide](user_guide.md)** - one worked example end to end: choose a
  scenario pair, set three parameters, run, and read the two headline output
  tables.
* **[Input data](input_data.md)** - the column-level contract for the three
  input CSVs, including the units traps.
* **[Methodology notes](methodology_notes.md)** - the five modelling
  behaviours that shape every result but belong to no single stage: scenario
  viability, geography matching, granularity, asset retirement, synthetic
  assets.
* **[Scenario catalog](scenario_catalog.md)** - candidate baseline/target
  scenario pairs to copy into
  `conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`.
* **[Troubleshooting](troubleshooting.md)** - the failure modes you are most
  likely to hit, with the exact error text.

!!! note "What the PDF is still good for"
    [ALTR Model User Guide](altr_documentation.pdf) remains a readable
    methodology narrative - what each stage does conceptually, in prose. Its
    input data dictionaries and *Additional notes* material now live on this
    site in maintained form ([input data](input_data.md),
    [methodology notes](methodology_notes.md)), corrected where the PDF has
    drifted from the code. Read the PDF for the *why*; read this site for the
    *how* and for anything the two disagree on.
