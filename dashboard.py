import streamlit as st
import pandas as pd
import os
import re
import io
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"
REQUIRED_COLS = ["股票名稱及代號", "代號", "撮合方式", "出關時間", "處置原因"]

# --- 2. 工具函式 ---
def get_weekday_cn(date_str):
    """將日期字串轉為極簡格式：12/24(三)"""
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        return f"{dt.month}/{dt.day}({weekdays[dt.weekday()]})"
    except:
        return str(date_str)

def convert_minguo_to_date(date_str):
    """將民國格式轉為西元並加 1 天 (出關日)"""
    try:
        clean_str = str(date_str).strip().replace(" ", "")
        y, m, d = map(int, clean_str.split('/'))
        return datetime(y + 1911, m, d) + timedelta(days=1)
    except:
        return None

def extract_match_mode(content):
    """從處置內容提取撮合分鐘 (5 或 20)"""
    content = str(content)
    if "20" in content or "二十分鐘" in content:
        return "20"
    return "5"

def translate_to_human(row):
    """將專業術語轉為白話解讀標籤"""
    reason = str(row.get('處置原因', ''))
    mode = str(row.get('撮合方式', ''))
    notes = []
    if "沖銷" in reason:
        notes.append("🚫當沖加關")
    if "20" in mode:
        notes.append("💀重刑犯(預收)")
    return " / ".join(notes) if notes else "一般冷卻"

# --- 3. 官方 CSV 檔案處理引擎 ---
def process_official_csv(uploaded_file):
    """解析官方 CSV (上市 punish.csv / 上櫃 disposal)"""
    results = []
    today = datetime.now()
    try:
        raw_bytes = uploaded_file.read()
        try:
            content = raw_bytes.decode('cp950') # 繁體常用編碼
        except UnicodeDecodeError:
            content = raw_bytes.decode('utf-8-sig')
            
        lines = content.splitlines()
        if not lines: return []

        if "公布處置有價證券資訊" in lines[0]:
            df = pd.read_csv(io.StringIO("\n".join(lines[1:])))
            time_col, reason_col = '處置起迄時間', '處置條件'
        elif "上櫃處置股票資訊" in lines[0] or "期間:" in lines[0]:
            df = pd.read_csv(io.StringIO("\n".join(lines[2:])))
            time_col, reason_col = '處置起訖時間', '處置原因'
        else:
            df = pd.read_csv(io.StringIO("\n".join(lines)))
            time_col = next((c for c in df.columns if '處置起' in c), None)
            reason_col = next((c for c in df.columns if '原因' in c or '條件' in c), None)

        for _, row in df.iterrows():
            try:
                name = str(row.get('證券名稱', '未知')).strip()
                code = str(row.get('證券代號', '')).split('.')[0].strip()
                measure_content = str(row.get('處置內容', ''))
                reason = str(row.get(reason_col, '')) if reason_col else ""
                period = str(row.get(time_col, ''))
                if not code or '~' not in period: continue
                end_date_part = period.split('~')[1]
                release_obj = convert_minguo_to_date(end_date_part)
                if release_obj and release_obj > today:
                    results.append({
                        "股票名稱及代號": f"{name} ({code})",
                        "代號": str(code),
                        "撮合方式": f"{extract_match_mode(measure_content)} 分鐘",
                        "出關時間": release_obj.strftime("%Y-%m-%d"),
                        "處置原因": reason
                    })
            except: continue
    except Exception as e:
        st.error(f"解析失敗：{e}")
    return results

# --- 4. 資料庫維護 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        try:
            df = pd.read_csv(JAIL_FILE, encoding='utf-8-sig').astype(str)
            for col in REQUIRED_COLS:
                if col not in df.columns: df[col] = ""
            today_str = datetime.now().strftime("%Y-%m-%d")
            return df[df["出關時間"] > today_str]
        except:
            return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.DataFrame(columns=REQUIRED_COLS)

def save_db(df):
    if not df.empty:
        df = df[REQUIRED_COLS]
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 主程式介面 ---
def main():
    st.title("⚖️ 處置中標的監控")
    
    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()
    
    if 'new_stocks' not in st.session_state:
        st.session_state.new_stocks = pd.DataFrame(columns=REQUIRED_COLS)

    # --- A. 數據更新區塊 ---
    with st.expander("📥 數據更新 (上傳官方 CSV)"):
        uploaded_files = st.file_uploader("上傳 CSV", type="csv", accept_multiple_files=True, label_visibility="collapsed")
        if uploaded_files:
            if st.button("執行匯入", use_container_width=True):
                all_new_data_list = []
                for f in uploaded_files:
                    f.seek(0)
                    all_new_data_list.extend(process_official_csv(f))
                
                if all_new_data_list:
                    new_upload_df = pd.DataFrame(all_new_data_list)
                    
                    # 邏輯：比對找出「新入選」的標的
                    existing_codes = set(st.session_state.jail_db['代號'].tolist())
                    new_entries = new_upload_df[~new_upload_df['代號'].isin(existing_codes)]
                    st.session_state.new_stocks = new_entries
                    
                    # 更新總資料庫
                    combined = pd.concat([st.session_state.jail_db, new_upload_df])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success(f"更新成功！偵測到 {len(new_entries)} 筆新進處置標的。")
                    st.rerun()

    db = st.session_state.jail_db
    if not db.empty:
        # 預處理顯示欄位
        def prepare_display(df):
            if df.empty: return df
            d = df.copy()
            d["🔓 出關日期"] = d["出關時間"].apply(get_weekday_cn)
            d["🚨 白話解讀"] = d.apply(translate_to_human, axis=1)
            return d.sort_values(by="出關時間")

        db_sorted = prepare_display(db)
        new_sorted = prepare_display(st.session_state.new_stocks)

        # --- B. 新增：明日進處置區塊 ---
        st.markdown("---")
        col_new_l, col_new_r = st.columns(2)
        with col_new_l:
            st.markdown("### 🆕 明日進處置")
            if not new_sorted.empty:
                st.dataframe(new_sorted[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)
            else:
                st.write("目前無新入選標的")
        with col_new_r:
            st.write("") # 右邊留空

        # --- C. 5分鐘 vs 20分鐘看板 ---
        st.markdown("---")
        col_5, col_20 = st.columns(2)
        with col_5:
            st.subheader("⏳ 5分鐘撮合")
            df_5 = db_sorted[db_sorted['撮合方式'].str.contains('5')]
            st.dataframe(df_5[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)

        with col_20:
            st.subheader("🚨 20分鐘撮合")
            df_20 = db_sorted[db_sorted['撮合方式'].str.contains('20')]
            st.dataframe(df_20[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)

        # --- D. 完整詳細清單 ---
        st.markdown("---")
        st.subheader("📋 完整監控清單")
        st.dataframe(db_sorted[["股票名稱及代號", "撮合方式", "🔓 出關日期", "處置原因"]], use_container_width=True, hide_index=True)
    else:
        st.info("資料庫目前為空。")

    with st.sidebar:
        st.subheader("⚙️ 系統管理")
        if st.button("🗑️ 清空資料庫"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=REQUIRED_COLS)
            st.session_state.new_stocks = pd.DataFrame(columns=REQUIRED_COLS)
            st.rerun()

if __name__ == "__main__":
    main()
