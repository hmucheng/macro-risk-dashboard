import streamlit as st
import json

st.set_page_config(page_title="大周期宏观风险 Dashboard", page_icon="📊", layout="wide")

@st.cache_data(ttl=60)
def load_data():
    with open("data/latest_scores.json", "r", encoding="utf-8") as f:
        return json.load(f)

data = load_data()

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

# --- 1. 新增：模型使用说明与新手指南 ---
with st.expander("📖 首次使用？点击查看 Dashboard 使用指南与设计逻辑"):
    st.markdown("""
    ### 🎯 本 Dashboard 的核心目的
    本系统旨在通过**大周期宏观基本面与估值指标**，评估当前市场（主要为美股）所处的宏观风险阶段，帮助投资者进行**战术性资产配置**，避免在牛市顶部过度加杠杆，或在熊市底部恐慌抛售。

    ### 🚥 风险得分 (CMRS) 与风控区间说明
    * **0 - 40 分 (安全区 / 🟢)**：市场估值便宜或处于合理区间，建议保持标准或高权益仓位（60%+）。
    * **40 - 75 分 (警戒区 / 🟡)**：市场处于中高估值阶段，建议分批锁定利润，降低 Beta 敞口。
    * **75 - 100 分 (极端泡沫区 / 🔴)**：各项指标触发历史极值，市场风险极高，触发 **SOP 战术收缩指令**，建议将权益仓位削减至 10%-20%，大部分资金回归避风港。
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

# --- 3. 四大子指标明细（带悬停提示与详细释义） ---
st.header("🔍 四大子指标明细")

indicators = data.get("indicators", {})

# 定义各指标的悬停提示 (Help Tooltip)
tooltips = {
    "erp": "股权风险溢价 (ERP) = 股票预期收益率 - 无风险利率。负值表示买股票的回报率甚至不如买国债。",
    "cape": "席勒市盈率 (CAPE) 剔除了通胀影响，用过去 10 年平均利润计算。>35 通常意味着极度泡沫。",
    "buffett": "巴菲特指数 = 股市总市值 / GDP。衡量股市是否严重脱离实体经济基本面。",
    "margin_debt": "保证金债务 / GDP 衡量杠杆炒股的狂热程度。极高分位数意味着踩踏风控风险极高。"
}

metrics = [
    ("股权风险溢价 (ERP)", "erp", tooltips["erp"]),
    ("席勒市盈率 (CAPE)", "cape", tooltips["cape"]),
    ("巴菲特指数", "buffett", tooltips["buffett"]),
    ("保证金债务/GDP", "margin_debt", tooltips["margin_debt"])
]

m1, m2, m3, m4 = st.columns(4)
cols = [m1, m2, m3, m4]

for (name, key, help_text), col in zip(metrics, cols):
    ind = indicators.get(key, {})
    with col:
        st.metric(
            label=name,
            value=f"{ind.get('raw_value', 0):.2f}",
            delta=f"风险分位数: {ind.get('percentile_score', 0):.1f}%",
            delta_color="inverse",
            help=help_text  # 添加悬停提示
        )

# --- 4. 新增：四大指标深度通俗拆解 ---
with st.expander("💡 为什么看这四个指标？点击查看四大指标深度通俗拆解"):
    st.markdown("""
    #### 1. 📊 股权风险溢价 (ERP, Equity Risk Premium)
    * **含义**：衡量“买股票比买无风险国债能多赚多少收益”。
    * **如何参考**：当 ERP 出现负数（分位数 > 90%）时，说明**股票收益率居然比买国债还低**，处于“高风险、低回报”的极端性价比失衡状态。

    #### 2. 📈 席勒市盈率 (CAPE)
    * **含义**：剔除短期经济波动，用**过去 10 年平均利润**计算的长期真实市盈率。
    * **如何参考**：美股历史平均 CAPE 在 15-25 之间。当 CAPE > 40 时，历史上仅出现在 2000 年互联网泡沫和 2021 年顶峰期。

    #### 3. 🏢 巴菲特指数 (Buffett Indicator)
    * **含义**：**股市总市值 / GDP**，即股市规模与实体经济总量的对比。
    * **如何参考**：< 80% 为低估，100% 为合理，> 200% 说明股市脱离实体经济，高度依赖资金推动。

    #### 4. 💸 保证金债务 / GDP (Margin Debt / GDP)
    * **含义**：投资者**借钱炒股（加杠杆）**的总金额占 GDP 的比例。
    * **如何参考**：分位数过高说明散户与机构都在过度加杠杆。一旦市场出现小幅回调，极易引发“强制平仓 -> 抛售 -> 连锁踩踏”。
    """)
