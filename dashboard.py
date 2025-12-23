import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta

# --- 1. 頁面配置 ---
st.set_page_config(page_title="處置監控系統", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心功能：深度解析國票處置區塊 ---
def fetch_all_disposal_data():
    """
    抓取國票證券紅框區塊內的所有資料
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 尋找目標表格 (紅框範圍)
        table = soup.find('table') 
        if not table:
            return pd.DataFrame()

        rows = table.find_all('tr')
        results = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        for row in rows:
            cols = row.find_all('td')
            # 國票處置表通常每列有 6 個欄位 
            if len(cols) >= 6:
                # a. 股票名稱及代號 (欄位 1)
                raw_name_code = cols[1].get_text(strip=True)
                # 分離名稱與代號，格式通常為：新盛力(4931) 
                code_match = re.search(r'\((\d{4,6})\)', raw_name_code)
                code = code_match.group(1) if code_match else ""
                name = raw_name_code.split('(')[0].strip()
                
                # b. 撮合方式 (欄位 2) 
                # 抓取 5 或 20
                match_mode = "".join(filter(str.isdigit, cols[2].get_text(strip=True)))
                
                # c. 解析日期與計算出關時間 (欄位 5：處置內容) 
                content_text = cols[5].get_text(strip=True)
                # 尋找格式如：2025-12-24 ~ 2026-01-08 
                dates = re.findall(r'(\d{4}-\d{2}-\d{2})', content_text)
                
                if len(dates) >= 2:
                    # 結束日期為第二個日期 
                    end_date_str = dates[1]
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
                    # 規則：處置結束時間的隔天才算出關
                    release_date = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
                    
                    # 3. 剔除功能：如果出關時間已到，則不顯示
                    if release_date > today_str:
                        results.append({
                            "股票名稱及代號": f"{name} ({code})",
                            "代號": code,
                            "撮合方式": f"{match_mode} 分鐘",
                            "出關時間": release_date
                        })
        
        return pd.DataFrame(results)
    except Exception as e:
        st.error(f"解析網頁失敗: {e}")
        return pd.DataFrame()

# --- 3. 資料庫管理 (每日自動同步) ---
def sync_jail_db():
    """
    每日同步：讀取網頁最新資料，並更新本地 CSV 
    """
    web_df = fetch_all_disposal_data()
    if not web_df.empty:
        # 直接以網頁最新的清單為準 (實現新進榜自動增加，過期自動剔除)
        # 排序：離出關日最近的排前面
        web_df = web_df.sort_values(by="出關時間")
        web_df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
        return web_df
    return pd.DataFrame()

# --- 4. 主程式介面 ---
def main():
    st.title("⚖️ 處置中")
    st.caption(f"數據同步來源：國票證券處置公告區 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    # 控制按鈕
    if st.button("🔄 同步國票清單", type="primary"):
        with st.spinner("正在解析紅框區域內所有處置標的..."):
            df = sync_jail_db()
            if not df.empty:
                st.success(f"同步成功！共抓取到 {len(df)} 筆處置中標的。")
            st.rerun()

    # 讀取並顯示
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        
        if not df.empty:
            # 顯示統計指標
            c1, c2, c3 = st.columns(3)
            c1.metric("總處置檔數", f"{len(df)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(df[df['撮合方式'].str.contains('20')])} 檔")
            c3.metric("5分鐘 (Level 1)", f"{len(df[df['撮合方式'].str.contains('5')])} 檔")

            st.markdown("---")
            # 呈現表格
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
            st.info("目前無處置標的資料。")
    else:
        st.info("請點擊同步按鈕開始追蹤。")

    st.divider()
    with st.expander("📝 處置數據解析規則"):
        st.write("1. **範圍**：完整掃描國票證券處置頁面之紅框區塊 。")
        st.write("2. **撮合**：自動區分 5 分鐘(第一次處置)與 20 分鐘(第二次/加重處置)。")
        st.write("3. **出關**：解析公告內容之結束日期，並自動 +1 天作為出關時間。")
        st.write("4. **維護**：點擊同步後，系統會自動比對最新公告，新進榜會增加，過期標的會自動剔除。")

if __name__ == "__main__":
    main()
