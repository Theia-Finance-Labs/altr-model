#!/usr/bin/env python3
import pandas as pd
import os

BLOCKLIST_FILE = "data/05_model_input/assets_filtered_by_pipeline.csv"
CLEAN_FILE = "data/05_model_input/downloaded_assets_clean.csv"
OUTPUT_FILE = "workspace/results_V20/AIM-CGE 2.2__clean_asset_granularity_with_staggered_shock_and_retirement/asset_npv.csv"

# Load clean data
print("Loading clean data...")
assets_clean = pd.read_csv(CLEAN_FILE)
clean_ids = set(assets_clean['asset_id'])

# Load existing blocklist if it exists (to add back for comparison)
if os.path.exists(BLOCKLIST_FILE):
    print(f"Loading existing blocklist from {BLOCKLIST_FILE}...")
    blocklist_df = pd.read_csv(BLOCKLIST_FILE)
    blocked_ids = set(blocklist_df['asset_id'])
    print(f"  Found {len(blocked_ids)} already blocked assets.")
    
    # Add back to the pool of "Potential Assets"
    potential_ids = clean_ids.union(blocked_ids)
    print(f"  Total potential assets (Clean + Blocked): {len(potential_ids)}")
else:
    potential_ids = clean_ids
    print(f"  Total potential assets: {len(potential_ids)}")

# Load model output
print("Loading model output...")
if not os.path.exists(OUTPUT_FILE):
    print(f"Error: Model output file not found at {OUTPUT_FILE}")
    exit(1)
    
asset_npv = pd.read_csv(OUTPUT_FILE)

# Real assets only in output (exclude synthetic)
asset_npv_real = asset_npv[~asset_npv['asset_id'].str.startswith('NEW_')]
output_ids = set(asset_npv_real['asset_id'])

# Identify missing assets (Potential - Output)
missing_ids = potential_ids - output_ids
print(f"Found {len(missing_ids)} assets that should be filtered.")

# Save to CSV
ids_to_filter = pd.DataFrame({'asset_id': list(missing_ids)})
ids_to_filter.to_csv(BLOCKLIST_FILE, index=False)
print(f"Saved IDs to {BLOCKLIST_FILE}")
