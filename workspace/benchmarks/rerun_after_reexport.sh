#!/bin/zsh
# Re-measure the decision suite on a fresh scenarios extract (e.g. after the
# fuel-price fix lands in the marts). Run from the repo root with the new
# data/05_model_input/ staged. Each arm is a full-universe run (~5 min); outputs
# under data/09_benchmarks/<label>/ (override with ALTR_BENCH_RUNS). The dcf
# block must be respecified whole when overriding any nested key.
set -euo pipefail
B=workspace/benchmarks
run() { uv run python $B/bench_run.py "$1" "$2" && uv run python $B/bench_metrics.py extract "$1"; }
DCF=$(uv run python -c "import yaml,json; print(json.dumps(yaml.safe_load(open('conf/base/parameters_calculate_asset_and_company_npv.yml'))['dcf']))")
run DEFAULT   '{}'
run TV_OFF    "$(uv run python -c "import json; d=json.loads('$DCF'); d['terminal_value']['method']='none'; print(json.dumps({'dcf': d}))")"
run SPREAD    "$(uv run python -c "import json; d=json.loads('$DCF'); d['brown_discount_spread']=0.01; print(json.dumps({'dcf': d}))")"
run LRMC      '{"price_floor": {"method": "lrmc", "discount_rate": 0.08}}'
run DISPATCH  '{"dispatch_floor": "own_variable_cost"}'
run HIRTH     '{"capture_price": {"method": "hirth2013", "wind_intercept": 1.1, "wind_slope": -1.5, "solar_intercept": 1.1, "solar_slope": -3.5, "vre_floor": 0.4, "dispatchable_cap": 2.0}}'
run DECOM50   '{"decom_cost_fraction_of_capex": null}'
for pair in "MESSAGE|AR6_MESSAGEix-GLOBIOM_1.1_EN_NoPolicy|AR6_MESSAGEix-GLOBIOM_1.1_EN_NPi2020_500" \
            "REMIND|AR6_REMIND-MAgPIE 2.1-4.2_EN_NoPolicy|AR6_REMIND-MAgPIE 2.1-4.2_SusDev_SSP2-PkBudg900" \
            "IMAGE|AR6_IMAGE 3.0_EN_NoPolicy|AR6_IMAGE 3.0_CO_2Deg2020"; do
  IFS='|' read -r label base target <<< "$pair"
  run "P_$label" "{\"baseline_scenario\": \"$base\", \"target_scenario\": \"$target\"}"
done
for arm in TV_OFF SPREAD LRMC DISPATCH HIRTH DECOM50 P_MESSAGE P_REMIND P_IMAGE; do
  echo "=== $arm vs DEFAULT ==="; uv run python $B/bench_metrics.py compare "$arm" DEFAULT
done
