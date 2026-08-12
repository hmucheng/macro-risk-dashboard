import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import io
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
st.caption("真实数据驱动：Yale Shiller | 美联储 FRED 官方 API | Yahoo Finance")
st.markdown("---")

# -----------------------------------------------------------------------------
# 2. 网络请求与 API Key 初始化
# -----------------------------------------------------------------------------

# 自动探测 API Key (优先 Streamlit Secrets，其次环境变量 os.environ)
FRED_API_KEY = None
if "FRED_API_KEY" in st.secrets:
    FRED_API_KEY = st.secrets["FRED_API_KEY"]
elif os.environ.get("FRED_API_KEY"):
    FRED_API_KEY = os.environ.get("FRED_API_KEY")

def get_robust_session():
    """创建一个具备自动重试机制的网络请求 Session"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,  # 失败后等待 1s, 2s, 4s 重试
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# -----------------------------------------------------------------------------
# 3. 官方 API 数据抓取模块
# -----------------------------------------------------------------------------

@st.cache_data(ttl=86400)
def fetch_shiller_cape():
    """从耶鲁大学官网直接读取 Shiller CAPE"""
    session = get_robust_session()
    url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    response = session.get(url, headers=headers, timeout=30)
    if response.status_code != 200:
        raise ValueError(f"无法连接耶鲁大学数据源 (HTTP {response.status_code})")
        
    excel_file = io.BytesIO(response.content)
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
    if res_df.empty:
        raise ValueError("耶鲁 CAPE 数据解析为空，数据源结构可能发生变动。")
        
    return float(res_df.iloc[-1]['CAPE']), res_df


@st.cache_data(ttl=86400)
def fetch_fred_series(series_id, api_key=None):
    """优先使用 FRED 官方 JSON API，无 Key 或异常时降级回退至网页端"""
    session = get_robust_session()
    
    # 路径 A：使用官方 REST API 接口 (最稳定、最快)
    if api_key:
        api_url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"
        try:
            res = session.get(api_url, timeout=30)
            if res.status_code == 200:
                data = res.json()
                obs = data.get('observations', [])
                if obs:
                    df = pd.DataFrame(obs)
                    df['DATE'] = pd.to_datetime(df['date'], errors='coerce')
                    df[series_id] = pd.to_numeric(df['value'], errors='coerce')
                    df = df.dropna(subset=['DATE', series_id]).sort_values('DATE').reset_index(drop=True)
                    return df[['DATE', series_id]]
        except Exception as e:
            st.warning(f"⚠️ FRED API 请求 [{series_id}] 触发异常，准备切换降级通道: {str(e)}")

    # 路径 B：降级网页端 CSV 通道
    csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    res = session.get(csv_url, headers=headers, timeout=35)
    if res.status_code != 200:
        raise ValueError(f"无法获取 FRED 数据集 [{series_id}]，状态码: HTTP {res.status_code}")
        
    df = pd.read_csv(io.StringIO(res.text))
    df.columns = [str(c).strip().upper() for c in df.columns]
    
    if 'DATE' not in df.columns:
        raise ValueError(f"FRED 响应中缺少 DATE 列: {list(df.columns)}")
        
    df['DATE'] = pd.to_datetime(df['DATE'], errors='coerce')
    val_cols = [c for c in df.columns if c != 'DATE']
    target_col = val_cols[0]
    df[target_col] = pd.to_numeric(df[target_col], errors='coerce')
    
    df = df.dropna(subset=['DATE', target_col]).sort_values('DATE').reset_index(drop=True)
    df = df.rename(columns={target_col: series_id})
    
    return df[['DATE', series_id]]


@st.cache_data(ttl=3600)
def fetch_sp500_technical():
    """从 Yahoo Finance 获取标普500数据"""
    ticker = yf.Ticker("^GSPC")
    hist = ticker.history(period="2y")
    if hist.empty:
        raise ValueError("Yahoo Finance 行情获取失败。")
        
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
# 4. 数据加载与核心逻辑计算
# -----------------------------------------------------------------------------

with st.spinner('正在通过美联储官方 API 极速加载真实数据...'):
    data_error = False
    try:
        # A. CAPE
        current_cape, cape_history_df = fetch_shiller_cape()
        
        # B. 10年期美债收益率
        df_10y = fetch_fred_series("DGS10", api_key=FRED_API_KEY)
        current_10y_yield = float(df_10y['DGS10'].iloc[-1])
        
        # C. 名义 GDP
        df_gdp = fetch_fred_series("GDP", api_key=FRED_API_KEY)
        latest_gdp = float(df_gdp['GDP'].iloc[-1])
        
        # D. 美股总市值指数 (Wilshire 5000)
        df_w5k = fetch_fred_series("WILL5000PRFC", api_key=FRED_API_KEY)
        
        # E. 技术面数据
        sp500_price, sp500_200ma, momentum_3m, sp500_hist = fetch_sp500_technical()
        
        # F. 巴菲特指数计算
        df_buffett = pd.merge_asof(df_w5k.sort_values('DATE'), df_gdp.sort_values('DATE'), on='DATE')
        df_buffett['Ratio'] = df_buffett['WILL5000PRFC'] / df_buffett['GDP']
        current_buffett_ratio = float(df_buffett['Ratio'].dropna().iloc[-1])
        
        # G. 隐含 ERP 计算
        earnings_yield = (1.0 / current_cape) * 100
        current_erp = earnings_yield - current_10y_yield
        
    except Exception as e:
        st.error(f"❌ 数据加载失败！系统已停止计算以防止产生错误决策。错误原因: {str(e)}")
        data_error = True

if not data_error:
    # -----------------------------------------------------------------------------
    # 5. 评分与决策归因
    # -----------------------------------------------------------------------------
    
    cape_series = cape_history_df['CAPE'].dropna()
    cape_percentile = float((cape_series < current_cape).mean() * 100)
    cape_score = cape_percentile
    
    erp_score = max(0.0, min(100.0, (5.5 - current_erp) / 5.5 * 100))
    
    buffett_series = df_buffett['Ratio'].dropna()
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
    # 6. Streamlit 渲染 UI
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
        st.subheader("🔍 四大指标得分与权重")
        scores_df = pd.DataFrame({
            "指标": ["Shiller CAPE", "隐含 ERP", "巴菲特指数", "融资杠杆"],
            "原始值": [f"{current_cape:.2f}", f"{current_erp:.2f}%", f"{current_buffett_ratio:.2f}", "中性"],
            "得分": [f"{cape_score:.1f}", f"{erp_score:.1f}", f"{buffett_score:.1f}", f"{margin_score:.1f}"],
            "权重": [f"{w_cape*100:.0f}%", f"{w_erp*100:.0f}%", f"{w_buffett*100:.0f}%", f"{w_margin*100:.0f}%"]
        })
        st.dataframe(scores_df, use_container_width=True, hide_index=True)

        st.subheader("⚠️ 风险控制")
        if valuation_risk_score > 70:
            st.error("🚨 **高风险区：** 市场处于偏贵区间，严禁使用杠杆，建议主动降低持仓。")
        elif valuation_risk_score < 30:
            st.success("🎉 **极度便宜区：** 触发大周期建仓信号！")
        else:
            st.warning("⚖️ **合理区间：** 风险与收益匹配，保持常态配置。")

    st.sidebar.title("⚙️ 数据源与 API 诊断")
    if FRED_API_KEY:
        st.sidebar.success("🟢 **FRED 官方 API Key:** 已检测并生效")
    else:
        st.sidebar.warning("🟡 **FRED API Key:** 未设置 (已启用备用通道)")
        
    st.sidebar.write("🟢 **Yale Shiller Excel:** 正常")
    st.sidebar.write("🟢 **Yahoo Finance (^GSPC):** 正常")
    st.sidebar.markdown("---")
    st.sidebar.caption(f"最后更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
