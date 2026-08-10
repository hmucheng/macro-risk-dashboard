# -*- coding: utf-8 -*-
"""
CMRS 多因子风险评分系统
严格符合专业金融定义的四大指标计算
"""

import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
from fredapi import Fred
import warnings

warnings.filterwarnings("ignore")

NTFY_URL = "https://ntfy.sh/smcb-z5hnfa1qj2x8vmnbr8uoqlqmrq49"


def send_ntfy_alert(title, message, priority="default"):
    """Send ntfy notification"""
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
    except Exception as e:
        print(f"Warning: ntfy push failed: {e}")


def get_risk_zone(score):
    """Map risk score to risk zone"""
    if score >= 75:
        return "RED: Extreme Bubble Zone"
    elif score >= 55:
        return "YELLOW: Risk Control Warning Zone"
    elif score >= 25:
        return "BLUE: Reasonable Holding Zone"
    else:
        return "GREEN: Low Risk Buying Zone"


def fetch_shiller_cape(start_year=1990):
    """
    Fetch Shiller CAPE data from official source
    Returns: Monthly DataFrame with CAPE values
    """
    print("  [Loading Shiller CAPE data...]")
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500/master/data/data.csv"
        df = pd.read_csv(url)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df[df["Date"].dt.year >= start_year].copy()
        df = df.sort_values("Date").set_index("Date")
        
        # Find CAPE column (may have different names)
        cape_col = None
        for col in df.columns:
            if "CAPE" in col.upper() or "PE10" in col.upper():
                cape_col = col
                break
        
        if cape_col is None:
            print("    WARNING: CAPE column not found in Shiller data")
            return None
        
        return df[[cape_col]].rename(columns={cape_col: "cape"})
    
    except Exception as e:
        print(f"    ERROR: Failed to load Shiller CAPE: {e}")
        return None


def fetch_gs10(fred, start_year=1990):
    """
    Fetch 10-year Treasury yield (GS10) from FRED
    Returns: Monthly DataFrame with GS10 values
    """
    print("  [Loading GS10 (10Y Treasury) data...]")
    try:
        gs10 = fred.get_series("GS10", observation_start=f"{start_year}-01-01")
        gs10_df = pd.DataFrame({"gs10": gs10})
        gs10_df.index.name = "Date"
        return gs10_df
    except Exception as e:
        print(f"    ERROR: Failed to load GS10: {e}")
        return None


def fetch_buffett_index(fred, start_year=1990):
    """
    Calculate Buffett Indicator = Total Market Cap / Nominal GDP
    Uses Federal Reserve Z.1 stock market value
    """
    print("  [Loading Buffett Index (Market Cap/GDP)...]")
    try:
        start_str = f"{start_year}-01-01"
        
        # Get nominal GDP (quarterly, billions of dollars)
        gdp = fred.get_series("GDP", observation_start=start_str)
        
        # Get stock market value from Federal Reserve Z.1
        # BOGZ1FL893064105Q: Total equity market value (quarterly, millions)
        try:
            market_cap = fred.get_series(
                "BOGZ1FL893064105Q", observation_start=start_str
            )
            market_cap = market_cap / 1000.0  # Convert to billions
            print("    [Using BOGZ1FL893064105Q - Federal Reserve Z.1 stock value]")
        except:
            print("    WARNING: Cannot fetch market cap from FRED")
            return None
        
        # Align to quarterly frequency (GDP is quarterly)
        df = pd.DataFrame({
            "market_cap": market_cap,
            "gdp": gdp
        })
        df = df.resample("QS").first().ffill()
        df = df.dropna()
        
        # Calculate ratio (no extra coefficients)
        df["buffett_raw"] = df["market_cap"] / df["gdp"]
        
        return df[["buffett_raw"]]
    
    except Exception as e:
        print(f"    ERROR: Failed to load Buffett Index: {e}")
        return None


def fetch_margin_debt(fred, start_year=1990):
    """
    Calculate Margin Debt / GDP
    Uses Federal Reserve Z.1 broker-dealer credit data
    """
    print("  [Loading Margin Debt/GDP...]")
    try:
        start_str = f"{start_year}-01-01"
        
        # Get GDP
        gdp = fred.get_series("GDP", observation_start=start_str)
        
        # Get margin debt: BOGZ1FL663067003Q
        # Broker-Dealer Credit (quarterly, millions)
        try:
            margin_debt = fred.get_series(
                "BOGZ1FL663067003Q", observation_start=start_str
            )
            margin_debt = margin_debt / 1000.0  # Convert to billions
            print("    [Using BOGZ1FL663067003Q - Fed Z.1 Broker-Dealer Credit]")
        except:
            print("    WARNING: Cannot fetch margin debt from FRED")
            return None
        
        # Align to quarterly
        df = pd.DataFrame({
            "margin_debt": margin_debt,
            "gdp": gdp
        })
        df = df.resample("QS").first().ffill()
        df = df.dropna()
        
        # Calculate ratio
        df["margin_debt_raw"] = df["margin_debt"] / df["gdp"]
        
        return df[["margin_debt_raw"]]
    
    except Exception as e:
        print(f"    ERROR: Failed to load margin debt: {e}")
        return None


def calculate_risk_score(df_all):
    """
    Calculate CMRS (Comprehensive Market Risk Score)
    
    Methodology:
    - Calculate 10-year rolling percentile for each indicator
    - Weight: ERP(35%) + CAPE(25%) + Buffett(20%) + Margin(20%)
    - Higher score = Higher risk
    """
    latest = df_all.iloc[-1]
    window = df_all.iloc[-120:]  # 10-year rolling window
    
    # Percentile calculations
    # NOTE: Direction matters for interpretation
    
    # ERP: Higher ERP = Lower risk, so REVERSE percentile
    erp_pct = 100.0 * (1.0 - (window["erp_raw"] <= latest["erp_raw"]).mean())
    
    # CAPE: Higher CAPE = Higher risk, so NORMAL percentile
    cape_pct = 100.0 * (window["cape"] <= latest["cape"]).mean()
    
    # Buffett: Higher ratio = Higher risk, so NORMAL percentile
    buffett_pct = 100.0 * (window["buffett_raw"] <= latest["buffett_raw"]).mean()
    
    # Margin Debt: Higher margin = Higher risk, so NORMAL percentile
    margin_pct = 100.0 * (window["margin_debt_raw"] <= latest["margin_debt_raw"]).mean()
    
    # Weighted score
    cmrs_score = round(
        0.35 * erp_pct + 0.25 * cape_pct + 0.20 * buffett_pct + 0.20 * margin_pct,
        1,
    )
    
    return {
        "cmrs_score": cmrs_score,
        "erp_pct": erp_pct,
        "cape_pct": cape_pct,
        "buffett_pct": buffett_pct,
        "margin_pct": margin_pct,
        "latest": latest,
    }


def get_position_advice(cmrs_score):
    """Generate position sizing recommendations based on CMRS score"""
    if cmrs_score >= 75:
        return {
            "equity_target": "10-20%",
            "cash_target": "80-90%",
            "risk_level": "EXTREME",
            "actions": [
                "Liquidate high-beta, overvalued stocks",
                "Move 80%+ to Treasury/money market funds",
                "Maintain only core, dividend-paying holdings",
            ]
        }
    elif cmrs_score >= 55:
        return {
            "equity_target": "30-50%",
            "cash_target": "50-70%",
            "risk_level": "HIGH",
            "actions": [
                "Lock in recent bull market gains",
                "Pause equity contributions",
                "Redirect new capital to short-duration bonds",
            ]
        }
    elif cmrs_score >= 25:
        return {
            "equity_target": "50-70%",
            "cash_target": "30-50%",
            "risk_level": "MODERATE",
            "actions": [
                "Maintain normal strategic allocation",
                "Continue regular dollar-cost averaging",
                "Rebalance quarterly",
            ]
        }
    else:
        return {
            "equity_target": "80-100%",
            "cash_target": "0-20%",
            "risk_level": "LOW",
            "actions": [
                "Market at historic lows - opportune time to accumulate",
                "Increase equity allocations systematically",
                "Convert cash reserves to equity ETFs",
            ]
        }


def run_pipeline():
    """Main execution pipeline"""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise ValueError("ERROR: FRED_API_KEY environment variable not set!")

    fred = Fred(api_key=api_key)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    print("\n" + "=" * 80)
    print("CMRS RISK ASSESSMENT PIPELINE")
    print("=" * 80)

    try:
        # Step 1: Fetch CAPE and ERP
        print("\n[1/4] Shiller CAPE & Equity Risk Premium")
        print("-" * 80)
        
        cape_df = fetch_shiller_cape(start_year=1990)
        gs10_df = fetch_gs10(fred, start_year=1990)
        
        if cape_df is None or gs10_df is None:
            raise ValueError("ERROR: Cannot fetch CAPE or GS10")
        
        # Align to monthly
        df_cape_erp = pd.concat([cape_df, gs10_df], axis=1).resample("MS").first().ffill()
        
        # Calculate ERP: (E/P) - Rf ≈ (1/CAPE) - (GS10/100)
        df_cape_erp["erp_raw"] = (1.0 / df_cape_erp["cape"]) - (df_cape_erp["gs10"] / 100.0)
        
        latest_cape = df_cape_erp["cape"].iloc[-1]
        latest_gs10 = df_cape_erp["gs10"].iloc[-1]
        latest_erp = df_cape_erp["erp_raw"].iloc[-1]
        
        print(f"  Latest CAPE: {latest_cape:.2f}")
        print(f"  Latest GS10: {latest_gs10:.2f}%")
        print(f"  Latest ERP: {latest_erp:.4f} ({latest_erp*100:.2f}%)")
        
        # Step 2: Fetch Buffett Index
        print("\n[2/4] Buffett Indicator (Market Cap/GDP)")
        print("-" * 80)
        
        buffett_df = fetch_buffett_index(fred, start_year=1990)
        if buffett_df is None:
            raise ValueError("ERROR: Cannot fetch Buffett Index")
        
        latest_buffett = buffett_df["buffett_raw"].iloc[-1]
        print(f"  Latest Buffett Index: {latest_buffett:.4f} ({latest_buffett*100:.2f}%)")
        
        # Step 3: Fetch Margin Debt
        print("\n[3/4] Margin Debt / GDP")
        print("-" * 80)
        
        margin_df = fetch_margin_debt(fred, start_year=1990)
        if margin_df is None:
            raise ValueError("ERROR: Cannot fetch Margin Debt")
        
        latest_margin = margin_df["margin_debt_raw"].iloc[-1]
        print(f"  Latest Margin/GDP: {latest_margin:.4f} ({latest_margin*100:.2f}%)")
        
        # Step 4: Align data and calculate CMRS
        print("\n[4/4] Multi-Factor Risk Score (CMRS)")
        print("-" * 80)
        
        df_all = pd.concat([
            df_cape_erp[["cape", "erp_raw"]],
            buffett_df.resample("MS").first().ffill(),
            margin_df.resample("MS").first().ffill(),
        ], axis=1).dropna()
        
        results = calculate_risk_score(df_all)
        
        cmrs_score = results["cmrs_score"]
        risk_zone = get_risk_zone(cmrs_score)
        
        print(f"\n  ERP Percentile: {results['erp_pct']:.1f} (Weight: 35%)")
        print(f"  CAPE Percentile: {results['cape_pct']:.1f} (Weight: 25%)")
        print(f"  Buffett Percentile: {results['buffett_pct']:.1f} (Weight: 20%)")
        print(f"  Margin Percentile: {results['margin_pct']:.1f} (Weight: 20%)")
        print(f"\n  CMRS Score: {cmrs_score}")
        print(f"  {risk_zone}")
        
        # Position recommendations
        position_advice = get_position_advice(cmrs_score)
        
        print(f"\n  Risk Level: {position_advice['risk_level']}")
        print(f"  Target Equity: {position_advice['equity_target']}")
        print(f"  Target Cash: {position_advice['cash_target']}")
        print(f"\n  Recommended Actions:")
        for action in position_advice['actions']:
            print(f"    - {action}")
        
        # Build output JSON
        output_data = {
            "timestamp": today_str,
            "cmrs_score": cmrs_score,
            "risk_zone": risk_zone,
            "indicators": {
                "cape": {
                    "value": float(latest_cape),
                    "percentile": float(results['cape_pct']),
                },
                "erp": {
                    "value": float(latest_erp),
                    "percentile": float(results['erp_pct']),
                },
                "buffett": {
                    "value": float(latest_buffett),
                    "percentile": float(results['buffett_pct']),
                },
                "margin_debt": {
                    "value": float(latest_margin),
                    "percentile": float(results['margin_pct']),
                },
            },
            "position_advice": position_advice,
        }
        
        # Save to JSON
        os.makedirs("data", exist_ok=True)
        json_path = "data/latest_scores.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        
        print(f"\n✓ Results saved to {json_path}")
        print("=" * 80)
        
        return output_data

    except Exception as e:
        print(f"\nERROR: Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    result = run_pipeline()
