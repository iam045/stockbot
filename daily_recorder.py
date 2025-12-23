import requests
import pandas as pd
import os
import urllib3
import re
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_FILE = "history_db.csv"
JAIL_FILE = "jail_list.csv"

def parse_disposal_date(content):
    try:
        match = re.search(r'至(\d{3})年(\d{1,2})月(\d{1,2})日', str(content))
        if match:
            year = int(match.group(1)) + 1911
            return datetime(year, int(match.group(2)), int(match.group(3)))
    except: pass
    return None

def update_data():
    today_str = datetime.now().strftime("%Y-%m-%d")
    headers = {'User-Agent': 'Mozilla/5.0'}
    all_data = []
    new_jail_codes = []

    # --- 1. 抓取注意與處置股 ---
    try:
        # 注意股
        r = requests.get("https://www.ibfs.com.tw/stock3/default13-1.aspx?xy=8&xt=1", headers=headers, verify=False)
        dfs = pd.read_html(r.text)
        for df in dfs:
            if '注意交易資訊' in str(df.columns):
                for _, row in df.iterrows():
                    code = ''.join(filter(str.isdigit, str(row.iloc[1])))
                    all_data.append({"日期": today_str, "代號": code, "狀態": "注意股"})
        
        # 處置股
        r = requests.get("https://www.ibfs.com.tw/stock3/measuringstock.aspx?xy=6&xt=1", headers=headers, verify=False)
        dfs = pd.read_html(r.text)
        for df in dfs:
            if '處置內容' in str(df.columns):
                for _, row in df.iterrows():
                    code = ''.join(filter(str.isdigit, str(row.iloc[1])))
                    content = row.iloc[5]
                    all_data.append({"日期": today_str, "代號": code, "狀態": "處置股"})
                    # 自動識別是否需要加入監控清單
                    end_dt = parse_disposal_date(content)
                    if end_dt and end_dt >= datetime.now():
                        new_jail_codes.append(code)
    except Exception as e:
        print(f"抓取失敗: {e}")

    # --- 2. 更新 history_db.csv ---
    if all_data:
        new_df = pd.DataFrame(all_data)
        if os.path.exists(DB_FILE):
            old_df = pd.read_csv(DB_FILE, dtype=str)
            final_df = pd.concat([old_df[old_df["日期"] != today_str], new_df], ignore_index=True)
        else:
            final_df = new_df
        final_df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')

    # --- 3. 自動更新 jail_list.csv (新增與移除) ---
    if os.path.exists(JAIL_FILE):
        jail_df = pd.read_csv(JAIL_FILE, dtype=str)
        existing_jail = jail_df['code'].tolist()
    else:
        existing_jail = []
    
    # 合併並去重
    updated_jail = list(set(existing_jail + new_jail_codes))
    pd.DataFrame({'code': updated_jail}).to_csv(JAIL_FILE, index=False)
    print("✅ 資料自動更新完成")

if __name__ == "__main__":
    update_data()
