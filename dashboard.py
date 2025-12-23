import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime, timedelta
# 注意：此版本使用 streamlit 內建的 gsheets 連接功能
from streamlit_gsheets import GSheetsConnection

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心 (雲端版)", layout="wide", page_icon="⚖️")

# 🚩 請在此處填入您的 Google Sheet 網址
SHEET_URL = "https://docs.google.com/spreadsheets/d/1coeAz5srsqGVxVVH86xj6SQsbHuHH2H54VGmt3bkjaU/edit?usp=sharing"

REQUIRED_COLS = ["股票名稱及代號", "代號", "撮合方式", "處置起日", "出關時間", "處置原因"]

# --- 2. 工具函式 ---
def get_logical_today():
    now = datetime.now()
    if now.hour < 6:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def get_simple_date(date_str):
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        return f"{dt.month}/{dt.day}({weekdays[dt.weekday()]})"
    except:
        return str(date_str)

def parse_period(period_str):
    try:
        clean_str = str(period_str).strip().replace(" ", "")
        sep = '~' if '~' in clean_str else '-'
        s_part, e_part = clean_str.split(sep)
        def m_to_iso(s):
            y, m, d = map(int, s.split('/'))
            return datetime(y + 1911, m, d)
        start_dt = m_to_iso(s_part)
        release_dt = m_to_iso(e_part) + timedelta(days=1)
        return start_dt.strftime("%Y-%m-%d"), release_dt.strftime("%Y-%m-%d")
    except:
        return None, None

def translate_to_human(row):
    reason = str(row.get('處置原因', ''))
    mode = str(row.get('撮合方式', ''))
    notes = []
    if "沖銷" in reason: notes.append("🚫當沖加關")
    if "20" in mode: notes.append("💀重刑犯(預收)")
    return " / ".join(notes) if notes else "一般冷卻"

# --- 3. Google Sheets 存取邏輯 ---
def load_db_from_gsheets():
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        # 讀取現有資料
        df = conn.read(spreadsheet=SHEET_URL, ttl="0") # ttl="0" 確保讀到最新
        df = df.astype(str)
        # 補齊欄位
        for col in REQUIRED_COLS:
            if col not in df.columns:
                df[col] = "1900-01-01" if col == "處置起日" else ""
        # 過濾過期資料
        logical_today = get_logical_today()
        return df[df["出關時間"] > logical_today]
    except:
        return pd.DataFrame(columns=REQUIRED_COLS)

def save_db_to_gsheets(df):
    if not df.empty:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # 整理欄位與去重
        df = df[REQUIRED_COLS].drop_duplicates(subset=['代號'], keep='last')
        # 寫回 Google Sheets
        conn.update(spreadsheet=SHEET_URL, data=df)

# --- 4. 檔案解析引擎 ---
def process_official_csv(uploaded_file):
    results = []
    logical_today = get_logical_today()
    try:
        raw_bytes = uploaded_file.read()
        try: content = raw_bytes.decode('cp950')
        except: content = raw_bytes.decode('utf-8-sig')
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
            s_dt, r_dt = parse_period(row.get(time_col, ''))
            code = str(row.get('證券代號', '')).split('.')[0].strip()
            if not code or not r_dt: continue
            if r_dt > logical_today:
                results.append({
                    "股票名稱及代號": f"{str(row.get('證券名稱','未知'))} ({code})",
                    "代號": code,
                    "撮合方式": f"20" if "20" in str(row.get('處置內容','')) else "5",
                    "處置起日": s_dt,
                    "出關時間": r_dt,
                    "處置原因": str(row.get(reason_col, ''))
                })
    except Exception as e:
        st.error(f"解析失敗：{e}")
    return results

# --- 5. 主介面 ---
def main():
    st.title("⚖️ 處置中標的監控 (雲端永久存檔版)")
    logical_today = get_logical_today()
    
    # 初始化
    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db_from_gsheets()

    with st.expander("📥 數據更新 (上傳官方 CSV)"):
        uploaded_files = st.file_uploader("上傳 CSV", type="csv", accept_multiple_files=True, label_visibility="collapsed")
        if uploaded_files:
            if st.button("執行匯入並同步至雲端", use_container_width=True):
                all_new_list = []
                for f in uploaded_files:
                    f.seek(0)
                    all_new_list.extend(process_official_csv(f))
                if all_new_list:
                    new_df = pd.DataFrame(all_new_list)
                    # 合併舊資料
                    combined = pd.concat([st.session_state.jail_db, new_df])
                    save_db_to_gsheets(combined)
                    st.session_state.jail_db = load_db_from_gsheets()
                    st.success("☁️ 已成功同步至 Google Sheets！")
                    st.rerun()

    db = st.session_state.jail_db
    if not db.empty:
        db_display = db.copy()
        db_display["🔓 出關日期"] = db_display["出關時間"].apply(get_simple_date)
        db_display["🚨 白話解讀"] = db_display.apply(translate_to_human, axis=1)
        db_sorted = db_display.sort_values(by="出關時間")

        # --- A. 明日進處置 ---
        df_new = db_sorted[db_sorted["處置起日"] > logical_today]
        st.markdown("---")
        col_new_l, col_new_r = st.columns(2)
        with col_new_l:
            st.markdown("### 🆕 明日進處置")
            if not df_new.empty:
                st.dataframe(df_new[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)
            else: st.write("目前無新入選標的")
        
        # --- B. 撮合看板 ---
        st.markdown("---")
        c5, c20 = st.columns(2)
        with c5:
            st.subheader("⏳ 5分鐘撮合")
            df_5 = db_sorted[db_sorted['撮合方式'].astype(str).str.contains('5')]
            st.dataframe(df_5[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)
        with c20:
            st.subheader("🚨 20分鐘撮合")
            df_20 = db_sorted[db_sorted['撮合方式'].astype(str).str.contains('20')]
            st.dataframe(df_20[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)

        # --- C. 完整清單 ---
        st.markdown("---")
        st.subheader("📋 完整監控清單")
        st.dataframe(db_sorted[["股票名稱及代號", "撮合方式", "🔓 出關日期", "處置原因"]], use_container_width=True, hide_index=True)
    else:
        st.info("☁️ 雲端資料庫目前為空。")

    with st.sidebar:
        st.subheader("⚙️ 系統管理")
        st.caption(f"邏輯今天：{logical_today}")
        if st.button("🗑️ 清空雲端資料庫"):
            # 建立空資料表並覆蓋 Google Sheets
            empty_df = pd.DataFrame(columns=REQUIRED_COLS)
            save_db_to_gsheets(empty_df)
            st.session_state.jail_db = empty_df
            st.rerun()

if __name__ == "__main__":
    main()
