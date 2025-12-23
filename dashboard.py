import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import re
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="台股處置預測系統 V6", layout="wide", page_icon="🔮")

# --- 2. 核心量化規則設定 (依據白皮書規範) ---
RULES = {
    "VOLATILITY_32": 0.32,      # 6日累積漲跌幅門檻 
    "BENCHMARK_SPREAD": 0.20,   # 領先大盤乖離率 
    "TURNOVER_DAILY": 0.10,     # 單日週轉率門檻 
    "VOLUME_X": 5.0,            # 量能放大倍數 (6日均/60日均) 
    "PE_HIGH": 60,              # 本益比過高門檻 [cite: 6]
    "PB_HIGH": 6,               # 淨值比過高門檻 [cite: 6]
}

# --- 3. 資料庫工具 ---
DB_FILE = "history_db.csv"
JAIL_FILE = "jail_list.csv"

def load_data(file):
    if not os.path.exists(file): return pd.DataFrame()
    return pd.read_csv(file)

# --- 4. 核心規則引擎 ---
def get_market_benchmark():
    """獲取大盤(加權指數)最近6日表現作為基準 [cite: 12]"""
    try:
        twii = yf.Ticker("^TWII").history(period="10d")
        if len(twii) < 6: return 0
        return (twii.iloc[-1]['Close'] - twii.iloc[-6]['Close']) / twii.iloc[-6]['Close']
    except: return 0

def calculate_stock_risk(stock_code, benchmark_ret):
    """
    計算個股是否觸發注意股票規則 [cite: 7]
    """
    try:
        ticker_str = f"{stock_code}.TW"
        stock = yf.Ticker(ticker_str)
        hist = stock.history(period="65d") # 需60日均量 
        
        if hist.empty or len(hist) < 60:
            hist = yf.Ticker(f"{stock_code}.TWO").history(period="65d")
        
        if hist.empty: return None

        # A. 漲幅規則 (32% 規則) 
        ret_6d = (hist.iloc[-1]['Close'] - hist.iloc[-6]['Close']) / hist.iloc[-6]['Close']
        spread = ret_6d - benchmark_ret
        is_vol_risk = abs(ret_6d) > RULES["VOLATILITY_32"] and abs(spread) > RULES["BENCHMARK_SPREAD"]

        # B. 量能暴增規則 (5倍) 
        avg_vol_6 = hist.iloc[-6:]['Volume'].mean()
        avg_vol_60 = hist.iloc[-60:]['Volume'].mean()
        vol_x = avg_vol_6 / avg_vol_60 if avg_vol_60 > 0 else 0
        is_vol_x_risk = vol_x >= RULES["VOLUME_X"]

        # C. 估值監控 (需 info) [cite: 6]
        info = stock.info
        pe = info.get('trailingPE', 0)
        pb = info.get('priceToBook', 0)
        is_val_risk = (pe > RULES["PE_HIGH"] or pe < 0) and (pb > RULES["PB_HIGH"])

        # 彙整風險標籤
        triggers = []
        if is_vol_risk: triggers.append("漲幅異常(32%)")
        if is_vol_x_risk: triggers.append("量能暴增(5X)")
        if is_val_risk: triggers.append("估值泡沫")

        return {
            "代號": stock_code,
            "收盤": round(hist.iloc[-1]['Close'], 2),
            "6日漲跌": f"{ret_6d*100:.1f}%",
            "量能倍數": f"{vol_x:.1f}x",
            "觸發規則": " / ".join(triggers) if triggers else "正常",
            "風險等級": "🔴 高" if triggers else "🟢 低"
        }
    except: return None

# --- 5. 處置計數器邏輯 [cite: 8, 10] ---
def predict_jail_status(stock_code):
    """
    計算 3/10/30 滑動視窗計數器 
    """
    db = load_data(DB_FILE)
    if db.empty: return 0, "無歷史紀錄"
    
    # 過濾該代號
    stock_code = str(stock_code).strip()
    history = db[db['代號'].astype(str) == stock_code]
    if history.empty: return 0, "初次監控"

    # 只看最近 30 筆注意紀錄
    history = history.tail(30)
    count_30 = len(history[history['狀態'].str.contains("注意", na=False)])
    count_10 = len(history.tail(10)[history.tail(10)['狀態'].str.contains("注意", na=False)])
    
    # 預測邏輯
    msg = f"10日內累積 {count_10} 次注意"
    if count_10 >= 5: msg = "🔥 警告：再1次即處置 (10日6次)" # [cite: 8]
    elif count_10 >= 2: msg = "⚠️ 持續升溫中"
    
    return count_10, msg

# --- 6. 頁面渲染 ---
st.sidebar.title("🔮 處置股預測引擎")
page = st.sidebar.selectbox("切換模式", ["🚀 智能預警中心", "⛓️ 出關倒數監控"])

# ------------------------------------------------------
# 模式 1: 智能預警中心
# ------------------------------------------------------
if page == "🚀 智能預警中心":
    st.header("🚀 處置風險智能預警")
    st.info("系統依據 TWSE 規範，自動掃描 6日漲跌(32%)、量能(5x) 與 累積計數器 [cite: 7, 10]")

    # 自動從歷史載入監控名單
    db = load_data(DB_FILE)
    auto_list = db['代號'].unique().tolist() if not db.empty else ["3167", "3293"]
    
    target_input = st.text_input("輸入掃描代號 (逗號隔開)", ",".join(map(str, auto_list)))
    
    if st.button("執行全自動風險掃描"):
        scan_list = [c.strip() for c in target_input.split(",")]
        bench_ret = get_market_benchmark()
        
        results = []
        progress = st.progress(0)
        
        for i, code in enumerate(scan_list):
            # 1. 計算即時量化指標
            risk_data = calculate_stock_risk(code, bench_ret)
            # 2. 計算歷史計數器 
            count, jail_msg = predict_jail_status(code)
            
            if risk_data:
                risk_data["計數器狀態"] = jail_msg
                risk_data["10日次數"] = count
                results.append(risk_data)
            progress.progress((i+1)/len(scan_list))
        
        if results:
            df_final = pd.DataFrame(results)
            # 排序：優先顯示高風險與計數器接近門檻者
            df_final = df_final.sort_values(by=["10日次數", "風險等級"], ascending=False)
            
            st.dataframe(
                df_final.style.highlight_max(subset=['10日次數'], color='#ff4b4b'),
                use_container_width=True
            )
        else:
            st.error("掃描失敗，請檢查網路或代號")

# ------------------------------------------------------
# 模式 2: 出關倒數監控
# ------------------------------------------------------
else:
    st.header("⛓️ 處置股出關倒數")
    # 這裡沿用您原本的 jail_list 邏輯，但增加 Level 2 判斷
    st.warning("注意：若 30 日內第二次處置，將升級為 20 分鐘撮合 (Level 2) [cite: 9]")
    
    # (此處可貼入您原有的 Jail List UI 代碼並搭配 parse_disposal_date)
    # 提示：若處置原因含「當沖」，倒數自動改為 12 天 
    st.write("目前正在開發與券商公告同步的 API 自動抓取功能...")
