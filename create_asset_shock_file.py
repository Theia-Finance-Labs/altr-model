#!/usr/bin/env python3

"""Create a minimal asset_level_staggered_shock.csv file from available data."""

import pandas as pd

def create_asset_shock_file():
    print("Creating asset_level_staggered_shock.csv from allocated_assets_to_companies.csv...")
    
    # Load the allocated assets data
    allocated_df = pd.read_csv("data/07_model_output/allocated_assets_to_companies.csv")
    
    print(f"Loaded {len(allocated_df)} rows from allocated_assets_to_companies.csv")
    print(f"Columns: {list(allocated_df.columns)}")
    
    # Create the asset shock file structure
    asset_shock = pd.DataFrame({
        'asset_id': allocated_df['asset_id'],
        'company_id': allocated_df['company_id'], 
        'scenario_geography': allocated_df['scenario_geography'],
        'sector': allocated_df['sector'],
        'technology': allocated_df['technology'],
        'year': allocated_df['year'].astype(int),
        'asset_age': allocated_df['asset_age'],
        'capacity_before_shock': allocated_df['asset_activity'],  # Use activity as capacity proxy
        'allocated_shock': 0.0,  # No shock applied initially
        'capacity_after_shock': allocated_df['asset_activity'],  # Same as before shock initially
        'is_synthetic': False,  # All real assets initially
        'late_sudden_phase': 'baseline'  # Default phase
    })
    
    print(f"Created asset shock data with {len(asset_shock)} rows")
    print(f"Columns: {list(asset_shock.columns)}")
    
    # Save to the expected location
    asset_shock.to_csv("data/08_reporting/asset_level_staggered_shock.csv", index=False)
    
    print("✅ Successfully created asset_level_staggered_shock.csv")
    print(f"File saved with {len(asset_shock)} rows")
    
    # Show sample
    print("\nSample data:")
    print(asset_shock.head(3).to_string(index=False))
    
if __name__ == "__main__":
    create_asset_shock_file()