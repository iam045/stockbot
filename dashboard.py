import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import urllib3
import os
import re
from datetime import datetime

# 關閉 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 頁面設定 ---
st.set_page_config(page_title="台股自動戰情雷達 V6", layout="wide", page_icon="🚀")

# ======================================================
# 檔案與路徑設定
# ======================================================
DB_FILE = "history_db.csv"
JAIL_FILE = "jail_list.csv"

# ======================================================
# 工具：解析日期與倒數
# ======================================================
def parse_disposal_date(content):
    try:
        match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(content))
        if match:
            year = int(match.group(1)) + 1911
            end_date = datetime(year, int(match.group(2)), int(match.group(3)))
            today = datetime.now()
            remaining = (end_date - today).days + 1
            return end_date.strftime("%Y-%m-%d"), remaining
    except: pass
    return "-", "-"

# ======================================================
# 核心功能：狀態查詢與運算
# ======================================================
def check_official_status(stock_code):
    target_code = ''.join(filter(str.isdigit, stock_code))
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # 查處置
        r = requests.get("https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1", headers=headers, verify=False, timeout=5)
        dfs = pd.read_html(r.text)
        for df in dfs:
            if '處置內容' in str(df.columns):
                mask = df.apply(lambda row: row.astype(str).str.contains(target_code).any(), axis=1)
                if not df[mask].empty: return "⛔ 處置中", df[mask].iloc[0][5]
        # 查注意
        r = requests.get("https://www.ibfs.com.tw/stock3/default13-1.aspx?xy=8&xt=1", headers=headers, verify=False, timeout=5)
        dfs = pd.read_html(r.text)
        for df in dfs:
            if '注意交易資訊' in str(df.columns):
                mask = df.apply(lambda row: row.astype(str).str.contains(target_code).any(), axis=1)
                if not df[mask].empty: return "⚠️ 注意股", df[mask].iloc[0][4]
    except: pass
    return "正常", "-"

def get_history_count(stock_code):
    stock_code = ''.join(filter(str.isdigit, stock_code))
    if not os.path.exists(DB_FILE): return 0
    try:
        df = pd.read_csv(DB_FILE, dtype={'代號': str})
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values(by="日期")
        target_df = df[df["代號"] == stock_code]
        if target_df.empty: return 0
        disposal_records = target_df[target_df["狀態"].str.contains("處置")]
        valid_df = target_df[target_df["日期"] > disposal_records.iloc[-1]["日期"]] if not disposal_records.empty else target_df
        return len(valid_df[valid_df["狀態"].str.contains("注意")])
    except: return 0

def analyze_price_risk(stock_code):
    ticker = f"{stock_code}.TW"
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1mo")
        if df.empty:
            ticker = f"{stock_code}.TWO"
            stock = yf.Ticker(ticker)
            df = stock.history(period="1mo")
        if len(df) < 6: return None
        benchmark = yf.Ticker("^TWII").history(period="1mo")
        bench_ret = (benchmark.iloc[-1]['Close'] - benchmark.iloc[-6]['Close']) / benchmark.iloc[-6]['Close']
        target_ret = max(0.32, bench_ret + 0.20)
        trigger = df.iloc[-6]['Close'] * (1 + target_ret)
        cur = df.iloc[-1]['Close']
        gap = ((trigger - cur) / cur) * 100
        risk = "🔴 觸發異常" if cur >= trigger else ("🟡 瀕臨觸發" if gap < 3 else "🟢 安全")
        return {"現價": round(cur, 2), "天花板": round(trigger, 2), "乖離%": f"{gap:.2f}%", "風險": risk}
    except: return None

# ======================================================
# 主介面
# ======================================================
st.sidebar.title("⚡ 自動化戰情系統")
page = st.sidebar.radio("切換視角", ["🔥 風險預警中心", "⛔ 處置出關倒數"])

if page == "🔥 風險預警中心":
    st.title("🔥 風險預警中心")
    st.markdown(f"🕒 **更新狀態**：已連結 GitHub 機器人資料庫 (`history_db.csv`)")
    
    if os.path.exists(DB_FILE):
        db_codes = pd.read_csv(DB_FILE, dtype=str)["代號"].unique().tolist()
        if db_codes:
            results = []
            with st.spinner(f"正在分析資料庫中 {len(db_codes)} 檔股票..."):
                for code in db_codes:
                    p_data = analyze_price_risk(code)
                    status, reason = check_official_status(code)
                    count = get_history_count(code)
                    if p_data:
                        results.append({"代號": code, "官方狀態": status, "累積次數": f"{count}次", **p_data, "原因": reason})
            
            if results:
                df = pd.DataFrame(results).sort_values(by="風險", ascending=False)
                st.dataframe(df.style.apply(lambda r: ['background-color: #ffcccc' if "處置" in str(r.官方狀態) else ('background-color: #fffbe6' if "注意" in str(r.官方狀態) else '') for _ in r], axis=1), use_container_width=True)
        else: st.info("資料庫目前無紀錄。")
    else: st.error("找不到資料庫，請檢查 GitHub 檔案。")

elif page == "⛔ 處置出關倒數":
    st.title("⛔ 處置出關倒數")
    st.caption("機器人每天 18:30 會自動掃描並更新此名單")
    
    if os.path.exists(JAIL_FILE):
        jail_codes = pd.read_csv(JAIL_FILE, dtype=str)['code'].tolist()
        if jail_codes:
            jail_res = []
            for code in jail_codes:
                p_info = analyze_price_risk(code)
                status, detail = check_official_status(code)
                end_d, days = parse_disposal_date(detail)
                msg = f"🔓 本日出關" if isinstance(days, int) and days <= 0 else (f"🔥 剩 {days} 天" if isinstance(days, int) and days <= 2 else f"⏳ 剩 {days} 天")
                jail_res.append({"代號": code, "現價": p_info['現價'] if p_info else "-", "倒數": msg, "結束日期": end_d, "公告": detail})
            
            st.dataframe(pd.DataFrame(jail_res).style.apply(lambda r: ['background-color: #ccffcc' if "🔓" in str(r.倒數) else '' for _ in r], axis=1), use_container_width=True)
        else: st.info("目前無處置中股票。")
    else: st.error("找不到處置清單，請檢查 GitHub 檔案。")
