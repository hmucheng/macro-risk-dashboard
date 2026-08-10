# -*- coding: utf-8 -*-
"""
CMRS 多因子风险评分系统
严格符合专业金融定义的四大指标计算（已修复 Shiller 官方数据源与解析逻辑）
"""

import io
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
    Fetch Shiller CAPE data directly from Robert Shiller's official Yale dataset
    """
    print("  [Loading Shiller CAPE data from Yale official source...]")
    try:
        url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
        response = requests.get(url, timeout=15)
        df = pd.read_excel(io.BytesIO(response.content), sheet_name="Data", skiprows=7)
        
        # Clean column names
        df.columns = [str(c).strip() for c in df.columns]
        
        date_col = df.columns[0]
        cape_col = None
        for col in df.columns:
            if "CAPE" in col.upper() or "P/E10" in col.upper():
                cape_col = col
                break
        
        if cape_col is None:
            cape_col = "CAPE"
            
        df = df[[date_col, cape_col]].dropna(subset=[date_col]).copy()
        df.columns = ["raw_date", "cape"]
        
        def parse_shiller_date(val):
            try:
                val_str = str(val).strip()
                if "." in val_str:
                    parts = val_str.split(".")
                    year = int(parts[0])
                    month = int(parts[1].ljust(2, '0')[:2])
                    if month < 1: month = 1
                    if month > 12: month = 12
                    return pd.Timestamp(year=year, month=month, day=1)
                else:
                    return pd.NaT
            except:
                return pd.NaT

        df["Date"] = df["raw_date"].apply(parse_shiller_date)
        df = df.dropna(subset=["Date"])
        df["cape"] = pd.to_numeric(df["cape"], errors="coerce")
        df = df.dropna(subset=["cape"])
        
        df = df[df["Date"].dt.year >= start_year].copy()
        df = df.sort_values("Date").set_index("Date")
        
        return df[["cape"]].resample("MS").first().ffill()
    
    except Exception as e:
        print(f"    ERROR: Failed to load Shiller CAPE: {e}")
        return None


def fetch_gs10(fred, start_year=1990):
    """
    Fetch 10-year Treasury yield (GS10) from FRED
    """
    print("  [Loading GS10 (10Y Treasury) data...]")
    try:
        gs10 = fred.get_series("GS10", observation_start=f"{start_year}-01-01")
        gs10_df = pd.DataFrame({"gs10": gs10})
        gs10_df.index.name = "Date"
        return gs10_df.resample("MS").first().ffill()
    except Exception as e:
        print(f"    ERROR: Failed to load GS10: {e}")
        return None


def fetch_buffett_index(fred, start_year=1990):
    """
    Calculate Buffett Indicator = Total Market Cap / Nominal GDP
    """
    print("  [Loading Buffett Index (Market Cap/GDP)...]")
    try:
        start_str = f"{start_year}-01-01"
        gdp = fred.get_series("GDP", observation_start=start_str)
        market_cap = fred.get_series("BOGZ1FL893064105Q", observation_start=start_str) / 1000.0
        
        df = pd.DataFrame({
            "market_cap": market_cap,
            "gdp": gdp
        })
        df = df.resample("MS").first().ffill()
        df["buffett_raw"] = df["market_cap"] / df["gdp"]
        return df[["buffett_raw"]]
    except Exception as e:
        print(f"    ERROR: Failed to load Buffett Index: {e}")
        return None


def fetch_margin_debt(fred, start_year=1990):
    """
    Calculate Margin Debt / GDP
    """
    print("  [Loading Margin Debt/GDP...]")
    try:
        start_str = f"{start_year}-01-01"
        gdp = fred.get_series("GDP", observation_start=start_str)
        margin_debt = fred.get_series("BOGZ1FL663067003Q", observation_start=start_str) / 1000.0
        
        df = pd.DataFrame({
            "margin_debt": margin_debt,
            "gdp": gdp
        })
        df = df.resample("MS").first().ffill()
        df["margin_debt_raw"] = df["margin_debt"] / df["gdp"]
        return df[["margin_debt_raw"]]
    except Exception as e:
        print(f"    ERROR: Failed to load margin debt: {e}")
        return None


def calculate_risk_score(df_all):
    """
    Calculate CMRS (Comprehensive Market Risk Score)
    """
    latest = df_all.iloc[-1]
    window = df_all.iloc[-120:]  # 10-year rolling window
    
    erp_pct = 100.0 * (1.0 - (window["erp_raw"] <= latest["erp_raw"]).mean())
    cape_pct = 100.0 * (window["cape"] <= latest["cape"]).mean()
    buffett_pct = 100.0 * (window["buffett_raw"] <= latest["buffett_raw"]).mean()
    margin_pct = 100.0 * (window["margin_debt_raw"] <= latest["margin_debt_raw"]).mean()
    
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
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise ValueError("ERROR: FRED_API_KEY environment variable not set!")

    fred = Fred(api_key=api_key)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    print("\n" + "=" * 80)
    print("CMRS RISK ASSESSMENT PIPELINE")
    print("=" * 80)

    try:
        cape_df = fetch_shiller_cape(start_year=1990)
        gs10_df = fetch_gs10(fred, start_year=1990)
        buffett_df = fetch_buffett_index(fred, start_year=1990)
        margin_df = fetch_margin_debt(fred, start_year=1990)
        
        if cape_df is None or gs10_df is None or buffett_df is None or margin_df is None:
            raise ValueError("ERROR: One or more data series failed to load.")
        
        df_all = pd.concat([
            cape_df,
            gs10_df,
            buffett_df,
            margin_df,
        ], axis=1).ffill().dropna()
        
        df_all["erp_raw"] = (1.0 / df_all["cape"]) - (df_all["gs10"] / 100.0)
        
        latest = df_all.iloc[-1]
        latest_cape = latest["cape"]
        latest_gs10 = latest["gs10"]
        latest_erp = latest["erp_raw"]
        latest_buffett = latest["buffett_raw"]
        latest_margin = latest["margin_debt_raw"]
        
        print(f"  Latest CAPE: {latest_cape:.2f}")
        print(f"  Latest GS10: {latest_gs10:.2f}%")
        print(f"  Latest ERP: {latest_erp:.4f} ({latest_erp*100:.2f}%)")
        print(f"  Latest Buffett Index: {latest_buffett:.4f} ({latest_buffett*100:.2f}%)")
        print(f"  Latest Margin/GDP: {latest_margin:.4f} ({latest_margin*100:.2f}%)")
        
        results = calculate_risk_score(df_all)
        cmrs_score = results["cmrs_score"]
        risk_zone = get_risk_zone(cmrs_score)
        
        print(f"\n  CMRS Score: {cmrs_score}")
        print(f"  {risk_zone}")
        
        position_advice = get_position_advice(cmrs_score)
        
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
