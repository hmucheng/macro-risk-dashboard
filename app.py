import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import re

st.set_page_config(page_title="iShares 官方 ETF 数据实时解析器", page_icon="🏛️", layout="wide")

# iShares 常用国债 ETF 数据库与参考兜底值
ISHARES_ETFS = {
    "TLT": {
        "name": "iShares 20+ Year Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf",
        "default_duration": 16.5,
        "default_yield": 5.17
    },
    "IEF": {
        "name": "iShares 7-10 Year Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239456/ishares-710-year-treasury-bond-etf",
        "default_duration": 7.2,
        "default_yield": 4.45
    },
    "SHY": {
        "name": "iShares 1-3 Year Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239452/ishares-13-year-treasury-bond-etf",
        "default_duration": 1.9,
        "default_yield": 4.20
    },
    "GOVT": {
        "name": "iShares U.S. Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239468/ishares-us-treasury-bond-etf",
        "default_duration": 6.1,
        "default_yield": 4.35
    }
}

# ---------------------------------------------------------
# 修复后的爬虫解析函数
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_ishares_official_data(ticker, url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    default_yield = ISHARES_ETFS[ticker]["default_yield"]
    default_duration = ISHARES_ETFS[ticker]["default_duration"]
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "fallback", "sec_yield": default_yield, "duration": default_duration}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        # 🔑 关键修复：加入 separator=' '，防止 2026 和 5.17 粘在一起变成 20265.17
        page_text = soup.get_text(separator=' ')
        
        # 1. 精确匹配 30-Day SEC Yield（限制整数部分最多2位数）
        sec_yield = None
        sec_matches = re.findall(r'30\s*Day\s*SEC\s*Yield.*?\b(\d{1,2}\.\d{2})%', page_text, re.IGNORECASE)
        if sec_matches:
            val = float(sec_matches[0])
            # 安全检查：收益率应该在 0% ~ 20% 之间
            if 0 < val < 20:
                sec_yield = val

        # 2. 精确匹配 Effective Duration
        duration = None
        dur_matches = re.findall(r'Effective\s*Duration.*?\b(\d{1,2}\.\d{1,2})\b', page_text, re.IGNORECASE)
        if dur_matches:
            val = float(dur_matches[0])
            # 安全检查：TLT/EDV等长久期品种久期一般 > 0.5
            if val > 0.5:
                duration = val

        # 回退逻辑 (Sanity Check)
        final_yield = sec_yield if sec_yield else default_yield
        final_duration = duration if duration else default_duration

        return {
            "status": "success" if (sec_yield and duration) else "partial",
            "sec_yield": final_yield,
            "duration": final_duration
        }
    except Exception as e:
        return {"status": "fallback", "sec_yield": default_yield, "duration": default_duration}

# ---------------------------------------------------------
# UI 布局
# ---------------------------------------------------------
st.title("🏛️ iShares 官网直连 — 官方 30-Day SEC Yield 计算器")

selected_ticker = st.sidebar.selectbox("选择 iShares 旗下 ETF:", list(ISHARES_ETFS.keys()))
etf_info = ISHARES_ETFS[selected_ticker]

# 抓取数据
with st.spinner(f"正在同步 iShares 官网数据 ({selected_ticker})..."):
    official_data = fetch_ishares_official_data(selected_ticker, etf_info["url"])

fetched_sec_yield = official_data["sec_yield"]
fetched_duration = official_data["duration"]

if official_data["status"] == "success":
    st.success("✅ 已精准抓取并解析 iShares 官网数据！")
else:
    st.info("ℹ️ 官网数据解析受限，已自动启用校验后备数据（确保显示正常）。")

# 指标卡片显示
c1, c2, c3 = st.columns(3)
c1.metric("官网 30-Day SEC Yield", f"{fetched_sec_yield:.2f}%")
c2.metric("官网有效久期 (Duration)", f"{fetched_duration:.2f} 年")
c3.markdown(f"[🔗 点击核对 iShares {selected_ticker} 官网页面]({etf_info['url']})")

st.markdown("---")

# 收益计算器
st.subheader("💡 收益模拟计算")
principal = st.number_input("投资本金 (USD):", value=10000, step=1000)
rate_change = st.slider("美联储未来利率变动预测 (%)", min_value=-2.5, max_value=2.5, value=-0.5, step=0.25, help="负数代表降息，正数代表加息")
years = st.slider("预计持有年限 (年)", min_value=0.5, max_value=3.0, value=1.0, step=0.5)

# 核心计算
annual_interest = principal * (fetched_sec_yield / 100) * years
price_change = principal * (-1 * fetched_duration * (rate_change / 100))
total_return = annual_interest + price_change
total_pct = (total_return / principal) * 100

res1, res2, res3 = st.columns(3)
res1.metric("预估总收益 (USD)", f"${total_return:,.2f}", delta=f"{total_pct:.2f}%")
res2.metric("纯利息收益 ( Yield 驱动)", f"${annual_interest:,.2f}")
res3.metric("股价资本利得 (久期驱动)", f"${price_change:,.2f}")
