import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime, timedelta
import io

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心 V15", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"
REQUIRED_COLS = ["股票名稱及代號", "代號", "撮合方式", "出關時間"]

# --- 2. 核心邏輯：日期與解析工具 ---
def convert_minguo_to_date(date_str):
    """將民國格式 (114/12/31) 轉為西元 datetime 並加 1 天"""
    try:
        # 處理可能的空格或隱形字元
        clean_str = date_str.strip().replace(" ", "")
        y, m, d = map(int, clean_str.split('/'))
        western_year = y + 1911
        # 規則：結束日之次日才算出關
        return datetime(western_year, m, d) + timedelta(days=1)
    except:
        return None

def extract_match_mode(content):
    """從處置內容提取撮合分鐘 (5 或 20)"""
    content = str(content)
    if "20" in content or "二十分鐘" in content:
        return "20"
    return "5"

# --- 3. 官方 CSV 檔案處理引擎 ---
def process_official_csv(uploaded_file):
    """解析上市(TWSE)或上櫃(TPEx)的 CSV 內容"""
    results = []
    today = datetime.now()
    
    try:
        # 讀取檔案內容進行初步判定
        content = uploaded_file.read().decode('utf-8-sig')
        lines = content.splitlines()
        
        # A. 上市 (TWSE) 判定：通常第一行是標題，第二行是欄位
        if "公布處置有價證券資訊" in lines[0]:
            df = pd.read_csv(io.StringIO("\n".join(lines[1:])))
            time_col = '處置起迄時間' # 上市用「迄」
        # B. 上櫃 (TPEx) 判定：通常前兩行是標題，第三行是欄位
        elif "上櫃處置股票資訊" in lines[0]:
            df = pd.read_csv(io.StringIO("\n".join(lines[2:])))
            time_col = '處置起訖時間' # 上櫃用「訖」
        else:
            # 萬一不符合以上格式，嘗試直接讀取
            df = pd.read_csv(io.StringIO(content))
            time_col = next((c for c in df.columns if '處置起' in c), None)

        # 核心清洗與整理
        for _, row in df.iterrows():
            try:
                # 取得必要資訊
                raw_name = str(row.get('證券名稱', '')).strip()
                raw_code = str(row.get('證券代號', '')).split('.')[0].strip()
                content = str(row.get('處置內容', ''))
                period = str(row.get(time_col, ''))
                
                if not raw_code or not period or '~' not in period:
                    continue

                # 解析出關日期
                end_date_str = period.split('~')[1]
                release_obj = convert_minguo_to_date(end_date_str)
                
                if release_obj and release_obj > today:
                    results.append({
                        "股票名稱及代號": f"{raw_name} ({raw_code})",
                        "代號": raw_code,
                        "撮合方式": f"{extract_match_mode(content)} 分鐘",
                        "出關時間": release_obj.strftime("%Y-%m-%d")
                    })
            except:
                continue
    except Exception as e:
        st.error(f"檔案 {uploaded_file.name} 解析失敗：{e}")
        
    return results

# --- 4. 資料庫維護與防錯 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        try:
            df = pd.read_csv(JAIL_FILE).astype(str)
            # 修正 KeyError：若欄位不符則強制重置
            if not all(col in df.columns for col in REQUIRED_COLS):
                return pd.DataFrame(columns=REQUIRED_COLS)
            
            # 自動剔除已過出關日的標的
            today_str = datetime.now().strftime("%Y-%m-%d")
            return df[df["出關時間"] > today_str]
        except:
            return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.DataFrame(columns=REQUIRED_COLS)

def save_db(df):
    if not df.empty:
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 介面呈現 ---
def main():
    st.title("⚖️ 處置中 - 官方匯入版")
    st.caption(f"數據自動化整理 | 今日：{datetime.now().strftime('%Y-%m-%d')}")

    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    tab1, tab2 = st.tabs(["📌 處置監控清單", "📥 匯入官方 CSV"])

    with tab1:
        db = st.session_state.jail_db
        if not db.empty:
            c1, c2 = st.columns(2)
            c1.metric("監控總數", f"{len(db)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(db[db['撮合方式'].str.contains('20')])} 檔")

            st.markdown("---")
            df_display = db.sort_values(by="出關時間")
            st.dataframe(
                df_display[["股票名稱及代號", "撮合方式", "出關時間"]],
                use_container_width=True,
                hide_index=True,
                column_config={"出關時間": "🔓 出關時間 (結束日+1)"}
            )
        else:
            st.info("目前清單為空。請至「匯入官方 CSV」上傳您下載的檔案。")

    with tab2:
        st.subheader("檔案匯入")
        st.markdown("請同時上傳 **證交所 (punish.csv)** 與 **櫃買 (disposal_information.csv)** 檔案。")
        
        uploaded_files = st.file_uploader("選擇 CSV 檔案...", type="csv", accept_multiple_files=True)
        
        if st.button("🚀 執行匯入與自動計算", type="primary"):
            if uploaded_files:
                all_new_data = []
                for f in uploaded_files:
                    all_new_data.extend(process_official_csv(f))
                
                if all_new_data:
                    new_df = pd.DataFrame(all_new_data)
                    combined = pd.concat([st.session_state.jail_db, new_df])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success(f"成功整理並匯入 {len(all_new_data)} 筆有效處置資料！")
                    st.rerun()
                else:
                    st.warning("檔案中未偵測到尚未出關的處置資料。")
            else:
                st.warning("請先選擇上傳檔案。")

        st.divider()
        if st.button("🗑️ 重置資料庫"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=REQUIRED_COLS)
            st.rerun()

if __name__ == "__main__":
    main()
