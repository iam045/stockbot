import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta

# --- 1. 系統與檔案設定 ---
st.set_page_config(page_title="處置監控中心", layout="wide", page_icon="⚖️")
# 使用 CSV 作為你的「本地 Excel」，你也可以直接在 GitHub 或本地用 Excel 打開它
JAIL_FILE = "jail_list.csv"

# --- 2. 核心邏輯：日期解析與出關計算 ---
def parse_release_date(content):
    """
    規則：抓取處置結束日期，並自動 +1 天作為出關日 
    """
    try:
        # 搜尋格式：至114年12月31日
        match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(content))
        if match:
            year = int(match.group(1)) + 1911
            month = int(match.group(2))
            day = int(match.group(3))
            end_date = datetime(year, month, day)
            # 處置結束時間的隔天才算出關 [cite: 29]
            release_date = end_date + timedelta(days=1)
            return release_date.strftime("%Y-%m-%d")
    except:
        pass
    return None

# --- 3. 核心邏輯：自動化同步 (新增與剔除) ---
def sync_data():
    """
    同步規則：
    1. 抓取國票官網最新清單
    2. 新進榜的標的自動加入
    3. 出關時間已到的標的自動剔除
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=10)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 尋找包含數據的表格 [cite: 6]
        table = None
        for t in soup.find_all('table'):
            if "處置內容" in t.text:
                table = t
                break
        
        if not table:
            st.error("未能定位到處置表格，請檢查網頁內容。")
            return

        # 讀取現有的資料庫
        if os.path.exists(JAIL_FILE):
            existing_df = pd.read_csv(JAIL_FILE)
        else:
            existing_df = pd.DataFrame(columns=["股票名稱及代號", "代號", "撮合方式", "出關時間"])

        new_entries = []
        today_str = datetime.now().strftime("%Y-%m-%d")
        rows = table.find_all('tr')

        for row in rows[1:]: # 跳過標題
            cols = [c.text.strip() for c in row.find_all(['td', 'th'])]
            if len(cols) < 5: continue
            
            # a. 股票名稱及代號 [cite: 6]
            name = cols[1]
            code = cols[2].split('.')[0]
            display_name = f"{name} ({code})"
            
            # b. 撮合方式 (5 or 20) [cite: 6, 29]
            mode_text = cols[3]
            match_mode = "20" if "20" in mode_text else "5"
            
            # c. 出關時間 (結束日+1) 
            release_date = parse_release_date(cols[5])
            
            if release_date:
                # 規則：如果今日已達出關時間，則不計入 [cite: 29]
                if release_date <= today_str:
                    continue
                
                new_entries.append({
                    "股票名稱及代號": display_name,
                    "代號": str(code),
                    "撮合方式": f"{match_mode} 分鐘",
                    "出關時間": release_date
                })

        # 合併新舊資料，並以「代號」為準去重
        new_df = pd.DataFrame(new_entries)
        if not new_df.empty:
            # 合併並保留最新資訊
            final_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['代號'], keep='last')
            # 再次執行剔除：移除掉所有已過期的標的
            final_df = final_df[final_df["出關時間"] > today_str]
            # 排序
            final_df = final_df.sort_values(by="出關時間")
            final_df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
            st.success("同步完成！已自動加入新標的並剔除已出關股票。")
        else:
            st.warning("國票官網目前似乎無有效的處置資料。")
            
    except Exception as e:
        st.error(f"同步過程中發生錯誤: {e}")

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置中標的監控中心")
    st.caption(f"依據證交所監視制度與國票官方資料 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    # 控制按鈕
    if st.button("🔄 同步國票最新清單 (自動更新/剔除)", type="primary"):
        sync_data()

    # 讀取並顯示
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        
        if not df.empty:
            # 統計資訊
            c1, c2 = st.columns(2)
            c1.metric("處置總數", f"{len(df)} 檔")
            c2.metric("20分鐘撮合 (Level 2)", f"{len(df[df['撮合方式'].str.contains('20')])} 檔")

            st.markdown("### 📌 目前處置中清單")
            st.dataframe(
                df[["股票名稱及代號", "撮合方式", "出關時間"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "出關時間": st.column_config.TextColumn("🔓 出關時間 (結束日+1)"),
                    "撮合方式": st.column_config.TextColumn("⏳ 撮合頻率")
                }
            )
        else:
            st.info("目前資料庫中無處置標的。")
    else:
        st.info("尚未建立資料庫，請點擊上方按鈕進行第一次同步。")

    st.divider()
    with st.expander("📝 處置規則說明 (依據官方解析)"):
        st.markdown(f"""
        1. **撮合方式**：
           - **Level 1 (5分鐘)**：首次滿足連續或累積條款 [cite: 29]。
           - **Level 2 (20分鐘)**：30日內第二次處置，需全額預收 [cite: 29]。
        2. **出關定義**：
           - 處置期間通常為 10 個營業日 [cite: 30]。
           - 根據需求，出關日設定為**公告結束日之次日**。
        3. **自動化邏輯**：
           - **新增**：同步時發現國票有新代號，自動存入 CSV。
           - **剔除**：若系統日期已達「出關時間」，同步時會自動將其從 CSV 中刪除。
        """)

if __name__ == "__main__":
    main()
