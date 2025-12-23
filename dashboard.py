import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta

# --- 1. 系統設定 ---
st.set_page_config(page_title="處置監控系統 V10", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心：超級日期解析器 ---
def super_date_parser(text):
    """
    極速解析各種日期格式：2025-12-24, 114/12/24, 114年12月24日
    並依規則回傳 結束日+1 天
    """
    text = str(text).replace(" ", "")
    # 規則：尋找「至」後面的日期 
    target_part = text.split("至")[-1] if "至" in text else text

    # 格式 A: 2025-12-24 或 2025/12/24
    iso_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', target_part)
    if iso_match:
        y, m, d = map(int, iso_match.groups())
        return (datetime(y, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")

    # 格式 B: 114年12月24日 或 114.12.24
    tw_match = re.search(r'(\d{3})[年./](\d{1,2})[月./](\d{1,2})', target_part)
    if tw_match:
        y, m, d = map(int, tw_match.groups())
        return (datetime(y + 1911, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")

    return None

# --- 3. 核心：地毯式掃描邏輯 ---
def fetch_all_jail_stocks():
    """
    不限表格，掃描全網頁所有包含股票代號與處置關鍵字的列
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        results = []
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 抓取所有 <tr> 標籤 (不限特定表格)
        all_rows = soup.find_all('tr')
        
        for row in all_rows:
            row_text = row.get_text("|", strip=True)
            
            # 關鍵特徵：必須包含代號 (4-5位數字) 且包含 撮合時間 [cite: 6, 12]
            code_match = re.search(r'\((\d{4,5})\)', row_text)
            if code_match and ("分鐘" in row_text or "撮合" in row_text):
                code = code_match.group(1)
                cells = [c.get_text(strip=True) for c in row.find_all('td')]
                
                if len(cells) >= 4:
                    # a. 股票名稱及代號 (欄位 1)
                    name = cells[1].split('(')[0].strip()
                    # b. 撮合方式 [cite: 6]
                    mode = "20" if "20" in cells[2] else "5"
                    # c. 出關時間 (解析處置內容或日期欄位)
                    # 優先從最後一欄(內容)解析，若無則看全行文字
                    release_date = super_date_parser(cells[-1]) or super_date_parser(row_text)
                    
                    if release_date:
                        # 規則：出關日 = 結束日+1，已過期則剔除
                        if release_date > today_str:
                            results.append({
                                "股票名稱及代號": f"{name} ({code})",
                                "代號": code,
                                "撮合方式": f"{mode} 分鐘",
                                "出關時間": release_date
                            })

        # 去重：以代號為準，保留最新出關日
        df = pd.DataFrame(results).drop_duplicates(subset=['代號'], keep='last')
        return df
    except Exception as e:
        st.error(f"掃描失敗: {e}")
        return pd.DataFrame()

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置中標的監控")
    st.caption(f"全自動地毯式掃描 | 更新時間：{datetime.now().strftime('%H:%M:%S')}")

    if st.button("🔄 同步國票清單 (全面掃描)", type="primary"):
        with st.spinner("正在執行全網頁列掃描，確保不漏掉任何一筆..."):
            df = fetch_all_jail_stocks()
            if not df.empty:
                df = df.sort_values(by="出關時間")
                df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
                st.success(f"同步成功！共抓取到 {len(df)} 筆處置標的。")
            else:
                st.warning("未偵測到處置標的，請確認網頁是否有資料。")
            st.rerun()

    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        if not df.empty:
            # 顯示統計
            c1, c2 = st.columns(2)
            c1.metric("總處置檔數", f"{len(df)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(df[df['撮合方式'].str.contains('20')])} 檔")

            st.dataframe(
                df[["股票名稱及代號", "撮合方式", "出關時間"]],
                use_container_width=True,
                hide_index=True,
                column_config={"出關時間": "🔓 出關時間 (結束日+1)"}
            )
        else:
            st.info("清單為空。")
    else:
        st.info("請點擊同步按鈕。")

if __name__ == "__main__":
    main()
