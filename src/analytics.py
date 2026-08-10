import json
import os
from datetime import datetime

def run_pipeline():
    # 此处放置计算逻辑，此处生成最新 JSON 结构
    latest_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "cmrs_score": 82.4,
        "risk_zone": "极端泡沫区",
        "gatekeeper_status": "TRIGGERED_BEARISH",
        "indicators": {
            "erp": { "raw_value": -0.007, "percentile_score": 95.2, "weight": 0.30 },
            "cape": { "raw_value": 41.2, "percentile_score": 96.1, "weight": 0.30 },
            "buffett": { "raw_value": 2.20, "percentile_score": 92.0, "weight": 0.20 },
            "margin_debt": { "raw_value": 0.046, "percentile_score": 94.5, "weight": 0.20 }
        },
        "gatekeeper": {
            "sp500_above_200sma_pct": 0.42,
            "condition_met": True
        },
        "sop_instructions": {
            "target_equity_pct": "10% - 20%",
            "target_cash_pct": "80% - 90%",
            "action_summary": "战术收缩 / 锁定胜果指令",
            "execution_steps": [
                "清理所有高 Beta、高估值概念股，仅保留极少量高股息核心底仓。",
                "80%+ 资金归避风港（1-3个月美债），享受高息同时锁定子弹。",
                "市场宽度已破 50%，一票否决强行将权益仓位削减至 10%-20% 极限位。"
            ]
        }
    }
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_scores.json", "w", encoding="utf-8") as f:
        json.dump(latest_data, f, ensure_ascii=False, indent=2)
    print("Data update complete.")

if __name__ == "__main__":
    run_pipeline()
