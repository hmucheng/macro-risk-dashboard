import os
import numpy as np
import pandas as pd
from fredapi import Fred


def generate_real_historical_scores():
  # 1. 验证 FRED API KEY
  api_key = os.environ.get("FRED_API_KEY")
  if not api_key:
    print("❌ 错误：未检测到 FRED_API_KEY！")
    print(
        "请在终端先运行: export FRED_API_KEY='你的密钥'，或直接在脚本中临时指定。"
    )
    return

  fred = Fred(api_key=api_key)
  print("⏳ 正在从 FRED API 抓取 2000 年至今的真实历史宏观序列...")

  try:
    # 2. 拉取 FRED 核心宏观时间序列 (2000-至今)
    # GS10: 10年期美债收益率 (%)
    # GDP: 美国名义 GDP (十亿美元, 季度数据)
    # WILL5000PRFC: Wilshire 5000 股市总市值代理指数
    # BOGZ1FL663067003Q: 证券保证金负债/杠杆代理指标
    gs10 = fred.get_series("GS10", observation_start="1995-01-01")
    gdp = fred.get_series("GDP", observation_start="1995-01-01")
    wilshire = fred.get_series("WILL5000PRFC", observation_start="1995-01-01")
    margin_debt = fred.get_series(
        "BOGZ1FL663067003Q", observation_start="1995-01-01"
    )

    # 3. 数据频次对齐与清洗 (重采样为月度频率 MS)
    df = pd.DataFrame({"gs10": gs10}).resample("MS").first()
    df["gdp"] = gdp.resample("MS").ffill()  # 季度 GDP 前向填充为月度
    df["wilshire"] = wilshire.resample("MS").first()
    df["margin"] = margin_debt.resample("MS").ffill()

    # 4. 获取席勒 CAPE 历史数据 (通过公开镜像)
    try:
      shiller_url = "https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv"
      shiller_df = pd.read_csv(shiller_url)
      shiller_df["Date"] = pd.to_datetime(shiller_df["Date"])
      shiller_df = shiller_df.set_index("Date").resample("MS").first()
      df["cape"] = shiller_df["PE"]
    except Exception as e:
      print(f"⚠️ 席勒数据读取受阻，改用 FRED S&P500 派生估算 CAPE: {e}")
      sp500 = (
          fred.get_series("SP500", observation_start="1995-01-01")
          .resample("MS")
          .first()
      )
      df["cape"] = sp500 / (sp500.rolling(120, min_periods=12).mean() * 0.75)

    # 5. 计算四大核心子指标原始值 (Raw Values)
    # ERP (股权风险溢价) = (1/CAPE) - 10年美债收益率
    df["earnings_yield"] = 1.0 / df["cape"]
    df["erp_raw"] = df["earnings_yield"] - (df["gs10"] / 100.0)

    # 巴菲特指数 = 股市总市值 / GDP (缩放系数调整)
    df["buffett_raw"] = (df["wilshire"] * 1.15) / (df["gdp"] / 10.0)

    # 保证金债务 / GDP
    df["margin_debt_raw"] = (df["margin"] / 1000.0) / df["gdp"]

    # 截取 2000-01-01 至今的完整月度序列
    df = df.loc["2000-01-01":].dropna(subset=["erp_raw", "buffett_raw"])

    print(f"🧮 成功获取 {len(df)} 个月真实历史点，正在进行无未来函数的动态分位数计算...")

    # 6. 逐月滚动计算 30 年动态分位数 (避免未来函数)
    history_rows = []
    for i in range(len(df)):
      current_date = df.index[i].strftime("%Y-%m-%d")
      window_df = df.iloc[: i + 1]  # 仅使用截至当前日期及之前的历史数据

      # 分位数计算 (0 - 100)
      # ERP 越小风险越高，故取 100 - rank
      erp_pct = 100.0 - (window_df["erp_raw"].rank(pct=True).iloc[-1] * 100.0)
      cape_pct = window_df["cape"].rank(pct=True).iloc[-1] * 100.0
      buffett_pct = window_df["buffett_raw"].rank(pct=True).iloc[-1] * 100.0
      margin_pct = window_df["margin_debt_raw"].rank(pct=True).iloc[-1] * 100.0

      # CMRS 综合得分 (等权重平均)
      cmrs_score = np.mean([erp_pct, cape_pct, buffett_pct, margin_pct])

      # 判定区间
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

    result_df = pd.DataFrame(history_rows)

    # 7. 写入 data/history_scores.csv
    os.makedirs("data", exist_ok=True)
    output_path = "data/history_scores.csv"
    result_df.to_csv(output_path, index=False)

    print("--------------------------------------------------")
    print(
        f"🎉 成功！已将 2000-2026 年共 {len(result_df)} 条真实历史数据写入 {output_path}"
    )
    print("--------------------------------------------------")

  except Exception as e:
    print(f"❌ 运行失败: {e}")


if __name__ == "__main__":
  generate_real_historical_scores()
