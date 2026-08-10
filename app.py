import json
import streamlit as st

st.set_page_config(
    page_title="大周期宏观风险 Dashboard", page_icon="📊", layout="wide"
)


@st.cache_data(ttl=60)
def load_data():
  with open("data/latest_scores.json", "r", encoding="utf-8") as f:
    return json.load(f)


data = load_data()


# 根据分位数或得分输出四区间状态
def get_indicator_status(percentile):
  if percentile >= 75:
    return "🔴 极端泡沫区"
  elif percentile >= 55:
    return "🟡 风控警戒区"
  elif percentile >= 25:
    return "🔵 合理持股区"
  else:
    return "🟢 低风险买入区"


# --- 顶部标题与说明 ---
st.title("📈 大周期宏观风险 Dashboard")
st.caption(
    f"数据更新日期: {data.get('timestamp')} (基于 30 年动态分位数模型)"
)

score = data.get("cmrs_score", 0)

# 计算当前得分属于四大区间中的哪一个
current_zone = get_indicator_status(score)

col_score, col_status = st.columns([1, 2])
with col_score:
  st.metric(label="综合宏观风险得分 (CMRS)", value=f"{score:.1f} / 100")
with col_status:
  st.subheader(f"当前市场状态: {current_zone}")

# --- 1. 使用指南折叠框（更新为四大区间） ---
with st.expander("📖 首次使用？点击查看 Dashboard 使用指南与四大风控区间"):
  st.markdown("""
    ### 🎯 本 Dashboard 的核心目的
    本系统旨在通过**大周期宏观基本面与估值指标**，评估当前市场（主要为美股）所处的宏观风险阶段，帮助投资者进行**战术性资产配置**。

    ### 🚦 风险得分 (CMRS) 与四大战术指令区间
    * **0 - 25 分 (🟢 低风险买入区)**：市场严重低估或处于周期底部，建议保持高权益仓位（**80%-100%**），适合积极建仓。
    * **25 - 55 分 (🔵 合理持股区)**：市场估值处于合理区间，建议保持标准权益仓位（**50%-70%**），安心持股享受增长。
    * **55 - 75 分 (🟡 风控警戒区)**：市场估值开始偏高，建议降低权益仓位（**30%-50%**），停止追高，分批锁定利润。
    * **75 - 100 分 (🔴 极端泡沫区)**：各项指标触发历史极值，触发 SOP 强制避险指令，权益仓位削减至 **10%-20%**，大部分资金回归短债/现金避风港。
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

# --- 3. 四大子指标明细（带格式化数值与四区间评估） ---
st.header("🔍 四大子指标明细与即时评估")

indicators = data.get("indicators", {})

metrics_config = [
    (
        "股权风险溢价 (ERP)",
        "erp",
        lambda x: f"{x * 100:.1f}%",
        (
            "股权风险溢价 = 股票预期收益率 -"
            " 无风险利率。负值表示买股票的回报率甚至不如买国债。"
        ),
    ),
    (
        "席勒市盈率 (CAPE)",
        "cape",
        lambda x: f"{x:.2f}",
        (
            "席勒市盈率剔除了通胀影响，用过去 10 年平均利润计算。>35"
            " 通常意味着极度泡沫。"
        ),
    ),
    (
        "巴菲特指数",
        "buffett",
        lambda x: f"{x * 100:.1f}%",
        (
            "巴菲特指数 = 股市总市值 / GDP。"
            " 衡量股市是否严重脱离实体经济基本面。"
        ),
    ),
    (
        "保证金债务 / GDP",
        "margin_debt",
        lambda x: f"{x * 100:.1f}%",
        (
            "保证金债务/GDP"
            " 衡量杠杆炒股的狂热程度。极高分位数意味着踩踏风控风险极高。"
        ),
    ),
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
    st.caption(f"**状态评估: {status_tag}**")
    st.metric(
        label=name,
        value=formatted_val,
        delta=f"历史风险分位数: {pct_val:.1f}%",
        delta_color="inverse",
        help=help_text,
    )

# --- 4. 深度通俗拆解 ---
with st.expander("💡 为什么看这四个指标？点击查看四大指标深度通俗拆解"):
  st.markdown("""
    #### 1. 📊 股权风险溢价 (ERP)
    * **呈现形式**：**百分比** (如 `-1.0%`)。
    * **含义**：衡量“买股票比买无风险国债多赚的回报”。负数说明**买股票甚至不如买无风险国债划算**。

    #### 2. 📈 席勒市盈率 (CAPE)
    * **呈现形式**：**倍数** (如 `41.20`)。
    * **含义**：剔除短期波动，用过去 10 年平均利润计算的长期估值。历史正常范围在 15-25。

    #### 3. 🏢 巴菲特指数
    * **呈现形式**：**百分比** (如 `220.0%`)。
    * **含义**：股市总市值占 GDP 的比例。`<80%` 为低估，`>120%` 偏贵，`>200%` 说明股市严重脱离实体经济。

    #### 4. 💸 保证金债务 / GDP
    * **呈现形式**：**百分比** (如 `5.0%`)。
    * **含义**：借钱炒股的资金量占 GDP 比例。比例极高时，大盘稍有风吹草动就容易引发强制平仓踩踏。
    """)
