import json
import os
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="大周期宏观风险 Dashboard", page_icon="📊", layout="wide"
)


@st.cache_data(ttl=60)
def load_data():
  with open("data/latest_scores.json", "r", encoding="utf-8") as f:
    return json.load(f)


data = load_data()


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
current_zone = get_indicator_status(score)

col_score, col_status = st.columns([1, 2])
with col_score:
  st.metric(label="综合宏观风险得分 (CMRS)", value=f"{score:.1f} / 100")
with col_status:
  st.subheader(f"当前市场状态: {current_zone}")

# --- 1. 使用指南折叠框 ---
with st.expander("📖 首次使用？点击查看 Dashboard 使用指南与四大风控区间"):
  st.markdown("""
    ### 🎯 本 Dashboard 的核心目的
    本系统旨在通过**大周期宏观基本面与估值指标**，评估当前市场所处的宏观风险阶段，帮助投资者进行**战术性资产配置**。

    ### 🚦 风险得分 (CMRS) 与四大战术指令区间
    * **0 - 25 分 (🟢 低风险买入区)**：建议保持高权益仓位（**80%-100%**），积极建仓。
    * **25 - 55 分 (🔵 合理持股区)**：建议保持标准权益仓位（**50%-70%**），安心持股享受复利。
    * **55 - 75 分 (🟡 风控警戒区)**：建议降低权益仓位（**30%-50%**），停止追高，分批锁定利润。
    * **75 - 100 分 (🔴 极端泡沫区)**：触发 SOP 强制避险指令，权益仓位削减至 **10%-20%**，大部分资金回归短债/现金避风港。
    """)

st.divider()

# --- 2. 自动化 SOP 投资执行指令与交互计算器 ---
st.header("🎯 自动化 SOP 投资执行指令")
sop = data.get("sop_instructions", {})

col1, col2 = st.columns(2)
with col1:
  st.info(f"**目标权益仓位 (股票/ETF):** {sop.get('target_equity_pct')}")
with col2:
  st.success(f"**目标固收仓位 (现金/短债):** {sop.get('target_cash_pct')}")

# 🧮 动态调仓算数计算器
st.subheader("🧮 SOP 动态调仓试算器")
portfolio_val = st.number_input("请输入您的当前可投资资产总额 ($ / ¥)：", min_value=0, value=100000, step=10000)

# 解析当前区间对应的比率（以极端泡沫区 10%-20% 为例）
if score >= 75:
  eq_min, eq_max = 0.10, 0.20
elif score >= 55:
  eq_min, eq_max = 0.30, 0.50
elif score >= 25:
  eq_min, eq_max = 0.50, 0.70
else:
  eq_min, eq_max = 0.80, 1.00

cash_min, cash_max = (1 - eq_max), (1 - eq_min)

c_calc1, c_calc2 = st.columns(2)
with c_calc1:
  st.metric(
      label="💡 建议股票 / ETF 目标金额",
      value=f"${portfolio_val * eq_min:,.0f} - ${portfolio_val * eq_max:,.0f}",
  )
with c_calc2:
  st.metric(
      label="🛡️ 建议现金 / 短债 目标金额",
      value=f"${portfolio_val * cash_min:,.0f} - ${portfolio_val * cash_max:,.0f}",
  )

st.write("📋 **具体执行步骤：**")
for step in sop.get("execution_steps", []):
  st.markdown(f"- {step}")

st.divider()

# --- 3. 📈 CMRS 历史得分走势图 ---
csv_path = "data/history_scores.csv"
if os.path.exists(csv_path):
  st.header("📈 CMRS 历史风险得分走势")
  df_hist = pd.read_csv(csv_path)

  if not df_hist.empty:
    fig = px.line(
        df_hist,
        x="date",
        y="cmrs_score",
        title="CMRS 历史走势与关键警戒线",
        markers=True,
        labels={"date": "日期", "cmrs_score": "综合风险得分"},
    )
    # 增加阈值警戒线
    fig.add_hline(
        y=75,
        line_dash="dash",
        line_color="red",
        annotation_text="🔴 极端泡沫线 (75)",
    )
    fig.add_hline(
        y=55,
        line_dash="dash",
        line_color="orange",
        annotation_text="🟡 风控警戒线 (55)",
    )
    fig.add_hline(
        y=25,
        line_dash="dash",
        line_color="green",
        annotation_text="🟢 低风险买入线 (25)",
    )
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- 4. 四大子指标明细与即时评估 ---
st.header("🔍 四大子指标明细与即时评估")
indicators = data.get("indicators", {})

metrics_config = [
    (
        "股权风险溢价 (ERP)",
        "erp",
        lambda x: f"{x * 100:.1f}%",
        "股权风险溢价 = 股票预期收益率 - 无风险利率。负值表示买股票的回报率不如买国债。",
    ),
    (
        "席勒市盈率 (CAPE)",
        "cape",
        lambda x: f"{x:.2f}",
        "席勒市盈率剔除了通胀影响，用过去 10 年平均利润计算。>35 通常意味着极度泡沫。",
    ),
    (
        "巴菲特指数",
        "buffett",
        lambda x: f"{x * 100:.1f}%",
        "巴菲特指数 = 股市总市值 / GDP。衡量股市是否严重脱离实体经济基本面。",
    ),
    (
        "保证金债务 / GDP",
        "margin_debt",
        lambda x: f"{x * 100:.1f}%",
        "保证金债务/GDP 衡量杠杆炒股的狂热程度。极高分位数意味着踩踏风控风险极高。",
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

# --- 5. 深度通俗拆解 ---
with st.expander("💡 为什么看这四个指标？点击查看四大指标深度通俗拆解"):
  st.markdown("""
    #### 1. 📊 股权风险溢价 (ERP)
    * **呈现形式**：**百分比** (如 `-1.0%`)。
    * **含义**：衡量“买股票比买无风险国债多赚的回报”。负数说明**买股票不如买无风险国债划算**。

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
