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
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        # 國票網站通常有多個表格，我們搜尋含有「處置內容」字眼的那個 
        dfs = pd.read_html(response.text)
        for df in dfs:
            if any("處置內容" in str(col) for col in df.columns) or any("處置內容" in str(cell) for cell in df.values):
                return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"連線國票網站失敗: {e}")
        return pd.DataFrame()

def parse_release_date(content):
    """
    解析結束日期，並計算出關日期 (結束日+1) [cite: 28, 30]
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

# --- 3. 資料庫管理 (自動化新增與剔除) ---
def sync_jail_list():
    """
    自動化同步邏輯：解決 KeyError 問題，改用動態欄位偵測 [cite: 7, 28]
    """
    new_data = fetch_ibf_disposal_data()
    if new_data.empty:
        return load_local_jail()

    # 清洗資料：移除可能存在的標題列重複
    if "證券名稱" in new_data.iloc[0].values:
        new_data.columns = new_data.iloc[0]
        new_data = new_data[1:]

    processed_list = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 動態欄位識別，避免 KeyError [cite: 7, 28]
    cols = new_data.columns.tolist()
    
    # 建立映射 (尋找最接近的欄位索引)
    name_idx = next((i for i, c in enumerate(cols) if "名稱" in str(c)), 1)
    code_idx = next((i for i, c in enumerate(cols) if "代號" in str(c)), 2)
    mode_idx = next((i for i, c in enumerate(cols) if "撮合" in str(c)), 3)
    content_idx = next((i for i, i_c in enumerate(cols) if "處置內容" in str(i_c)), -1)

    for _, row in new_data.iterrows():
        try:
            name = str(row.iloc[name_idx])
            code = str(row.iloc[code_idx]).split('.')[0].strip()
            match_mode = str(row.iloc[mode_idx])
            # 如果 content_idx 找不到，嘗試最後一欄
            content = str(row.iloc[content_idx]) if content_idx != -1 else str(row.iloc[-1])
            
            release_date = parse_release_date(content)
            
            # 剔除已出關的標的
            if release_date != "解析失敗" and release_date <= today_str:
                continue
                
            processed_list.append({
                "股票名稱及代號": f"{name} ({code})",
                "代號": code,
                "撮合方式": f"{match_mode} 分鐘",
                "出關時間": release_date,
                "最後更新": today_str
            })
        except:
            continue

    df_jail = pd.DataFrame(processed_list)
    if not df_jail.empty:
        # 存檔前移除重複
        df_jail = df_jail.drop_duplicates(subset=['代號'])
        df_jail.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
    return df_jail

def load_local_jail():
    if os.path.exists(JAIL_FILE):
        try:
            return pd.read_csv(JAIL_FILE)
        except:
            return pd.DataFrame()
    return pd.DataFrame()

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置監控系統")
    st.caption(f"數據更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    col_a, col_b = st.columns([1, 4])
    with col_a:
        if st.button("🔄 同步國票清單", type="primary"):
            with st.spinner("正在抓取資料..."):
                sync_jail_list()
                st.success("同步完成")
                st.rerun()

    st.header("📌 處置中")
    df_jail = load_local_jail()

    if df_jail.empty:
        st.info("目前無處置中標的。請點擊「同步國票清單」。")
    else:
        # 依出關時間排序 [cite: 28, 30]
        df_display = df_jail.sort_values(by="出關時間")
        
        st.dataframe(
            df_display[["股票名稱及代號", "撮合方式", "出關時間"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "出關時間": st.column_config.TextColumn("🔓 出關時間 (結束日+1)"),
                "撮合方式": st.column_config.TextColumn("⏳ 撮合頻率")
            }
        )

        c1, c2 = st.columns(2)
        c1.metric("當前處置總數", f"{len(df_jail)} 檔")
        c2.metric("今日日期", datetime.now().strftime("%m/%d"))

    st.divider()
    st.markdown("""
    ### 📖 操作說明
    1. **自動新增**：點擊「同步」會自動抓取國票最新公告並加入新標的。
    2. **自動剔除**：系統會判斷「出關時間」，若已過期則不會顯示在表中。
    3. **出關定義**：本表顯示之日期為「處置結束日之隔日」。
    """)

if __name__ == "__main__":
    main()
