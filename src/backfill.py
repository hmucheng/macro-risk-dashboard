import os
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred

def generate_real_historical_scores():
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("❌ 错误：未检测到 FRED_API_KEY！")
        return

    fred = Fred(api_key=api_key)
    print("⏳ 正在拉取数据并应用【10年动态自适应滚动窗口】算法...")

    try:
        # 1. 获取基础数据
        gs10 = fred.get_series('GS10', observation_start='1990-01-01')
        gdp = fred.get_series('GDP', observation_start='1990-01-01')

        sp500_ticker = yf.Ticker("^GSPC")
        sp500_hist = sp500_ticker.history(start="1990-01-01", interval="1mo")
        sp500_close = sp500_hist['Close']
        sp500_close.index = sp500_close.index.tz_localize(None)

        df = pd.DataFrame({'gs10': gs10, 'sp500': sp500_close}).resample('MS').first()
        df['gdp'] = gdp.resample('MS').ffill()
        df = df.ffill().bfill()

        # 2. 计算原始子指标
        # 席勒 CAPE Proxy
        df['cape'] = df['sp500'] / (df['sp500'].rolling(120, min_periods=24).mean() * 0.70)
        # ERP (股权风险溢价)
        df['erp_raw'] = (1.0 / df['cape']) - (df['gs10'] / 100.0)
        # 巴菲特指数 Proxy
        df['buffett_raw'] = (df['sp500'] * 1.45) / (df['gdp'] / 10.0)
        # 杠杆与离差率
        df['margin_debt_raw'] = df['sp500'] / df['sp500'].rolling(36, min_periods=12).mean()

        df = df.loc['2000-01-01':].dropna()

        # 3. 核心改进：10 年 (120 个月) 动态自适应滚动分位数计算
        ROLLING_WINDOW = 120 # 10 年滚动窗口
        history_rows = []

        for i in range(len(df)):
            current_date = df.index[i].strftime('%Y-%m-%d')
            
            # 取最近 10 年（最大 120 个月）的历史数据进行相对比较
            start_idx = max(0, i - ROLLING_WINDOW)
            window_df = df.iloc[start_idx : i + 1]

            # 计算在过去 10 年新常态下的相对百分位
            erp_pct = 100.0 - (window_df['erp_raw'].rank(pct=True).iloc[-1] * 100.0)
            cape_pct = window_df['cape'].rank(pct=True).iloc[-1] * 100.0
            buffett_pct = window_df['buffett_raw'].rank(pct=True).iloc[-1] * 100.0
            margin_pct = window_df['margin_debt_raw'].rank(pct=True).iloc[-1] * 100.0

            # 综合得分为四个指标相对百分位数的均值
            cmrs_score = np.mean([erp_pct, cape_pct, buffett_pct, margin_pct])

            if cmrs_score >= 75:
                zone = "🔴 极端泡沫区"
            elif cmrs_score >= 55:
                zone = "🟡 风控警戒区"
            elif cmrs_score >= 25:
                zone = "🔵 合理持股区"
            else:
                zone = "🟢 低风险买入区"

            history_rows.append({
                'date': current_date,
                'cmrs_score': round(cmrs_score, 1),
                'risk_zone': zone,
                'erp_raw': round(df['erp_raw'].iloc[i], 4),
                'cape_raw': round(df['cape'].iloc[i], 2),
                'buffett_raw': round(df['buffett_raw'].iloc[i], 2),
                'margin_debt_raw': round(df['margin_debt_raw'].iloc[i], 4)
            })

        result_df = pd.DataFrame(history_rows)
        os.makedirs("data", exist_ok=True)
        result_df.to_csv("data/history_scores.csv", index=False)
        print("🎉 优化成功！10年自适应动态历史曲线已更新！")

    except Exception as e:
        print(f"❌ 运行失败: {e}")

if __name__ == "__main__":
    generate_real_historical_scores()
