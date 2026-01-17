FROM python:3.11-slim

WORKDIR /app

# 安裝 Chrome 和相關依賴
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    --no-install-recommends \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt python-dotenv

# 複製程式碼
COPY . .

# 設定 Chrome 環境變數
ENV CHROME_BIN=/usr/bin/google-chrome
ENV DISPLAY=:99

# 暴露 PORT
EXPOSE 8080

# 執行 Web 應用程式
CMD ["python", "web_app.py"]
