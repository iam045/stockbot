import streamlit as st
import pandas as pd
import re
import os
from datetime import datetime, timedelta

# --- 1. 頁面配置 ---
st.set_page_config(page_title="台股處置監控系統", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心邏輯：解析與計算 ---
def parse_and_process(text):
    """
    智慧解析：從文字塊中提取資料並執行 結束日+1 邏輯 [cite: 28, 30]
    """
    results = []
    lines = text.split('\n')
    today_str = datetime.now().strftime("%Y-%m-%d")

    for line in lines:
        # a. 提取股票名稱及代號
        code_match = re.search(r'(\d{4,6})', line)
        if not code_match: continue
        
        code = code_match.group(1)
        name_match = re.search(r'([\u4e00-\u9fa5\w]+)', line.replace(code, ""))
        name = name_match.group(1).strip() if name_match else "未知"

        # b. 撮合方式 (5 或 20) [cite: 29]
        mode = "20" if "20" in line else "5"

        # c. 出關時間 (結束日 + 1) 
        # 搜尋日期格式 114/12/24 或 2025/12/24
        date_matches = re.findall(r'(\d{3,4})[/-](\d{1,2})[/-](\d{1,2})', line)
        if date_matches:
            y, m, d = map(int, date_matches[-1]) # 取最後一個日期為結束日
            if y < 1900: y += 1911 # 民國轉西元
            
            # 規則：處置結束時間的隔天才算出關
            release_date = (datetime(y, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")
            
            # 只有尚未出關的才加入
            if release_date > today_str:
                results.append({
                    "股票名稱及代號": f"{name} ({code})",
                    "代號": code,
                    "撮合方式": f"{mode} 分鐘",
                    "出關時間": release_date
                })
    return results

# --- 3. 資料庫存取 ---
def load_db():
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE).astype(str)
        # 讀取時自動剔除已出關標的
        today_str = datetime.now().strftime("%Y-%m-%d")
        return df[df["出關時間"] > today_str]
    return pd.DataFrame(columns=["股票名稱及代號", "代號", "撮合方式", "出關時間"])

def save_db(df):
    # 去重並儲存
    df.drop_duplicates(subset=['代號'], keep='last').to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置中")
    st.caption(f"手動管理模式 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    if 'jail_db' not in st.session_state:
        st.session_state.jail_db = load_db()

    tab1, tab2 = st.tabs(["📌 處置監控清單", "📥 更新資料 (手動貼上)"])

    with tab1:
        db = st.session_state.jail_db
        if not db.empty:
            # 統計指標
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
            st.info("目前資料庫為空。請至「更新資料」分頁進行同步。")

    with tab2:
        st.subheader("📥 更新數據入口")
        st.markdown("""
        **更新步驟：**
        1. 到 [證交所](https://www.twse.com.tw/zh/announcement/punish.html) 或 [櫃買中心](https://www.tpex.org.tw/zh-tw/announce/market/disposal.html) 複製表格。
        2. 將內容**直接貼在下方框框**。
        3. 系統會自動辨識新進榜股票，並自動計算「出關時間」。
        """)
        
        raw_input = st.text_area("請在此處貼上官網複製的文字...", height=200, placeholder="例如：新盛力 (4931) 20 ... 至115年01月08日")
        
        if st.button("🚀 開始同步與計算", type="primary"):
            if raw_input:
                new_data = parse_and_process(raw_input)
                if new_data:
                    new_df = pd.DataFrame(new_data)
                    combined = pd.concat([st.session_state.jail_db, new_df])
                    save_db(combined)
                    st.session_state.jail_db = load_db()
                    st.success(f"成功更新！已自動加入新標的並剔除過期股票。")
                    st.rerun()
                else:
                    st.error("未能解析有效資料，請確認包含代號與日期。")
            else:
                st.warning("內容不可為空。")

        st.divider()
        if st.button("🗑️ 清空所有歷史資料 (重置)"):
            if os.path.exists(JAIL_FILE): os.remove(JAIL_FILE)
            st.session_state.jail_db = pd.DataFrame(columns=["股票名稱及代號", "代號", "撮合方式", "出關時間"])
            st.rerun()

if __name__ == "__main__":
    main()
