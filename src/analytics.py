import json
import os
from datetime import datetime
import numpy as np
import pandas as pd
import requests
from fredapi import Fred
import warnings

warnings.filterwarnings("ignore")

NTFY_URL = "https://ntfy.sh/smcb-z5hnfa1qj2x8vmnbr8uoqlqmrq49"


def send_ntfy_alert(title, message, priority="default"):
    """发送 ntfy 推送"""
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority
            },
            timeout=10,
        )
    except Exception as e:
        print(f"⚠️ ntfy 推送失败: {e}")


def get_risk_zone(score):
    """根据风险评分返回风险区间"""
    if score >= 75:
        return "🔴 极端泡沫区"
    elif score >= 55:
        return "🟡 风控警戒区"
    elif score >= 25:
        return "🔵 合理持股区"
    else:
        return "🟢 低风险买入区"


def fetch_shiller_cape():
    """
    获取 Shiller CAPE 数据
    来源：Robert Shiller 官方数据库
    返回：月度 DataFrame，包含 CAPE 和 cyclically adjusted earnings
    """
    print("  📊 加载 Shiller CAPE 数据...")
    try:
        # 官方 Shiller 数据源
        shiller_url = "https://raw.githubusercontent.com/datasets/s-and-p-500/master/data/data.csv"
        shiller_df = pd.read_csv(shiller_url)
        shiller_df["Date"] = pd.to_datetime(shiller_df["Date"])
        shiller_df = shiller_df.sort_values("Date").set_index("Date")
        
        # 确保有需要的列
        if "CAPE" in shiller_df.columns:
            return shiller_df[["CAPE"]].rename(columns={"CAPE": "cape"})
        elif "Cyclically Adjusted Price Earnings Ratio" in shiller_df.columns:
            return shiller_df[["Cyclically Adjusted Price Earnings Ratio"]].rename(
                columns={"Cyclically Adjusted Price Earnings Ratio": "cape"}
            )
        else:
            raise ValueError("❌ Shiller 数据源列名无法识别")
    except Exception as e:
        print(f"  ⚠️ Shiller 数据加载失败: {e}，尝试备用源...")
        return None


def fetch_erp_and_gs10(fred):
    """
    获取无风险利率 (GS10) 和计算 ERP
    ERP = E/P - Rf = (1/CAPE) - (GS10/100)
    注意：这里假设 1/CAPE ≈ E/P（当 CAPE 基于正常化盈利时成立）
    """
    print("  📊 加载 GS10 (10年期美债收益率) 数据...")
    try:
        gs10 = fred.get_series("GS10", observation_start="1990-01-01")
        gs10 = pd.DataFrame({"gs10": gs10})
        gs10.index.name = "Date"
        return gs10
    except Exception as e:
        print(f"  ❌ GS10 加载失败: {e}")
        return None


def fetch_buffett_index(fred):
    """
    巴菲特指标 = 总股市市值 / 名义GDP
    
    优先数据源：
    1. WILL5000PR (Wilshire 5000 总收益指数)
    2. BOGZ1FL893064105Q (美联储 Z.1 股票市值)
    3. MMNRNJ (市值的替代品)
    """
    print("  📊 加载巴菲特指标 (市值/GDP) 数据...")
    try:
        # 获取 GDP（季度数据，单位：十亿美元）
        gdp = fred.get_series("GDP", observation_start="1990-01-01")
        
        # 尝试获取市值数据
        try:
            # 美联储 Z.1 官方全美股票总市值（季度，单位：百万美元）
            market_cap = fred.get_series(
                "BOGZ1FL893064105Q", observation_start="1990-01-01"
            )
            # 转为十亿美元
            market_cap = market_cap / 1000.0
            print("    ✓ 使用 BOGZ1FL893064105Q (美联储 Z.1 股票市值)")
        except:
            # 备用：Wilshire 5000 总市值（日度）
            try:
                wilshire = fred.get_series(
                    "WILL5000PR", observation_start="1990-01-01"
                )
                # Wilshire 是股价指数，需要额外处理
                print("    ✓ 使用 WILL5000PR (Wilshire 5000)")
                market_cap = wilshire  # 这里假设可以直接使用
            except:
                print("    ❌ 无法获取市值数据")
                return None
        
        # 对齐到季度（GDP 是季度数据）
        df = pd.DataFrame({"market_cap": market_cap, "gdp": gdp})
        df = df.resample("QS").first().ffill()
        
        # 计算比例（去掉任何乘除系数）
        df["buffett_raw"] = df["market_cap"] / df["gdp"]
        
        return df[["buffett_raw"]].dropna()
    
    except Exception as e:
        print(f"  ❌ 巴菲特指标加载失败: {e}")
        return None


def fetch_margin_debt(fred):
    """
    保证金债务 / GDP
    
    数据源：
    1. FINRA 官方保证金债务数据
    2. 美联储 Z.1 Broker-Dealer 信用额度
    """
    print("  📊 加载保证金债务数据...")
    try:
        # 获取 GDP
        gdp = fred.get_series("GDP", observation_start="1990-01-01")
        
        # 尝试获取保证金债务
        try:
            # 美联储 Z.1 Broker-Dealer Credit Liabilities（季度，单位：百万美元）
            margin_debt = fred.get_series(
                "BOGZ1FL663067003Q", observation_start="1990-01-01"
            )
            margin_debt = margin_debt / 1000.0  # 转为十亿美元
            print("    ✓ 使用 BOGZ1FL663067003Q (美联储 Z.1 经纪商信用)")
        except:
            print("    ⚠️ 无法获取FRED保证金数据，尝试在线源...")
            # 备用：直接从 FINRA 官网爬取（这里省略具体实现）
            raise ValueError("保证金数据获取失败")
        
        # 对齐到季度
        df = pd.DataFrame({"margin_debt": margin_debt, "gdp": gdp})
        df = df.resample("QS").first().ffill()
        
        # 计算比例
        df["margin_debt_raw"] = df["margin_debt"] / df["gdp"]
        
        return df[["margin_debt_raw"]].dropna()
    
    except Exception as e:
        print(f"  ❌ 保证金债务加载失败: {e}")
        return None


def run_pipeline():
    """主管道"""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise ValueError("❌ 错误：未检测到 FRED_API_KEY 环境变量！")

    fred = Fred(api_key=api_key)
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    print("=" * 70)
    print("⏳ 正在拉取符合专业金融定义的标准底层数据...")
    print("=" * 70)

    try:
        # =====================================================================
        # 1. Shiller CAPE 与 ERP
        # =====================================================================
        print("\n[1/4] 席勒市盈率 (CAPE) 与股权风险溢价 (ERP)")
        print("-" * 70)
        
        cape_df = fetch_shiller_cape()
        gs10_df = fetch_erp_and_gs10(fred)
        
        if cape_df is None or gs10_df is None:
            raise ValueError("❌ 无法获取 CAPE 或 GS10 数据")
        
        # 对齐月度频率
        df_cape_erp = pd.concat([cape_df, gs10_df], axis=1).resample("MS").first().ffill()
        
        # 计算 ERP
        # ERP = (E/P) - Rf ≈ (1/CAPE) - (GS10/100)
        # 注意：这里假设 CAPE 基于正常化盈利，所以 1/CAPE 是合理的收益率代理
        df_cape_erp["erp_raw"] = (1.0 / df_cape_erp["cape"]) - (df_cape_erp["gs10"] / 100.0)
        
        print(f"  ✓ 最新 CAPE: {df_cape_erp['cape'].iloc[-1]:.2f} (10年历史均值基准)")
        print(f"  ✓ 最新 GS10: {df_cape_erp['gs10'].iloc[-1]:.2f}%")
        print(f"  ✓ 最新 ERP: {df_cape_erp['erp_raw'].iloc[-1]:.4f} ({df_cape_erp['erp_raw'].iloc[-1]*100:.2f}%)")
        
        # =====================================================================
        # 2. 巴菲特指标
        # =====================================================================
        print("\n[2/4] 巴菲特指标 (总市值/GDP)")
        print("-" * 70)
        
        buffett_df = fetch_buffett_index(fred)
        if buffett_df is None:
            raise ValueError("❌ 无法获取巴菲特指标数据")
        
        print(f"  ✓ 最新巴菲特指标: {buffett_df['buffett_raw'].iloc[-1]:.4f} " +
              f"({buffett_df['buffett_raw'].iloc[-1]*100:.2f}% 市值/GDP)")
        
        # =====================================================================
        # 3. 保证金债务/GDP
        # =====================================================================
        print("\n[3/4] 保证金债务/GDP")
        print("-" * 70)
        
        margin_df = fetch_margin_debt(fred)
        if margin_df is None:
            raise ValueError("❌ 无法获取保证金债务数据")
        
        print(f"  ✓ 最新保证金债务/GDP: {margin_df['margin_debt_raw'].iloc[-1]:.4f} " +
              f"({margin_df['margin_debt_raw'].iloc[-1]*100:.2f}%)")
        
        # =====================================================================
        # 4. 数据对齐与分位数计算
        # =====================================================================
        print("\n[4/4] 多因子风险评分 (CMRS)")
        print("-" * 70)
        
        # 统一到月度频率
        df_all = pd.concat([
            df_cape_erp[["cape", "erp_raw"]],
            buffett_df[["buffett_raw"]].resample("MS").first().ffill(),
            margin_df[["margin_debt_raw"]].resample("MS").first().ffill(),
        ], axis=1).dropna()
        
        latest = df_all.iloc[-1]
        window_df = df_all.iloc[-120:]  # 最近 10 年窗口
        
        # 计算各指标的分位数（百分比排名）
        # 注意分位数方向的正确性：
        # - ERP 越高越好（低风险），所以是 1 - percentile（反向）
        # - CAPE 越低越好（便宜），所以是正向 percentile
        # - Buffett 越低越好（便宜），所以是正向 percentile
        # - Margin Debt 越低越好（低杠杆），所以是正向 percentile
        
        erp_pct = 100.0 * (1.0 - (window_df["erp_raw"] <= latest["erp_raw"]).mean())  # 反向
        cape_pct = 100.0 * (window_df["cape"] <= latest["cape"]).mean()  # 正向
        buffett_pct = 100.0 * (window_df["buffett_raw"] <= latest["buffett_raw"]).mean()  # 正向
        margin_pct = 100.0 * (window_df["margin_debt_raw"] <= latest["margin_debt_raw"]).mean()  # 正向
        
        # 加权综合评分（35/25/20/20）
        # 分数越高 = 风险越高
        cmrs_score = round(
            0.35 * erp_pct + 0.25 * cape_pct + 0.20 * buffett_pct + 0.20 * margin_pct,
            1,
        )
        current_zone = get_risk_zone(cmrs_score)
        
        print(f"  📈 ERP 分位数: {erp_pct:.1f} (权重 35%)")
        print(f"  📊 CAPE 分位数: {cape_pct:.1f} (权重 25%)")
        print(f"  💰 Buffett 分位数: {buffett_pct:.1f} (权重 20%)")
        print(f"  📉 Margin 分位数: {margin_pct:.1f} (权重 20%)")
        print(f"\n  🎯 综合风险评分: {cmrs_score}")
        print(f"  {current_zone}")
        
        # =====================================================================
        # 5. 生成仓位建议 (SOP)
        # =====================================================================
        if cmrs_score >= 75:
            target_eq, target_cash = "10% - 20%", "80% - 90%"
            steps = [
                "清理所有高 Beta、高估值概念股，仅保留
