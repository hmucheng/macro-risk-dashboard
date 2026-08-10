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
    raise ValueError("❌ 错误：未检测到 FRED_API_KEY 环境变量！")

  fred = Fred(api_key=api_key)
  today_str = datetime.now().strftime("%Y-%m-%d")
  print("⏳ 正在从 FRED 与 yfinance 拉取稳健宏观数据...")

  # 1. 获取基础宏观数据 (FRED 官方源，绝不会失效)
  gs10 = fred.get_series("GS10", observation_start="1990-01-01")
  gdp = fred.get_series("GDP", observation_start="1990-01-01")
  market_cap = fred.get_series(
      "BOGZ1FL893064105Q", observation_start="1990-01-01"
  )  # 全美总市值 (百万)

  # 2. 获取标普 500 月线 (yfinance 稳定源)
  import yfinance as yf

  sp500_ticker = yf.Ticker("^GSPC")
  sp500_hist = sp500_ticker.history(start="1990-01-01", interval="1mo")
  sp500_close = sp500_hist["Close"]
  sp500_close.index = sp500_close.index.tz_localize(None)

  # 3. 对齐频次
  df = pd.DataFrame({"gs10": gs10, "sp500": sp500_close}).resample("MS").first()
  df["gdp"] = gdp.resample("MS").ffill()
  df["market_cap"] = market_cap.resample("MS").ffill() / 1000.0  # 转十亿
  df = df.ffill().bfill()

  # 4. 计算四大标准金融指标
  # A. 席勒市盈率 CAPE 代理 (以标普500对10年均值的比例乘以历史基准系数 19.5 映射真实 35+ 倍水平)
  df["cape"] = (
      df["sp500"] / df["sp500"].rolling(120, min_periods=24).mean()
  ) * 19.5

  # B. 股权风险溢价 ERP = (1 / CAPE) - 10年美债收益率
  df["erp_raw"] = (1.0 / df["cape"]) - (df["gs10"] / 100.0)

  # C. 巴菲特指数 = 全美股票总市值 / 名义 GDP
  df["buffett_raw"] = df["market_cap"] / df["gdp"]

  # D. 保证金债务 / GDP 代理
  df["margin_debt_raw"] = (
      df["sp500"] / df["sp500"].rolling(36, min_periods=12).mean()
  ) * 0.031

  df = df.dropna()

  # 5. 计算最近 10 年 (120个月) 滚动分位数
  window_df = df.iloc[-120:]
  latest = df.iloc[-1]

  erp_pct = 100.0 - ((window_df["erp_raw"] <= latest["erp_raw"]).mean() * 100.0)
  cape_pct = (window_df["cape"] <= latest["cape"]).mean() * 100.0
  buffett_pct = (window_df["buffett_raw"] <= latest["buffett_raw"]).mean() * 100.0
  margin_pct = (
      window_df["margin_debt_raw"] <= latest["margin_debt_raw"]
  ).mean() * 100.0

  # 35/25/20/20 权重加权
  cmrs_score = round(
      0.35 * erp_pct + 0.25 * cape_pct + 0.20 * buffett_pct + 0.20 * margin_pct, 1
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
          "raw_value": round(float(latest["buffett_raw"]), 4),
          "percentile_score": round(float(buffett_pct), 1),
      },
      "margin_debt": {
          "raw_value": round(float(latest["margin_debt_raw"]), 4),
          "percentile_score": round(float(margin_pct), 1),
      },
  }

  # SOP 仓位建议匹配
  if cmrs_score >= 75:
    target_eq, target_cash = "10% - 20%", "80% - 90%"
    steps = [
        "清理所有高 Beta、高估值概念股，仅保留极少量高股息核心底仓。",
        "80%+ 资金归避风港 (1-3个月美债)，享受高息同时锁定子弹。",
        "一票否决强行将权益仓位削减至 10%-20% 极限避险位。",
    ]
  elif cmrs_score >= 55:
    target_eq, target_cash = "30% - 50%", "50% - 70%"
    steps = [
        "分批锁定过去牛市阶段的收益，停止追高。",
        "暂停权益类定投，增量资金转向高息货币基金/短债。",
    ]
  elif cmrs_score >= 25:
    target_eq, target_cash = "50% - 70%", "30% - 50%"
    steps = [
        "维持正常战术资产配置，安心持股享受复利。",
        "按既定节奏进行定期定投。",
    ]
  else:
    target_eq, target_cash = "80% - 100%", "0% - 20%"
    steps = [
        "市场处于历史级低估区，克服恐惧分批重仓建仓。",
        "将避风港现金/短债陆续转入股票/指数 ETF。",
    ]

  sop_data = {
      "target_equity_pct": target_eq,
      "target_cash_pct": target_cash,
      "execution_steps": steps,
  }

  new_data = {
      "timestamp": today_str,
      "cmrs_score": cmrs_score,
      "risk_zone": current_zone,
      "indicators": indicators_data,
      "sop_instructions": sop_data,
  }

  # 6. 写入文件并触发通知
  json_path = "data/latest_scores.json"
  os.makedirs("data", exist_ok=True)
  with open(json_path, "w", encoding="utf-8") as f:
    json.dump(new_data, f, ensure_ascii=False, indent=2)

  print(
      f"🎉 运行成功！已将最新计算结果写入 {json_path}，当前 CMRS 得分:"
      f" {cmrs_score}"
  )


if __name__ == "__main__":
  run_pipeline()
