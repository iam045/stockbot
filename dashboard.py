import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime, timedelta
import io

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心 V16", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"
REQUIRED_COLS = ["股票名稱及代號", "代號", "撮合方式", "出關時間"]

# --- 2. 核心邏輯：日期與解析工具 ---
def convert_minguo_to_date(date_str):
    """將民國格式 (114/12/31) 轉為西元 datetime 並加 1 天 (出關日)"""
    try:
        clean_str = date_str.strip().replace(" ", "")
        y, m, d = map(int, clean_str.split('/'))
        western_year = y + 1911
        # 規則：處置結束時間的隔天（結束日+1）才算出關
        return datetime(western_year, m, d) + timedelta(days=1)
    except:
        return None

def extract_match_mode(content):
    """從處置內容提取撮合分鐘 (5 或 20)"""
    content = str(content)
    if "20" in content or "二十分鐘" in content:
        return "20"
    return "5"

# --- 3. 官方 CSV 檔案處理引擎 (修正編碼問題) ---
def process_official_csv(uploaded_file):
    """解析上市(TWSE)或上櫃(TPEx)的 CSV 內容，支援 Big5 編碼"""
    results = []
    today = datetime.now()
    
    try:
        # 解決編碼問題：優先嘗試 cp950 (繁體中文常用編碼)
        raw_bytes = uploaded_file.read()
        try:
            content = raw_bytes.decode('cp950')
        except UnicodeDecodeError:
            content = raw_bytes.decode('utf-8-sig') # 備援使用帶 BOM 的 UTF-8
            
        lines = content.splitlines()
        if not lines: return []

        # A. 上市 (punish.csv) 判定
        if "公布處置有價證券資訊" in lines[0]:
            # 第 2 行 (索引 1) 才是真正的欄位標頭
            df = pd.read_csv(io.StringIO("\n".join(lines[1:])))
            time_col = '處置起迄時間'
        # B. 上櫃 (disposal_information) 判定
        elif "上櫃處置股票資訊" in lines[0] or "期間:" in lines[0]:
            # 第 3 行 (索引 2) 才是真正的欄位標頭
            df = pd.read_csv(io.StringIO("\n".join(lines[2:])))
            time_col = '處置起訖時間'
        else:
            # 泛用嘗試：自動找尋包含「證券代號」的那一行作為標頭
            header_idx = 0
            for i, line in enumerate(lines[:5]):
                if "證券代號" in line:
                    header_idx = i
                    break
            df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
            time_col = next((c for c in df.columns if '處置起' in c), None)

        # 清洗與整理資料
        for _, row in df.iterrows():
            try:
                # 取得必要資訊並轉為字串
                name = str(row.get('證券名稱', '')).strip()
                # 處理代號可能被讀成浮點數的情況 (如 4931.0)
                code_raw = str(row.get('證券代號', '')).split('.')[0].strip()
                measure_content = str(row.get('處置內容', ''))
                period = str(row.get(time_col, ''))
                
                if not code_raw or not period or '~' not in period:
                    continue

                # 解析出關日期 (結束日+1)
                end_date_part = period.split('~')[1]
                release_obj = convert_minguo_to_date(end_date_part)
                
                if release_obj and release_obj > today:
                    results.append({
                        "股票名稱及代號": f"{name} ({code_raw})",
                        "代號": code_raw,
                        "撮合方式": f"{extract_match_mode(measure_content)} 分鐘",
                        "出關時間": release_obj.strftime("%Y-%m-%d")
                    })
            except:
                continue
    except Exception as e:
        st.error(f"檔案 {uploaded_file.name} 處理失敗：{e}")
        
    return results

# --- 4. 資料庫維護與防錯 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        try:
            # 讀取本地 CSV 也預設使用 utf-8-sig 以相容 Excel
            df = pd.read_csv(JAIL_FILE, encoding='utf-8-sig').astype(str)
            # 防錯：若欄位不符則重置
            if not all(col in df.columns for col in REQUIRED_COLS):
                return pd.DataFrame(columns=REQUIRED_COLS)
            
            # 自動過期剔除
            today_str = datetime.now().strftime("%Y-%m-%d")
            return df[df["出關時間"] > today_str]
        except:
            return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.DataFrame(columns=REQUIRED_COLS)

def save_db(df):
    if not df.empty:
        # 去重並存檔
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 介面呈現 ---
def main():
    st.title("⚖️ 處置中 - 官方 CSV 匯入系統")
    st.caption(f"已支援 Big5 編碼自動轉換 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    tab1, tab2 = st.tabs(["📌 處置監控清單", "📥 上傳官方檔案"])

    with tab1:
        db = st.session_state.jail_db
        if not db.empty:
            c1, c2 = st.columns(2)
            c1.metric("監控中總數", f"{len(db)} 檔")
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
            st.info("清單為空。請上傳證交所(punish.csv)或櫃買(disposal)的 CSV 檔。")

    with tab2:
        st.subheader("CSV 數據匯入")
        st.info("提示：系統會自動辨識上市/上櫃格式，並修正 Big5 編碼錯誤。")
        
        uploaded_files = st.file_uploader("請選擇 CSV 檔案...", type="csv", accept_multiple_files=True)
        
        if st.button("🚀 執行自動整理與匯入", type="primary"):
            if uploaded_files:
                all_new_data = []
                for f in uploaded_files:
                    # 每次讀取前重置指標位
                    f.seek(0)
                    all_new_data.extend(process_official_csv(f))
                
                if all_new_data:
                    new_df = pd.DataFrame(all_new_data)
                    combined = pd.concat([st.session_state.jail_db, new_df])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success(f"成功匯入 {len(all_new_data)} 筆尚未出關的處置標的！")
                    st.rerun()
                else:
                    st.warning("檔案解析成功，但未發現「尚未出關」的標的。")
            else:
                st.warning("請先選擇上傳檔案。")

        st.divider()
        if st.button("🗑️ 重置資料庫檔案"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=REQUIRED_COLS)
            st.rerun()

if __name__ == "__main__":
    main()
