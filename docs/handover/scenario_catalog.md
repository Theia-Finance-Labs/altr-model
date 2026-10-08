# Scenario catalog

This page preserves, verbatim, the commented-out scenario pairs that used to sit
inside the input-preparation parameters file. None of it is active
configuration: it is a lookup list you copy values *from* into
`conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`.

## Known scenario pairs

Candidate `baseline_scenario` / `target_scenario` pairs, one pair per IAM
provider, as previously commented in the parameters file. Copy a pair into
`conf/base/parameters_prepare_scenario_asset_and_company_inputs.yml`; both
members must exist in the `scenario` column of
`data/05_model_input/scenarios.csv`.

!!! warning "Same provider: the model does not enforce it - you do"
    Pick both members of a pair from one provider block. The model asserts only
    that the two scenarios **start in the same year**; it never checks the
    provider. A cross-provider pair that shares a start year runs to
    completion, silently intersecting the two providers' geographies and
    technologies and logging one warning - a completed run on a shrunken
    universe, not an error. Same-provider is a rule you enforce.

The pair verified against the **2026-09-01 extract** - the best-covered pair in
it (9,360 rows each, 26 years, 20 geographies, 18 technologies), and the one
both the committed fixture and the internal full-universe `conf/full`
environment run:

```yaml
baseline_scenario: "AR6_WITCH 5.0_EN_NoPolicy"
target_scenario: "AR6_WITCH 5.0_EN_NPi2020_500"
```

Older candidates, from earlier extract vintages:

```yaml
# baseline_scenario: "AR6_COFFEE 1.1_EN_NPi2020_1000_COV"
# target_scenario: "AR6_COFFEE 1.1_EN_INDCi2030_1000_COV_NDCp"
# baseline_scenario: "AR6_MESSAGEix-GLOBIOM_GEI 1.0_SSP2_int_mc_50"
# target_scenario: "AR6_MESSAGEix-GLOBIOM_GEI 1.0_SSP2_openres_lc_50"
# baseline_scenario: "AR6_REMIND-MAgPIE 2.1-4.3_DeepElec_SSP2_Base"
# target_scenario: "AR6_REMIND-MAgPIE 2.1-4.3_DeepElec_SSP2_ HighRE_Budg900"
# baseline_scenario: "AR6_IMACLIM 1.1_ADVANCE_NoPolicy_WP6"
# target_scenario: "AR6_IMACLIM 1.1_ADVANCE_INDC_WP6"
# baseline_scenario: "AR6_AIM/CGE 2.2_EN_NPi2020_1200f"
# target_scenario: "AR6_AIM/CGE 2.2_EN_NPi2020_900f"
# Note (corrected 2026-09-02): filter_scenarios does NOT prepend
# "AR6_<provider>_" — it asserts the configured name appears VERBATIM in the
# `scenario` column and prefixes nothing. Copy the full prefixed names exactly
# as listed above. If your scenarios extract ships bare names, the prefix must
# be restored upstream — the internal staging script that does it
# (scripts/stage_marts_inputs.py) is not part of a delivered copy.
```

Scenario names change between extract vintages: the AIM/CGE pair at the bottom
is still the one shipped in `conf/base`, but it is **not in the 2026-09-01
extract** (AIM/CGE 2.2 appears there as `EN_INDCi2100` / `EN_NPi2020_500f`).
Before trusting any pair on this page, list what your extract actually carries:

```bash
uv run python -c "import pandas as pd; \
print(sorted(pd.read_csv('data/05_model_input/scenarios.csv', \
usecols=['scenario'])['scenario'].unique()))"
```
