# Scenario catalog

This page preserves, verbatim, the commented-out scenario pairs that used to sit
inside `conf/base/parameters_inputs_processing.yml`. None of it is active
configuration: it is a lookup list you copy values *from* into
`conf/base/parameters.yml`.

## Known scenario pairs

Candidate `baseline_scenario` / `target_scenario` pairs, one pair per IAM
provider, as previously commented in the parameters file. Copy a pair into
`conf/base/parameters.yml`; both members must exist in the `scenario` column of
`data/05_model_input/downloaded_scenarios.csv`.

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
# Note: filter_scenarios prepends "AR6_<provider>_" automatically
```
