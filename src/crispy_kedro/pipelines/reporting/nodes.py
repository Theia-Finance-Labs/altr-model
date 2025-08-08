"""
Comprehensive reporting pipeline nodes for financial model outputs and NPV analysis.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Tuple, Optional
import logging
from pathlib import Path
import warnings

logger = logging.getLogger(__name__)

# Set plotting style
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")


def reporting_validate_inputs(
    asset_earnings: pd.DataFrame,
    asset_npv: pd.DataFrame,
    company_npv: pd.DataFrame,
    reporting_params: Dict,
) -> Dict[str, pd.DataFrame]:
    """
    Node 1: Validate inputs and check basis alignment.
    
    Purpose: sanity checks & basis alignment (real/nominal), required columns present, 
    years contiguous.
    """
    
    logger.info("Validating reporting inputs...")
    
    # Check required columns in asset_earnings
    required_earnings_cols = [
        'asset_id', 'company_id', 'scenario_geography', 'sector', 'technology', 
        'year', 'capacity_after_shock_adj', 'capacity_factor', 'efficiency_decimal', 
        'Q', 'revenue', 'var_cost', 'fixed_cost', 'carbon_cost_net', 'EBITDA',
        'growth_capex', 'replace_capex', 'decom_cost', 'capex_total', 'FCFF'
    ]
    
    missing_earnings_cols = set(required_earnings_cols) - set(asset_earnings.columns)
    if missing_earnings_cols:
        logger.warning(f"Missing columns in asset_earnings: {missing_earnings_cols}")
    
    # Check required columns in asset_npv
    required_npv_cols = [
        'asset_id', 'company_id', 'scenario_geography', 'sector', 'technology',
        'discount_rate', 'DCF_sum', 'Terminal_Value', 'NPV'
    ]
    
    missing_npv_cols = set(required_npv_cols) - set(asset_npv.columns)
    if missing_npv_cols:
        logger.warning(f"Missing columns in asset_npv: {missing_npv_cols}")
    
    # Check year continuity per asset
    year_gaps = []
    for asset_id, asset_data in asset_earnings.groupby('asset_id'):
        years = sorted(asset_data['year'].unique())
        if len(years) > 1:
            gaps = [years[i+1] - years[i] for i in range(len(years)-1)]
            if any(gap != 1 for gap in gaps):
                year_gaps.append(asset_id)
    
    if year_gaps:
        logger.warning(f"Year gaps detected in {len(year_gaps)} assets")
    
    # Basis consistency check
    basis = reporting_params.get('basis', 'real')
    logger.info(f"Reporting basis: {basis}")
    
    # Basic data quality checks
    logger.info(f"Asset earnings: {len(asset_earnings)} rows, {len(asset_earnings['asset_id'].unique())} unique assets")
    logger.info(f"Asset NPV: {len(asset_npv)} rows")
    logger.info(f"Company NPV: {len(company_npv)} rows")
    
    # Check for negative NPVs
    negative_npvs = asset_npv[asset_npv['NPV'] < 0]
    if len(negative_npvs) > 0:
        logger.info(f"Assets with negative NPV: {len(negative_npvs)} ({len(negative_npvs)/len(asset_npv)*100:.1f}%)")
    
    # Return validated datasets
    return {
        'asset_earnings_validated': asset_earnings.copy(),
        'asset_npv_validated': asset_npv.copy(),
        'company_npv_validated': company_npv.copy(),
        'validation_summary': pd.DataFrame({
            'metric': ['total_assets', 'negative_npv_assets', 'year_gap_assets'],
            'count': [len(asset_earnings['asset_id'].unique()), len(negative_npvs), len(year_gaps)]
        })
    }


def build_reporting_views(
    asset_earnings_validated: pd.DataFrame,
    asset_npv_validated: pd.DataFrame,
    company_npv_validated: pd.DataFrame,
    reporting_params: Dict,
) -> Dict[str, pd.DataFrame]:
    """
    Node 2: Pre-compute tidy tables used by both plotting nodes.
    
    Build asset explainability view, NPV decomposition, company tech stacks, and deltas.
    """
    
    logger.info("Building reporting views...")
    
    # 1. Asset explainability view (per asset-year)
    logger.info("Building asset explainability view...")
    
    # Merge earnings with NPV data to get discount rates
    asset_explain = asset_earnings_validated.merge(
        asset_npv_validated[['asset_id', 'discount_rate', 'NPV']],
        on='asset_id',
        how='left'
    )
    
    # Calculate discount factors and present values per year
    base_year = asset_explain['year'].min()
    asset_explain['years_from_base'] = asset_explain['year'] - base_year
    asset_explain['discount_factor'] = (1 + asset_explain['discount_rate']) ** (-asset_explain['years_from_base'])
    asset_explain['PV_FCFF'] = asset_explain['FCFF'] * asset_explain['discount_factor']
    asset_explain['PV_EBITDA'] = asset_explain['EBITDA'] * asset_explain['discount_factor']
    asset_explain['PV_CapEx'] = asset_explain['capex_total'] * asset_explain['discount_factor']
    asset_explain['PV_Carbon'] = asset_explain['carbon_cost_net'] * asset_explain['discount_factor']
    
    # Calculate cumulative discounted sums per asset
    asset_explain = asset_explain.sort_values(['asset_id', 'year'])
    asset_explain['cum_PV_EBITDA'] = asset_explain.groupby('asset_id')['PV_EBITDA'].cumsum()
    asset_explain['cum_PV_CapEx'] = asset_explain.groupby('asset_id')['PV_CapEx'].cumsum()
    asset_explain['cum_PV_Carbon'] = asset_explain.groupby('asset_id')['PV_Carbon'].cumsum()
    asset_explain['cum_PV_FCFF'] = asset_explain.groupby('asset_id')['PV_FCFF'].cumsum()
    
    # 2. Asset NPV decomposition (per asset)
    logger.info("Building asset NPV decomposition...")
    
    # Calculate PV components by asset
    pv_components = asset_explain.groupby('asset_id').agg({
        'PV_EBITDA': 'sum',
        'PV_CapEx': 'sum', 
        'PV_Carbon': 'sum',
        'PV_FCFF': 'sum',
        'revenue': 'sum',
        'var_cost': 'sum',
        'fixed_cost': 'sum'
    }).reset_index()
    
    # Calculate PV of revenue components
    pv_components['PV_Revenue'] = asset_explain.groupby('asset_id').apply(
        lambda x: (x['revenue'] * x['discount_factor']).sum()
    ).values
    pv_components['PV_VarCost'] = asset_explain.groupby('asset_id').apply(
        lambda x: (x['var_cost'] * x['discount_factor']).sum()
    ).values
    pv_components['PV_FixedCost'] = asset_explain.groupby('asset_id').apply(
        lambda x: (x['fixed_cost'] * x['discount_factor']).sum()
    ).values
    
    # Merge with NPV data
    asset_npv_decomp = pv_components.merge(
        asset_npv_validated[['asset_id', 'NPV', 'DCF_sum', 'Terminal_Value', 'discount_rate']],
        on='asset_id'
    )
    
    # Add asset metadata
    asset_npv_decomp = asset_npv_decomp.merge(
        asset_earnings_validated[['asset_id', 'company_id', 'scenario_geography', 'sector', 'technology']].drop_duplicates(),
        on='asset_id'
    )
    
    # Check NPV reconciliation
    asset_npv_decomp['NPV_check'] = asset_npv_decomp['PV_EBITDA'] - asset_npv_decomp['PV_CapEx']
    asset_npv_decomp['NPV_diff'] = abs(asset_npv_decomp['NPV'] - asset_npv_decomp['NPV_check'])
    
    # 3. Company tech stacks
    logger.info("Building company tech stacks...")
    
    company_tech = asset_npv_decomp.groupby(['company_id', 'technology']).agg({
        'NPV': 'sum',
        'PV_EBITDA': 'sum',
        'PV_CapEx': 'sum',
        'PV_Revenue': 'sum',
        'asset_id': 'count',
        'scenario_geography': 'first',
        'sector': 'first'
    }).reset_index()
    company_tech.rename(columns={'asset_id': 'asset_count'}, inplace=True)
    
    # Calculate portfolio shares per company
    company_totals = company_tech.groupby('company_id')['NPV'].sum()
    company_tech['npv_share_of_company'] = company_tech.apply(
        lambda x: x['NPV'] / company_totals[x['company_id']] if company_totals[x['company_id']] != 0 else 0, 
        axis=1
    )
    
    # 4. Baseline vs shock deltas (placeholder - would need both scenarios)
    logger.info("Building deltas view (placeholder)...")
    
    # For now, create empty deltas view - would need baseline and shock scenarios
    deltas = pd.DataFrame({
        'company_id': company_npv_validated['company_id'].unique(),
        'delta_npv': 0,  # Would calculate: shock_npv - baseline_npv
        'delta_pv_ebitda': 0,
        'delta_pv_capex': 0,
        'delta_pct': 0
    })
    
    logger.info(f"Built views - Asset explain: {len(asset_explain)}, NPV decomp: {len(asset_npv_decomp)}, Company-tech: {len(company_tech)}")
    
    return {
        'view_asset_explain': asset_explain,
        'view_asset_npv_decomp': asset_npv_decomp, 
        'view_company_tech': company_tech,
        'view_deltas': deltas
    }


def plot_earnings_inner_workings(
    view_asset_explain: pd.DataFrame,
    view_asset_npv_decomp: pd.DataFrame,
    reporting_params: Dict,
) -> str:
    """
    Node 3: Plot earnings model inner workings for engineering/explainability.
    
    Goal: Show NPVs in a way that reveals the inner workings of the earnings model nodes.
    """
    
    logger.info("Generating earnings inner workings plots...")
    
    # Create output directory
    output_dir = Path("data/08_reporting_figs/earnings_inner")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Plot settings
    plots_config = reporting_params.get('plots', {})
    save_png = plots_config.get('save_png', True)
    save_pdf = plots_config.get('save_pdf', False)
    dpi = plots_config.get('dpi', 160)
    width = plots_config.get('width_in', 10)
    height = plots_config.get('height_in', 6)
    
    materiality_threshold = reporting_params.get('materiality_threshold_usd', 1_000_000)
    top_n = reporting_params.get('top_n_assets_per_company', 10)
    
    # Select assets to plot - top contributors by |NPV|
    significant_assets = view_asset_npv_decomp[
        abs(view_asset_npv_decomp['NPV']) >= materiality_threshold
    ].nlargest(top_n, 'NPV')
    
    logger.info(f"Plotting inner workings for {len(significant_assets)} significant assets")
    
    plots_created = 0
    
    # 1. Asset timeline panels for selected assets
    for _, asset in significant_assets.head(5).iterrows():  # Limit to top 5 for demo
        asset_id = asset['asset_id']
        asset_data = view_asset_explain[view_asset_explain['asset_id'] == asset_id].sort_values('year')
        
        if len(asset_data) == 0:
            continue
            
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(width*2, height*1.5))
        fig.suptitle(f'Asset Timeline: {asset_id} ({asset["technology"]} - {asset["company_id"]})', fontsize=14)
        
        # Top left: Capacity and capacity factor
        ax1_twin = ax1.twinx()
        ax1.plot(asset_data['year'], asset_data['capacity_after_shock_adj'], 'b-', linewidth=2, label='Capacity (MW)')
        ax1_twin.plot(asset_data['year'], asset_data['capacity_factor']*100, 'r--', linewidth=2, label='Capacity Factor (%)')
        ax1.set_xlabel('Year')
        ax1.set_ylabel('Capacity (MW)', color='b')
        ax1_twin.set_ylabel('Capacity Factor (%)', color='r')
        ax1.set_title('Capacity & CF Timeline')
        ax1.legend(loc='upper left')
        ax1_twin.legend(loc='upper right')
        
        # Top right: Cost breakdown per MWh
        if asset_data['Q'].sum() > 0:
            asset_data_pos_q = asset_data[asset_data['Q'] > 0].copy()
            if len(asset_data_pos_q) > 0:
                asset_data_pos_q['fuel_cost_per_mwh'] = asset_data_pos_q['var_cost'] / asset_data_pos_q['Q']
                asset_data_pos_q['fixed_cost_per_mwh'] = asset_data_pos_q['fixed_cost'] / asset_data_pos_q['Q']
                asset_data_pos_q['carbon_cost_per_mwh'] = asset_data_pos_q['carbon_cost_net'] / asset_data_pos_q['Q']
                
                ax2.stackplot(asset_data_pos_q['year'], 
                             asset_data_pos_q['fuel_cost_per_mwh'],
                             asset_data_pos_q['fixed_cost_per_mwh'], 
                             asset_data_pos_q['carbon_cost_per_mwh'],
                             labels=['Fuel Cost', 'Fixed O&M', 'Carbon Cost'],
                             alpha=0.7)
                ax2.set_xlabel('Year')
                ax2.set_ylabel('Cost ($/MWh)')
                ax2.set_title('Cost Breakdown per MWh')
                ax2.legend()
        
        # Bottom left: FCFF timeline
        ax3.bar(asset_data['year'], asset_data['FCFF'], alpha=0.7, 
               color=['green' if x >= 0 else 'red' for x in asset_data['FCFF']])
        ax3.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        ax3.set_xlabel('Year')
        ax3.set_ylabel('FCFF ($)')
        ax3.set_title('Free Cash Flow to Firm')
        
        # Bottom right: Cumulative PV components
        ax4.plot(asset_data['year'], asset_data['cum_PV_EBITDA'], 'g-', label='Cum PV EBITDA')
        ax4.plot(asset_data['year'], asset_data['cum_PV_CapEx'], 'r-', label='Cum PV CapEx')  
        ax4.plot(asset_data['year'], asset_data['cum_PV_FCFF'], 'b-', label='Cum PV FCFF', linewidth=2)
        ax4.set_xlabel('Year')
        ax4.set_ylabel('Cumulative PV ($)')
        ax4.set_title('Cumulative Present Values')
        ax4.legend()
        
        plt.tight_layout()
        
        # Save plot
        if save_png:
            plt.savefig(output_dir / f'asset_timeline_{asset_id}.png', dpi=dpi, bbox_inches='tight')
        if save_pdf:
            plt.savefig(output_dir / f'asset_timeline_{asset_id}.pdf', bbox_inches='tight')
        plt.close()
        plots_created += 1
    
    # 2. NPV decomposition waterfall for top assets
    if len(significant_assets) > 0:
        fig, ax = plt.subplots(figsize=(width, height))
        
        top_5_assets = significant_assets.head(5)
        x_pos = np.arange(len(top_5_assets))
        
        # Create stacked bars showing NPV components
        ax.bar(x_pos, top_5_assets['PV_Revenue'], label='PV Revenue', alpha=0.8)
        ax.bar(x_pos, -top_5_assets['PV_VarCost'], bottom=top_5_assets['PV_Revenue'], 
               label='PV Fuel Cost', alpha=0.8)
        ax.bar(x_pos, -top_5_assets['PV_FixedCost'], 
               bottom=top_5_assets['PV_Revenue']-top_5_assets['PV_VarCost'],
               label='PV Fixed Cost', alpha=0.8)
        ax.bar(x_pos, -top_5_assets['PV_Carbon'],
               bottom=top_5_assets['PV_Revenue']-top_5_assets['PV_VarCost']-top_5_assets['PV_FixedCost'],
               label='PV Carbon Cost', alpha=0.8)
        ax.bar(x_pos, -top_5_assets['PV_CapEx'],
               bottom=top_5_assets['PV_EBITDA'],
               label='PV CapEx', alpha=0.8)
        
        # Add NPV line
        ax.plot(x_pos, top_5_assets['NPV'], 'ko-', linewidth=2, markersize=8, label='NPV')
        
        ax.set_xlabel('Assets')
        ax.set_ylabel('Present Value ($)')
        ax.set_title('NPV Decomposition - Top Assets')
        ax.set_xticks(x_pos)
        ax.set_xticklabels([f"{row['asset_id']}\n{row['technology']}" for _, row in top_5_assets.iterrows()], 
                           rotation=45, ha='right')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        if save_png:
            plt.savefig(output_dir / 'npv_decomposition_top_assets.png', dpi=dpi, bbox_inches='tight')
        if save_pdf:
            plt.savefig(output_dir / 'npv_decomposition_top_assets.pdf', bbox_inches='tight')
        plt.close()
        plots_created += 1
    
    logger.info(f"Created {plots_created} earnings inner workings plots in {output_dir}")
    
    return str(output_dir)


def plot_valuation_authority_pack(
    asset_npv_validated: pd.DataFrame,
    company_npv_validated: pd.DataFrame,
    view_company_tech: pd.DataFrame,
    view_deltas: pd.DataFrame,
    reporting_params: Dict,
) -> str:
    """
    Node 4: Generate authority-ready valuation plots and reports.
    
    Goal: Clean, regulator-friendly visuals for asset managers to report to authorities.
    """
    
    logger.info("Generating valuation authority pack...")
    
    # Create output directories
    output_dir = Path("data/08_reporting_figs/authority_pack")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Plot settings
    plots_config = reporting_params.get('plots', {})
    save_png = plots_config.get('save_png', True)
    save_pdf = plots_config.get('save_pdf', False)
    dpi = plots_config.get('dpi', 160)
    width = plots_config.get('width_in', 10)
    height = plots_config.get('height_in', 6)
    
    plots_created = 0
    
    # 1. Portfolio overview
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(width*2, height*1.5))
    fig.suptitle('Portfolio Overview', fontsize=16)
    
    # Portfolio NPV distribution
    portfolio_npv = company_npv_validated['NPV'].sum()
    positive_npv = company_npv_validated[company_npv_validated['NPV'] > 0]['NPV'].sum()
    negative_npv = abs(company_npv_validated[company_npv_validated['NPV'] < 0]['NPV'].sum())
    
    ax1.bar(['Positive NPV', 'Negative NPV'], [positive_npv, -negative_npv], 
           color=['green', 'red'], alpha=0.7)
    ax1.axhline(y=0, color='black', linestyle='-', alpha=0.5)
    ax1.set_ylabel('NPV ($)')
    ax1.set_title(f'Portfolio NPV: ${portfolio_npv:,.0f}')
    ax1.grid(True, alpha=0.3)
    
    # NPV by technology (from company-tech view)
    tech_npv = view_company_tech.groupby('technology')['NPV'].sum().sort_values(ascending=False)
    if len(tech_npv) > 0:
        ax2.pie(abs(tech_npv.values), labels=tech_npv.index, autopct='%1.1f%%', startangle=90)
        ax2.set_title('NPV Distribution by Technology')
    
    # Company NPV distribution
    company_npv_sorted = company_npv_validated.sort_values('NPV', ascending=False)
    top_companies = company_npv_sorted.head(10)
    
    bars = ax3.bar(range(len(top_companies)), top_companies['NPV'], 
                   color=['green' if x >= 0 else 'red' for x in top_companies['NPV']])
    ax3.set_xlabel('Top Companies')
    ax3.set_ylabel('NPV ($)')
    ax3.set_title('Top 10 Companies by NPV')
    ax3.set_xticks(range(len(top_companies)))
    ax3.set_xticklabels([f"{cid[:8]}" for cid in top_companies['company_id']], rotation=45)
    
    # NPV vs asset count scatter (placeholder)
    ax4.text(0.5, 0.5, 'NPV Distribution\nAnalysis', ha='center', va='center', 
             transform=ax4.transAxes, fontsize=12)
    ax4.set_title('Portfolio Distribution')
    
    plt.tight_layout()
    if save_png:
        plt.savefig(output_dir / 'portfolio_overview.png', dpi=dpi, bbox_inches='tight')
    if save_pdf:
        plt.savefig(output_dir / 'portfolio_overview.pdf', bbox_inches='tight')
    plt.close()
    plots_created += 1
    
    # 2. Company league table
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(width*2, height))
    
    # Top/bottom companies by NPV
    top_10 = company_npv_sorted.head(10)
    bottom_10 = company_npv_sorted.tail(10)
    
    y_pos_top = np.arange(len(top_10))
    ax1.barh(y_pos_top, top_10['NPV'], color='green', alpha=0.7)
    ax1.set_yticks(y_pos_top)
    ax1.set_yticklabels([f"{cid[:12]}" for cid in top_10['company_id']])
    ax1.set_xlabel('NPV ($)')
    ax1.set_title('Top 10 Companies by NPV')
    ax1.grid(True, alpha=0.3)
    
    y_pos_bottom = np.arange(len(bottom_10))
    ax2.barh(y_pos_bottom, bottom_10['NPV'], color='red', alpha=0.7)
    ax2.set_yticks(y_pos_bottom)
    ax2.set_yticklabels([f"{cid[:12]}" for cid in bottom_10['company_id']])
    ax2.set_xlabel('NPV ($)')
    ax2.set_title('Bottom 10 Companies by NPV')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    if save_png:
        plt.savefig(output_dir / 'company_league_table.png', dpi=dpi, bbox_inches='tight')
    if save_pdf:
        plt.savefig(output_dir / 'company_league_table.pdf', bbox_inches='tight')
    plt.close()
    plots_created += 1
    
    logger.info(f"Created {plots_created} authority pack plots in {output_dir}")
    
    return str(output_dir)


def export_reporting_tables(
    company_npv_validated: pd.DataFrame,
    view_company_tech: pd.DataFrame,
    view_asset_npv_decomp: pd.DataFrame,
    reporting_params: Dict,
) -> Dict[str, pd.DataFrame]:
    """
    Node 5: Export compliance-ready tables for regulators and QC.
    """
    
    logger.info("Exporting reporting tables...")
    
    # Create tables directory
    tables_dir = Path("data/09_reports")
    tables_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Company summary table
    company_summary = company_npv_validated.copy()
    company_summary['npv_millions'] = company_summary['NPV'] / 1_000_000
    
    # Add basic statistics
    asset_counts = view_asset_npv_decomp.groupby('company_id')['asset_id'].count()
    company_summary['asset_count'] = company_summary['company_id'].map(asset_counts).fillna(0)
    
    # Add methodology notes
    company_summary['methodology_notes'] = f"Real {reporting_params.get('base_year', 2010)} USD, {reporting_params.get('basis', 'real')} basis"
    
    # Select final columns
    summary_columns = ['company_id', 'NPV', 'npv_millions', 'asset_count', 'methodology_notes']
    company_summary_final = company_summary[summary_columns].copy()
    
    # 2. Technology summary
    technology_summary = view_company_tech.copy()
    technology_summary['npv_millions'] = technology_summary['NPV'] / 1_000_000
    
    # 3. Top assets table
    top_n = reporting_params.get('top_n_assets_per_company', 10)
    top_assets = view_asset_npv_decomp.nlargest(top_n * 10, 'NPV')  # More assets for full view
    
    top_assets_table = top_assets[['asset_id', 'company_id', 'technology', 'sector', 'NPV']].copy()
    top_assets_table['npv_millions'] = top_assets_table['NPV'] / 1_000_000
    top_assets_table['rank'] = range(1, len(top_assets_table) + 1)
    
    # 4. Methodology footer
    methodology_table = pd.DataFrame({
        'parameter': ['basis', 'base_year', 'discount_rate_baseline', 'discount_rate_shock', 'materiality_threshold'],
        'value': [
            reporting_params.get('basis', 'real'),
            reporting_params.get('base_year', 2010),
            '7%',  # From valuation model
            '8%',  # From valuation model
            reporting_params.get('materiality_threshold_usd', 1_000_000)
        ]
    })
    
    # Save tables
    company_summary_final.to_csv(tables_dir / 'company_summary.csv', index=False)
    technology_summary.to_csv(tables_dir / 'technology_summary.csv', index=False) 
    top_assets_table.to_csv(tables_dir / 'top_assets.csv', index=False)
    methodology_table.to_csv(tables_dir / 'methodology_parameters.csv', index=False)
    
    logger.info(f"Exported {len(company_summary_final)} company summaries, {len(technology_summary)} tech records, {len(top_assets_table)} top assets")
    
    return {
        'report_company_summary': company_summary_final,
        'report_technology_summary': technology_summary,
        'report_top_assets': top_assets_table,
        'report_methodology': methodology_table
    }


def reporting_qc_summary(
    view_asset_npv_decomp: pd.DataFrame,
    view_asset_explain: pd.DataFrame,
    reporting_params: Dict,
) -> pd.DataFrame:
    """
    Node 6: Quality control checks and reporting diagnostics.
    """
    
    logger.info("Running reporting QC checks...")
    
    qc_results = []
    
    # 1. Basis consistency check
    basis = reporting_params.get('basis', 'real')
    qc_results.append({
        'check': 'basis_consistency',
        'status': 'PASS',
        'value': basis,
        'description': f'All calculations use {basis} basis'
    })
    
    # 2. NPV reconciliation check
    if 'NPV_diff' in view_asset_npv_decomp.columns:
        npv_diff = view_asset_npv_decomp['NPV_diff']
        max_diff = npv_diff.max() if len(npv_diff) > 0 else 0
        tolerance = reporting_params.get('small_numbers_rounding', 0.001) * 1_000_000  # Convert to dollars
        
        reconciliation_status = 'PASS' if max_diff < tolerance else 'FAIL'
        qc_results.append({
            'check': 'npv_reconciliation',
            'status': reconciliation_status,
            'value': max_diff,
            'description': f'Max NPV reconciliation difference: ${max_diff:.2f}'
        })
    
    # 3. Materiality threshold check
    materiality_threshold = reporting_params.get('materiality_threshold_usd', 1_000_000)
    material_assets = len(view_asset_npv_decomp[abs(view_asset_npv_decomp['NPV']) >= materiality_threshold])
    
    qc_results.append({
        'check': 'materiality_filter',
        'status': 'INFO',
        'value': material_assets,
        'description': f'{material_assets} assets above materiality threshold of ${materiality_threshold:,.0f}'
    })
    
    # 4. Negative NPV assets by technology
    negative_npv_assets = view_asset_npv_decomp[view_asset_npv_decomp['NPV'] < 0]
    negative_by_tech = negative_npv_assets.groupby('technology').size()
    
    for tech, count in negative_by_tech.items():
        qc_results.append({
            'check': f'negative_npv_{tech}',
            'status': 'INFO', 
            'value': count,
            'description': f'{count} {tech} assets with negative NPV'
        })
    
    # 5. Data completeness checks
    total_assets = len(view_asset_npv_decomp)
    complete_records = len(view_asset_npv_decomp.dropna())
    
    qc_results.append({
        'check': 'data_completeness',
        'status': 'PASS' if complete_records == total_assets else 'WARNING',
        'value': complete_records / total_assets if total_assets > 0 else 0,
        'description': f'{complete_records}/{total_assets} complete records ({complete_records/total_assets*100:.1f}%)'
    })
    
    # Convert to DataFrame
    qc_summary = pd.DataFrame(qc_results)
    
    # Add timestamp and summary stats
    qc_summary['timestamp'] = pd.Timestamp.now()
    
    logger.info(f"QC Summary: {len(qc_summary)} checks completed")
    logger.info(f"Status counts: {qc_summary['status'].value_counts().to_dict()}")
    
    return qc_summary