import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta

# --- 1. 頁面配置 ---
st.set_page_config(page_title="處置監控 (多選上傳版)", layout="wide", page_icon="⚖️")

# --- 2. 工具函式 ---
def get_logical_today():
    """凌晨 6 點前視為前一交易日，適配半夜作業直覺"""
    now = datetime.now()
    if now.hour < 6:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def get_simple_date(date_str):
    """格式化為 12/24(三)"""
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        weekdays = ["一", "二", "三", "四", "五", "六", "日"]
        return f"{dt.month}/{dt.day}({weekdays[dt.weekday()]})"
    except:
        return str(date_str)

def parse_period(period_str):
    """將官方期間格式轉為西元日期 (起日, 出關日)"""
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
    """白話解讀標籤"""
    reason = str(row.get('處置原因', ''))
    mode = str(row.get('撮合方式', ''))
    notes = []
    if "沖銷" in reason: notes.append("🚫當沖加關")
    if "20" in mode: notes.append("💀重刑犯(預收)")
    return " / ".join(notes) if notes else "一般冷卻"

# --- 3. 檔案解析引擎 ---
def process_official_csv(uploaded_file):
    """解析上市與上櫃 CSV，處理編碼與標頭"""
    results = []
    logical_today = get_logical_today()
    try:
        raw_bytes = uploaded_file.read()
        try: content = raw_bytes.decode('cp950') # 台灣官方 CSV 常用編碼
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
            # 僅保留尚未出關的資料
            if r_dt > logical_today:
                results.append({
                    "股票名稱及代號": f"{str(row.get('證券名稱','未知'))} ({code})",
                    "代號": code,
                    "撮合方式": "20" if "20" in str(row.get('處置內容','')) else "5",
                    "處置起日": s_dt,
                    "出關時間": r_dt,
                    "處置原因": str(row.get(reason_col, ''))
                })
    except: pass
    return results

# --- 4. 主介面 ---
def main():
    st.title("⚖️ 處置中標的監控")
    logical_today = get_logical_today()
    
    # 儲存在 Session State，避免重新整理網頁時消失
    if 'current_db' not in st.session_state:
        st.session_state.current_db = pd.DataFrame()

    with st.expander("📥 數據更新 (請全選您的備份 CSV 檔案)", expanded=True):
        uploaded_files = st.file_uploader("多選上傳", type="csv", accept_multiple_files=True, label_visibility="collapsed")
        if uploaded_files:
            if st.button("🚀 執行多檔合併解析", use_container_width=True):
                all_data_list = []
                for f in uploaded_files:
                    f.seek(0)
                    all_data_list.extend(process_official_csv(f))
                
                if all_data_list:
                    full_df = pd.DataFrame(all_data_list)
                    # 自動去重：以「代號」為主，保留最後一筆
                    st.session_state.current_db = full_df.drop_duplicates(subset=['代號'], keep='last')
                    st.success(f"合併完成！共整理出 {len(st.session_state.current_db)} 檔處置標的。")
                    st.rerun()

    db = st.session_state.current_db
    if not db.empty:
        # 顯示資料預處理
        db_disp = db.copy()
        db_disp["🔓 出關日期"] = db_disp["出關時間"].apply(get_simple_date)
        db_disp["🚨 白話解讀"] = db_disp.apply(translate_to_human, axis=1)
        db_sorted = db_disp.sort_values(by="出關時間")

        # --- A. 明日進處置 (起日 > 邏輯今天) ---
        df_new = db_sorted[db_sorted["處置起日"] > logical_today]
        st.markdown("---")
        l, r = st.columns(2)
        with l:
            st.markdown("### 🆕 明日進處置")
            if not df_new.empty:
                st.dataframe(df_new[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)
            else:
                st.write("目前無新入選標的")
        with r: st.write("")

        # --- B. 撮合分欄顯示 (所有標的) ---
        st.markdown("---")
        c5, c20 = st.columns(2)
        with c5:
            st.subheader("⏳ 5分鐘撮合")
            df_5 = db_sorted[db_sorted['撮合方式'].astype(str).str.contains('5')]
            if not df_5.empty:
                st.dataframe(df_5[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)
            else: st.write("無 5 分鐘標的")
        with c20:
            st.subheader("🚨 20分鐘撮合")
            df_20 = db_sorted[db_sorted['撮合方式'].astype(str).str.contains('20')]
            if not df_20.empty:
                st.dataframe(df_20[["股票名稱及代號", "🔓 出關日期", "🚨 白話解讀"]], hide_index=True, use_container_width=True)
            else: st.write("無 20 分鐘標的")

        # --- C. 完整資料庫 ---
        st.markdown("---")
        st.subheader("📋 完整監控總表")
        st.dataframe(db_sorted[["股票名稱及代號", "撮合方式", "🔓 出關日期", "處置原因"]], use_container_width=True, hide_index=True)
    else:
        st.info("請上傳您的處置股 CSV 檔案（支援多選同時匯入）。")

if __name__ == "__main__":
    main()
