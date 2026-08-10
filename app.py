import streamlit as st
import json

st.set_page_config(page_title="大周期宏观风险 Dashboard", page_icon="📊", layout="wide")

@st.cache_data(ttl=60)
def load_data():
    with open("data/latest_scores.json", "r", encoding="utf-8") as f:
        return json.load(f)

data = load_data()

# 辅助函数：根据分位数输出直观判断结果与颜色标志
def get_indicator_status(percentile):
    if percentile >= 85:
        return "🔴 极端高估/极高风险"
    elif percentile >= 70:
        return "🟠 偏高/中度风险"
    elif percentile >= 40:
        return "🟡 合理/温和状态"
    else:
        return "🟢 低估/安全区域"

# --- 顶部标题与说明 ---
st.title("📈 大周期宏观风险 Dashboard")
st.caption(f"数据更新日期: {data.get('timestamp')} (基于 30 年动态分位数模型)")

score = data.get("cmrs_score", 0)
zone = data.get("risk_zone", "未知")

col_score, col_status = st.columns([1, 2])
with col_score:
    st.metric(label="综合宏观风险得分 (CMRS)", value=f"{score:.1f} / 100")
with col_status:
    st.subheader(f"当前市场状态: 🔴 {zone}")

# --- 1. 使用指南折叠框 ---
with st.expander("📖 首次使用？点击查看 Dashboard 使用指南与设计逻辑"):
    st.markdown("""
    ### 🎯 本 Dashboard 的核心目的
    本系统旨在通过**大周期宏观基本面与估值指标**，评估当前市场（主要为美股）所处的宏观风险阶段，帮助投资者进行**战术性资产配置**。

    ### 🚥 风险得分 (CMRS) 与风控区间说明
    * **0 - 40 分 (安全区 / 🟢)**：建议保持标准或高权益仓位（60%+）。
    * **40 - 75 分 (警戒区 / 🟡)**：建议分批锁定利润，降低 Beta 敞口。
    * **75 - 100 分 (极端泡沫区 / 🔴)**：建议将权益仓位削减至 10%-20%，大部分资金回归避风港。
    """)

st.divider()

# --- 2. 自动化 SOP 投资执行指令 ---
st.header("🎯 自动化 SOP 投资执行指令")
sop = data.get("sop_instructions", {})

col1, col2 = st.columns(2)
with col1:
    st.info(f"**目标权益仓位 (股票/ETF):** {sop.get('target_equity_pct')}")
with col2:
    st.success(f"**目标固收仓位 (现金/短债):** {sop.get('target_cash_pct')}")

st.subheader("📋 具体执行步骤：")
for step in sop.get("execution_steps", []):
    st.markdown(f"- {step}")

st.divider()

# --- 3. 四大子指标明细（带格式化数值与即时判断） ---
st.header("🔍 四大子指标明细与即时评估")

indicators = data.get("indicators", {})

# 配置四大指标的展示参数: (名称, 键名, 格式化规则, 悬停解释)
metrics_config = [
    (
        "股权风险溢价 (ERP)",
        "erp",
        lambda x: f"{x * 100:.1f}%",  # 小数转百分比
        "股权风险溢价 = 股票预期收益率 - 无风险利率。负值表示买股票的回报率甚至不如买国债。"
    ),
    (
        "席勒市盈率 (CAPE)",
        "cape",
        lambda x: f"{x:.2f}",         # 保持倍数显示
        "席勒市盈率剔除了通胀影响，用过去 10 年平均利润计算。>35 通常意味着极度泡沫。"
    ),
    (
        "巴菲特指数",
        "buffett",
        lambda x: f"{x * 100:.1f}%",  # 小数转百分比
        "巴菲特指数 = 股市总市值 / GDP。衡量股市是否严重脱离实体经济基本面。"
    ),
    (
        "保证金债务 / GDP",
        "margin_debt",
        lambda x: f"{x * 100:.1f}%",  # 小数转百分比
        "保证金债务/GDP 衡量杠杆炒股的狂热程度。极高分位数意味着踩踏风控风险极高。"
    )
]

m1, m2, m3, m4 = st.columns(4)
cols = [m1, m2, m3, m4]

for (name, key, fmt_func, help_text), col in zip(metrics_config, cols):
    ind = indicators.get(key, {})
    raw_val = ind.get("raw_value", 0)
    pct_val = ind.get("percentile_score", 0)
    
    formatted_val = fmt_func(raw_val)
    status_tag = get_indicator_status(pct_val)

    with col:
        # 显示即时判断标签
        st.caption(f"**状态评估: {status_tag}**")
        st.metric(
            label=name,
            value=formatted_val,
            delta=f"历史风险分位数: {pct_val:.1f}%",
            delta_color="inverse",
            help=help_text
        )

# --- 4. 深度通俗拆解 ---
with st.expander("💡 为什么看这四个指标？点击查看四大指标深度通俗拆解"):
    st.markdown("""
    #### 1. 📊 股权风险溢价 (ERP)
    * **当前呈现**：**百分比形式** (如 `-1.0%`)。
    * **含义**：衡量“买股票比买无风险国债多赚的回报”。负数说明**买股票甚至不如买无风险国债划算**。

    #### 2. 📈 席勒市盈率 (CAPE)
    * **当前呈现**：**倍数形式** (如 `41.20`)。
    * **含义**：剔除短期波动，用过去 10 年平均利润计算的长期估值。历史正常范围在 15-25。

    #### 3. 🏢 巴菲特指数
    * **当前呈现**：**百分比形式** (如 `220.0%`)。
    * **含义**：股市总市值占 GDP 的比例。`>120%` 偏贵，`>200%` 说明股市严重脱离实体经济。

    #### 4. 💸 保证金债务 / GDP
    * **当前呈现**：**百分比形式** (如 `5.0%`)。
    * **含义**：借钱炒股的资金量占 GDP 比例。比例极高时，大盘稍有风吹草动就容易引发强制平仓踩踏。
    """)
