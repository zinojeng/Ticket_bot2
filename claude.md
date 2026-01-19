# 🚄 Ticket-Bot 開發設計文檔

> 本文件記錄了 Ticket-Bot 專案的所有設計概念、架構決策與實作細節。
> 
> 最後更新：2026-01-19

---

## 目錄

1. [專案概述](#專案概述)
2. [環境設定](#環境設定)
3. [驗證碼識別策略](#驗證碼識別策略)
4. [多設定檔支援](#多設定檔支援)
5. [時間區間篩選](#時間區間篩選)
6. [訂票成功自動停止](#訂票成功自動停止)
7. [成功後再循環次數](#成功後再循環次數)
8. [退票功能](#退票功能)
9. [腳本執行流程](#腳本執行流程)
10. [設定檔欄位說明](#設定檔欄位說明)

---

## 專案概述

Ticket-Bot 是一個自動化台灣高鐵（THSRC）訂票工具，透過自動化流程完成：

1. **連線高鐵網站** → 取得 Session ID 和驗證碼
2. **驗證碼識別** → 使用雙重 OCR 策略提高準確率
3. **查詢車次** → 根據設定的時間區間篩選班次
4. **自動選擇** → 選擇最短車程或優惠車次
5. **完成訂票** → 填寫乘客資料並提交

---

## 環境設定

### 問題背景

macOS 使用 Homebrew 安裝的 Python 會遇到 `externally-managed-environment` 錯誤（PEP 668），阻止直接使用 `pip install` 安裝系統層級的套件。

### 解決方案：虛擬環境

使用 Python 虛擬環境 (`venv`) 隔離專案依賴：

```bash
# 建立虛擬環境
python3 -m venv venv

# 啟用虛擬環境
source venv/bin/activate

# 安裝依賴（在虛擬環境中）
pip install -r requirements.txt
```

### script.sh 實作

```bash
# 建立虛擬環境（如果不存在）
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 啟用虛擬環境
source venv/bin/activate

# 使用虛擬環境中的 pip 和 python
venv/bin/pip install -r requirements.txt
venv/bin/python ticket_bot.py thsrc -a
```

### .env 環境變數

API 金鑰透過 `.env` 檔案管理：

```bash
# .env 檔案內容
GEMINI_API_KEY=your_api_key_here
```

載入方式（shell script）：

```bash
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi
```

載入方式（Python）：

```python
from dotenv import load_dotenv
import pathlib

env_path = pathlib.Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)  # override=True 強制覆蓋系統環境變數
```

---

## 驗證碼識別策略

### 設計理念

高鐵驗證碼識別是訂票成功的關鍵。我們採用 **雙重 OCR + 仲裁機制** 來最大化識別準確率。

### 三層識別架構

```
┌─────────────────────────────────────────────────────────────────┐
│                        驗證碼圖片                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼                               ▼
    ┌──────────────────┐            ┌──────────────────┐
    │   holey.cc OCR   │            │   Gemini 3 Flash │
    │  (專門訓練模型)   │            │   (AI 視覺模型)   │
    └──────────────────┘            └──────────────────┘
              │                               │
              │         結果 A                │         結果 B
              └───────────────┬───────────────┘
                              ▼
                    ┌──────────────────┐
                    │     比對結果     │
                    └──────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼                               ▼
        結果一致                          結果不一致
              │                               │
              ▼                               ▼
    ┌──────────────────┐            ┌──────────────────┐
    │    直接使用      │            │   仲裁判斷       │
    │   （信心度高）    │            │  (Gemini 3 再判) │
    └──────────────────┘            └──────────────────┘
```

### holey.cc OCR

專門為台灣高鐵驗證碼訓練的 OCR 模型：

```python
base64_url_safe = base64_str.replace('+', '-').replace('/', '_').replace('=', '')
data = {'base64_str': base64_url_safe}
ocr_res = httpx.post('https://holey.cc/api/captcha', json=data)
holey_result = ocr_res.json().get('data')  # e.g., "A2B3"
```

### Gemini 3 Flash

Google 的 AI 視覺模型，用於獨立識別和仲裁：

```python
api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"

prompt = "Read the 4 characters in this CAPTCHA image. Output EXACTLY 4 characters (A-Z, 0-9) ONLY."

payload = {
    "contents": [{
        "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/png", "data": base64_image}}
        ]
    }],
    "generationConfig": {
        "maxOutputTokens": 256,  # Gemini 3 是思考模型，需要更多 token
        "temperature": 0.1,
        "topP": 0.1
    }
}
```

### 仲裁機制

當兩個識別結果不一致時，讓 Gemini 3 作為「仲裁者」做最終判斷：

```python
def _ocr_arbitrate_with_gemini(self, base64_image, result_a, result_b, api_key):
    prompt = f"""This CAPTCHA image has been recognized by two different OCR systems:
- System A (specialized OCR): {result_a}
- System B (AI vision): {result_b}

Look at the image carefully and determine which result is CORRECT.

IMPORTANT:
- Characters that often get confused: 0/O, 1/I, 5/S, 8/B, 2/Z, 6/G, 9/P

Output ONLY the correct 4-character code. No explanation."""
```

### 決策邏輯

```python
if holey_result.upper() == gemini_result.upper():
    # 兩者一致 → 直接使用
    return gemini_result
else:
    # 不一致 → 啟動仲裁
    final_result = self._ocr_arbitrate_with_gemini(...)
    if final_result:
        return final_result
    else:
        # 仲裁失敗 → 優先使用 holey.cc（專門訓練）
        return holey_result
```

---

## 多設定檔支援

### 使用場景

需要同時運行多個不同設定的訂票任務，例如：
- 不同日期
- 不同出發/抵達站
- 不同時間區間

### 實作方式

#### 1. 命令列參數

```bash
# 使用預設設定檔 (user_config.toml)
python ticket_bot.py thsrc -a

# 使用自訂設定檔
python ticket_bot.py thsrc -a -c user_config2.toml
```

#### 2. ticket_bot.py 支援

```python
parser.add_argument(
    '-c', '--config',
    dest='config_file',
    help="path to custom config file",
)

if args.config_file:
    config_path = Path(args.config_file)
    if not config_path.is_absolute():
        config_path = Path(os.path.dirname(__file__)) / config_path
    config = Config.from_toml(config_path)
```

#### 3. 獨立腳本

- `script.sh` → 使用 `user_config.toml`
- `script2.sh` → 使用 `user_config2.toml`

可以同時在兩個終端機視窗中運行不同設定的訂票任務。

---

## 時間區間篩選

### 設計目的

原本只能設定「出發時間起點」，現在可以設定完整的時間區間，例如只搜尋 12:30 ~ 13:00 之間的班次。

### 設定欄位

```toml
[fields.THSRC]
outbound-time = '12:30'      # 出發時間（搜尋起始時間）
outbound-time-end = '13:00'  # 出發時間結束（搜尋結束時間，留空則不限制）
inbound-time = ''            # 抵達時間限制（選填）
```

### 實作邏輯

```python
def confirm_train(self, html_page, default_value: int = 1):
    trains = []
    outbound_time_end = self.fields.get('outbound-time-end', '')
    
    for train in html_page.find_all('input', {...}):
        departure_time = train['querydeparture']
        
        # 過濾出發時間結束
        if outbound_time_end:
            if datetime.strptime(departure_time, '%H:%M').time() > \
               datetime.strptime(outbound_time_end, '%H:%M').time():
                continue  # 跳過超過結束時間的班次
        
        trains.append({...})
```

### 自動選擇邏輯

在指定時間區間內，自動選擇：
1. **優惠班次** → 有折扣的優先
2. **最短車程** → 在符合條件的班次中選擇車程最短的

```python
if self.auto:
    # 優先選擇有折扣的班次
    if has_discount:
        trains = list(filter(lambda t: t['discount'], trains)) or trains
    
    # 選擇最短車程
    trains = [min(trains, key=lambda t: datetime.strptime(t['duration'], '%H:%M').time())]
```

---

## 訂票成功自動停止

### 問題描述

原本的 `while true` 無限循環會在訂票成功後繼續執行，導致：
1. 不必要的重複訂票
2. 成功畫面被 `clear` 清除

### 解決方案

#### Python 端：成功後 exit(0)

```python
def print_result(self, html_page):
    # ... 印出訂票結果 ...
    
    # 訂票成功，自動停止程式
    self.logger.info("\n🎉 訂票成功！程式自動停止。")
    sys.exit(0)  # 成功退出碼
```

#### Shell 端：檢查 exit code

```bash
while true
do
    venv/bin/python ticket_bot.py thsrc -a
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        echo "🎉🎉🎉 訂票成功！程式已停止。🎉🎉🎉"
        afplay /System/Library/Sounds/Glass.aiff  # 播放提示音
        break  # 停止循環
    fi
    
    # 失敗才重試
    sleep 5
    clear
done
```

---

## 成功後再循環次數

### 設計目的

有時候需要預訂多張票（例如家人分開訂），可以設定成功後還要再嘗試幾次。

### 設定欄位

```toml
[schedules.THSRC]
datetime = ''
success-repeat = 0  # 成功後再循環次數（0 = 成功後立即停止，3 = 成功後再嘗試3次）
```

### 設定說明

| 設定值 | 行為 | 總成功次數 |
|--------|------|-----------|
| `success-repeat = 0` | 成功 1 次後立即停止 | 1 次 |
| `success-repeat = 1` | 成功後再嘗試 1 次 | 最多 2 次 |
| `success-repeat = 3` | 成功後再嘗試 3 次 | 最多 4 次 |

### Shell 實作

```bash
# 從設定檔讀取 success-repeat
SUCCESS_REPEAT=$(grep -E "^success-repeat\s*=" "$CONFIG_FILE" | sed "s/.*=\s*\([0-9]*\).*/\1/")
SUCCESS_REPEAT=${SUCCESS_REPEAT:-0}

# 成功計數器
SUCCESS_COUNT=0
TOTAL_SUCCESS_NEEDED=$((SUCCESS_REPEAT + 1))

while true
do
    venv/bin/python ticket_bot.py thsrc -a
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        echo "🎉 訂票成功！(第 $SUCCESS_COUNT 次成功，共需 $TOTAL_SUCCESS_NEEDED 次)"
        afplay /System/Library/Sounds/Glass.aiff
        
        if [ $SUCCESS_COUNT -ge $TOTAL_SUCCESS_NEEDED ]; then
            echo "🎉🎉🎉 已完成 $SUCCESS_COUNT 次成功訂票！程式停止。🎉🎉🎉"
            break
        else
            REMAINING=$((TOTAL_SUCCESS_NEEDED - SUCCESS_COUNT))
            echo "⏳ 還需要成功 $REMAINING 次，10秒後繼續..."
            sleep 10
        fi
    else
        echo "⚠️ 程式異常退出，5秒後重試..."
        sleep 5
        clear
    fi
done
```

---

## 退票功能

### 設計目的

提供批次取消高鐵訂位的功能，支援：
- 單筆退票
- 多筆批次退票
- 互動式手動輸入
- 使用相同的驗證碼識別策略（holey.cc + Gemini 3）

### 檔案結構

```
Ticket-Bot/
├── cancel_bot.py           # 退票主程式
├── cancel_config.toml      # 退票設定檔
├── cancel.sh               # 退票啟動腳本
└── services/
    └── thsrc_cancel.py     # 退票服務類
```

### 使用方式

#### 方式 1：設定檔批次退票（推薦）

編輯 `cancel_config.toml`，使用「一個身分證 + 多個訂位代號」的簡潔格式：

```toml
[batch]
enabled = true
id = 'A123456789'                        # 身分證字號
pnr_list = '12345678, 87654321, 11112222'  # 多筆訂位代號（用逗號分隔）

# 或者用多行格式：
# pnr_list = '''
# 12345678
# 87654321
# 11112222
# '''
```

執行：

```bash
./cancel.sh
```

#### 方式 2：命令列直接退票

```bash
# 單筆退票
./cancel.sh A123456789 12345678

# 多筆退票（用逗號分隔）
./cancel.sh A123456789 "12345678,87654321,11112222"

# 跳過確認直接退票
./cancel.sh A123456789 "12345678,87654321" -y

# 或使用 Python 直接執行
python cancel_bot.py --id A123456789 --pnr "12345678,87654321"
```

#### 方式 3：互動模式

```bash
./cancel.sh -i
# 或
python cancel_bot.py -i
```

互動模式支援兩種輸入方式：

**批次模式（推薦）：**
```
選擇模式 [1=批次/2=個別] (預設: 1): 1

📦 批次退票模式
----------------------------------------
身分證字號: A123456789

📋 輸入訂位代號（可用逗號、空格或換行分隔）
   範例: 12345678, 87654321, 11112222
----------------------------------------
12345678, 87654321, 11112222

✅ 已加入 3 筆退票資料
```

**個別模式：**
```
選擇模式 [1=批次/2=個別] (預設: 1): 2

📝 個別退票模式
----------------------------------------
身分證字號 (輸入 q 結束): A123456789
訂位代號: 12345678
✅ 已加入: A123****89 / 12345678
...
```

### 設定檔說明

```toml
# =====================================================
# 方式一：批次退票（推薦）
# =====================================================
[batch]
enabled = true
id = 'A123456789'                         # 身分證字號
pnr_list = '12345678, 87654321, 11112222'  # 多筆訂位代號

# =====================================================
# 方式二：個別退票（舊格式）
# =====================================================
[[cancellations]]
id = 'A123456789'    # 身分證字號
pnr = '12345678'     # 訂位代號
enabled = false      # 設為 false 則跳過

# =====================================================
# 執行設定
# =====================================================
[settings]
mode = 'all'                    # 退票模式：'single'（只退第一筆）或 'all'（全部）
delay_between = 5               # 每筆退票間隔秒數
max_captcha_retries = 10        # 驗證碼最大重試次數
confirm_before_cancel = true    # 退票前是否確認

# =====================================================
# HTTP 標頭
# =====================================================
[headers]
User-Agent = 'Mozilla/5.0 ...'
```

### 退票流程圖

```
┌─────────────────────────────────────────────────────────────────┐
│                        cancel.sh 啟動                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   載入 .env      │
                    │  (API 金鑰)      │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ 讀取退票設定檔   │
                    │cancel_config.toml│
                    └──────────────────┘
                              │
                              ▼
          ┌──────────────────────────────────────┐
          │         對每筆退票資料循環           │
          │  ┌────────────────────────────────┐  │
          │  │  1. 連線訂位紀錄查詢頁面      │  │
          │  │  2. 取得驗證碼圖片            │  │
          │  │  3. OCR 識別驗證碼            │  │
          │  │  4. 登入查詢訂位              │  │
          │  │  5. 顯示訂位資訊              │  │
          │  │  6. 確認是否退票              │  │
          │  │  7. 執行退票                  │  │
          │  └────────────────────────────────┘  │
          │                   │                  │
          │     ┌─────────────┼─────────────┐    │
          │     ▼             ▼             ▼    │
          │   成功          失敗        驗證錯誤  │
          │     │             │             │    │
          │     ▼             ▼             ▼    │
          │  記錄成功      記錄失敗     重試驗證  │
          │     │             │             │    │
          │     └─────────────┼─────────────┘    │
          │                   │                  │
          │              下一筆退票              │
          └──────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   退票結果總結   │
                    │  ✅ 成功: X 筆   │
                    │  ❌ 失敗: Y 筆   │
                    └──────────────────┘
```

### 命令列參數

```bash
python cancel_bot.py [選項]

選項：
  -c, --config FILE    指定設定檔路徑（預設: cancel_config.toml）
  -i, --interactive    互動模式：手動輸入退票資訊
  -y, --yes            跳過確認，直接執行退票
  --id ID              直接指定身分證字號（需搭配 --pnr）
  --pnr PNR            直接指定訂位代號（需搭配 --id）
  --repeat N           重複執行次數（預設: 1）
```

### 範例輸出

```
🚄 高鐵退票機器人啟動
============================================================

==================================================
🎫 處理退票: 12345678
   身分證: A123****89
==================================================

📡 連線高鐵訂位紀錄查詢頁面...
嘗試連線... (1/3)
✅ Session ID: abc123def456...
+ holey.cc 識別: A2B3
✨ 使用 Gemini 3 Flash 識別中...
+ Gemini 3 識別: A2B3
🎯 兩者一致，信心度高！

📋 訂位資訊:
   訂位代號: 12345678
   付款狀態: 已付款
   乘車日期: 2026/01/25
   車次: 123
   行程: 台北 08:00 → 台中 08:48
   座位: 3車 5A, 3車 5B

❓ 確定要取消此訂位嗎？(y/N): y
🔄 執行退票中...
✅ 訂位 12345678 已成功取消！

============================================================
📊 退票結果總結
============================================================
   ✅ 成功: 1 筆
   ❌ 失敗: 0 筆
============================================================
```

---

## 腳本執行流程

### script.sh 完整流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        script.sh 啟動                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   載入 .env      │
                    │  (API 金鑰)      │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ 讀取 success-    │
                    │ repeat 設定      │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ 建立/啟用 venv   │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ 安裝 requirements│
                    └──────────────────┘
                              │
                              ▼
          ┌──────────────────────────────────────┐
          │            while true 循環           │
          │  ┌────────────────────────────────┐  │
          │  │     執行 ticket_bot.py         │  │
          │  └────────────────────────────────┘  │
          │                   │                  │
          │     ┌─────────────┼─────────────┐    │
          │     ▼             ▼             ▼    │
          │  exit=0       exit=1       其他      │
          │  (成功)       (失敗)       (錯誤)    │
          │     │             │             │    │
          │     ▼             │             │    │
          │  SUCCESS_COUNT++  │             │    │
          │  播放提示音       │             │    │
          │     │             │             │    │
          │     ▼             │             │    │
          │  達到目標次數？    │             │    │
          │  ┌───┴───┐        │             │    │
          │  ▼       ▼        ▼             ▼    │
          │ Yes     No     5秒後重試  5秒後重試  │
          │  │       │        │             │    │
          │  ▼       │        │             │    │
          │ break    │        │             │    │
          │          └────────┴─────────────┘    │
          └──────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   程式結束       │
                    └──────────────────┘
```

---

## 設定檔欄位說明

### user_config.toml 完整結構

```toml
# =====================================================
# 排程設定
# =====================================================
[schedules]

[schedules.THSRC]
datetime = ''           # 預計訂票時間 (e.g. 2026-01-20 00:00)
success-repeat = 0      # 成功後再循環次數

# =====================================================
# HTTP 標頭
# =====================================================
[headers]
User-Agent = 'Mozilla/5.0 ...'  # 從瀏覽器複製

# =====================================================
# 目錄設定
# =====================================================
[directories]
# logs = 'logs/'  # 可自訂日誌目錄

# =====================================================
# 訂票欄位設定
# =====================================================
[fields]

[fields.THSRC]
id = 'A123456789'         # 身分證字號
start-station = 'Taipei'  # 出發站
dest-station = 'Taichung' # 抵達站
outbound-date = '2026-01-20'  # 出發日期
outbound-time = '12:00'       # 出發時間（搜尋起始）
outbound-time-end = '13:00'   # 出發時間結束（留空不限制）
inbound-time = ''             # 抵達時間限制（留空不限制）
preferred-seat = ''           # 座位偏好 (window/aisle)
car-type = 'normal'           # 車廂類型 (normal/business)
train-no = ''                 # 指定車次（留空則時間搜尋）
email = 'user@example.com'    # 通知信箱
phone = '0912345678'          # 手機號碼
tgo-id = ''                   # TGO 會員 ID
tax-id = ''                   # 統一編號（公司報帳）

# =====================================================
# 票種數量
# =====================================================
[fields.THSRC.ticket]
adult = 1     # 全票
child = 0     # 孩童票 (6-11)
disabled = 0  # 愛心票
elder = 0     # 敬老票 (65+)
college = 0   # 大學生票
teenager = 0  # 少年票 (12-18)

# =====================================================
# 特殊票種身分證
# =====================================================
[fields.THSRC.ids]
disabled = []                       # 愛心票身分證
elder = ['A270002017', 'B123456789']  # 敬老票身分證

# =====================================================
# 代理伺服器設定
# =====================================================
[proxies]
# us = 'http://127.0.0.1:7890'

# =====================================================
# NordVPN 設定
# =====================================================
[nordvpn]
username = ''
password = ''
```

---

## 車站代碼對照表

| 中文名稱 | 英文名稱 | 代碼 |
|----------|----------|------|
| 南港 | Nangang | 1 |
| 台北 | Taipei | 2 |
| 板橋 | Banqiao | 3 |
| 桃園 | Taoyuan | 4 |
| 新竹 | Hsinchu | 5 |
| 苗栗 | Miaoli | 6 |
| 台中 | Taichung | 7 |
| 彰化 | Changhua | 8 |
| 雲林 | Yunlin | 9 |
| 嘉義 | Chiayi | 10 |
| 台南 | Tainan | 11 |
| 左營 | Zuouing | 12 |

---

## 常見問題排解

### 1. externally-managed-environment 錯誤

```
error: externally-managed-environment
```

**解決**：使用虛擬環境（參見 [環境設定](#環境設定)）

### 2. GEMINI_API_KEY 未讀取

**原因**：系統環境變數覆蓋 `.env` 檔案

**解決**：使用 `override=True`

```python
load_dotenv(dotenv_path=env_path, override=True)
```

### 3. 驗證碼一直錯誤

**可能原因**：
- holey.cc 服務不穩定
- Gemini API 金鑰無效
- 網路連線問題

**解決**：
- 檢查 `.env` 中的 `GEMINI_API_KEY`
- 確認網路連線正常
- 查看 logs 中的錯誤訊息

### 4. 找不到符合條件的班次

**可能原因**：
- `outbound-time-end` 設定的區間太窄
- 該時段沒有班次

**解決**：擴大時間區間或移除 `outbound-time-end` 設定

---

## 版本歷史

| 版本 | 日期 | 更新內容 |
|------|------|----------|
| v1.1 | 2026-01-19 | 新增退票功能：批次退票、互動模式、多種使用方式 |
| v1.0 | 2026-01-19 | 初始版本：雙重 OCR、時間區間、成功停止、再循環次數 |

---

## 貢獻者

- Zino Jeng

---

## License

MIT License
