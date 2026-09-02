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
# be restored during staging — scripts/stage_marts_inputs.py does it.
```

The AIM/CGE pair at the bottom is the one shipped as the default. The committed
fixture slice uses a WITCH pair instead
(`conf/fixture/parameters_prepare_scenario_asset_and_company_inputs.yml`),
because that is what `tests/fixtures/data/scenarios.csv` contains.
