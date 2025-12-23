import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta

# --- 1. 系統設定與檔案路徑 ---
st.set_page_config(page_title="處置監控中心", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list_v8.csv"

# --- 2. 核心：智慧爬蟲邏輯 ---
def smart_scrape_ibf():
    """
    使用 BeautifulSoup 進行精準定位，而非僅用 pd.read_html
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        response.encoding = 'utf-8' # 確保中文不亂碼
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 尋找包含「處置」關鍵字的表格
        table = None
        for t in soup.find_all('table'):
            if "處置內容" in t.text:
                table = t
                break
        
        if table is None: return pd.DataFrame()

        data = []
        rows = table.find_all('tr')
        for row in rows[1:]: # 跳過表頭
            cols = row.find_all(['td', 'th'])
            if len(cols) < 5: continue
            
            row_text = [c.text.strip() for c in cols]
            
            # 智慧提取資訊：利用正則表達式抓取括號內的代號
            # 格式範例：新盛力 (4931) 
            name_raw = row_text[1]
            code_match = re.search(r'(\d{4,6})', row_text[2])
            code = code_match.group(1) if code_match else "未知"
            name = name_raw.split('(')[0].strip()
            
            # 撮合方式：提取數字 
            match_mode = "".join(filter(str.isdigit, row_text[3]))
            
            # 內容解析出關時間 (結束日+1)
            content = row_text[5] if len(row_text) > 5 else ""
            release_date = parse_release_date_logic(content)
            
            data.append({
                "股票名稱": name,
                "代號": code,
                "撮合方式": match_mode,
                "出關時間": release_date,
                "處置原因": row_text[4] # 處置條件 
            })
            
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"智慧爬蟲啟動失敗: {e}")
        return pd.DataFrame()

def parse_release_date_logic(content):
    """
    實作規則：抓取「至114年12月31日」，回傳隔天
    """
    try:
        match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(content))
        if match:
            year = int(match.group(1)) + 1911
            month = int(match.group(2))
            day = int(match.group(3))
            end_date = datetime(year, month, day)
            release_date = end_date + timedelta(days=1)
            return release_date.strftime("%Y-%m-%d")
    except:
        pass
    return "需手動確認"

# --- 3. 資料庫存取與自動維護 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        return pd.read_csv(JAIL_FILE).astype(str)
    return pd.DataFrame(columns=["股票名稱", "代號", "撮合方式", "出關時間", "處置原因"])

def save_db(df):
    # 自動剔除：過濾掉出關時間早於今天的標的
    today_str = datetime.now().strftime("%Y-%m-%d")
    df = df[df["出關時間"] >= today_str]
    df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 4. Streamlit 介面設計 ---
def main():
    st.title("🛡️ 處置監控智慧雷達")
    
    # 初始化資料庫
    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    # --- 功能選單 ---
    tab1, tab2 = st.tabs(["📌 處置中標的", "⚙️ 資料庫管理"])

    with tab1:
        st.header("處置中股票清單")
        
        # 快速統計資訊 [cite: 9]
        db = st.session_state.jail_db
        if not db.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("總處置檔數", f"{len(db)} 檔")
            c2.metric("20分鐘(Level 2)", f"{len(db[db['撮合方式'] == '20'])} 檔")
            c3.metric("5分鐘(Level 1)", f"{len(db[db['撮合方式'] == '5'])} 檔")
            
            # 格式化合併名稱與代號顯示
            db_display = db.copy()
            db_display["股票名稱及代號"] = db_display["股票名稱"] + " (" + db_display["代號"] + ")"
            
            # 依照出關時間排序
            db_display = db_display.sort_values(by="出關時間")
            
            st.dataframe(
                db_display[["股票名稱及代號", "撮合方式", "出關時間", "處置原因"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "出關時間": st.column_config.TextColumn("🔓 出關日期 (結束日+1)"),
                    "撮合方式": st.column_config.TextColumn("⏳ 撮合頻率 (分)")
                }
            )
        else:
            st.info("資料庫目前為空，請至管理頁面同步資料。")

    with tab2:
        st.header("數據維護中心")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 同步國票最新清單", type="primary"):
                scraped_df = smart_scrape_ibf()
                if not scraped_df.empty:
                    # 融合現有資料與抓取資料
                    new_db = pd.concat([st.session_state.jail_db, scraped_df]).drop_duplicates(subset=['代號'], keep='last')
                    st.session_state.jail_db = new_db
                    save_db(new_db)
                    st.success("同步成功！系統已依據規則自動計算出關日與剔除過期標的。")
                    st.rerun()
                else:
                    st.error("未能抓取到網頁資料，請檢查網路。")
        
        with col2:
            if st.button("🗑️ 清空所有資料庫 (重置)"):
                st.session_state.jail_db = pd.DataFrame(columns=["股票名稱", "代號", "撮合方式", "出關時間", "處置原因"])
                if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
                st.rerun()

        st.divider()
        st.subheader("✍️ 手動快速校正")
        st.write("如果自動抓取有誤，您可以直接編輯下表，編輯完後記得點擊下方存檔：")
        edited_df = st.data_editor(st.session_state.jail_db, num_rows="dynamic", use_container_width=True)
        
        if st.button("💾 儲存手動修改"):
            st.session_state.jail_db = edited_df
            save_db(edited_df)
            st.success("手動修改已存檔！")

if __name__ == "__main__":
    main()
