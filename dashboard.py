import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
from datetime import datetime, timedelta

# --- 1. 頁面基礎配置 ---
st.set_page_config(page_title="處置監控系統 V9", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心功能：強化版處置資料抓取 ---
def fetch_enhanced_disposal_data():
    """
    強化版爬蟲：掃描紅框內所有資料列，確保不遺漏任何一檔處置股
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 抓取所有資料行
        all_rows = soup.find_all('tr')
        results = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        for row in all_rows:
            # 取得該行所有單元格文字
            cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
            
            # 根據來源圖示，有效的處置資料行通常包含 6 個欄位以上 
            if len(cells) >= 6:
                # 判定是否為標題列 (跳過含有 '公告日期' 的行)
                if "公告日期" in cells[0]:
                    continue
                
                # a. 股票名稱及代號 (欄位 1) 
                name_code_raw = cells[1]
                # 使用正則提取括號內的數字代號
                code_match = re.search(r'\((\d{4,6})\)', name_code_raw)
                if not code_match: continue # 若無代號則視為無效行
                
                code = code_match.group(1)
                name = name_code_raw.split('(')[0].strip()
                
                # b. 撮合方式 (欄位 2) 
                # 提取 5 或 20
                match_mode = "".join(filter(str.isdigit, cells[2]))
                
                # c. 出關時間解析 (欄位 5：處置內容) [cite: 6, 15]
                content = cells[5]
                # 抓取所有日期格式 YYYY-MM-DD
                dates = re.findall(r'(\d{4}-\d{2}-\d{2})', content)
                
                # 若處置內容無 ISO 格式，嘗試抓取民國格式
                if not dates:
                    tw_match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', content)
                    if tw_match:
                        y = int(tw_match.group(1)) + 1911
                        m = int(tw_match.group(2))
                        d = int(tw_match.group(3))
                        dates = [None, f"{y}-{m:02d}-{d:02d}"]

                if len(dates) >= 2:
                    # 結束日為區間的最後一個日期 [cite: 12, 14]
                    end_date_str = dates[-1]
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
                    # 規則：處置結束時間的隔天才算出關
                    release_date = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
                    
                    # 3. 剔除規則：若已過出關日則不存入
                    if release_date > today_str:
                        results.append({
                            "股票名稱及代號": f"{name} ({code})",
                            "代號": code,
                            "撮合方式": f"{match_mode} 分鐘",
                            "出關時間": release_date
                        })
        
        return pd.DataFrame(results).drop_duplicates(subset=['代號'])
    except Exception as e:
        st.error(f"數據抓取失敗: {e}")
        return pd.DataFrame()

# --- 3. 資料庫管理與同步 ---
def sync_data():
    """
    執行同步：讀取網頁最新狀態並覆蓋本地資料庫
    """
    new_df = fetch_enhanced_disposal_data()
    if not new_df.empty:
        # 以出關日期排序
        new_df = new_df.sort_values(by="出關時間")
        new_df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
        return new_df
    return pd.DataFrame()

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置中標的監控")
    st.caption(f"即時同步國票證券公告資料 | 今日：{datetime.now().strftime('%Y-%m-%d')}")

    # 同步按鈕
    if st.button("🔄 同步國票清單 (全面掃描)", type="primary"):
        with st.spinner("正在進行全網頁深度掃描..."):
            df = sync_data()
            if not df.empty:
                st.success(f"同步完成！共成功抓取 {len(df)} 檔處置標的。")
            else:
                st.warning("目前網頁似乎無新的處置資料。")
            st.rerun()

    # 顯示區
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        if not df.empty:
            # 統計資訊
            c1, c2, c3 = st.columns(3)
            c1.metric("總處置檔數", f"{len(df)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(df[df['撮合方式'].str.contains('20')])} 檔")
            c3.metric("5分鐘 (Level 1)", f"{len(df[df['撮合方式'].str.contains('5')])} 檔")

            st.markdown("---")
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
            st.info("清單目前為空，請點擊同步按鈕。")
    else:
        st.info("尚未建立資料庫，請點擊上方按鈕執行第一次同步。")

    st.divider()
    with st.expander("🛠️ 強化版技術說明"):
        st.write("1. **全行掃描**：跳過巢狀表格限制，直接掃描頁面所有 TR 標籤，確保紅框內每一行都被讀取 。")
        st.write("2. **多重日期解析**：支援 ISO (2025-12-24) 與 民國 (114年) 雙格式解析 [cite: 6, 8]。")
        st.write("3. **出關日邏輯**：嚴格執行結束日期 + 1 天。")
        st.write("4. **自動維護**：新進榜自動加入，已過出關時間標的於同步時自動剔除。")

if __name__ == "__main__":
    main()
