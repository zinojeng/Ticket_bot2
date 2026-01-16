"""
簡單的 HTTP 服務器 + 訂票程式
用於 Zeabur 等雲端平台部署
"""
import os
import sys
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# 全域狀態
status = {
    "started_at": datetime.now().isoformat(),
    "ticket_process": None,
    "last_check": None
}

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            response = f'''{{
    "status": "running",
    "started_at": "{status['started_at']}",
    "service": "THSRC Ticket Bot",
    "message": "訂票程式正在運行中..."
}}'''
            self.wfile.write(response.encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # 禁用日誌輸出

def run_ticket_bot():
    """在背景執行訂票程式"""
    print("🚀 啟動訂票程式...")
    process = subprocess.Popen(
        [sys.executable, "ticket_bot.py", "thsrc", "-a"],
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    status["ticket_process"] = process
    process.wait()
    print("✅ 訂票程式已結束")

def main():
    # 取得 PORT（Zeabur 會設定這個環境變數）
    port = int(os.environ.get("PORT", 8080))
    
    # 在背景執行訂票程式
    ticket_thread = threading.Thread(target=run_ticket_bot, daemon=True)
    ticket_thread.start()
    
    # 啟動 HTTP 服務器
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 HTTP 服務器運行在 port {port}")
    print(f"📋 健康檢查: http://localhost:{port}/health")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹️ 停止服務...")
        server.shutdown()

if __name__ == "__main__":
    main()
