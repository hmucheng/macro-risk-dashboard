import json
import os
from datetime import datetime
import pandas as pd
import requests

# NTFY 推送频道地址
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
  # -------------------------------------------------------------
  # 1. 此处保持你原本的 FRED 数据抓取与 CMRS 得分计算逻辑
  # (以下为示例逻辑，请确保保留你原本真实的抓取与计算代码)
  # -------------------------------------------------------------
  today_str = datetime.now().strftime("%Y-%m-%d")

  # 假设计算出的当前数据
  cmrs_score = 82.4  # 替换为你实际算出的 score
  current_zone = get_risk_zone(cmrs_score)

  indicators_data = {
      "erp": {"raw_value": -0.01, "percentile_score": 95.2},
      "cape": {"raw_value": 41.20, "percentile_score": 96.1},
      "buffett": {"raw_value": 2.20, "percentile_score": 92.0},
      "margin_debt": {"raw_value": 0.05, "percentile_score": 94.5},
  }

  sop_data = {
      "target_equity_pct": "10% - 20%",
      "target_cash_pct": "80% - 90%",
      "execution_steps": [
          "清理所有高 Beta、高估值概念股，仅保留极少量高股息核心底仓。",
          "80%+ 资金归避风港 (1-3个月美债)，享受高息同时锁定子弹。",
          "市场宽度已突破 50%，一票否决强行将权益仓位削减至 10%-20% 极限位。",
      ],
  }

  # 构建新的 JSON 数据包
  new_data = {
      "timestamp": today_str,
      "cmrs_score": cmrs_score,
      "risk_zone": current_zone,
      "indicators": indicators_data,
      "sop_instructions": sop_data,
  }

  # -------------------------------------------------------------
  # 2. 状态变更检测与 ntfy 消息提醒
  # -------------------------------------------------------------
  json_path = "data/latest_scores.json"
  previous_zone = None

  if os.path.exists(json_path):
    try:
      with open(json_path, "r", encoding="utf-8") as f:
        old_json = json.load(f)
        previous_zone = old_json.get("risk_zone")
    except Exception as e:
      print(f"读取历史 JSON 失败: {e}")

  # 如果风险状态发生跨越，触发高优先级的 ntfy 警报推送
  if previous_zone and previous_zone != current_zone:
    alert_title = f"⚠️ 宏观风控状态变更提醒！"
    alert_msg = (
        f"宏观风险状态发生切换！\n上一状态: {previous_zone}\n当前状态:"
        f" {current_zone}\n当前 CMRS 综合得分: {cmrs_score:.1f}\n请及时调整仓位！"
    )
    send_ntfy_alert(alert_title, alert_msg, priority="high")

  # 写入最新的 JSON 文件
  os.makedirs("data", exist_ok=True)
  with open(json_path, "w", encoding="utf-8") as f:
    json.dump(new_data, f, ensure_ascii=False, indent=2)

  # -------------------------------------------------------------
  # 3. 历史数据追加持久化 (data/history_scores.csv)
  # -------------------------------------------------------------
  csv_path = "data/history_scores.csv"
  history_row = {
      "date": today_str,
      "cmrs_score": cmrs_score,
      "risk_zone": current_zone,
      "erp_raw": indicators_data["erp"]["raw_value"],
      "cape_raw": indicators_data["cape"]["raw_value"],
      "buffett_raw": indicators_data["buffett"]["raw_value"],
      "margin_debt_raw": indicators_data["margin_debt"]["raw_value"],
  }

  if os.path.exists(csv_path):
    df_hist = pd.read_csv(csv_path)
    # 如果今天还没记录过，追加写入；如果已记录，覆盖今天这行
    if today_str in df_hist["date"].values:
      df_hist.loc[df_hist["date"] == today_str, list(history_row.keys())] = (
          list(history_row.values())
      )
    else:
      df_hist = pd.concat(
          [df_hist, pd.DataFrame([history_row])], ignore_index=True
      )
  else:
    df_hist = pd.DataFrame([history_row])

  df_hist.to_csv(csv_path, index=False)
  print("✅ 数据持久化与更新成功完成！")


if __name__ == "__main__":
  run_pipeline()
