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

# --- 2. 工具函式：日期與白話解讀 ---
def get_weekday_cn(date_str):
    """將日期字串轉為極簡格式：12/24(三)"""
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        # 格式化為 MM/DD(週)
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
    """從處置內容提取撮合分鐘"""
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
    """解析官方 CSV，支援 Big5"""
    results = []
    today = datetime.now()
    try:
        raw_bytes = uploaded_file.read()
        try:
            content = raw_bytes.decode('cp950') 
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
                end_date_str = period.split('~')[1]
                release_obj = convert_minguo_to_date(end_date_str)
                if release_obj and release_obj > today:
                    results.append({
                        "股票名稱及代號": f"{name} ({code})",
                        "代號": code,
                        "撮合方式": f"{extract_match_mode(measure_content)} 分鐘",
                        "出關時間": release_obj.strftime("%Y-%m-%d"),
                        "處置原因": reason
                    })
            except: continue
    except Exception as e:
        st.error(f"解析 {uploaded_file.name} 失敗：{e}")
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
        except: return pd.DataFrame(columns=REQUIRED_COLS)
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

    with st.expander("📥 數據更新 (上傳官方 CSV)"):
        uploaded_files = st.file_uploader("上傳 CSV", type="csv", accept_multiple_files=True, label_visibility="collapsed")
        if uploaded_files:
            if st.button("執行匯入", use_container_width=True):
                all_new_data = []
                for f in uploaded_files:
                    f.seek(0)
                    all_new_data.extend(process_official_csv(f))
                if all_new_data:
                    combined = pd.concat([st.session_state.jail_db, pd.DataFrame(all_new_data)])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success("更新完成")
                    st.rerun()

    db = st.session_state.jail_db
    if not db.empty:
        # 數據預處理
        db_display = db.copy()
        # 轉換格式為 12/24(三)
        db_display["🔓 出關日期"] = db_display["出關時間"].apply(get_weekday_cn)
        db_display["🚨 白話解讀"] = db_display.apply(translate_to_human, axis=1)
        # 排序仍依照原始 YYYY-MM-DD 確保跨年正確
        db_sorted = db_display.sort_values(by="出關時間")

        # --- 分欄顯示 ---
        st.markdown("---")
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("⏳ 5分鐘撮合")
            df_5 = db_sorted[db_sorted['撮合方式'].str.contains('5')]
            st.dataframe(df_5[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)

        with col_right:
            st.subheader("🚨 20分鐘撮合")
            df_20 = db_sorted[db_sorted['撮合方式'].str.contains('20')]
            st.dataframe(df_20[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)

        # --- 完整 Data 展示 ---
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
            st.rerun()

if __name__ == "__main__":
    main()
