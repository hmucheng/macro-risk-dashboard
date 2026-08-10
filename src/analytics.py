import os
import json
from datetime import datetime
from fredapi import Fred
import yfinance as yf

def get_fred_key():
    # 优先从环境变量获取（GitHub Actions 运行时），没有则提示
    return os.environ.get("FRED_API_KEY")

def run_pipeline():
    api_key = get_fred_key()
    
    if api_key:
        try:
            fred = Fred(api_key=api_key)
            # 示例：拉取 10 年期美债收益率 (DGS10)
            ten_year_yield = fred.get_series_latest_release('DGS10').iloc[-1]
            print(f"成功从 FRED 获取最新10年期美债收益率: {ten_year_yield}%")
        except Exception as e:
            print(f"FRED 数据拉取失败，将使用备用计算逻辑: {e}")
    else:
        print("未检测到 FRED_API_KEY，使用默认/模拟逻辑运行")

    # TODO: 在这里编写你的分位数得分与 CMRS 风险算法逻辑
    # 以下为更新后的 JSON 生成逻辑
    latest_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "cmrs_score": 82.4,
        "risk_zone": "极端泡沫区",
        "gatekeeper_status": "TRIGGERED_BEARISH",
        "indicators": {
            "erp": {"raw_value": -0.007, "percentile_score": 95.2, "weight": 0.30},
            "cape": {"raw_value": 41.2, "percentile_score": 96.1, "weight": 0.30},
            "buffett": {"raw_value": 2.20, "percentile_score": 92.0, "weight": 0.20},
            "margin_debt": {"raw_value": 0.046, "percentile_score": 94.5, "weight": 0.20}
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
                "80%+ 资金归避风港 (1-3个月美债)，享受高息同时锁定子弹。",
                "市场宽度已破 50%，一票否决强行将权益仓位削减至 10%-20% 极限位。"
            ]
        }
    }

    # 写入 JSON
    os.makedirs("data", exist_ok=True)
    with open("data/latest_scores.json", "w", encoding="utf-8") as f:
        json.dump(latest_data, f, ensure_ascii=False, indent=2)
    print("Data update complete.")

if __name__ == "__main__":
    run_pipeline()
