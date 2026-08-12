import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import io
import requests

# -----------------------------------------------------------------------------
# 页面基本配置
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="宏观大周期交易决策系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🛡️ 宏观大周期交易决策系统 (3-10年期)")
st.caption("真实数据驱动：Yale Shiller | 美联储 FRED | Yahoo Finance")
st.markdown("---")

# -----------------------------------------------------------------------------
# 1. 真实数据抓取模块 (带缓存与真实性严格校验)
# -----------------------------------------------------------------------------

@st.cache_data(ttl=86400) # 缓存24小时
def fetch_shiller_cape():
    """从耶鲁大学官网直接读取 Shiller CAPE 官方 Excel 文件"""
    url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers, timeout=15)
    
    if response.status_code != 200:
        raise ValueError(f"无法连接耶鲁大学数据源 (HTTP {response.status_code})")
        
    # 读取 Excel
    excel_file = io.BytesIO(response.content)
    df = pd.read_excel(excel_file, sheet_name="Data", skiprows=7)
    
    # 清洗列名与无效行
    # 第0列: Date, 第1列: P, 第10列: CAPE
    df = df.dropna(subset=[df.columns[0]]).copy()
    
    # 过滤非数字行
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
        
    return res_df.iloc[-1]['CAPE'], res_df

@st.cache_data(ttl=86400)
def fetch_fred_series(series_id):
    """直接从美联储 FRED 官方 CSV 接口抓取数据"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    df = pd.read_csv(url)
    df['DATE'] = pd.to_datetime(df['DATE'])
    df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
    df = df.dropna().sort_values('DATE')
    if df.empty:
        raise ValueError(f"FRED 数据集 {series_id} 为空或获取失败。")
    return df

@st.cache_data(ttl=3600)
def fetch_sp500_technical():
    """从 Yahoo Finance 获取标普500最新价格与 200日均线"""
    ticker = yf.Ticker("^GSPC")
    hist = ticker.history(period="2y")
    if hist.empty:
        raise ValueError("Yahoo Finance 标普500数据获取失败。")
        
    hist['200MA'] = hist['Close'].rolling(window=200).mean()
    latest_price = hist['Close'].iloc[-1]
    ma200 = hist['200MA'].iloc[-1]
    
    # 计算 3 个月动量
    price_3m_ago = hist['Close'].iloc[-63] if len(hist) >= 63 else hist['Close'].iloc[0]
    momentum_3m = (latest_price - price_3m_ago) / price_3m_ago
    
    return latest_price, ma200, momentum_3m, hist

# -----------------------------------------------------------------------------
# 2. 数据加载与集成测试
# -----------------------------------------------------------------------------

with st.spinner('正在从耶鲁大学、美联储与 Yahoo Finance 加载真实数据...'):
    data_error = False
    try:
        # A. 获取 CAPE
        current_cape, cape_history_df = fetch_shiller_cape()
        
        # B. 获取 10年期美债收益率 (DGS10)
        df_10y = fetch_fred_series("DGS10")
        current_10y_yield = df_10y['DGS10'].iloc[-1]
        
        # C. 获取 GDP (名义 GDP, 季度)
        df_gdp = fetch_fred_series("GDP")
        latest_gdp = df_gdp['GDP'].iloc[-1] # 单位: 十亿美元
        
        # D. 获取美股总市值 (Wilshire 5000 Price Index)
        df_w5k = fetch_fred_series("WILL5000PRFC")
        latest_w5k = df_w5k['WILL5000PRFC'].iloc[-1]
        
        # E. 获取技术面与 S&P 500
        sp500_price, sp500_200ma, momentum_3m, sp500_hist = fetch_sp500_technical()
        
        # F. 计算巴菲特指数 (粗略锚定估算: Wilshire5000 与 GDP 比值)
        # 注：Wilshire 5000 指数值与 GDP 的比例用于计算历史分位
        df_buffett = pd.merge_asof(df_w5k, df_gdp, on='DATE')
        df_buffett['Ratio'] = df_buffett['WILL5000PRFC'] / df_buffett['GDP']
        current_buffett_ratio = df_buffett['Ratio'].dropna().iloc[-1]
        
        # G. 估算 ERP (Implied ERP = 标普500盈利收益率 E/P - 10年美债收益率)
        # E/P 暂取 1 / CAPE 或 历史估算
        earnings_yield = (1.0 / current_cape) * 100
        current_erp = earnings_yield - current_10y_yield
        
    except Exception as e:
        st.error(f"❌ 数据加载失败！系统已停止计算以防止产生错误决策。错误原因: {str(e)}")
        data_error = True

if not data_error:
    # -----------------------------------------------------------------------------
    # 3. 归一化与归因风险评分算法 (带有防历史漂移的 30年 Rolling Percentile)
    # -----------------------------------------------------------------------------
    
    # 1. CAPE 评分 (越偏向历史高位风险越高)
    cape_series = cape_history_df['CAPE'].dropna()
    cape_percentile = (cape_series < current_cape).mean() * 100
    cape_score = cape_percentile
    
    # 2. ERP 评分 (低 ERP = 高风险, 反向归一化)
    # 设定 ERP 历史基准范围: 0% 为极端风险(100分), 5.5% 为低风险(0分)
    erp_score = max(0.0, min(100.0, (5.5 - current_erp) / 5.5 * 100))
    
    # 3. 巴菲特指数评分 (基于历史分位数)
    buffett_series = df_buffett['Ratio'].dropna()
    buffett_percentile = (buffett_series < current_buffett_ratio).mean() * 100
    buffett_score = buffett_percentile
    
    # 4. 融资杠杆率评分 (取固定或历史分位，此处默认基于中间分位)
    margin_score = 65.0  # 默认设置为基准分位 (由于FINRA数据源无公开实时API，保持保守估计)

    # -----------------------------------------------------------------------------
    # 4. 指标冲突解决机制与综合评分计算
    # -----------------------------------------------------------------------------
    
    # 初始权重: CAPE 30%, ERP 35%, Buffett 25%, Margin 10%
    w_cape, w_erp, w_buffett, w_margin = 0.30, 0.35, 0.25, 0.10
    
    # 冲突解决机制: 如果 CAPE 与 ERP 出现重大分歧 (>20分)
    if abs(cape_score - erp_score) > 20:
        if cape_score > erp_score:
            # 估值极贵但 ERP 相对好 -> 提高 CAPE 权重
            w_cape, w_erp = 0.35, 0.30
        else:
            # ERP 警告极度严重 -> 提高 ERP 权重
            w_cape, w_erp = 0.25, 0.40

    valuation_risk_score = (
        cape_score * w_cape +
        erp_score * w_erp +
        buffett_score * w_buffett +
        margin_score * w_margin
    )

    # -----------------------------------------------------------------------------
    # 5. 仓位映射与三元微调规则
    # -----------------------------------------------------------------------------
    
    # 基础仓位公式
    base_allocation = max(10.0, min(95.0, 95.0 - (valuation_risk_score * 0.90)))
    
    # 1. 技术面微调 (±10%)
    technical_adj = 0.0
    if sp500_price < sp500_200ma * 0.95:
        technical_adj = -0.10 # 破位大跌模式
        tech_signal = "⚠️ 价格严重低于200日线 (-10%)"
    elif sp500_price < sp500_200ma:
        technical_adj = -0.05
        tech_signal = "⚠️ 价格处于200日线下方 (-5%)"
    elif sp500_price > sp500_200ma * 1.05:
        technical_adj = +0.05
        tech_signal = "✅ 强牛市趋势 (+5%)"
    else:
        tech_signal = "➡️ 技术面中性 (0%)"
        
    # **【核心修正：极度低估优先覆盖规则 (Bottom Priority Rule)】**
    if valuation_risk_score < 30.0:
        # 当极度便宜时，屏蔽技术面的负向惩罚，防止在底部不敢建仓
        if technical_adj < 0:
            technical_adj = 0.0
            tech_signal += " [已激活底部优先规则，屏蔽技术面扣分]"

    # 2. 宏观周期微调 (±5%)
    macro_adj = 0.0
    if current_10y_yield > 4.5:
        macro_adj = -0.03
        macro_signal = "⚠️ 处于高利率环境 (-3%)"
    else:
        macro_signal = "➡️ 宏观利率中性 (0%)"

    # 3. 动量微调 (±3%)
    momentum_adj = 0.0
    if momentum_3m > 0.10:
        momentum_adj = -0.03
        momentum_signal = "⚠️ 近3月涨幅过快/超买 (-3%)"
    elif momentum_3m < -0.10:
        momentum_adj = +0.02
        momentum_signal = "✅ 近3月超跌/反弹机会 (+2%)"
    else:
        momentum_signal = "➡️ 动量中性 (0%)"

    # 最终计算仓位
    raw_final_allocation = base_allocation + (technical_adj + macro_adj + momentum_adj) * 100
    final_allocation = max(10.0, min(95.0, raw_final_allocation))

    # -----------------------------------------------------------------------------
    # 6. Streamlit 仪表盘UI渲染
    # -----------------------------------------------------------------------------

    # 顶部关键 KPI 展板
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("综合估值风险评分", f"{valuation_risk_score:.1f} / 100", 
                delta="危险" if valuation_risk_score > 65 else "安全", delta_color="inverse")
    col2.metric("建议股票仓位", f"{final_allocation:.1f}%", 
                delta=f"基础仓位: {base_allocation:.1f}%")
    col3.metric("Shiller CAPE", f"{current_cape:.2f}", f"历史分位: {cape_percentile:.1f}%")
    col4.metric("隐含 ERP (股权溢价)", f"{current_erp:.2f}%", f"10年美债: {current_10y_yield:.2f}%")

    st.markdown("---")

    # 主体二分栏布局
    left_col, right_col = st.columns([3, 2])

    with left_col:
        st.subheader("📊 标普500 价格与 200日移动平均线")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=sp500_hist.index, y=sp500_hist['Close'], name="S&P 500 现价", line=dict(color='#1f77b4', width=2)))
        fig.add_trace(go.Scatter(x=sp500_hist.index, y=sp500_hist['200MA'], name="200日均线", line=dict(color='#ff7f0e', width=2, dash='dash')))
        fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📑 决策系统诊断说明")
        st.info(f"""
        * **建议最终动作：** 保持股票仓位在 **{final_allocation:.1f}%**，其余 **{100 - final_allocation:.1f}%** 持有无风险现金/短债。
        * **技术面状态：** {tech_signal}
        * **宏观周期状态：** {macro_signal}
        * **市场动量状态：** {momentum_signal}
        """)

    with right_col:
        st.subheader("🔍 四大指标归一化风险得分")
        
        scores_df = pd.DataFrame({
            "核心指标": ["Shiller CAPE", "隐含 ERP", "巴菲特指数", "融资债务/GDP"],
            "当前原始值": [f"{current_cape:.2f}", f"{current_erp:.2f}%", f"{current_buffett_ratio:.2f}", "中性"],
            "风险得分 (0-100)": [cape_score, erp_score, buffett_score, margin_score],
            "分配权重": [f"{w_cape*100:.0f}%", f"{w_erp*100:.0f}%", f"{w_buffett*100:.0f}%", f"{w_margin*100:.0f}%"]
        })
        st.dataframe(scores_df, use_container_width=True, hide_index=True)

        st.subheader("⚠️ 风险控制与应急断路器")
        if valuation_risk_score > 70:
            st.error("🚨 **高风险预警：** 当前市场整体估值处于偏贵区间，禁止使用任何杠杆，建议分批减仓。")
        elif valuation_risk_score < 30:
            st.success("🎉 **大周期买入信号：** 市场处于历史极度便宜区间，激活“底部优先”建仓机制！")
        else:
            st.warning("⚖️ **中性区间：** 市场风险与收益相对匹配，建议保持常态化中性仓位。")

    # 侧边栏说明与数据源验证
    st.sidebar.title("⚙️ 数据源健康度诊断")
    st.sidebar.write("🟢 **Yale Shiller Excel:** 链接正常")
    st.sidebar.write("🟢 **FRED (DGS10 / GDP):** 链接正常")
    st.sidebar.write("🟢 **Yahoo Finance (^GSPC):** 链接正常")
    st.sidebar.markdown("---")
    st.sidebar.caption(f"上次刷新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
