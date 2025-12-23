import streamlit as st
import pandas as pd
import os
import re
import io
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"
REQUIRED_COLS = ["股票名稱及代號", "代號", "撮合方式", "出關時間"]

# --- 2. 核心邏輯：日期與解析工具 ---
def convert_minguo_to_date(date_str):
    """將民國格式轉為西元 datetime 並加 1 天"""
    try:
        clean_str = date_str.strip().replace(" ", "")
        y, m, d = map(int, clean_str.split('/'))
        western_year = y + 1911
        # 規則：處置結束時間的隔天才算出關
        return datetime(western_year, m, d) + timedelta(days=1)
    except:
        return None

def extract_match_mode(content):
    """從處置內容提取撮合分鐘"""
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
        raw_bytes = uploaded_file.read()
        try:
            content = raw_bytes.decode('cp950') # 支援 Big5
        except UnicodeDecodeError:
            content = raw_bytes.decode('utf-8-sig') # 支援 UTF-8
            
        lines = content.splitlines()
        if not lines: return []

        # A. 證交所 (上市 punish.csv)
        if "公布處置有價證券資訊" in lines[0]:
            df = pd.read_csv(io.StringIO("\n".join(lines[1:])))
            time_col = '處置起迄時間'
        # B. 櫃買中心 (上櫃 disposal)
        elif "上櫃處置股票資訊" in lines[0] or "期間:" in lines[0]:
            df = pd.read_csv(io.StringIO("\n".join(lines[2:])))
            time_col = '處置起訖時間'
        else:
            header_idx = 0
            for i, line in enumerate(lines[:5]):
                if "證券代號" in line:
                    header_idx = i
                    break
            df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
            time_col = next((c for c in df.columns if '處置起' in c), None)

        for _, row in df.iterrows():
            try:
                name = str(row.get('證券名稱', '')).strip()
                code = str(row.get('證券代號', '')).split('.')[0].strip()
                measure_content = str(row.get('處置內容', ''))
                period = str(row.get(time_col, ''))
                
                if not code or not period or '~' not in period:
                    continue

                end_date_part = period.split('~')[1]
                release_obj = convert_minguo_to_date(end_date_part)
                
                if release_obj and release_obj > today:
                    results.append({
                        "股票名稱及代號": f"{name} ({code})",
                        "代號": code,
                        "撮合方式": f"{extract_match_mode(measure_content)} 分鐘",
                        "出關時間": release_obj.strftime("%Y-%m-%d")
                    })
            except:
                continue
    except Exception as e:
        st.error(f"解析 {uploaded_file.name} 失敗：{e}")
    return results

# --- 4. 資料庫維護 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        try:
            df = pd.read_csv(JAIL_FILE, encoding='utf-8-sig').astype(str)
            if not all(col in df.columns for col in REQUIRED_COLS):
                return pd.DataFrame(columns=REQUIRED_COLS)
            # 自動剔除已出關標的
            today_str = datetime.now().strftime("%Y-%m-%d")
            return df[df["出關時間"] > today_str]
        except:
            return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.DataFrame(columns=REQUIRED_COLS)

def save_db(df):
    if not df.empty:
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 主程式介面 ---
def main():
    st.title("⚖️ 處置中標的監控")
    
    # 初始化資料
    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    # --- A. 簡化上傳 UI (收納在 Expander) ---
    with st.expander("📥 數據更新 (上傳官方 CSV)"):
        uploaded_files = st.file_uploader("請選擇 punish.csv 或 disposal.csv", type="csv", accept_multiple_files=True, label_visibility="collapsed")
        if uploaded_files:
            if st.button("執行匯入", use_container_width=True):
                all_new_data = []
                for f in uploaded_files:
                    f.seek(0)
                    all_new_data.extend(process_official_csv(f))
                if all_new_data:
                    new_df = pd.DataFrame(all_new_data)
                    combined = pd.concat([st.session_state.jail_db, new_df])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success(f"已匯入 {len(all_new_data)} 筆資料")
                    st.rerun()

    # --- B. 主監控列表 ---
    db = st.session_state.jail_db
    if not db.empty:
        # 頂部快訊
        c1, c2, c3 = st.columns([1, 1, 2])
        c1.metric("總處置檔數", f"{len(db)} 檔")
        c2.metric("20分鐘(L2)", f"{len(db[db['撮合方式'].str.contains('20')])} 檔")
        c3.caption(f"🕒 更新時間：{datetime.now().strftime('%m/%d %H:%M')}")

        st.markdown("---")
        # 排序並顯示
        df_display = db.sort_values(by="出關時間")
        st.dataframe(
            df_display[["股票名稱及代號", "撮合方式", "出關時間"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "股票名稱及代號": st.column_config.TextColumn("證券標的"),
                "撮合方式": st.column_config.TextColumn("⏳ 撮合"),
                "出關時間": st.column_config.TextColumn("🔓 出關 (結束日+1)")
            }
        )
    else:
        st.info("目前資料庫為空。請展開上方「數據更新」進行檔案匯入。")

    # --- C. 功能區域 (重置) ---
    with st.sidebar:
        st.subheader("系統管理")
        if st.button("🗑️ 清空資料庫"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=REQUIRED_COLS)
            st.rerun()

if __name__ == "__main__":
    main()
