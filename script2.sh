#!/bin/bash

# 取得腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 設定檔路徑（使用 user_config2.toml）
CONFIG_FILE="user_config2.toml"

# 載入 .env 環境變數
if [ -f ".env" ]; then
    echo "Loading .env file..."
    export $(grep -v '^#' .env | xargs)
    echo "GEMINI_API_KEY loaded: ${GEMINI_API_KEY:0:10}...${GEMINI_API_KEY: -4}"
fi

# 從設定檔讀取 success-repeat 次數（預設為 0）
SUCCESS_REPEAT=$(grep -E "^success-repeat\s*=" "$CONFIG_FILE" | head -1 | sed "s/.*=\s*\([0-9]*\).*/\1/")
SUCCESS_REPEAT=${SUCCESS_REPEAT:-0}  # 如果未設定，預設為 0

echo "📋 設定檔: $CONFIG_FILE"
echo "🔄 成功後再循環次數: $SUCCESS_REPEAT"

# 建立虛擬環境（如果不存在）
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 啟用虛擬環境
echo "Activating virtual environment..."
source venv/bin/activate

# 確認使用虛擬環境中的 pip
echo "Using pip from: $(which pip)"

# Install requirements if not already installed
echo "Installing requirements..."
venv/bin/pip install -r requirements.txt

# Check if installation was successful
if [ $? -ne 0 ]; then
    echo "Error: Failed to install requirements"
    exit 1
fi

echo "Requirements installed successfully"
echo "Starting ticket bot..."
echo ""

# 成功計數器
SUCCESS_COUNT=0
TOTAL_SUCCESS_NEEDED=$((SUCCESS_REPEAT + 1))  # 總共需要成功的次數（例如：再循環3次 = 總共4次）

# 無限循環
while true
do
    # 執行 Python 腳本（使用虛擬環境中的 python）
    venv/bin/python ticket_bot.py thsrc -a -c "$CONFIG_FILE"
    EXIT_CODE=$?
    
    # 如果 Python 腳本成功退出（exit code 0），表示訂票成功
    if [ $EXIT_CODE -eq 0 ]; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        echo ""
        echo "🎉 訂票成功！(第 $SUCCESS_COUNT 次成功，共需 $TOTAL_SUCCESS_NEEDED 次)"
        
        # 播放提示音（macOS）
        afplay /System/Library/Sounds/Glass.aiff 2>/dev/null || true
        
        # 檢查是否達到目標次數
        if [ $SUCCESS_COUNT -ge $TOTAL_SUCCESS_NEEDED ]; then
            echo ""
            echo "🎉🎉🎉 已完成 $SUCCESS_COUNT 次成功訂票！程式停止。🎉🎉🎉"
            echo ""
            break
        else
            REMAINING=$((TOTAL_SUCCESS_NEEDED - SUCCESS_COUNT))
            echo "⏳ 還需要成功 $REMAINING 次，10秒後繼續..."
            sleep 10
        fi
    else
        # 其他情況（錯誤或中斷），等待後重試
        echo "⚠️ 程式異常退出 (exit code: $EXIT_CODE)，5秒後重試..."
        sleep 5
        clear
    fi
done
