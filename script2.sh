#!/bin/bash

# 取得腳本所在目錄
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

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

# 無限循環
while true
do
    # 執行 Python 腳本（使用虛擬環境中的 python）
    #venv/bin/python ticket_bot.py thsrc -a
    venv/bin/python ticket_bot.py thsrc -a -c user_config2.toml

    # 等待 5 秒
    sleep 5
    # 清除終端屏幕
    clear
done
