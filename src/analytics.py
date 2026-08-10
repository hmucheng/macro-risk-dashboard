import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
from fredapi import Fred

NTFY_URL = "https://ntfy.sh/smcb-z5hnfa1qj2x8vmnbr8uoqlqmrq49"


def send_ntfy_alert(title, message, priority="default"):
  """发送 ntfy 消息提醒"""
  try:
    requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={"Title": title.encode("utf-8"), "Priority": priority},
        timeout=10,
    )
    print("✅ ntfy 推送消息成功")
  except Exception as e:
    print(f"⚠️ ntfy 推送失败: {e}")


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
  print("⏳ 正在从标准金融 API 拉取无系数真实数据...")

  try:
    # -------------------------------------------------------------
    # 1. 巴菲特指数 (美联储官方全美股票总市值 / 名义 GDP)
    # BOGZ1FL893064105Q: 百万美元 | GDP: 十亿美元
    # -------------------------------------------------------------
    market_cap = fred.get_series(
        "BOGZ1FL893064105Q", observation_start="1990-01-01"
    )
    gdp = fred.get_series("GDP", observation_start="1990-01-01")

    df_buffett = pd.DataFrame(
        {"market_cap": market_cap / 1000.0, "gdp": gdp}
    ).dropna()
    df_buffett["buffett_raw"] = df_buffett["market_cap"] / df_buffett["gdp"]

    # -------------------------------------------------------------
    # 2. 真实 CAPE 与 ERP (罗伯特·席勒 Yale 官方数据集 + 美联储 10 年美债)
    # -------------------------------------------------------------
    shiller_url = "https://raw.githubusercontent.com/datasets/s-and-p-500-derived/master/data/monthly.csv"
    shiller_df = pd.read_csv(shiller_url)
    shiller_df["Date"] = pd.to_datetime(shiller_df["Date"])
    shiller_df = shiller_df.set_index("Date").sort_index()

    gs10 = fred.get_series("GS10", observation_start="1990-01-01")

    df_cape = (
        pd.DataFrame({
            "cape": shiller_df[
                "Cyclically Adjusted Price Earnings Ratio (CAPE)"
            ],
            "gs10": gs10,
        })
        .resample("MS")
        .first()
        .ffill()
    )

    # 真实 ERP 计算：(1 / CAPE) - 10年期美债收益率
    df_cape["erp_raw"] = (1.0 / df_cape["cape"]) - (df_cape["gs10"] / 100.0)

    # -------------------------------------------------------------
    # 3. 保证金债务 / GDP (FINRA 官方 Margin Debt 数据)
    # -------------------------------------------------------------
    try:
      finra_url = "https://raw.githubusercontent.com/datasets/finra-margin-debt/main/data/margin-debt.csv"
      finra_df = pd.read_csv(finra_url)
      finra_df["Date"] = pd.to_datetime(finra_df["Date"])
      finra_df = finra_df.set_index("Date").sort_index()
      margin_series = finra_df["Margin Debt"] / 1000.0  # 转十亿美元
    except Exception:
      # 备用源：美联储证券信用杠杆序列
      margin_series = fred.get_series(
          "BOGZ1FL663067003Q", observation_start="1990-01-01"
      )

    df_margin = (
        pd.DataFrame({"margin_debt": margin_series, "gdp": gdp})
        .resample("MS")
        .first()
        .ffill()
    )
    df_margin["margin_debt_raw"] = df_margin["margin_debt"] / df_margin["gdp"]

    # -------------------------------------------------------------
    # 4. 数据合并与 10 年动态分位数计算
    # -------------------------------------------------------------
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
    window_df = df_all.iloc[-120:]  # 取最近 120 个月 (10年)

    erp_pct = 100.0 - ((window_df["erp_raw"] <= latest["erp_raw"]).mean() * 100.0)
    cape_pct = (window_df["cape"] <= latest["cape"]).mean() * 100.0
    buffett_pct = (
        window_df["buffett_raw"] <= latest["buffett_raw"]
    ).mean() * 100.0
    margin_pct = (
        window_df["margin_debt_raw"] <= latest["margin_debt_raw"]
    ).mean() * 100.0

    # 35/25/20/20 优化权重加权
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

    # 动态匹配 SOP 指令
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

    # -------------------------------------------------------------
    # 5. 关键写入步骤：保存更新至 data/latest_scores.json
    # -------------------------------------------------------------
    json_path = "data/latest_scores.json"
    previous_zone = None

    if os.path.exists(json_path):
      try:
        with open(json_path, "r", encoding="utf-8") as f:
          old_json = json.load(f)
          previous_zone = old_json.get("risk_zone")
      except Exception:
        pass

    # 若风控状态发生跨越，触发高优先级 ntfy 推送
    if previous_zone and previous_zone != current_zone:
      alert_title = "⚠️ 宏观风控状态变更提醒！"
      alert_msg = (
          f"宏观风险状态切换！\n上一状态: {previous_zone}\n当前状态:"
          f" {current_zone}\n当前 CMRS 得分: {cmrs_score}\n请及时调整仓位！"
      )
      send_ntfy_alert(alert_title, alert_msg, priority="high")

    os.makedirs("data", exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
      json.dump(new_data, f, ensure_ascii=False, indent=2)

    print(f"🎉 成功！最新数据已成功写入 data/latest_scores.json！")
    print(f"📊 最新巴菲特指标: {latest['buffett_raw']*100:.1f}%")
    print(f"📊 最新 CAPE: {latest['cape']:.2f}")

  except Exception as e:
    print(f"❌ 运行失败: {e}")


if __name__ == "__main__":
  run_pipeline()
