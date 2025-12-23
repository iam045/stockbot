import streamlit as st
import pandas as pd
import requests
import re
import os
from datetime import datetime, timedelta

# --- 1. 系統設定 ---
st.set_page_config(page_title="處置監控系統", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心邏輯：日期解析與出關計算 ---
def parse_release_date(text):
    """
    規則：抓取處置結束日期，並自動 +1 天作為出關日
    支援「至115年01月06日」或「2026-01-06」兩種格式
    """
    # 格式 1: 至114年12月31日
    match_tw = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(text))
    if match_tw:
        y = int(match_tw.group(1)) + 1911
        m = int(match_tw.group(2))
        d = int(match_tw.group(3))
        return (datetime(y, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # 格式 2: 2025-12-24 ~ 2026-01-08 
    match_iso = re.findall(r'(\d{4})-(\d{1,2})-(\d{1,2})', str(text))
    if match_iso and len(match_iso) >= 2:
        y, m, d = map(int, match_iso[1]) # 取第二個日期作為結束日
        return (datetime(y, m, d) + timedelta(days=1)).strftime("%Y-%m-%d")
    
    return None

# --- 3. 核心邏輯：自動化同步 (新增與剔除) ---
def sync_data():
    """
    1. 全表格掃描：抓取國票官網所有表格
    2. 新進榜自動加入，過期自動剔除
    """
    url = "https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, verify=False, timeout=15)
        dfs = pd.read_html(response.text)
        
        new_entries = []
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 遍歷所有表格，尋找包含「撮合」或「處置內容」的資料列
        for df in dfs:
            for _, row in df.iterrows():
                row_str = " ".join(row.astype(str))
                # 跳過欄位定義列
                if "證券名稱" in row_str or "撮合" in row_str:
                    continue
                
                # 偵測是否有代號 (4-5位數字)
                code_match = re.search(r'(\d{4,6})', row_str)
                if code_match:
                    code = code_match.group(1)
                    # 抓取名稱：通常在代號前後
                    name = str(row.iloc[1]).split('(')[0].strip()
                    
                    # 撮合方式 (5 or 20) [cite: 29]
                    mode = "20" if "20" in row_str else "5"
                    
                    # 解析出關時間
                    release_date = parse_release_date(row_str)
                    
                    if release_date:
                        # 規則：處置結束時間的隔天才算出關，今日已出關則剔除
                        if release_date <= today_str:
                            continue
                            
                        new_entries.append({
                            "股票名稱及代號": f"{name} ({code})",
                            "代號": str(code),
                            "撮合方式": f"{mode} 分鐘",
                            "出關時間": release_date
                        })

        if not new_entries:
            st.warning("未能從網頁抓取到有效資料，請確認國票網站是否正常。")
            return

        # 處理本地資料庫
        if os.path.exists(JAIL_FILE):
            existing_df = pd.read_csv(JAIL_FILE)
        else:
            existing_df = pd.DataFrame()

        new_df = pd.DataFrame(new_entries)
        # 合併、去重並自動剔除過期標的
        final_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['代號'], keep='last')
        final_df = final_df[final_df["出關時間"] > today_str]
        
        # 排序：最近要出關的在最前面
        final_df = final_df.sort_values(by="出關時間")
        final_df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
        st.success(f"同步完成！目前監控中共有 {len(final_df)} 檔處置標的。")
            
    except Exception as e:
        st.error(f"同步失敗：{e}")

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置中")
    st.caption(f"數據來源：國票證券官方處置公告 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    # 控制按鈕
    if st.button("🔄 同步國票清單", type="primary"):
        with st.spinner("正在掃描全網頁表格並計算出關日..."):
            sync_data()
            st.rerun()

    # 讀取並顯示
    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        
        if not df.empty:
            # 統計指標 [cite: 29]
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
            st.info("目前清單中無處置標的。")
    else:
        st.info("請點擊同步按鈕開始監控。")

    st.divider()
    with st.expander("🛠️ 規則說明"):
        st.write("1. **股票名稱及代號**：從公告中提取標的名稱與代碼。")
        st.write("2. **撮合方式**：區分 5 分鐘與 20 分鐘撮合 [cite: 29, 30]。")
        st.write("3. **出關時間**：依據需求設定為「處置結束日之隔日」。")
        st.write("4. **自動化**：同步時會自動將到期股票從 CSV 剔除，並加入新公告的標的。")

if __name__ == "__main__":
    main()
