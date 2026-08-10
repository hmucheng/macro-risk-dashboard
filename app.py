import streamlit as st
import json

st.set_page_config(page_title="大周期宏观风险 Dashboard", page_icon="📊", layout="wide")

@st.cache_data(ttl=60)
def load_data():
    with open("data/latest_scores.json", "r", encoding="utf-8") as f:
        return json.load(f)

data = load_data()

st.title("📈 大周期宏观风险 Dashboard")
st.caption(f"数据更新日期：{data.get('timestamp')} (基于 30 年动态分位数模型)")

score = data.get("cmrs_score", 0)
zone = data.get("risk_zone", "未知")

st.metric(label="综合宏观风险得分 (CMRS)", value=f"{score:.1f} / 100")
st.subheader(f"当前市场状态：🔴 {zone}")

st.divider()

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

st.header("🔍 四大子指标明细")
indicators = data.get("indicators", {})
m1, m2, m3, m4 = st.columns(4)

metrics = [
    ("股权风险溢价 (ERP)", "erp", m1),
    ("席勒市盈率 (CAPE)", "cape", m2),
    ("巴菲特指数", "buffett", m3),
    ("保证金债务/GDP", "margin_debt", m4)
]

for name, key, col in metrics:
    ind = indicators.get(key, {})
    with col:
        st.metric(
            label=name,
            value=f"{ind.get('raw_value', 0):.2f}",
            delta=f"风险分位数: {ind.get('percentile_score', 0):.1f}%",
            delta_color="inverse"
        )
