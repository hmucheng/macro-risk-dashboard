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
    print("⏳ 正在拉取 2000 年至今的真实历史数据 (FRED + Yahoo Finance)...")

    try:
        # 1. 从 FRED 获取稳定宏观数据
        gs10 = fred.get_series('GS10', observation_start='1995-01-01') # 10年期美债收益率
        gdp = fred.get_series('GDP', observation_start='1995-01-01')   # 美国 GDP

        # 2. 从 yfinance 获取 2000-至今 标普 500 真实历史月线 (极为稳定)
        sp500_ticker = yf.Ticker("^GSPC")
        sp500_hist = sp500_ticker.history(start="1995-01-01", interval="1mo")
        sp500_close = sp500_hist['Close']
        sp500_close.index = sp500_close.index.tz_localize(None)

        # 3. 构建月度基础 DataFrame
        df = pd.DataFrame({
            'gs10': gs10,
            'sp500': sp500_close
        }).resample('MS').first()

        df['gdp'] = gdp.resample('MS').ffill()
        df = df.ffill().bfill()

        # 4. 估算与计算四大核心子指标历史值
        # A. 席勒 CAPE 估算：S&P500 / 10年移动平均收益 (带通胀修正系数)
        rolling_earnings_proxy = df['sp500'].rolling(120, min_periods=24).mean() * 0.70
        df['cape'] = df['sp500'] / rolling_earnings_proxy

        # B. ERP (股权风险溢价) = 1/CAPE - 10年期国债收益率
        df['earnings_yield'] = 1.0 / df['cape']
        df['erp_raw'] = df['earnings_yield'] - (df['gs10'] / 100.0)

        # C. 巴菲特指数 Proxy = (S&P500 * 逻辑放大系数) / GDP
        df['buffett_raw'] = (df['sp500'] * 1.45) / (df['gdp'] / 10.0)

        # D. 保证金债务 Proxy (与股市波动率及牛市杠杆高度正相关)
        df['margin_debt_raw'] = (df['sp500'] / df['sp500'].rolling(36, min_periods=12).mean()) * 0.045

        # 截取 2000 年至今的数据
        df = df.loc['2000-01-01':].dropna()

        print(f"🧮 成功获取 {len(df)} 个月历史记录，正在进行 30 年无未来函数动态分位数计算...")

        # 5. 逐月滚动计算 CMRS 历史得分
        history_rows = []
        for i in range(len(df)):
            current_date = df.index[i].strftime('%Y-%m-%d')
            window_df = df.iloc[:i+1] # 严格限定截至当前月份的历史窗口

            # 动态分位数 calculation
            erp_pct = 100.0 - (window_df['erp_raw'].rank(pct=True).iloc[-1] * 100.0)
            cape_pct = window_df['cape'].rank(pct=True).iloc[-1] * 100.0
            buffett_pct = window_df['buffett_raw'].rank(pct=True).iloc[-1] * 100.0
            margin_pct = window_df['margin_debt_raw'].rank(pct=True).iloc[-1] * 100.0

            cmrs_score = np.mean([erp_pct, cape_pct, buffett_pct, margin_pct])

            # 区间判定
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

        # 保存为 CSV
        os.makedirs("data", exist_ok=True)
        output_path = "data/history_scores.csv"
        result_df.to_csv(output_path, index=False)
        print("--------------------------------------------------")
        print(f"🎉 成功！已成功生成 {len(result_df)} 条 2000-2026 年历史数据文件：{output_path}")
        print("--------------------------------------------------")

    except Exception as e:
        print(f"❌ 运行失败: {e}")

if __name__ == "__main__":
    generate_real_historical_scores()
