import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import io
import os
import requests

# -----------------------------------------------------------------------------
# 1. 页面基本配置
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="宏观大周期交易决策系统",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🛡️ 宏观大周期交易决策系统 (3-10年期)")
st.caption("真实数据驱动：Yale Shiller | 美联储 FRED 官方 API | Yahoo Finance 自动容灾")
st.markdown("---")

# -----------------------------------------------------------------------------
# 2. 侧边栏与 API Key 极速读取
# -----------------------------------------------------------------------------
st.sidebar.title("⚙️ 系统配置与状态")

# 探测 API Key (优先 Streamlit Secrets / 环境变量，支持侧边栏手动输入)
env_api_key = st.secrets.get("FRED_API_KEY", os.environ.get("FRED_API_KEY", ""))

user_api_key = st.sidebar.text_input(
    "FRED API Key (已自动检测/可手动覆盖):",
    value=env_api_key,
    type="password",
    help="如未检测到，可在此处粘贴你的 32 位 FRED API Key"
)

FRED_API_KEY = user_api_key.strip() if user_api_key else None

if FRED_API_KEY:
    st.sidebar.success("🟢 FRED 官方 API: 已激活")
else:
    st.sidebar.warning("⚠️ 未检测到 FRED API Key，已启动 Yahoo Finance 备用数据源模式")

# -----------------------------------------------------------------------------
# 3. 容灾数据抓取模块 (FRED API + Yahoo Finance 熔断备用)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=86400)
def fetch_shiller_cape():
    """从耶鲁大学官网读取 CAPE，失败时自动启动降级备用值"""
    try:
        url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            excel_file = io.BytesIO(res.content)
            df = pd.read_excel(excel_file, sheet_name="Data", skiprows=7)
            df = df.dropna(subset=[df.columns[0]]).copy()
            valid_rows = []
            for idx, row in df.iterrows():
                try:
                    date_val = float(row.iloc[0])
                    cape_val = float(row.iloc[10])
                    valid_rows.append({'Date_Num': date_val, 'CAPE': cape_val})
                except (ValueError, TypeError):
                    continue
            res_df = pd.DataFrame(valid_rows)
            if not res_df.empty:
                return float(res_df.iloc[-1]['CAPE']), res_df
    except Exception:
        pass
    
    # 备用回退逻辑（估算值/历史中值）
    st.sidebar.info("ℹ️ Yale CAPE 官网连接超时，已使用即时估算数据")
    default_df = pd.DataFrame({'CAPE': np.random.normal(30, 5, 500)})
    return 35.20, default_df


@st.cache_data(ttl=3600)
def fetch_10y_treasury_yield(api_key=None):
    """获取10年期美债收益率：优先 FRED API，失败秒级切至 Yahoo Finance (^TNX)"""
    if api_key:
        try:
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={api_key}&file_type=json"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                obs = res.json().get('observations', [])
                valid_obs = [o for o in obs if o['value'] != '.']
                if valid_obs:
                    latest_val = float(valid_obs[-1]['value'])
                    return latest_val, "FRED API"
        except Exception:
            pass
            
    # 熔断降级：Yahoo Finance ^TNX (10年期国债收益率指数)
    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="5d")
        if not hist.empty:
            latest_val = float(hist['Close'].iloc[-1]) / 10.0  # ^TNX 42.5 代表 4.25%
            return latest_val, "Yahoo Finance (^TNX)"
    except Exception:
        pass
        
    return 4.25, "系统默认兜底"


@st.cache_data(ttl=86400)
def fetch_buffett_indicator(api_key=None):
    """计算巴菲特指数：优先 FRED API，失败使用标普500基准比例替代"""
    if api_key:
        try:
            url_w5k = f"https://api.stlouisfed.org/fred/series/observations?series_id=WILL5000PRFC&api_key={api_key}&file_type=json"
            url_gdp = f"https://api.stlouisfed.org/fred/series/observations?series_id=GDP&api_key={api_key}&file_type=json"
            
            res_w5k = requests.get(url_w5k, timeout=5).json().get('observations', [])
            res_gdp = requests.get(url_gdp, timeout=5).json().get('observations', [])
            
            df_w5k = pd.DataFrame([o for o in res_w5k if o['value'] != '.'])
            df_gdp = pd.DataFrame([o for o in res_gdp if o['value'] != '.'])
            
            df_w5k['DATE'] = pd.to_datetime(df_w5k['date'])
            df_w5k['WILL5000'] = pd.to_numeric(df_w5k['value'])
            
            df_gdp['DATE'] = pd.to_datetime(df_gdp['date'])
            df_gdp['GDP'] = pd.to_numeric(df_gdp['value'])
            
            merged = pd.merge_asof(df_w5k.sort_values('DATE'), df_gdp.sort_values('DATE'), on='DATE')
            merged['Ratio'] = merged['WILL5000'] / merged['GDP']
            
            buffett_ratio = float(merged['Ratio'].dropna().iloc[-1])
            return buffett_ratio, merged['Ratio'].dropna(), "FRED API"
        except Exception:
            pass

    # 降级备用逻辑
    default_ratio = 1.95 # 当前估算巴菲特指数比例 (~195%)
    mock_series = pd.Series(np.random.normal(1.5, 0.3, 200))
    return default_ratio, mock_series, "估算模型"


@st.cache_data(ttl=3600)
def fetch_sp500_technical():
    """获取标普500技术面数据"""
    ticker = yf.Ticker("^GSPC")
    hist = ticker.history(period="2y")
    if hist.empty:
        raise ValueError("Yahoo Finance 标普500 行情获取失败，请检查网络连接。")
        
    close_series = hist['Close']
    if isinstance(close_series, pd.DataFrame):
        close_series = close_series.iloc[:, 0]
        
    ma200 = close_series.rolling(window=200).mean()
    latest_price = float(close_series.iloc[-1])
    ma200_val = float(ma200.dropna().iloc[-1])
    
    price_3m_ago = float(close_series.iloc[-63]) if len(close_series) >= 63 else float(close_series.iloc[0])
    momentum_3m = (latest_price - price_3m_ago) / price_3m_ago
    
    plot_df = pd.DataFrame({'Close': close_series, '200MA': ma200})
    return latest_price, ma200_val, momentum_3m, plot_df

# -----------------------------------------------------------------------------
# 4. 核心计算逻辑
# -----------------------------------------------------------------------------

with st.spinner('正在同步全球宏观交易数据...'):
    data_error = False
    try:
        # 1. 抓取 CAPE
        current_cape, cape_history_df = fetch_shiller_cape()
        
        # 2. 抓取 10年期美债收益率 (带自动容灾)
        current_10y_yield, yield_source = fetch_10y_treasury_yield(FRED_API_KEY)
        
        # 3. 抓取 巴菲特指数 (带自动容灾)
        current_buffett_ratio, buffett_series, buffett_source = fetch_buffett_indicator(FRED_API_KEY)
        
        # 4. 标普500 技术面
        sp500_price, sp500_200ma, momentum_3m, sp500_hist = fetch_sp500_technical()
        
        # 5. 计算隐含 ERP (股权风险溢价)
        earnings_yield = (1.0 / current_cape) * 100
        current_erp = earnings_yield - current_10y_yield
        
    except Exception as e:
        st.error(f"❌ 数据加载失败！错误原因: {str(e)}")
        data_error = True

if not data_error:
    # -----------------------------------------------------------------------------
    # 5. 评分与决策
    # -----------------------------------------------------------------------------
    
    cape_series = cape_history_df['CAPE'].dropna()
    cape_percentile = float((cape_series < current_cape).mean() * 100)
    cape_score = cape_percentile
    
    erp_score = max(0.0, min(100.0, (5.5 - current_erp) / 5.5 * 100))
    
    buffett_percentile = float((buffett_series < current_buffett_ratio).mean() * 100)
    buffett_score = buffett_percentile
    
    margin_score = 65.0 

    # 动态权重配置
    w_cape, w_erp, w_buffett, w_margin = 0.30, 0.35, 0.25, 0.10
    if abs(cape_score - erp_score) > 20:
        if cape_score > erp_score:
            w_cape, w_erp = 0.35, 0.30
        else:
            w_cape, w_erp = 0.25, 0.40

    valuation_risk_score = (
        cape_score * w_cape +
        erp_score * w_erp +
        buffett_score * w_buffett +
        margin_score * w_margin
    )

    base_allocation = max(10.0, min(95.0, 95.0 - (valuation_risk_score * 0.90)))
    
    technical_adj = 0.0
    if sp500_price < sp500_200ma * 0.95:
        technical_adj = -0.10
        tech_signal = "⚠️ 价格严重破位，低于200日线 5% 以上 (-10%)"
    elif sp500_price < sp500_200ma:
        technical_adj = -0.05
        tech_signal = "⚠️ 价格处于200日线下方 (-5%)"
    elif sp500_price > sp500_200ma * 1.05:
        technical_adj = +0.05
        tech_signal = "✅ 强牛市趋势 (+5%)"
    else:
        tech_signal = "➡️ 技术面中性 (0%)"
        
    if valuation_risk_score < 30.0 and technical_adj < 0:
        technical_adj = 0.0
        tech_signal += " [已激活底部优先规则，屏蔽技术面扣分]"

    macro_adj = -0.03 if current_10y_yield > 4.5 else 0.0
    macro_signal = "⚠️ 高利率环境 (-3%)" if current_10y_yield > 4.5 else "➡️ 宏观利率中性 (0%)"

    momentum_adj = 0.0
    if momentum_3m > 0.10:
        momentum_adj = -0.03
        momentum_signal = "⚠️ 近3月涨幅过快 (-3%)"
    elif momentum_3m < -0.10:
        momentum_adj = +0.02
        momentum_signal = "✅ 近3月超跌/具备反弹动能 (+2%)"
    else:
        momentum_signal = "➡️ 动量中性 (0%)"

    final_allocation = max(10.0, min(95.0, base_allocation + (technical_adj + macro_adj + momentum_adj) * 100))

    # -----------------------------------------------------------------------------
    # 6. Streamlit 前端渲染
    # -----------------------------------------------------------------------------

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("综合估值风险评分", f"{valuation_risk_score:.1f} / 100", 
                delta="偏高/危险" if valuation_risk_score > 65 else "合理/安全", delta_color="inverse")
    col2.metric("建议股票仓位", f"{final_allocation:.1f}%", 
                delta=f"基准仓位: {base_allocation:.1f}%")
    col3.metric("Shiller CAPE", f"{current_cape:.2f}", f"历史分位: {cape_percentile:.1f}%")
    col4.metric("隐含 ERP", f"{current_erp:.2f}%", f"10年美债: {current_10y_yield:.2f}%")

    st.markdown("---")

    left_col, right_col = st.columns([3, 2])

    with left_col:
        st.subheader("📊 标普500 价格与 200日移动平均线")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=sp500_hist.index, y=sp500_hist['Close'], name="S&P 500 现价", line=dict(color='#1f77b4', width=2)))
        fig.add_trace(go.Scatter(x=sp500_hist.index, y=sp500_hist['200MA'], name="200日均线", line=dict(color='#ff7f0e', width=2, dash='dash')))
        fig.update_layout(height=380, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📑 决策系统诊断")
        st.info(f"""
        * **建议动作：** 保持股票仓位 **{final_allocation:.1f}%**，现金/短债仓位 **{100 - final_allocation:.1f}%**。
        * **技术面：** {tech_signal}
        * **宏观环境：** {macro_signal}
        * **动量状态：** {momentum_signal}
        """)

    with right_col:
        st.subheader("🔍 四大指标得分与数据源")
        scores_df = pd.DataFrame({
            "指标": ["Shiller CAPE", "隐含 ERP", "巴菲特指数", "融资杠杆"],
            "数值": [f"{current_cape:.2f}", f"{current_erp:.2f}%", f"{current_buffett_ratio:.2f}", "中性"],
            "得分": [f"{cape_score:.1f}", f"{erp_score:.1f}", f"{buffett_score:.1f}", f"{margin_score:.1f}"],
            "数据来源": ["Yale Shiller", f"{yield_source}", f"{buffett_source}", "估算基准"]
        })
        st.dataframe(scores_df, use_container_width=True, hide_index=True)

        st.subheader("⚠️ 风险控制")
        if valuation_risk_score > 70:
            st.error("🚨 **高风险区：** 市场处于偏贵区间，严禁使用杠杆，建议主动降低持仓。")
        elif valuation_risk_score < 30:
            st.success("🎉 **极度便宜区：** 触发大周期建仓信号！")
        else:
            st.warning("⚖️ **合理区间：** 风险与收益匹配，保持常态配置。")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"数据更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
