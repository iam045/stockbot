import streamlit as st
import pandas as pd
import os
import re
import io
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"
# 標準欄位定義
REQUIRED_COLS = ["股票名稱及代號", "代號", "撮合方式", "出關時間", "處置原因"]

# --- 2. 工具函式 ---
def get_weekday_cn(date_str):
    """將日期字串轉為帶有星期幾的格式 (週X)"""
    try:
        dt = datetime.strptime(str(date_str), "%Y-%m-%d")
        weekdays = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
        return f"{date_str} ({weekdays[dt.weekday()]})"
    except:
        return str(date_str)

def convert_minguo_to_date(date_str):
    """將民國格式轉為西元 datetime 並加 1 天"""
    try:
        clean_str = str(date_str).strip().replace(" ", "")
        y, m, d = map(int, clean_str.split('/'))
        # 規則：處置結束時間的隔天才算出關
        return datetime(y + 1911, m, d) + timedelta(days=1)
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
    """解析上市(TWSE)或上櫃(TPEx)的 CSV 內容，支援 Big5"""
    results = []
    today = datetime.now()
    try:
        raw_bytes = uploaded_file.read()
        try:
            content = raw_bytes.decode('cp950') # 台灣官方 CSV 常用編碼
        except UnicodeDecodeError:
            content = raw_bytes.decode('utf-8-sig')
            
        lines = content.splitlines()
        if not lines: return []

        # 判定來源
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
            # 強制補齊欄位
            for col in REQUIRED_COLS:
                if col not in df.columns:
                    df[col] = ""
            # 自動過期剔除
            today_str = datetime.now().strftime("%Y-%m-%d")
            return df[df["出關時間"] > today_str]
        except:
            return pd.DataFrame(columns=REQUIRED_COLS)
    return pd.DataFrame(columns=REQUIRED_COLS)

def save_db(df):
    if not df.empty:
        # 存檔前過濾欄位
        df = df[REQUIRED_COLS]
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 主程式介面 ---
def main():
    st.title("⚖️ 處置中標的監控")
    
    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    # --- A. 簡化上傳 UI ---
    with st.expander("📥 數據更新 (上傳官方 CSV)"):
        uploaded_files = st.file_uploader("選擇 punish.csv 或 disposal.csv", type="csv", accept_multiple_files=True, label_visibility="collapsed")
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
                    st.success("已更新資料庫")
                    st.rerun()

    db = st.session_state.jail_db
    if not db.empty:
        # 1. 預先處理顯示資料
        db_display = db.copy()
        db_display["出關日期"] = db_display["出關時間"].apply(get_weekday_cn)
        # 處理原因標籤
        def add_tags(row):
            reason = str(row['處置原因'])
            mode = str(row['撮合方式'])
            tags = []
            if "沖銷" in reason: tags.append("⚠️當沖加長")
            if "20" in mode: tags.append("🔴累犯/加重")
            return f"{reason} {' '.join(tags)}".strip()
        
        db_display["備註/原因"] = db_display.apply(add_tags, axis=1)
        db_sorted = db_display.sort_values(by="出關時間")

        # --- B. 左右分欄顯示 (純表格，無卡片) ---
        st.markdown("---")
        col_5, col_20 = st.columns(2)
        
        with col_5:
            st.markdown("### ⏳ 5分鐘處置")
            df_5 = db_sorted[db_sorted['撮合方式'].str.contains('5')]
            if not df_5.empty:
                st.dataframe(df_5[["股票名稱及代號", "出關日期", "備註/原因"]], hide_index=True, use_container_width=True)
            else:
                st.write("目前無 5 分鐘處置標的")

        with col_20:
            st.markdown("### 🚨 20分鐘處置")
            df_20 = db_sorted[db_sorted['撮合方式'].str.contains('20')]
            if not df_20.empty:
                st.dataframe(df_20[["股票名稱及代號", "出關日期", "備註/原因"]], hide_index=True, use_container_width=True)
            else:
                st.write("目前無 20 分鐘處置標的")

        # --- C. 原本的大 Data 表格 ---
        st.markdown("---")
        st.markdown("### 📋 完整處置清單")
        # 確保顯示欄位都存在
        st.dataframe(
            db_sorted[["股票名稱及代號", "撮合方式", "出關日期", "處置原因"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "出關日期": st.column_config.TextColumn("🔓 出關時間 (結束日+1)")
            }
        )
    else:
        st.info("資料庫清單目前為空。")

    with st.sidebar:
        st.subheader("⚙️ 系統管理")
        if st.button("🗑️ 清空資料庫"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=REQUIRED_COLS)
            st.rerun()

if __name__ == "__main__":
    main()
