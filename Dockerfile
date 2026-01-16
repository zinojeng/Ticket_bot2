FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt python-dotenv

# 複製程式碼
COPY . .

# 暴露 PORT
EXPOSE 8080

# 執行 Web 應用程式
CMD ["python", "web_app.py"]
