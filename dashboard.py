import streamlit as st
import pandas as pd
import requests
import os
from datetime import datetime, timedelta

# --- 1. 頁面基礎設定 ---
st.set_page_config(page_title="處置監控中心 V12", layout="wide", page_icon="⚖️")
JAIL_FILE = "jail_list.csv"

# --- 2. 核心：官方 API 抓取邏輯 ---
def fetch_official_data():
    """
    從證交所(TWSE)與櫃買中心(TPEx) API 直接抓取處置資料
    """
    today_tw = (datetime.now() - timedelta(days=0)).strftime("%Y%m%d")
    results = []

    # A. 證交所 (上市股票)
    # 網址: https://www.twse.com.tw/zh/announcement/punish.html
    try:
        twse_url = f"https://www.twse.com.tw/rwd/zh/announcement/punish?response=json&_={today_tw}"
        res = requests.get(twse_url, timeout=10)
        data = res.json()
        if "data" in data:
            for row in data["data"]:
                # row[1]: 代號, row[2]: 名稱, row[3]: 處置期間, row[4]: 處置措施
                code = str(row[1]).strip()
                name = str(row[2]).strip()
                period = str(row[3])
                measure = str(row[4])
                
                # 解析出關日期 (抓取期間末端日期並 +1)
                release_date = parse_official_date(period)
                # 判定撮合方式
                mode = "20" if "20" in measure else "5"
                
                results.append({
                    "股票名稱及代號": f"{name} ({code})",
                    "代號": code,
                    "撮合方式": f"{mode} 分鐘",
                    "出關時間": release_date
                })
    except Exception as e:
        st.error(f"上市資料抓取失敗: {e}")

    # B. 櫃買中心 (上櫃股票)
    # 網址: https://www.tpex.org.tw/zh-tw/announce/market/disposal.html
    try:
        # 櫃買 API 需要指定日期
        tpex_url = f"https://www.tpex.org.tw/web/stock/announcement/disposal/disposal_result.php?l=zh-tw&_={today_tw}"
        res = requests.get(tpex_url, timeout=10)
        data = res.json()
        if "aaData" in data:
            for row in data["aaData"]:
                # row[1]: 代號, row[2]: 名稱, row[8]: 處置內容
                code = str(row[1]).strip()
                name = str(row[2]).strip()
                content = str(row[8])
                
                # 撮合方式
                mode = "20" if "20" in content else "5"
                # 解析出關日期
                release_date = parse_official_date(content)
                
                results.append({
                    "股票名稱及代號": f"{name} ({code})",
                    "代號": code,
                    "撮合方式": f"{mode} 分鐘",
                    "出關時間": release_date
                })
    except Exception as e:
        st.error(f"上櫃資料抓取失敗: {e}")

    return pd.DataFrame(results)

def parse_official_date(text):
    """
    解析官方格式日期並執行 +1 天邏輯
    範例: 114/12/24 - 115/01/08
    """
    import re
    # 搜尋所有 民國格式日期
    matches = re.findall(r'(\d{3})/(\d{2})/(\d{2})', text)
    if matches:
        # 取最後一個日期作為結束日
        y, m, d = map(int, matches[-1])
        end_date = datetime(y + 1911, m, d)
        # 規則：結束日之次日才算出關
        return (end_date + timedelta(days=1)).strftime("%Y-%m-%d")
    return "解析失敗"

# --- 3. 資料庫管理 ---
def sync_jail_list():
    today_str = datetime.now().strftime("%Y-%m-%d")
    new_df = fetch_official_data()
    
    if not new_df.empty:
        # 1. 剔除規則：自動移除已過出關日的標的
        new_df = new_df[new_df["出關時間"] > today_str]
        
        # 2. 合併與去重
        new_df = new_df.drop_duplicates(subset=['代號']).sort_values(by="出關時間")
        new_df.to_csv(JAIL_FILE, index=False, encoding='utf-8-sig')
        return new_df
    return pd.DataFrame()

# --- 4. 介面呈現 ---
def main():
    st.title("⚖️ 處置中")
    st.caption(f"數據來源：TWSE/TPEx 官方 API 直連 | 今日日期：{datetime.now().strftime('%Y-%m-%d')}")

    if st.button("🔄 同步官方即時清單", type="primary"):
        with st.spinner("正在對接證交所與櫃買中心 API..."):
            sync_jail_list()
            st.rerun()

    if os.path.exists(JAIL_FILE):
        df = pd.read_csv(JAIL_FILE)
        if not df.empty:
            c1, c2 = st.columns(2)
            c1.metric("上市櫃處置總數", f"{len(df)} 檔")
            c2.metric("20分鐘 (Level 2)", f"{len(df[df['撮合方式'].str.contains('20')])} 檔")

            st.markdown("---")
            st.dataframe(
                df[["股票名稱及代號", "撮合方式", "出關時間"]],
                use_container_width=True,
                hide_index=True,
                column_config={"出關時間": "🔓 出關時間 (結束日+1)"}
            )
        else:
            st.info("目前官方查無有效處置標的。")
    else:
        st.info("請點擊同步按鈕獲取官方數據。")

    st.divider()
    with st.expander("🛠️ 數據架構說明"):
        st.write("1. **官方直連**：跳過券商網頁，直接讀取證交所與櫃買中心後端 JSON 數據 [cite: 3, 22]。")
        st.write("2. **出關邏輯**：嚴格抓取處置末日並執行 +1 天運算。")
        st.write("3. **自動清洗**：同步時會自動比對系統時間，移除過期標的。")

if __name__ == "__main__":
    main()
