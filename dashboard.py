import streamlit as st
import pandas as pd
import os
import re
import io
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控中心", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"
# 標準化欄位定義
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
    """將民國格式轉為西元 datetime 並加 1 天 (出關日) """
    try:
        clean_str = str(date_str).strip().replace(" ", "")
        y, m, d = map(int, clean_str.split('/'))
        # 規則：處置結束時間的隔天才算出關
        return datetime(y + 1911, m, d) + timedelta(days=1)
    except:
        return None

def extract_match_mode(content):
    """從處置內容提取撮合分鐘 (5 或 20) [cite: 9, 10]"""
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
        # 處理 Big5 (CP950) 編碼
        raw_bytes = uploaded_file.read()
        try:
            content = raw_bytes.decode('cp950')
        except UnicodeDecodeError:
            content = raw_bytes.decode('utf-8-sig')
            
        lines = content.splitlines()
        if not lines: return []

        # 判定來源與標頭位置
        if "公布處置有價證券資訊" in lines[0]:
            # 上市 (punish.csv)
            df = pd.read_csv(io.StringIO("\n".join(lines[1:])))
            time_col, reason_col = '處置起迄時間', '處置條件'
        elif "上櫃處置股票資訊" in lines[0] or "期間:" in lines[0]:
            # 上櫃 (disposal...csv)
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

                # 提取結束日期並計算出關日 (結束日+1) 
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
        st.error(f"解析檔案失敗：{e}")
    return results

# --- 4. 資料庫維護與自動修復 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        try:
            df = pd.read_csv(JAIL_FILE, encoding='utf-8-sig').astype(str)
            # 自動補齊缺失欄位，防止 KeyError [cite: 20]
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
        # 確保依序儲存標準欄位
        df = df[REQUIRED_COLS]
        df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 5. 主程式介面 ---
def main():
    st.title("⚖️ 處置中標的監控")
    
    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    # --- A. 數據更新區塊 ---
    with st.expander("📥 數據更新 (上傳官方 CSV)"):
        uploaded_files = st.file_uploader("請上傳 punish.csv 或 disposal.csv", type="csv", accept_multiple_files=True, label_visibility="collapsed")
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
                    st.success("資料庫更新成功")
                    st.rerun()

    db = st.session_state.jail_db
    if not db.empty:
        # 資料預處理
        db_display = db.copy()
        # 確保顯示日期存在
        db_display["顯示日期"] = db_display["出關時間"].apply(get_weekday_cn)
        db_sorted = db_display.sort_values(by="出關時間")

        # --- B. 頂部數據概覽 ---
        c1, c2, c3 = st.columns(3)
        c1.metric("總處置檔數", f"{len(db_sorted)} 檔")
        c2.metric("5分鐘撮合", f"{len(db_sorted[db_sorted['撮合方式'].str.contains('5')])} 檔")
        c3.metric("20分鐘撮合", f"{len(db_sorted[db_sorted['撮合方式'].str.contains('20')])} 檔")

        # --- C. 完整資料清單 (移除卡片，直接呈現表格) ---
        st.markdown("---")
        # 安全選取欄位，避免 KeyError
        cols_to_show = ["股票名稱及代號", "撮合方式", "顯示日期", "處置原因"]
        # 確保所有顯示欄位都在 DataFrame 中
        final_cols = [c for c in cols_to_show if c in db_sorted.columns]
        
        st.dataframe(
            db_sorted[final_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "股票名稱及代號": st.column_config.TextColumn("證券標的"),
                "顯示日期": st.column_config.TextColumn("🔓 出關時間 (結束日+1)"),
                "處置原因": st.column_config.TextColumn("處置理由")
            }
        )
    else:
        st.info("目前資料庫為空。")

    with st.sidebar:
        st.subheader("⚙️ 系統管理")
        if st.button("🗑️ 清空資料庫"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=REQUIRED_COLS)
            st.rerun()

if __name__ == "__main__":
    main()
