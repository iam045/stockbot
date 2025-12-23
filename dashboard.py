import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import os
import re
from datetime import datetime, timedelta

# --- 1. 頁面配置與白皮書參數 ---
st.set_page_config(page_title="處置預測系統 V7", layout="wide", page_icon="⚖️")

# 依據白皮書量化標準定義 [cite: 23, 25, 26]
QUANT_RULES = {
    "VOLATILITY_6D": 0.32,      # 6日累積漲跌幅 > 32% 
    "SPREAD_BENCHMARK": 0.20,   # 與大盤乖離 > 20% 
    "VOLUME_X": 5.0,            # 6日均量較60日均量放大 5 倍 
    "TURNOVER_SINGLE": 0.10,    # 單日週轉率 > 10% 
    "PE_LIMIT": 60,             # 本益比 > 60 [cite: 26]
    "PB_LIMIT": 6,              # 淨值比 > 6 [cite: 26]
}

DB_FILE = "history_db.csv"
JAIL_FILE = "jail_list.csv"

# --- 2. 自動爬蟲模組 (抓取國票證券實時資訊) ---
def fetch_official_data():
    """從國票證券抓取今日最新的注意與處置名單 [cite: 6, 18]"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 爬取處置股網址 
    url_dis = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    # 爬取注意股網址 [cite: 1]
    url_att = "https://www.ibfs.com.tw/stock3/default13-1.aspx?xy=8&xt=1"
    
    try:
        res_dis = requests.get(url_dis, headers=headers, verify=False, timeout=5)
        res_att = requests.get(url_att, headers=headers, verify=False, timeout=5)
        
        # 抓取表格
        dis_list = pd.read_html(res_dis.text)[0]
        att_list = pd.read_html(res_att.text)[0]
        
        return dis_list, att_list
    except Exception as e:
        st.error(f"爬蟲連線失敗: {e}")
        return None, None

# --- 3. 核心預測邏輯 (計數器與量化分析) ---
def update_history_db(att_df):
    """將今日注意股存入資料庫，用於計算 10日6次 等邏輯 """
    if att_df is None or att_df.empty: return
    
    today = datetime.now().strftime("%Y-%m-%d")
    # 假設 att_df 的代號在 '代號' 或 '證券名稱' 欄位
    new_records = []
    for _, row in att_df.iterrows():
        code = str(row.get('代號', row.get('證券名稱', ''))).split('(')[-1].replace(')', '')
        new_records.append({"日期": today, "代號": code, "狀態": "注意"})
    
    if os.path.exists(DB_FILE):
        old_db = pd.read_csv(DB_FILE)
        combined = pd.concat([old_db, pd.DataFrame(new_records)]).drop_duplicates(subset=['日期', '代號'])
        combined.to_csv(DB_FILE, index=False)
    else:
        pd.DataFrame(new_records).to_csv(DB_FILE, index=False)

def analyze_risk_counter(stock_code):
    """計算 10 日內注意次數 """
    if not os.path.exists(DB_FILE): return 0
    db = pd.read_csv(DB_FILE)
    db['日期'] = pd.to_datetime(db['日期'])
    
    # 取最近 10 個營業日 
    ten_days_ago = datetime.now() - timedelta(days=15)
    stock_history = db[(db['代號'].astype(str) == str(stock_code)) & (db['日期'] >= ten_days_ago)]
    return len(stock_history)

# --- 4. 介面設計 ---
st.title("🔥 台股處置股預測引擎 V7")
st.markdown(f"**當前日期：** {datetime.now().strftime('%Y-%m-%d')} | **監視準則：** 依據證交所處置作業要點 ")

# 側邊欄控制
if st.sidebar.button("🔄 立即同步最新爬蟲資料"):
    dis, att = fetch_official_data()
    if att is not None:
        update_history_db(att)
        st.sidebar.success("資料庫已更新！")

# 頁面分頁
tab1, tab2, tab3 = st.tabs(["🎯 處置風險預測", "🔒 目前被關禁閉", "📉 歷史統計"])

with tab1:
    st.subheader("分析目標股票是否即將「被關」")
    target_code = st.text_input("輸入股票代號 (例如: 4931)", "4931")
    
    if st.button("開始量化診斷"):
        # 1. 抓取股價與量能 
        ticker = yf.Ticker(f"{target_code}.TW")
        hist = ticker.history(period="65d")
        
        if not hist.empty:
            # 漲幅計算
            ret_6d = (hist.iloc[-1]['Close'] - hist.iloc[-6]['Close']) / hist.iloc[-6]['Close']
            # 量能放大 
            vol_6 = hist.iloc[-6:]['Volume'].mean()
            vol_60 = hist.iloc[-60:]['Volume'].mean()
            vol_ratio = vol_6 / vol_60
            
            # 計數器 
            att_count = analyze_risk_counter(target_code)
            
            # 顯示指標
            c1, c2, c3 = st.columns(3)
            c1.metric("6日累積漲幅", f"{ret_6d*100:.1f}%", delta="門檻 32%")
            c2.metric("量能放大倍數", f"{vol_ratio:.1f}x", delta="門檻 5x")
            c3.metric("10日內注意次數", f"{att_count} 次", delta="門檻 6次")
            
            # 預測結論
            if att_count >= 5:
                st.error(f"🚨 高度預警：{target_code} 已累積 {att_count} 次注意，再 1 次即進入處置！ ")
            elif ret_6d > 0.30:
                st.warning(f"⚠️ 漲幅預警：漲幅已接近 32% 門檻，隨時可能列入注意股票。 ")
            else:
                st.success("✅ 目前各項指標尚在安全範圍內。")
        else:
            st.warning("查無股票資料，請檢查代號或市場（.TW / .TWO）")

with tab2:
    st.subheader("出關倒數清單")
    dis, att = fetch_official_data()
    if dis is not None:
        st.dataframe(dis, use_container_width=True)
        st.caption("資料來源：國票證券官方處置公告 ")
    else:
        st.info("請點擊左側「同步」按鈕獲取資料。")

with tab3:
    st.subheader("歷史注意紀錄 (用於計數器)")
    if os.path.exists(DB_FILE):
        st.table(pd.read_csv(DB_FILE).tail(10))
    else:
        st.write("尚無歷史資料。")
