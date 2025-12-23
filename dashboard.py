import streamlit as st
import pandas as pd
import time

# ==========================================
# 1. 頁面基本配置
# ==========================================
st.set_page_config(
    page_title="風險預警中心",
    page_icon="🔥",
    layout="wide"
)

# ==========================================
# 2. 核心功能：檢查股票狀態 (修正 TypeError)
# ==========================================
def check_official_status(stock_code):
    """
    檢查股票官方狀態，並具備強大的錯誤處理機制。
    """
    try:
        # 處理空值 (NaN) 或 None
        if pd.isna(stock_code) or stock_code is None:
            return "資料缺失", "CSV 中此欄位為空"

        # 強制轉為字串並去除小數點 (防止 2330.0 這種格式)
        stock_code_str = str(stock_code).split('.')[0].strip()

        # 核心修正：確保傳入 filter 的是字串，並提取數字部分
        target_code = ''.join(filter(str.isdigit, stock_code_str))

        # 如果提取後是空的字串
        if not target_code:
            return "格式錯誤", f"無法辨識的代碼: {stock_code}"

        # --- 這裡放置你原本的檢查邏輯 (範例模擬) ---
        # 假設邏輯：串接 API 或爬蟲檢查
        # 這裡可以根據你的需求擴充
        return "正常", f"代碼 {target_code} 運作中"

    except Exception as e:
        # 萬一發生其他不可預期的錯誤，回傳錯誤訊息而不崩潰
        return "系統錯誤", f"發生異常: {str(e)}"

# ==========================================
# 3. 主程式介面
# ==========================================
def main():
    # 標題與圖示
    st.markdown("# 🔥 風險預警中心")
    
    # 顯示目前連接狀態
    st.info("🕒 **更新狀態**：已連結 GitHub 機器人資料庫 (`history_db.csv`) ")

    try:
        # 讀取 CSV 資料庫
        # 使用 low_memory=False 確保大型資料讀取穩定
        df = pd.read_csv('history_db.csv')

        if df.empty:
            st.warning("目前資料庫中沒有任何股票數據。")
            return

        # 自動偵測股票代號欄位 (相容不同名稱)
        possible_columns = ['股票代號', '股票', '代碼', 'code', 'Stock']
        col_name = next((c for c in possible_columns if c in df.columns), df.columns[0])

        # 轉換為清單
        stock_list = df[col_name].tolist()
        total_stocks = len(stock_list)

        # 建立進度條
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []

        # ==========================================
        # 4. 批次分析迴圈
        # ==========================================
        for i, code in enumerate(stock_list):
            # 更新進度條文字
            current_progress = (i + 1) / total_stocks
            status_text.markdown(f"🔄 **正在分析資料庫中 {total_stocks} 檔股票...** ({i+1}/{total_stocks})")
            progress_bar.progress(current_progress)

            # 呼叫檢查函式 (帶防錯)
            status, reason = check_official_status(code)
            
            results.append({
                "股票代碼": code,
                "分析結果": status,
                "詳細原因/備註": reason
            })

            # 若資料量很大，可稍微停頓避免 UI 卡死
            # time.sleep(0.01)

        # 清除進度顯示
        status_text.empty()
        progress_bar.empty()

        # ==========================================
        # 5. 顯示最後結果
        # ==========================================
        st.success(f"✅ 分析完成！共處理 {total_stocks} 筆資料。")
        
        # 將結果轉為 DataFrame 顯示
        res_df = pd.DataFrame(results)
        
        # 使用 Streamlit Dataframe 呈現，支援排序與搜尋
        st.dataframe(
            res_df, 
            use_container_width=True,
            column_config={
                "分析結果": st.column_config.TextColumn("分析結果", width="small"),
            }
        )

    except FileNotFoundError:
        st.error("❌ 找不到 `history_db.csv`。請確認檔案是否已上傳至 GitHub 並與 `dashboard.py` 同目錄。")
    except Exception as e:
        st.error(f"❌ 程式執行發生錯誤：{e}")

if __name__ == "__main__":
    main()
