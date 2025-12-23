import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import re
import os
from datetime import datetime, timedelta

# --- 1. 基礎設定 ---
st.set_page_config(page_title="台股處置預警雷達", layout="wide", page_icon="⚡")
JAIL_FILE = "jail_list.csv"
DB_FILE = "attention_history.csv" # 儲存注意股歷史以計算計數器

# --- 2. 核心：智慧數據同步 ---
def fetch_raw_disposal():
    """從國票網站抓取原始處置清單，僅提取核心文字避免解析錯誤"""
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        dfs = pd.read_html(response.text)
        return dfs[0] if dfs else pd.DataFrame()
    except:
        return pd.DataFrame()

def get_release_date(text):
    """解析出關日期：抓取結束日並 +1 天 """
    match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(text))
    if match:
        y = int(match.group(1)) + 1911
        m = int(match.group(2))
        d = int(match.group(3))
        # 處置結束時間的隔天才算出關
        return (datetime(y, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")
    return "-"

# --- 3. 核心：預測模型運算 (依據白皮書) ---
def calculate_quant_risk(code):
    """計算白皮書中定義的量化風險 [cite: 7, 13]"""
    try:
        # 抓取最近 65 天數據以計算 60 日均量 [cite: 5]
        ticker = yf.Ticker(f"{code}.TW")
        df = ticker.history(period="65d")
        if df.empty: return None

        # 1. 漲幅過大監控 (32% 規則) 
        ret_6d = (df.iloc[-1]['Close'] - df.iloc[-6]['Close']) / df.iloc[-6]['Close']
        
        # 2. 量能倍增監控 (5倍規則) [cite: 5, 7]
        vol_6 = df.iloc[-6:]['Volume'].mean()
        vol_60 = df.iloc[-60:]['Volume'].mean()
        vol_x = vol_6 / vol_60 if vol_60 > 0 else 0
        
        return {"ret": ret_6d, "vol_x": vol_x, "price": df.iloc[-1]['Close']}
    except:
        return None

# --- 4. 主介面 ---
def main():
    st.sidebar.title("戰情雷達導航")
    menu = st.sidebar.radio("功能切換", ["📌 處置中", "🔮 預測雷達"])

    # --- 頁面 1: 處置中 (保留並優化) ---
    if menu == "📌 處置中":
        st.header("📌 處置中標的監控")
        st.caption("自動同步國票清單，並依據結束日之次日計算出關時間")

        if st.button("🔄 同步最新數據"):
            raw_data = fetch_raw_disposal()
            if not raw_data.empty:
                processed = []
                for _, row in raw_data.iterrows():
                    # a. 股票名稱及代號
                    name_code = f"{row.iloc[1]} ({row.iloc[2]})"
                    # b. 撮合方式 (提取數字 5 或 20) 
                    match_val = "".join(filter(str.isdigit, str(row.iloc[3])))
                    # c. 出關時間 (結束日+1) 
                    release = get_release_date(row.iloc[5])
                    
                    # 剔除已過期標的
                    if release != "-" and release < datetime.now().strftime("%Y-%m-%d"):
                        continue
                        
                    processed.append({
                        "股票名稱及代號": name_code,
                        "撮合方式": f"{match_val} 分鐘",
                        "出關時間": release,
                        "代號": str(row.iloc[2])
                    })
                
                pd.DataFrame(processed).to_csv(JAIL_FILE, index=False)
                st.success("同步完成並已自動剔除過期標的！")

        if os.path.exists(JAIL_FILE):
            df_jail = pd.read_csv(JAIL_FILE).sort_values(by="出關時間")
            st.dataframe(df_jail[["股票名稱及代號", "撮合方式", "出關時間"]], use_container_width=True, hide_index=True)
        else:
            st.info("請先點擊同步按鈕。")

    # --- 頁面 2: 預測雷達 (新功能建議) ---
    elif menu == "🔮 預測雷達":
        st.header("🔮 處置風險預測雷達")
        st.info("依據白皮書量化規則，計算個股是否即將觸發「注意」或「處置」")
        
        input_codes = st.text_input("輸入欲追蹤的股票代號 (如: 4931, 3081)", "4931")
        if st.button("啟動量化預測分析"):
            codes = [c.strip() for c in input_codes.split(",")]
            results = []
            for c in codes:
                risk = calculate_quant_risk(c)
                if risk:
                    # 判定邏輯 (白皮書規則：漲幅 > 32% 或 量能 > 5倍) [cite: 7]
                    status = "✅ 安全"
                    if risk['ret'] > 0.32: status = "🚨 漲幅過大"
                    elif risk['vol_x'] > 5.0: status = "🔥 量能爆發"
                    
                    results.append({
                        "代號": c,
                        "當前價格": round(risk['price'], 2),
                        "6日累積漲幅": f"{risk['ret']*100:.1f}%",
                        "量能放大倍數": f"{risk['vol_x']:.1f}x",
                        "預警狀態": status
                    })
            st.table(results)

if __name__ == "__main__":
    main()
