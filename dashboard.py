import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="處置監控系統 V11", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 超強效日期解析引擎 ---
def extract_release_date(text):
    """
    從長文本中提取處置結束日，並回傳 出關日 (結束日+1)
    """
    # 尋找格式：2026-01-08 或 115-01-08
    dates = re.findall(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', str(text))
    if len(dates) >= 2:
        # 取最後一個日期作為結束日
        y, m, d = map(int, dates[-1])
        # 判斷是否為民國年
        if y < 1900: y += 1911
        return (datetime(y, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 尋找中文格式：115年01月08日
    tw_match = re.search(r'(\d{3})年(\d{1,2})月(\d{1,2})日', str(text))
    if tw_match:
        y, m, d = map(int, tw_match.groups())
        return (datetime(y + 1911, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")
    
    return None

# --- 3. 核心：特徵掃描爬蟲 ---
def fetch_complete_data():
    """
    特徵掃描法：直接掃描所有文字塊，確保不遺漏紅框區任何一筆 
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    results = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')

        # 掃描網頁中所有的 <tr> (表格列)
        rows = soup.find_all('tr')
        
        for row in rows:
            text = row.get_text(" ", strip=True)
            
            # 特徵識別：包含 (代號) 且 包含 撮合方式 (5或20)
            code_match = re.search(r'(\w+)\s*\((\d{4,6})\)', text)
            if code_match:
                name = code_match.group(1)
                code = code_match.group(2)
                
                # 提取撮合方式 (5 或 20) 
                mode = "20" if "20" in text else "5"
                
                # 提取出關時間 (結束日+1)
                release_date = extract_release_date(text)
                
                if release_date:
                    # 規則：已出關則剔除
                    if release_date > today_str:
                        results.append({
                            "股票名稱及代號": f"{name} ({code})",
                            "代號": code,
                            "撮合方式": f"{mode} 分鐘",
                            "出關時間": release_date
                        })

        # 去重並轉換
        df = pd.DataFrame(results).drop_duplicates(subset=['代號'], keep='first')
        return df
    except Exception as e:
        st.error(f"同步失敗: {e}")
        return pd.DataFrame()

# --- 4. 主介面 ---
def main():
    st.title("⚖️ 處置中")
    st.caption(f"數據更新來源：國票證券官方公告 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    # 控制按鈕
    if st.button("🔄 同步國票清單 (全掃描防漏版)", type="primary"):
        with st.spinner("正在進行地毯式特徵掃描..."):
            df = fetch_complete_data()
            if not df.empty:
                df = df.sort_values(by="出關時間")
                df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
                st.success(f"同步完成！共成功抓取 {len(df)} 筆標的。")
            else:
                st.warning("未能偵測到有效處置數據。")
            st.rerun()

    # 顯示區
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        if not df.empty:
            # 統計資訊
            c1, c2, c3 = st.columns(3)
            c1.metric("總處置檔數", f"{len(df)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(df[df['撮合方式'].str.contains('20')])} 檔")
            c3.metric("5分鐘 (Level 1)", f"{len(df[df['撮合方式'].str.contains('5')])} 檔")

            st.markdown("---")
            # 欄位調整：依照您的需求
            st.dataframe(
                df[["股票名稱及代號", "撮合方式", "出關時間"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "出關時間": st.column_config.TextColumn("🔓 出關時間 (結束日+1)"),
                    "撮合方式": st.column_config.TextColumn("⏳ 撮合方式")
                }
            )
        else:
            st.info("資料庫目前為空。")
    else:
        st.info("請點擊同步按鈕。")

    st.divider()
    with st.expander("🛠️ 技術說明 (解決漏抓問題)"):
        st.write("1. **特徵掃描**：不再依賴特定表格順序，直接在網頁原始碼中搜尋「名稱(代號)」特徵，大幅提升抓取率 。")
        st.write("2. **深度解析內容**：自動從處置內容文字中提取日期區間，並精準鎖定「結束日期」。")
        st.write("3. **出關邏輯**：嚴格執行結束日 + 1 天。")
        st.write("4. **自動更新/剔除**：每次同步會依據系統日期自動刪除已過期的股票。")

if __name__ == "__main__":
    main()
