#!/bin/bash

# =====================================================
# 高鐵退票機器人啟動腳本
# =====================================================

# 取得腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚄 高鐵退票機器人"
echo "================================"

# 載入 .env 環境變數
if [ -f ".env" ]; then
    echo "📂 Loading .env file..."
    export $(grep -v '^#' .env | xargs)
    if [ -n "$GEMINI_API_KEY" ]; then
        echo "🔑 GEMINI_API_KEY loaded: ${GEMINI_API_KEY:0:10}...${GEMINI_API_KEY: -4}"
    fi
fi

# 建立虛擬環境（如果不存在）
if [ ! -d "venv" ]; then
    echo "🔧 Creating virtual environment..."
    python3 -m venv venv
fi

# 啟用虛擬環境
echo "🔄 Activating virtual environment..."
source venv/bin/activate

# 安裝依賴
echo "📦 Checking requirements..."
venv/bin/pip install -r requirements.txt -q

if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to install requirements"
    exit 1
fi

echo ""

# 檢查參數
if [ "$1" == "-i" ] || [ "$1" == "--interactive" ]; then
    # 互動模式
    echo "🎯 啟動互動模式..."
    venv/bin/python cancel_bot.py -i
elif [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    # 顯示說明
    venv/bin/python cancel_bot.py --help
elif [ -n "$1" ] && [ -n "$2" ]; then
    # 直接指定身分證和訂位代號（支援多筆，用逗號分隔）
    echo "🎯 直接退票模式"
    echo "   身分證: $1"
    echo "   訂位代號: $2"
    echo ""
    
    # 檢查是否有 -y 參數
    if [ "$3" == "-y" ]; then
        venv/bin/python cancel_bot.py --id "$1" --pnr "$2" -y
    else
        venv/bin/python cancel_bot.py --id "$1" --pnr "$2"
    fi
else
    # 使用設定檔模式
    if [ -f "cancel_config.toml" ]; then
        echo "📋 使用設定檔: cancel_config.toml"
        echo ""
        venv/bin/python cancel_bot.py "$@"
    else
        echo "❌ 找不到設定檔 cancel_config.toml"
        echo ""
        echo "💡 使用方式:"
        echo "   1. 設定檔模式: 編輯 cancel_config.toml 後執行 ./cancel.sh"
        echo "   2. 直接指定:   ./cancel.sh <身分證> <訂位代號>"
        echo "   3. 互動模式:   ./cancel.sh -i"
        echo ""
        echo "📌 範例:"
        echo "   ./cancel.sh A123456789 12345678              # 單筆退票"
        echo "   ./cancel.sh A123456789 \"12345678,87654321\"   # 多筆退票"
        echo "   ./cancel.sh A123456789 12345678 -y           # 跳過確認"
        echo "   ./cancel.sh -i                                # 互動模式"
        exit 1
    fi
fi

echo ""
echo "================================"
echo "✅ 退票作業完成"
