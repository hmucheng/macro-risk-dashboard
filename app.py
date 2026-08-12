import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import io
import requests

# -----------------------------------------------------------------------------
# 页面基本配置
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="宏观大周期交易决策系统",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🛡️ 宏观大周期交易决策系统 (3-10年期)")
st.caption("真实数据驱动：Yale Shiller | 美联储 FRED | Yahoo Finance")
st.markdown("---")

# -----------------------------------------------------------------------------
# 1. 真实数据抓取模块 (增强容错与列名归一化)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=86400) # 缓存24小时
def fetch_shiller_cape():
    """从耶鲁大学官网直接读取 Shiller CAPE 官方 Excel 文件"""
    url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    response = requests.get(url, headers=headers, timeout=20)
    
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
def fetch_fred_series(series_id):
    """直接从美联储 FRED 抓取 CSV 并强制归一化列名"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    res = requests.get(url, headers=headers, timeout=20)
    if res.status_code != 200:
        raise ValueError(f"无法获取 FRED 数据集 [{series_id}]，状态码: HTTP {res.status_code}")
        
    df = pd.read_csv(io.StringIO(res.text))
    
    # 强制将所有列名转换为去除空格的大写字母，解决 date 与 DATE 不匹配问题
    df.columns = [str(c).strip().upper() for c in df.columns]
    
    if 'DATE' not in df.columns:
        raise ValueError(f"FRED 数据集 [{series_id}] 响应中缺失 DATE 列，收到的列为: {list(df.columns)}")
        
    df['DATE'] = pd.to_datetime(df['DATE'], errors='coerce')
    
    # 获取数值列（排除 DATE 之外的列）
    val_cols = [c for c in df.columns if c != 'DATE']
    if not val_cols:
        raise ValueError(f"FRED 数据集 [{series_id}] 未找到有效数值列。")
        
    target_col = val_cols[0]
    df[target_col] = pd.to_numeric(df[target_col], errors='coerce')
    
    df = df.dropna(subset=['DATE', target_col]).sort_values('DATE').reset_index(drop=True)
    df = df.rename(columns={target_col: series_id})
    
    return df[['DATE', series_id]]


@st.cache_data(ttl=3600)
def fetch_sp500_technical():
    """从 Yahoo Finance 获取标普500最新价格与 200日均线"""
    ticker = yf.Ticker("^GSPC")
    hist = ticker.history(period="2y")
    if hist.empty:
        raise ValueError("Yahoo Finance 标普500行情获取失败。")
        
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
# 2. 数据加载与决策计算
# -----------------------------------------------------------------------------

with st.spinner('正在从耶鲁大学、美联储与 Yahoo Finance 安全同步数据...'):
    data_error = False
    try:
        # A. CAPE
        current_cape, cape_history_df = fetch_shiller_cape()
        
        # B. 10年期美债收益率
        df_10y = fetch_fred_series("DGS10")
        current_10y_yield = float(df_10y['DGS10'].iloc[-1])
        
        # C. 名义 GDP
        df_gdp = fetch_fred_series("GDP")
        latest_gdp = float(df_gdp['GDP'].iloc[-1])
        
        # D. 美股总市值指数 (Wilshire 5000)
        df_w5k = fetch_fred_series("WILL5000PRFC")
        
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
    # 3. 风险评分与决策逻辑
    # -----------------------------------------------------------------------------
    
    # 1. CAPE 分位数
    cape_series = cape_history_df['CAPE'].dropna()
    cape_percentile = float((cape_series < current_cape).mean() * 100)
    cape_score = cape_percentile
    
    # 2. ERP 评分
    erp_score = max(0.0, min(100.0, (5.5 - current_erp) / 5.5 * 100))
    
    # 3. 巴菲特指数分位数
    buffett_series = df_buffett['Ratio'].dropna()
    buffett_percentile = float((buffett_series < current_buffett_ratio).mean() * 100)
    buffett_score = buffett_percentile
    
    # 4. 融资杠杆率 (默认基准分位)
    margin_score = 65.0 

    # 动态权重与冲突解决
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

    # 仓位计算与微调
    base_allocation = max(10.0, min(95.0, 95.0 - (valuation_risk_score * 0.90)))
    
    # 技术面信号
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
        
    # 底部优先保护规则
    if valuation_risk_score < 30.0:
        if technical_adj < 0:
            technical_adj = 0.0
            tech_signal += " [已激活底部优先规则，屏蔽技术面扣分]"

    # 宏观与动量调整
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
    # 4. Streamlit 界面呈现
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

    st.sidebar.title("⚙️ 数据源状态")
    st.sidebar.write("🟢 **Yale Shiller Excel:** 正常")
    st.sidebar.write("🟢 **FRED (DGS10 / GDP / W5K):** 正常")
    st.sidebar.write("🟢 **Yahoo Finance (^GSPC):** 正常")
    st.sidebar.markdown("---")
    st.sidebar.caption(f"最后更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
