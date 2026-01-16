FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt python-dotenv

# 複製程式碼
COPY . .

# 執行訂票程式
CMD ["python", "ticket_bot.py", "thsrc", "-a"]
