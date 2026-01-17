FROM python:3.11-slim

WORKDIR /app

# Cache buster - 改變這個值強制重建
ARG CACHEBUST=3

# 安裝 Chromium 和 ChromeDriver（版本自動匹配）
RUN echo "Cache bust: $CACHEBUST" && \
    apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && chromium --version \
    && chromedriver --version

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt python-dotenv

# 複製程式碼
COPY . .

# 設定 Chrome 環境變數
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# 暴露 PORT
EXPOSE 8080

# 執行 Web 應用程式
CMD ["python", "web_app.py"]
