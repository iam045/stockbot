import streamlit as st
import pandas as pd
import requests
import re
import os
from datetime import datetime, timedelta

# --- 1. 基礎設定 ---
st.set_page_config(page_title="處置監控系統", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心功能：爬蟲與解析 ---
def fetch_ibf_disposal_data():
    """
    從國票證券抓取即時處置股清單
    網址：https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # 國票的表格通常在 index 0
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        dfs = pd.read_html(response.text)
        if not dfs:
            return pd.DataFrame()
        
        raw_df = dfs[0]
        # 根據來源 ，欄位包含：公告日期, 證券名稱, 代號, 撮合方式, 處置內容
        return raw_df
    except Exception as e:
        st.error(f"連線國票網站失敗: {e}")
        return pd.DataFrame()

def parse_release_date(content):
    """
    從處置內容解析結束日期，並計算出關日期 (結束日+1)
    """
    try:
        # 匹配格式：至114年12月31日 
        match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(content))
        if match:
            year = int(match.group(1)) + 1911
            month = int(match.group(2))
            day = int(match.group(3))
            end_date = datetime(year, month, day)
            # 規則：處置結束時間的隔天才算出關
            release_date = end_date + timedelta(days=1)
            return release_date.strftime("%Y-%m-%d")
    except:
        pass
    return "解析失敗"

# --- 3. 資料庫管理 (新增與剔除) ---
def sync_jail_list():
    """
    自動化同步邏輯：
    1. 抓取國票最新名單
    2. 解析出關時間
    3. 過濾已過期的標的
    """
    new_data = fetch_ibf_disposal_data()
    if new_data.empty:
        return load_local_jail()

    processed_list = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    for _, row in new_data.iterrows():
        # a. 股票名稱及代號
        name = str(row['證券名稱'])
        code = str(row['代號']).split('.')[0]
        
        # b. 搓合方式 (5 or 20) [cite: 29]
        match_mode = str(row['撮合方式']) 
        
        # c. 出關時間 (結束日+1)
        release_date = parse_release_date(row['處置內容'])
        
        # 剔除功能：如果出關日期小於等於今天，代表已出關，不加入清單
        if release_date != "解析失敗" and release_date <= today_str:
            continue
            
        processed_list.append({
            "股票名稱及代號": f"{name} ({code})",
            "代號": code,
            "撮合方式": f"{match_mode} 分鐘",
            "出關時間": release_date,
            "最後更新": today_str
        })

    df_jail = pd.DataFrame(processed_list)
    if not df_jail.empty:
        df_jail.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
    return df_jail

def load_local_jail():
    if os.path.exists(JAIL_FILE):
        return pd.read_csv(JAIL_FILE)
    return pd.DataFrame()

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置監控系統")
    st.caption("依據證交所監視制度與國票官方資料自動更新")

    # --- 功能列 ---
    col_a, col_b = st.columns([1, 4])
    with col_a:
        if st.button("🔄 同步國票清單", type="primary"):
            with st.spinner("正在爬取並比對數據..."):
                sync_jail_list()
                st.rerun()

    # --- 頁面 1: 處置中 ---
    st.header("📌 處置中")
    df_jail = load_local_jail()

    if df_jail.empty:
        st.info("目前無處置中標的，或請點擊「同步國票清單」。")
    else:
        # 格式化顯示
        # 依照出關時間排序，最近的排前面
        df_display = df_jail.sort_values(by="出關時間")
        
        # 顯示表格
        st.dataframe(
            df_display[["股票名稱及代號", "撮合方式", "出關時間"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "出關時間": st.column_config.TextColumn("🔓 出關時間 (結束日+1)"),
                "撮合方式": st.column_config.TextColumn("⏳ 撮合頻率")
            }
        )

        # 簡單統計
        count_5 = len(df_jail[df_jail['撮合方式'].str.contains('5')])
        count_20 = len(df_jail[df_jail['撮合方式'].str.contains('20')])
        
        c1, c2 = st.columns(2)
        c1.metric("5分鐘撮合 (Level 1)", f"{count_5} 檔")
        c2.metric("20分鐘撮合 (Level 2)", f"{count_20} 檔")

    st.divider()
    st.markdown("""
    ### 📖 處置規則速查
    * **第一次處置**：約每 5 分鐘撮合一次，期間 10 個營業日 [cite: 29]。
    * **第二次處置 (累犯)**：最近 30 日內第二次觸發，約每 20 分鐘撮合一次，並需全額預收 [cite: 29]。
    * **出關日計算**：本表顯示之時間已依據需求調整為「處置結束日之次日」。
    """)

if __name__ == "__main__":
    main()
