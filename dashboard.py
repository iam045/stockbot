import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心 V14", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心邏輯：日期與撮合解析 ---
def convert_minguo_to_date(date_str):
    """
    將民國格式 (114/12/31) 轉換為 Python datetime 並加 1 天 (出關日)
    """
    try:
        y, m, d = map(int, date_str.split('/'))
        western_year = y + 1911
        # 規則：處置結束時間的隔天才算出關
        return datetime(western_year, m, d) + timedelta(days=1)
    except:
        return None

def extract_match_mode(content):
    """
    從處置內容中提取撮合分鐘數 (5 或 20)
    """
    content = str(content)
    if "20" in content or "二十分鐘" in content:
        return "20"
    return "5"

# --- 3. 檔案處理邏輯 ---
def process_uploaded_files(files):
    """
    讀取並整理上傳的官方 CSV 資料
    """
    combined_results = []
    today = datetime.now()

    for uploaded_file in files:
        filename = uploaded_file.name.lower()
        try:
            # A. 判斷是否為上市 (TWSE) 檔案：通常名稱含 punish
            if "punish" in filename:
                df = pd.read_csv(uploaded_file, header=1) # 上市 CSV 第一行為標題，第二行為欄位名
            # B. 判斷是否為上櫃 (TPEx) 檔案
            else:
                df = pd.read_csv(uploaded_file) # 上櫃 CSV 通常直接讀取
            
            # 確保必要欄位存在
            required = ['證券名稱', '證券代號', '處置起訖時間', '處置內容']
            if not all(col in df.columns for col in required):
                st.error(f"檔案 {uploaded_file.name} 格式不符，請確認是官方下載的處置公告 CSV。")
                continue

            for _, row in df.iterrows():
                # 1. 股票名稱及代號
                name = str(row['證券名稱']).strip()
                # 處理代號為 float 的情況
                code = str(int(float(row['證券代號']))) if pd.notna(row['證券代號']) else "未知"
                
                # 2. 撮合方式 (5 or 20)
                mode = extract_match_mode(row['處置內容'])
                
                # 3. 出關時間 (結束日+1)
                period = str(row['處置起訖時間'])
                if '~' in period:
                    end_date_str = period.split('~')[1]
                    release_date_obj = convert_minguo_to_date(end_date_str)
                    
                    if release_date_obj:
                        # 規則：只有尚未出關的才加入清單
                        if release_date_obj > today:
                            combined_results.append({
                                "股票名稱及代號": f"{name} ({code})",
                                "代號": code,
                                "撮合方式": f"{mode} 分鐘",
                                "出關時間": release_date_obj.strftime("%Y-%m-%d")
                            })
        except Exception as e:
            st.error(f"讀取檔案 {uploaded_file.name} 時發生錯誤：{e}")

    return pd.DataFrame(combined_results)

# --- 4. 資料庫維護 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE).astype(str)
        # 讀取時自動剔除已出關標的
        today_str = datetime.now().strftime("%Y-%m-%d")
        return df[df["出關時間"] > today_str]
    return pd.DataFrame(columns=["股票名稱及代號", "代號", "撮合方式", "出關時間"])

def save_db(df):
    if not df.empty:
        # 去重並保留最新
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 介面呈現 ---
def main():
    st.title("⚖️ 處置中 - 官方數據匯入中心")
    st.caption(f"目前時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    tab1, tab2 = st.tabs(["📌 處置監控清單", "📥 上傳官方檔案"])

    with tab1:
        db = st.session_state.jail_db
        if not db.empty:
            c1, c2 = st.columns(2)
            c1.metric("監控總數", f"{len(db)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(db[db['撮合方式'].str.contains('20')])} 檔")

            st.markdown("---")
            # 依出關時間排序
            df_display = db.sort_values(by="出關時間")
            st.dataframe(
                df_display[["股票名稱及代號", "撮合方式", "出關時間"]],
                use_container_width=True,
                hide_index=True,
                column_config={"出關時間": "🔓 出關時間 (結束日+1)"}
            )
        else:
            st.info("目前資料庫為空。請至「上傳官方檔案」分頁匯入 CSV。")

    with tab2:
        st.subheader("📥 匯入官方 CSV 數據")
        st.markdown("""
        **操作步驟：**
        1. 至 **證交所** 或 **櫃買中心** 下載處置有價證券的 CSV 檔案。
        2. 將這兩個檔案同時拖入下方（支援多檔上傳）。
        3. 系統會自動解析並更新 `jail_list.csv`。
        """)
        
        uploaded_files = st.file_uploader("請選擇官方 CSV 檔案...", type="csv", accept_multiple_files=True)
        
        if st.button("🚀 開始自動整理並匯入", type="primary"):
            if uploaded_files:
                new_df = process_uploaded_files(uploaded_files)
                if not new_df.empty:
                    # 合併舊資料
                    combined = pd.concat([st.session_state.jail_db, new_df])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success(f"匯入成功！已從檔案中提取出 {len(new_df)} 筆有效處置標的。")
                    st.rerun()
                else:
                    st.error("未能從檔案中解析出有效的處置標的，請確認日期是否已過期。")
            else:
                st.warning("請先上傳檔案。")

        st.divider()
        if st.button("🗑️ 清空資料庫"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=["股票名稱及代號", "代號", "撮合方式", "出關時間"])
            st.rerun()

if __name__ == "__main__":
    main()
