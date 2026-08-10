import os
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred


def generate_real_historical_scores():
  api_key = os.environ.get("FRED_API_KEY")
  if not api_key:
    print("❌ 错误：未检测到 FRED_API_KEY！请在 GitHub Secrets 中配置。")
    return

  fred = Fred(api_key=api_key)
  print(
      "⏳ 正在拉取数据并应用【10年自适应窗口 + 优化权重 (35% ERP / 25% CAPE / 20%"
      " 巴菲特 / 20% 杠杆)】..."
  )

  try:
    # 1. 从 FRED 获取无风险利率 (10年期美债) 与美国 GDP
    gs10 = fred.get_series("GS10", observation_start="1990-01-01")
    gdp = fred.get_series("GDP", observation_start="1990-01-01")

    # 2. 从 yfinance 获取标普 500 历史月线
    sp500_ticker = yf.Ticker("^GSPC")
    sp500_hist = sp500_ticker.history(start="1990-01-01", interval="1mo")
    sp500_close = sp500_hist["Close"]
    sp500_close.index = sp500_close.index.tz_localize(None)

    # 3. 对齐数据频次 (月度第一天)
    df = pd.DataFrame({"gs10": gs10, "sp500": sp500_close}).resample("MS").first()
    df["gdp"] = gdp.resample("MS").ffill()
    df = df.ffill().bfill()

    # 4. 计算四大子指标原始值
    # A. 席勒 CAPE Proxy (标普500 / 10年移动平均收益)
    df["cape"] = df["sp500"] / (
        df["sp500"].rolling(120, min_periods=24).mean() * 0.70
    )

    # B. ERP (股权风险溢价) = 1/CAPE - 10年期美债收益率
    df["erp_raw"] = (1.0 / df["cape"]) - (df["gs10"] / 100.0)

    # C. 巴菲特指数 Proxy = (标普500 * 调整系数) / GDP
    df["buffett_raw"] = (df["sp500"] * 1.45) / (df["gdp"] / 10.0)

    # D. 市场杠杆/离差率 Proxy
    df["margin_debt_raw"] = df["sp500"] / df["sp500"].rolling(
        36, min_periods=12
    ).mean()

    # 截取 2000 年至今的数据
    df = df.loc["2000-01-01":].dropna()

    # 5. 计算 10 年 (120 个月) 动态自适应滚动分位数与加权 CMRS 得分
    ROLLING_WINDOW = 120
    history_rows = []

    for i in range(len(df)):
      current_date = df.index[i].strftime("%Y-%m-%d")

      # 划定当前月份往前推 10 年的历史对比窗口
      start_idx = max(0, i - ROLLING_WINDOW)
      window_df = df.iloc[start_idx : i + 1]

      # 计算当前月份在过去 10 年中的百分位数排名
      erp_pct = 100.0 - (window_df["erp_raw"].rank(pct=True).iloc[-1] * 100.0)
      cape_pct = window_df["cape"].rank(pct=True).iloc[-1] * 100.0
      buffett_pct = window_df["buffett_raw"].rank(pct=True).iloc[-1] * 100.0
      margin_pct = window_df["margin_debt_raw"].rank(pct=True).iloc[-1] * 100.0

      # 💡 应用非对称优化权重加权计算综合 CMRS 得分
      cmrs_score = (
          0.35 * erp_pct
          + 0.25 * cape_pct
          + 0.20 * buffett_pct
          + 0.20 * margin_pct
      )

      # 判断所属风险区间
      if cmrs_score >= 75:
        zone = "🔴 极端泡沫区"
      elif cmrs_score >= 55:
        zone = "🟡 风控警戒区"
      elif cmrs_score >= 25:
        zone = "🔵 合理持股区"
      else:
        zone = "🟢 低风险买入区"

      history_rows.append({
          "date": current_date,
          "cmrs_score": round(cmrs_score, 1),
          "risk_zone": zone,
          "erp_raw": round(df["erp_raw"].iloc[i], 4),
          "cape_raw": round(df["cape"].iloc[i], 2),
          "buffett_raw": round(df["buffett_raw"].iloc[i], 2),
          "margin_debt_raw": round(df["margin_debt_raw"].iloc[i], 4),
      })

    # 6. 保存计算结果为 CSV 文件
    result_df = pd.DataFrame(history_rows)
    os.makedirs("data", exist_ok=True)
    output_path = "data/history_scores.csv"
    result_df.to_csv(output_path, index=False)

    print("--------------------------------------------------")
    print(
        f"🎉 成功！已使用优化权重重新生成 {len(result_df)} 条历史得分记录："
        f" {output_path}"
    )
    print("--------------------------------------------------")

  except Exception as e:
    print(f"❌ 生成历史数据失败: {e}")


if __name__ == "__main__":
  generate_real_historical_scores()
