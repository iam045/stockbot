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
st.set_page_config(page_title="台股戰情雷達 V5", layout="wide", page_icon="⚡")

# ======================================================
# 工具：檔案存取 (處置股專用名單)
# ======================================================
JAIL_FILE = "jail_list.csv"

def load_jail_list():
    if not os.path.exists(JAIL_FILE):
        return []
    try:
        df = pd.read_csv(JAIL_FILE, dtype=str)
        return df['code'].tolist()
    except:
        return []

def save_jail_list(codes):
    df = pd.DataFrame({'code': codes})
    df.to_csv(JAIL_FILE, index=False)

def add_to_jail(code):
    code = ''.join(filter(str.isdigit, code))
    current_list = load_jail_list()
    if code and code not in current_list:
        current_list.append(code)
        save_jail_list(current_list)
        return True
    return False

def remove_from_jail(codes_to_remove):
    current_list = load_jail_list()
    new_list = [c for c in current_list if c not in codes_to_remove]
    save_jail_list(new_list)

# ======================================================
# 工具：解析日期與倒數 (核心邏輯)
# ======================================================
def parse_disposal_date(content):
    """
    從公告文字中抓出「結束日期」，並計算剩餘天數
    """
    try:
        # 1. 抓取格式：至115年01月06日
        match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(content))
        if match:
            year = int(match.group(1)) + 1911
            month = int(match.group(2))
            day = int(match.group(3))
            end_date = datetime(year, month, day)
            today = datetime.now()
            
            # 計算剩餘天數 (包含今天)
            remaining = (end_date - today).days + 1
            return end_date.strftime("%Y-%m-%d"), remaining
    except:
        pass
    return "-", "-"

# ======================================================
# 核心功能：爬蟲與運算 (沿用 V3)
# ======================================================
def check_official_status(stock_code):
    target_code = ''.join(filter(str.isdigit, stock_code))
    headers = {'User-Agent': 'Mozilla/5.0'}
    status = "正常"
    detail = "-"
    
    try:
        # 查處置
        url_disposal = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
        r = requests.get(url_disposal, headers=headers, verify=False, timeout=3)
        dfs = pd.read_html(r.text)
        if dfs:
            for df in dfs:
                if '處置內容' in str(df.columns):
                    mask = df.apply(lambda row: row.astype(str).str.contains(target_code).any(), axis=1)
                    if not df[mask].empty:
                        return "⛔ 處置中", df[mask].iloc[0][5]
        # 查注意
        url_attention = "https://www.ibfs.com.tw/stock3/default13-1.aspx?xy=8&xt=1"
        r = requests.get(url_attention, headers=headers, verify=False, timeout=3)
        dfs = pd.read_html(r.text)
        if dfs:
            for df in dfs:
                if '注意交易資訊' in str(df.columns):
                    mask = df.apply(lambda row: row.astype(str).str.contains(target_code).any(), axis=1)
                    if not df[mask].empty:
                        return "⚠️ 注意股", df[mask].iloc[0][4]
    except:
        pass
    return status, detail

def get_db_stocks():
    db_file = "history_db.csv"
    if not os.path.exists(db_file): return []
    try:
        df = pd.read_csv(db_file, dtype={'代號': str})
        return df["代號"].astype(str).str.strip().unique().tolist()
    except: return []

def get_history_count(stock_code):
    # (保持 V3 邏輯)
    db_file = "history_db.csv"
    stock_code = ''.join(filter(str.isdigit, stock_code))
    if not os.path.exists(db_file): return 0
    try:
        df = pd.read_csv(db_file, dtype={'代號': str})
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values(by="日期")
        target_df = df[df["代號"] == stock_code]
        if target_df.empty: return 0
        
        disposal_records = target_df[target_df["狀態"].str.contains("處置")]
        if not disposal_records.empty:
            last_date = disposal_records.iloc[-1]["日期"]
            valid_df = target_df[target_df["日期"] > last_date]
        else:
            valid_df = target_df
        return len(valid_df[valid_df["狀態"].str.contains("注意")])
    except: return 0

def analyze_price_risk(stock_code):
    # (保持 V3 邏輯)
    stock_code = stock_code.strip()
    ticker = f"{stock_code}.TW"
    try:
        stock = yf.Ticker(ticker)
        if stock.history(period="5d").empty:
            ticker = f"{stock_code}.TWO"
            stock = yf.Ticker(ticker)

        df = stock.history(period="1mo")
        benchmark = yf.Ticker("^TWII")
        df_bench = benchmark.history(period="1mo")
        if len(df) < 6: return None

        price_start = df.iloc[-6]['Close']
        bench_start = df_bench.iloc[-6]['Close']
        current_price = df.iloc[-1]['Close']
        bench_current = df_bench.iloc[-1]['Close']
        
        bench_return = (bench_current - bench_start) / bench_start
        target_return = max(0.32, bench_return + 0.20)
        trigger_price = price_start * (1 + target_return)
        gap_pct = ((trigger_price - current_price) / current_price) * 100
        
        risk_msg = "🟢 安全"
        if current_price >= trigger_price: risk_msg = "🔴 觸發異常"
        elif gap_pct < 3: risk_msg = "🟡 瀕臨觸發"
            
        return {
            "代號": stock_code,
            "收盤價": round(current_price, 2),
            "天花板": round(trigger_price, 2),
            "乖離(%)": f"{gap_pct:.2f}%",
            "風險": risk_msg
        }
    except: return None

# ======================================================
# 主程式：頁面導航
# ======================================================
st.sidebar.title("⚡ 戰情雷達")
page = st.sidebar.radio("選擇功能", ["📊 潛在風險監控", "⛔ 處置股倒數"])

# ------------------------------------------------------
# 頁面 1: 潛在風險監控 (V3 原版功能)
# ------------------------------------------------------
if page == "📊 潛在風險監控":
    st.title("📊 潛在風險監控")
    st.caption("針對尚未進處置，但有違規風險的股票")
    
    mode = st.radio("掃描來源：", ("A. 手動輸入", "B. 歷史黑名單"), horizontal=True)
    
    scan_list = []
    if mode == "A. 手動輸入":
        user_input = st.text_area("輸入代號", "3167, 3293, 2330", height=70)
        if user_input: scan_list = user_input.split(",")
    else:
        scan_list = get_db_stocks()
        st.info(f"資料庫載入 {len(scan_list)} 檔")

    if st.button("🚀 開始掃描", type="primary"):
        if not scan_list:
            st.warning("無目標股票")
        else:
            results = []
            progress = st.progress(0)
            status_text = st.empty()
            
            for i, code in enumerate(scan_list):
                code = code.strip()
                if not code: continue
                status_text.text(f"分析中: {code}")
                
                price_data = analyze_price_risk(code)
                official_status, reason = check_official_status(code)
                count = get_history_count(code)
                
                if price_data:
                    price_data["官方狀態"] = official_status
                    price_data["累積次數"] = f"{count} 次"
                    price_data["公告原因"] = reason
                    results.append(price_data)
                progress.progress((i+1)/len(scan_list))
            
            status_text.empty()
            
            if results:
                df = pd.DataFrame(results)
                cols = ["代號", "官方狀態", "累積次數", "風險", "收盤價", "天花板", "乖離(%)", "公告原因"]
                df = df[cols]
                
                # 排序邏輯
                df["sort_key"] = 0
                df.loc[df["官方狀態"].str.contains("處置"), "sort_key"] = 3
                df.loc[(df["官方狀態"].str.contains("注意")) & (df["風險"].str.contains("🔴")), "sort_key"] = 2
                df.loc[df["風險"].str.contains("🔴"), "sort_key"] = 1
                df = df.sort_values(by="sort_key", ascending=False).drop(columns=["sort_key"])

                def highlight(row):
                    styles = [''] * len(row)
                    if "處置" in str(row["官方狀態"]): return ['background-color: #ffcccc; color: darkred'] * len(row)
                    elif "注意" in str(row["官方狀態"]): return ['background-color: #fffbe6; color: #664d03'] * len(row)
                    return styles

                st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True, height=500)
            else:
                st.error("查無資料")

# ------------------------------------------------------
# 頁面 2: 處置股倒數 (新功能)
# ------------------------------------------------------
elif page == "⛔ 處置股倒數":
    st.title("⛔ 處置股出關倒數")
    st.caption("專門監控已經被關禁閉的股票，掌握出關行情")
    
    # --- 新增/刪除 區域 ---
    col1, col2 = st.columns([1, 2])
    
    with col1:
        with st.form("add_jail_form"):
            new_code = st.text_input("新增處置股代號", placeholder="例如: 3081")
            submitted = st.form_submit_button("➕ 加入監控")
            if submitted and new_code:
                if add_to_jail(new_code):
                    st.success(f"{new_code} 已加入")
                    st.rerun()
                else:
                    st.warning("代號已存在或無效")
                    
    # --- 讀取清單並顯示 ---
    jail_list = load_jail_list()
    
    if not jail_list:
        st.info("目前清單是空的。請在左側新增正在被處置的股票。")
    else:
        # 移除選單
        with col2:
            to_remove = st.multiselect("勾選以移除 (結束處置)", jail_list)
            if to_remove:
                if st.button("🗑️ 確認移除"):
                    remove_from_jail(to_remove)
                    st.rerun()

        st.divider()
        
        # 掃描並計算倒數
        jail_results = []
        progress = st.progress(0)
        
        for i, code in enumerate(jail_list):
            # 抓即時股價
            price_info = analyze_price_risk(code) # 借用這裡的抓股價功能
            current_price = price_info['收盤價'] if price_info else "-"
            
            # 抓處置公告
            status, detail = check_official_status(code)
            
            # 解析日期
            end_date, days_left = parse_disposal_date(detail)
            
            # 判斷燈號
            countdown_msg = "無法解析"
            if isinstance(days_left, int):
                if days_left <= 0:
                    countdown_msg = "🔓 本日出關"
                elif days_left <= 2:
                    countdown_msg = f"🔥 剩 {days_left} 天 (準備噴出)"
                else:
                    countdown_msg = f"⏳ 剩 {days_left} 天"
            
            jail_results.append({
                "代號": code,
                "現價": current_price,
                "出關倒數": countdown_msg,
                "結束日期": end_date,
                "處置公告內容": detail
            })
            progress.progress((i+1)/len(jail_list))
            
        progress.empty()
        
        if jail_results:
            df_jail = pd.DataFrame(jail_results)
            
            # 顏色標記：快出關的亮綠燈
            def highlight_jail(row):
                styles = [''] * len(row)
                val = str(row["出關倒數"])
                if "🔓" in val:
                    return ['background-color: #ccffcc; color: darkgreen; font-weight: bold'] * len(row)
                elif "🔥" in val:
                    return ['background-color: #e6fffa; color: #006600; font-weight: bold'] * len(row)
                return styles

            st.dataframe(
                df_jail.style.apply(highlight_jail, axis=1), 
                use_container_width=True,
                column_config={
                    "處置公告內容": st.column_config.TextColumn("處置公告內容", width="large")
                }
            )
        else:
            st.write("讀取資料中...")
