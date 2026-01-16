#!/bin/bash

# Install requirements if not already installed
echo "Installing requirements..."
pip3 install -r requirements.txt

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
    # 執行 Python 腳本
    python3 ticket_bot.py thsrc -a
    # 等待 5 秒
    sleep 5
    # 清除終端屏幕
    clear
done
