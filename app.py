import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import plotly.graph_objects as go
import re

st.set_page_config(page_title="iShares 官方 ETF 数据实时解析器", page_icon="🏛️", layout="wide")

# iShares 常用国债 ETF 的官方 Product ID / URL 映射
ISHARES_ETFS = {
    "TLT": {
        "name": "iShares 20+ Year Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf",
        "default_duration": 16.5
    },
    "IEF": {
        "name": "iShares 7-10 Year Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239456/ishares-710-year-treasury-bond-etf",
        "default_duration": 7.2
    },
    "SHY": {
        "name": "iShares 1-3 Year Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239452/ishares-13-year-treasury-bond-etf",
        "default_duration": 1.9
    },
    "GOVT": {
        "name": "iShares U.S. Treasury Bond ETF",
        "url": "https://www.ishares.com/us/products/239468/ishares-us-treasury-bond-etf",
        "default_duration": 6.1
    }
}

# ---------------------------------------------------------
# 从 iShares 官网抓取 SEC Yield 和 Effective Duration 的函数
# ---------------------------------------------------------
@st.cache_data(ttl=3600)  # 缓存 1 小时，提高加载速度
def fetch_ishares_official_data(url):
    # 伪装真实的浏览器 User-Agent 绕过 iShares 反爬虫拦截
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"HTTP {response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        
        # 1. 匹配 30-Day SEC Yield
        sec_yield = None
        # 寻找包含 "30 Day SEC Yield" 附近的百分比数值
        sec_match = re.search(r'30\s*Day\s*SEC\s*Yield.*?\b(\d+\.\d+)%', page_text, re.IGNORECASE | re.DOTALL)
        if sec_match:
            sec_yield = float(sec_match.group(1))
            
        # 2. 匹配 Effective Duration (久期)
        duration = None
        dur_match = re.search(r'Effective\s*Duration.*?\b(\d+\.\d+)', page_text, re.IGNORECASE | re.DOTALL)
        if dur_match:
            duration = float(dur_match.group(1))

        return {
            "status": "success",
            "sec_yield": sec_yield,
            "duration": duration
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ---------------------------------------------------------
# UI 布局
# ---------------------------------------------------------
st.title("🏛️ iShares 官网直连 — 官方 30-Day SEC Yield 计算器")

selected_ticker = st.sidebar.selectbox("选择 iShares 旗下 ETF:", list(ISHARES_ETFS.keys()))
etf_info = ISHARES_ETFS[selected_ticker]

# 抓取官方数据
with st.spinner(f"正在读取 iShares 官网页面 ({selected_ticker})..."):
    official_data = fetch_ishares_official_data(etf_info["url"])

if official_data["status"] == "success" and official_data["sec_yield"] is not None:
    fetched_sec_yield = official_data["sec_yield"]
    fetched_duration = official_data["duration"] or etf_info["default_duration"]
    st.success("✅ 已成功从 iShares 官网同步最精确的官方 30-Day SEC Yield 数据！")
else:
    # 兜底回退逻辑（防止官网网页 DOM 结构调整导致正则失效）
    st.warning("⚠️ 未能从官网页面自动解析出最新数据，使用预设兜底数据。")
    fetched_sec_yield = 5.17
    fetched_duration = etf_info["default_duration"]

# 展示官方抓取到的指标卡片
c1, c2, c3 = st.columns(3)
c1.metric("官网 30-Day SEC Yield", f"{fetched_sec_yield}%")
c2.metric("官网有效久期 (Effective Duration)", f"{fetched_duration} 年")
c3.markdown(f"[🔗 点击查看 iShares {selected_ticker} 原始官网页面]({etf_info['url']})")

st.markdown("---")

# 情景推演控件
principal = st.number_input("投资本金 (USD):", value=10000, step=1000)
rate_change = st.slider("美联储未来利率变动预测 (%)", min_value=-2.5, max_value=2.5, value=-0.5, step=0.25)
years = st.slider("预计持有年限 (年)", min_value=0.5, max_value=3.0, value=1.0, step=0.5)

# 根据官网数据算总收益
annual_interest = principal * (fetched_sec_yield / 100) * years
price_change = principal * (-1 * fetched_duration * (rate_change / 100))
total_return = annual_interest + price_change
total_pct = (total_return / principal) * 100

st.subheader("📊 收益计算结果")
res1, res2, res3 = st.columns(3)
res1.metric("预估总收益 (USD)", f"${total_return:,.2f}", delta=f"{total_pct:.2f}%")
res2.metric("纯利息收益 (官方 Yield 驱动)", f"${annual_interest:,.2f}")
res3.metric("股价资本利得 (久期驱动)", f"${price_change:,.2f}")
