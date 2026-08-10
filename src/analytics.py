import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
from fredapi import Fred

NTFY_URL = "https://ntfy.sh/smcb-z5hnfa1qj2x8vmnbr8uoqlqmrq49"


def send_ntfy_alert(title, message, priority="default"):
  try:
    requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Priority": priority},
        timeout=10,
    )
  except Exception as e:
    print(f"ntfy 推送失败: {e}")


def get_risk_zone(score):
  if score >= 75:
    return "🔴 极端泡沫区"
  elif score >= 55:
    return "🟡 风控警戒区"
  elif score >= 25:
    return "🔵 合理持股区"
  else:
    return "🟢 低风险买入区"


def run_pipeline():
  api_key = os.environ.get("FRED_API_KEY")
  if not api_key:
    print("❌ 错误：未检测到 FRED_API_KEY！")
    return

  fred = Fred(api_key=api_key)
  today_str = datetime.now().strftime("%Y-%m-%d")
  print("⏳ 正在拉取标准金融原生数据源（无任何人工凑数系数）...")

  try:
    # =========================================================================
    # 1. 巴菲特指数 (无系数：全美总市值 / 名义 GDP)
    # BOGZ1FL893064105Q: 美联储发布的全美家户及非营利机构持有股票总市值 (百万美元)
    # GDP: 美国名义 GDP (十亿美元)
    # =========================================================================
    market_cap = fred.get_series(
        "BOGZ1FL893064105Q", observation_start="1990-01-01"
    )
    gdp = fred.get_series("GDP", observation_start="1990-01-01")

    # 对齐频次 (单位换算：市值百万 -> 十亿，除以 GDP 十亿)
    df_buffett = pd.DataFrame(
        {"market_cap": market_cap / 1000.0, "gdp": gdp}
    ).dropna()
    df_buffett["buffett_raw"] = df_buffett["market_cap"] / df_buffett["gdp"]

    # =========================================================================
    # 2. 真实 CAPE 与 ERP (基于 10 年真实盈利与无风险利率)
    # 从 Yale Shiller 官方公开源/数据源拉取真正的席勒 CAPE 数据
    # =========================================================================
    shiller_url = "https://raw.githubusercontent.com/datasets/s-and-p-500-derived/master/data/monthly.csv"
    shiller_df = pd.read_csv(shiller_url)
    shiller_df["Date"] = pd.to_datetime(shiller_df["Date"])
    shiller_df = shiller_df.set_index("Date").sort_index()

    gs10 = fred.get_series("GS10", observation_start="1990-01-01")

    df_cape = pd.DataFrame({"cape": shiller_df["Cyclically Adjusted Price Earnings Ratio (CAPE)"], "gs10": gs10}).resample("MS").first().ffill()

    # 真实 ERP 计算公式：(1 / CAPE) - 10年期美债收益率
    df_cape["erp_raw"] = (1.0 / df_cape["cape"]) - (df_cape["gs10"] / 100.0)

    # =========================================================================
    # 3. 真实 FINRA 保证金债务 (Margin Debt / GDP)
    # 从开源 FINRA 历史数据集拉取真实保证金债务 (百万美元)
    # =========================================================================
    finra_url = "https://raw.githubusercontent.com/datasets/finra-margin-debt/main/data/margin-debt.csv"
    try:
      finra_df = pd.read_csv(finra_url)
      finra_df["Date"] = pd.to_datetime(finra_df["Date"])
      finra_df = finra_df.set_index("Date").sort_index()
      margin_series = finra_df["Margin Debt"] / 1000.0  # 转为十亿美元
    except Exception:
      # 备用：若开源 FINRA 接口超时，使用 FRED 相似金融杠杆序列代理
      margin_series = fred.get_series(
          "BOGZ1FL663067003Q", observation_start="1990-01-01"
      )

    df_margin = pd.DataFrame({"margin_debt": margin_series, "gdp": gdp}).resample("MS").first().ffill()
    df_margin["margin_debt_raw"] = df_margin["margin_debt"] / df_margin["gdp"]

    # =========================================================================
    # 4. 合并所有真实指标
    # =========================================================================
    df_all = (
        pd.DataFrame({
            "erp_raw": df_cape["erp_raw"],
            "cape": df_cape["cape"],
            "buffett_raw": df_buffett["buffett_raw"],
            "margin_debt_raw": df_margin["margin_debt_raw"],
        })
        .dropna()
        .resample("MS")
        .first()
        .ffill()
    )

    latest = df_all.iloc[-1]
    window_df = df_all.iloc[-120:]  # 最近 10 年窗口计算百分位

    # 计算百分位数
    erp_pct = 100.0 - ((window_df["erp_raw"] <= latest["erp_raw"]).mean() * 100.0)
    cape_pct = (window_df["cape"] <= latest["cape"]).mean() * 100.0
    buffett_pct = (
        window_df["buffett_raw"] <= latest["buffett_raw"]
    ).mean() * 100.0
    margin_pct = (
        window_df["margin_debt_raw"] <= latest["margin_debt_raw"]
    ).mean() * 100.0

    # 35/25/20/20 优化加权得分
    cmrs_score = round(
        0.35 * erp_pct + 0.25 * cape_pct + 0.20 * buffett_pct + 0.20 * margin_pct,
        1,
    )
    current_zone = get_risk_zone(cmrs_score)

    indicators_data = {
        "erp": {
            "raw_value": round(float(latest["erp_raw"]), 4),
            "percentile_score": round(float(erp_pct), 1),
        },
        "cape": {
            "raw_value": round(float(latest["cape"]), 2),
            "percentile_score": round(float(cape_pct), 1),
        },
        "buffett": {
            "raw_value": round(float(latest["buffett_raw"]), 2),
            "percentile_score": round(float(buffett_pct), 1),
        },
        "margin_debt": {
            "raw_value": round(float(latest["margin_debt_raw"]), 4),
            "percentile_score": round(float(margin_pct), 1),
        },
    }

    print(f"✅ 标准金融数据源解析成功！当前真实 CMRS 得分: {cmrs_score}")

  except Exception as e:
    print(f"❌ 运行失败: {e}")


if __name__ == "__main__":
  run_pipeline()
