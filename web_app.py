"""
THSRC 訂票 Web 介面
可部署到 Zeabur 等雲端平台
"""
import os
import sys
import json
import threading
import queue
import secrets
import hashlib
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from string import Template
from http.cookies import SimpleCookie
import rtoml

# 密碼設定（必須透過環境變數設定）
APP_PASSWORD = os.environ.get("APP_PASSWORD")
if not APP_PASSWORD:
    print("⚠️  警告：未設定 APP_PASSWORD 環境變數！")
    print("請設定環境變數：export APP_PASSWORD=你的密碼")
    print("或在 Zeabur 控制台設定環境變數")
    # 開發環境可以繼續運行，但會提示
    APP_PASSWORD = None  # 將在登入時檢查

# Session 管理
active_sessions = {}  # token -> expiry_time

# 全域狀態
app_state = {
    "status": "idle",  # idle, searching, found, error
    "message": "",
    "logs": [],
    "current_task": None,
    "result": None
}

log_queue = queue.Queue()

def generate_session_token():
    """生成安全的 session token"""
    return secrets.token_hex(32)

def verify_session(token):
    """驗證 session 是否有效"""
    if token in active_sessions:
        if datetime.now() < active_sessions[token]:
            return True
        else:
            del active_sessions[token]
    return False

def create_session():
    """創建新的 session"""
    token = generate_session_token()
    # Session 有效期 24 小時
    active_sessions[token] = datetime.now() + timedelta(hours=24)
    return token

# 登入頁面模板
LOGIN_TEMPLATE = Template('''<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>登入 - 高鐵訂票助手</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #E35205;
            --primary-dark: #C44800;
            --bg: #0F0F1A;
            --card-bg: #1A1A2E;
            --text: #EAEAEA;
            --text-muted: #8892B0;
            --border: #2D2D44;
            --error: #FF4757;
            --accent: #16213E;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Noto Sans TC', -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background-image: 
                radial-gradient(ellipse at top, rgba(227, 82, 5, 0.15) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(22, 33, 62, 0.3) 0%, transparent 50%);
        }
        
        .login-container {
            width: 100%;
            max-width: 400px;
            padding: 1rem;
        }
        
        .login-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 2.5rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        
        .logo {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        .logo h1 {
            font-size: 2rem;
            background: linear-gradient(135deg, var(--primary), #FF7B54);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .logo p {
            color: var(--text-muted);
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        
        .form-group {
            margin-bottom: 1.5rem;
        }
        
        label {
            display: block;
            font-size: 0.875rem;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }
        
        input {
            width: 100%;
            padding: 1rem;
            font-size: 1rem;
            font-family: inherit;
            background: var(--accent);
            border: 1px solid var(--border);
            border-radius: 10px;
            color: var(--text);
            transition: all 0.2s;
        }
        
        input:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(227, 82, 5, 0.2);
        }
        
        .btn {
            width: 100%;
            padding: 1rem;
            font-size: 1.1rem;
            font-weight: 600;
            font-family: inherit;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
            box-shadow: 0 4px 16px rgba(227, 82, 5, 0.4);
            transition: all 0.2s;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(227, 82, 5, 0.5);
        }
        
        .error-msg {
            background: rgba(255, 71, 87, 0.1);
            border: 1px solid var(--error);
            color: var(--error);
            padding: 0.75rem 1rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
            text-align: center;
            display: $error_display;
        }
        
        .footer {
            text-align: center;
            margin-top: 1.5rem;
            color: var(--text-muted);
            font-size: 0.8rem;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-card">
            <div class="logo">
                <h1>🚄 高鐵訂票助手</h1>
                <p>請輸入密碼以繼續</p>
            </div>
            
            <div class="error-msg">$error_message</div>
            
            <form method="POST" action="/login">
                <div class="form-group">
                    <label for="password">密碼</label>
                    <input type="password" id="password" name="password" 
                           placeholder="請輸入密碼" required autofocus>
                </div>
                
                <button type="submit" class="btn">🔓 登入</button>
            </form>
            
            <p class="footer">🔒 此頁面受密碼保護</p>
        </div>
    </div>
</body>
</html>
''')

# 車站列表
STATIONS = [
    ("NanGang", "南港"),
    ("Taipei", "台北"),
    ("Banqiao", "板橋"),
    ("Taoyuan", "桃園"),
    ("Hsinchu", "新竹"),
    ("Miaoli", "苗栗"),
    ("Taichung", "台中"),
    ("Changhua", "彰化"),
    ("Yunlin", "雲林"),
    ("Chiayi", "嘉義"),
    ("Tainan", "台南"),
    ("Zuoying", "左營"),
]

# 時間選項
TIMES = [
    "00:00", "00:30", "06:00", "06:30", "07:00", "07:30",
    "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
    "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
    "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
    "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00", "22:30",
    "23:00", "23:30"
]

# 使用 Template 避免 CSS 中的 {} 被誤解
HTML_TEMPLATE = Template('''<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>高鐵訂票助手</title>
    <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #E35205;
            --primary-dark: #C44800;
            --secondary: #1A1A2E;
            --accent: #16213E;
            --bg: #0F0F1A;
            --card-bg: #1A1A2E;
            --text: #EAEAEA;
            --text-muted: #8892B0;
            --success: #00D97E;
            --error: #FF4757;
            --border: #2D2D44;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Noto Sans TC', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg);
            color: var(--text);
            min-height: 100vh;
            background-image: 
                radial-gradient(ellipse at top, rgba(227, 82, 5, 0.1) 0%, transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(22, 33, 62, 0.3) 0%, transparent 50%);
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem 1rem;
        }
        
        header {
            text-align: center;
            margin-bottom: 2rem;
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--primary), #FF7B54);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-muted);
            font-size: 1rem;
        }
        
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
        }
        
        .card-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .form-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 1rem;
        }
        
        @media (max-width: 600px) {
            .form-grid {
                grid-template-columns: 1fr;
            }
        }
        
        .form-group {
            margin-bottom: 1rem;
        }
        
        .form-group.full-width {
            grid-column: span 2;
        }
        
        @media (max-width: 600px) {
            .form-group.full-width {
                grid-column: span 1;
            }
        }
        
        label {
            display: block;
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
        }
        
        input, select {
            width: 100%;
            padding: 0.875rem 1rem;
            font-size: 1rem;
            font-family: inherit;
            background: var(--accent);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            transition: all 0.2s ease;
        }
        
        input:focus, select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(227, 82, 5, 0.2);
        }
        
        select {
            cursor: pointer;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='%238892B0' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 0.75rem center;
            background-size: 1rem;
            padding-right: 2.5rem;
        }
        
        .ticket-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
        }
        
        @media (max-width: 600px) {
            .ticket-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        
        .ticket-input {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .ticket-input input {
            width: 60px;
            text-align: center;
            padding: 0.5rem;
        }
        
        .ticket-input span {
            font-size: 0.875rem;
            color: var(--text-muted);
        }
        
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 1rem 2rem;
            font-size: 1.125rem;
            font-weight: 600;
            font-family: inherit;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
            width: 100%;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
            box-shadow: 0 4px 16px rgba(227, 82, 5, 0.4);
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(227, 82, 5, 0.5);
        }
        
        .btn-primary:active {
            transform: translateY(0);
        }
        
        .btn-primary:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .btn-stop {
            background: var(--error);
            color: white;
            margin-top: 1rem;
        }
        
        .status-card {
            background: linear-gradient(135deg, var(--accent), var(--secondary));
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 1rem;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        
        .status-dot.idle { background: var(--text-muted); animation: none; }
        .status-dot.searching { background: var(--primary); }
        .status-dot.found { background: var(--success); animation: none; }
        .status-dot.error { background: var(--error); animation: none; }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.1); }
        }
        
        .log-container {
            max-height: 300px;
            overflow-y: auto;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 1rem;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 0.8rem;
            line-height: 1.6;
        }
        
        .log-entry {
            color: var(--text-muted);
            margin-bottom: 0.25rem;
        }
        
        .log-entry.success { color: var(--success); }
        .log-entry.error { color: var(--error); }
        .log-entry.info { color: var(--primary); }
        
        .result-card {
            background: linear-gradient(135deg, rgba(0, 217, 126, 0.1), rgba(0, 217, 126, 0.05));
            border-color: var(--success);
        }
        
        .result-card .card-title {
            color: var(--success);
        }
        
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.875rem;
        }
        
        .hidden { display: none !important; }
        
        .spinner {
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚄 高鐵訂票助手</h1>
            <p class="subtitle">自動搜尋並訂購台灣高鐵車票</p>
        </header>
        
        <form id="bookingForm" class="card">
            <h2 class="card-title">📝 訂票資訊</h2>
            
            <div class="form-grid">
                <div class="form-group">
                    <label for="startStation">起站</label>
                    <select id="startStation" name="startStation" required>
                        $station_options
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="destStation">終站</label>
                    <select id="destStation" name="destStation" required>
                        $station_options_dest
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="outboundDate">日期</label>
                    <input type="date" id="outboundDate" name="outboundDate" required>
                </div>
                
                <div class="form-group">
                    <label for="outboundTime">時間（最早出發）</label>
                    <select id="outboundTime" name="outboundTime" required>
                        $time_options
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="carType">車廂類型</label>
                    <select id="carType" name="carType">
                        <option value="normal">標準車廂</option>
                        <option value="business">商務車廂</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="preferredSeat">座位偏好</label>
                    <select id="preferredSeat" name="preferredSeat">
                        <option value="">無偏好</option>
                        <option value="window">靠窗</option>
                        <option value="aisle">靠走道</option>
                    </select>
                </div>
                
                <div class="form-group full-width">
                    <label for="trainNo">指定車次（可選）</label>
                    <input type="text" id="trainNo" name="trainNo" 
                           placeholder="留空則依時間搜尋，如：0123">
                </div>
                
                <div class="form-group full-width">
                    <label>票種數量</label>
                    <div class="ticket-grid">
                        <div class="ticket-input">
                            <input type="number" id="adult" name="adult" value="1" min="0" max="10">
                            <span>成人</span>
                        </div>
                        <div class="ticket-input">
                            <input type="number" id="child" name="child" value="0" min="0" max="10">
                            <span>孩童(6-11)</span>
                        </div>
                        <div class="ticket-input">
                            <input type="number" id="teenager" name="teenager" value="0" min="0" max="10">
                            <span>少年(12-18)</span>
                        </div>
                        <div class="ticket-input">
                            <input type="number" id="college" name="college" value="0" min="0" max="10">
                            <span>大學生</span>
                        </div>
                        <div class="ticket-input">
                            <input type="number" id="disabled" name="disabled" value="0" min="0" max="10">
                            <span>愛心</span>
                        </div>
                        <div class="ticket-input">
                            <input type="number" id="elder" name="elder" value="0" min="0" max="10">
                            <span>敬老(65+)</span>
                        </div>
                    </div>
                </div>
                
                <div class="form-group full-width">
                    <label for="personalId">訂票人身分證字號</label>
                    <input type="text" id="personalId" name="personalId" 
                           placeholder="A123456789" maxlength="10" required
                           pattern="[A-Za-z][12][0-9]{8}">
                </div>
                
                <div class="form-group full-width" id="disabledIdsGroup" style="display:none;">
                    <label for="disabledIds">愛心票身分證（每行一個）</label>
                    <textarea id="disabledIds" name="disabledIds" rows="2" 
                              placeholder="A123456789&#10;B987654321" 
                              style="width:100%;padding:0.875rem;background:var(--accent);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:inherit;resize:vertical;"></textarea>
                </div>
                
                <div class="form-group full-width" id="elderIdsGroup" style="display:none;">
                    <label for="elderIds">敬老票身分證（每行一個）</label>
                    <textarea id="elderIds" name="elderIds" rows="2" 
                              placeholder="A123456789&#10;B987654321"
                              style="width:100%;padding:0.875rem;background:var(--accent);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:inherit;resize:vertical;"></textarea>
                </div>
                
                <div class="form-group">
                    <label for="email">Email 通知</label>
                    <input type="email" id="email" name="email" 
                           placeholder="example@gmail.com">
                </div>
                
                <div class="form-group">
                    <label for="phone">手機號碼（簡訊通知）</label>
                    <input type="tel" id="phone" name="phone" 
                           placeholder="0912345678" maxlength="10">
                </div>
                
                <div class="form-group">
                    <label for="tgoId">TGO 會員 ID（可選）</label>
                    <input type="text" id="tgoId" name="tgoId" 
                           placeholder="會員身分證字號" maxlength="10">
                </div>
                
                <div class="form-group">
                    <label for="taxId">統一編號（可選）</label>
                    <input type="text" id="taxId" name="taxId" 
                           placeholder="公司統編" maxlength="8">
                </div>
            </div>
            
            <button type="submit" class="btn btn-primary" id="submitBtn">
                <span>🔍 開始搜尋訂票</span>
            </button>
        </form>
        
        <div id="statusCard" class="card status-card hidden">
            <h2 class="card-title">📊 執行狀態</h2>
            
            <div class="status-indicator">
                <div class="status-dot" id="statusDot"></div>
                <span id="statusText">等待中...</span>
            </div>
            
            <div class="log-container" id="logContainer">
                <div class="log-entry">等待開始...</div>
            </div>
            
            <button type="button" class="btn btn-stop hidden" id="stopBtn" onclick="stopSearch()">
                ⏹️ 停止搜尋
            </button>
        </div>
        
        <div id="resultCard" class="card result-card hidden">
            <h2 class="card-title">✅ 訂票成功</h2>
            <div id="resultContent"></div>
        </div>
        
        <footer>
            <p>⚠️ 本工具僅供學習使用，請遵守高鐵訂票規則</p>
        </footer>
    </div>
    
    <script>
        // 設定預設日期為明天
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        document.getElementById('outboundDate').value = tomorrow.toISOString().split('T')[0];
        document.getElementById('outboundDate').min = tomorrow.toISOString().split('T')[0];
        
        // 預設時間為 12:00
        document.getElementById('outboundTime').value = '12:00';
        
        // 預設終站為台中
        document.getElementById('destStation').value = 'Taichung';
        
        // 動態顯示愛心票/敬老票身分證欄位
        document.getElementById('disabled').addEventListener('change', function() {
            document.getElementById('disabledIdsGroup').style.display = 
                this.value > 0 ? 'block' : 'none';
        });
        
        document.getElementById('elder').addEventListener('change', function() {
            document.getElementById('elderIdsGroup').style.display = 
                this.value > 0 ? 'block' : 'none';
        });
        
        let pollingInterval = null;
        
        document.getElementById('bookingForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());
            
            // 驗證至少有一張票
            const totalTickets = parseInt(data.adult || 0) + parseInt(data.child || 0) + 
                                parseInt(data.elder || 0) + parseInt(data.disabled || 0) + 
                                parseInt(data.college || 0) + parseInt(data.teenager || 0);
            if (totalTickets === 0) {
                alert('請至少選擇一張票！');
                return;
            }
            
            // 驗證愛心票身分證數量
            if (parseInt(data.disabled || 0) > 0) {
                const disabledIds = (data.disabledIds || '').trim().split('\\n').filter(id => id.trim());
                if (disabledIds.length < parseInt(data.disabled)) {
                    alert('請輸入足夠的愛心票身分證！');
                    return;
                }
            }
            
            // 驗證敬老票身分證數量
            if (parseInt(data.elder || 0) > 0) {
                const elderIds = (data.elderIds || '').trim().split('\\n').filter(id => id.trim());
                if (elderIds.length < parseInt(data.elder)) {
                    alert('請輸入足夠的敬老票身分證！');
                    return;
                }
            }
            
            // 顯示狀態區塊
            document.getElementById('statusCard').classList.remove('hidden');
            document.getElementById('stopBtn').classList.remove('hidden');
            document.getElementById('submitBtn').disabled = true;
            document.getElementById('submitBtn').innerHTML = '<div class="spinner"></div><span>搜尋中...</span>';
            
            updateStatus('searching', '正在啟動訂票程式...');
            
            try {
                const response = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                if (result.success) {
                    addLog('✅ 訂票程式已啟動', 'success');
                    startPolling();
                } else {
                    updateStatus('error', '啟動失敗: ' + result.message);
                    addLog('❌ ' + result.message, 'error');
                    resetForm();
                }
            } catch (err) {
                updateStatus('error', '連線錯誤');
                addLog('❌ ' + err.message, 'error');
                resetForm();
            }
        });
        
        function startPolling() {
            pollingInterval = setInterval(async () => {
                try {
                    const response = await fetch('/api/status');
                    const data = await response.json();
                    
                    updateStatus(data.status, data.message);
                    
                    // 更新日誌
                    if (data.logs && data.logs.length > 0) {
                        const logContainer = document.getElementById('logContainer');
                        logContainer.innerHTML = data.logs.map(log => 
                            '<div class="log-entry ' + log.type + '">' + log.time + ' ' + log.message + '</div>'
                        ).join('');
                        logContainer.scrollTop = logContainer.scrollHeight;
                    }
                    
                    // 檢查是否完成
                    if (data.status === 'found' || data.status === 'error') {
                        stopPolling();
                        if (data.status === 'found' && data.result) {
                            showResult(data.result);
                        }
                        resetForm();
                    }
                } catch (err) {
                    console.error('Polling error:', err);
                }
            }, 2000);
        }
        
        function stopPolling() {
            if (pollingInterval) {
                clearInterval(pollingInterval);
                pollingInterval = null;
            }
        }
        
        async function stopSearch() {
            try {
                await fetch('/api/stop', { method: 'POST' });
                stopPolling();
                updateStatus('idle', '已停止搜尋');
                addLog('⏹️ 使用者停止搜尋', 'info');
                resetForm();
            } catch (err) {
                console.error('Stop error:', err);
            }
        }
        
        function updateStatus(status, message) {
            const dot = document.getElementById('statusDot');
            const text = document.getElementById('statusText');
            
            dot.className = 'status-dot ' + status;
            text.textContent = message;
        }
        
        function addLog(message, type) {
            type = type || '';
            const logContainer = document.getElementById('logContainer');
            const time = new Date().toLocaleTimeString('zh-TW');
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + type;
            entry.textContent = time + ' ' + message;
            logContainer.appendChild(entry);
            logContainer.scrollTop = logContainer.scrollHeight;
        }
        
        function showResult(result) {
            const resultCard = document.getElementById('resultCard');
            const resultContent = document.getElementById('resultContent');
            
            resultContent.innerHTML = 
                '<p><strong>訂票代號：</strong>' + (result.bookingId || 'N/A') + '</p>' +
                '<p><strong>車次：</strong>' + (result.trainNo || 'N/A') + '</p>' +
                '<p><strong>日期：</strong>' + (result.date || 'N/A') + '</p>' +
                '<p><strong>出發時間：</strong>' + (result.departureTime || 'N/A') + '</p>' +
                '<p><strong>座位：</strong>' + (result.seats || 'N/A') + '</p>';
            
            resultCard.classList.remove('hidden');
        }
        
        function resetForm() {
            document.getElementById('submitBtn').disabled = false;
            document.getElementById('submitBtn').innerHTML = '<span>🔍 開始搜尋訂票</span>';
            document.getElementById('stopBtn').classList.add('hidden');
        }
    </script>
</body>
</html>
''')

class TicketBotHandler(BaseHTTPRequestHandler):
    def get_session_token(self):
        """從 Cookie 中取得 session token"""
        cookie_header = self.headers.get('Cookie', '')
        cookies = SimpleCookie(cookie_header)
        if 'session' in cookies:
            return cookies['session'].value
        return None
    
    def is_authenticated(self):
        """檢查是否已登入"""
        token = self.get_session_token()
        return token and verify_session(token)
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        # 健康檢查不需要認證
        if parsed.path == "/health":
            self.send_json({"status": "ok", "service": "THSRC Ticket Bot Web"})
            return
        
        # 登入頁面
        if parsed.path == "/login":
            self.serve_login_page(show_error=False)
            return
        
        # 登出
        if parsed.path == "/logout":
            token = self.get_session_token()
            if token and token in active_sessions:
                del active_sessions[token]
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0")
            self.end_headers()
            return
        
        # 其他頁面需要認證
        if not self.is_authenticated():
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        
        if parsed.path == "/" or parsed.path == "/index.html":
            self.serve_html()
        elif parsed.path == "/api/status":
            self.serve_status()
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        
        # 處理登入
        if parsed.path == "/login":
            self.handle_login()
            return
        
        # 其他 API 需要認證
        if not self.is_authenticated():
            self.send_json({"success": False, "message": "未登入"})
            return
        
        if parsed.path == "/api/start":
            self.handle_start()
        elif parsed.path == "/api/stop":
            self.handle_stop()
        else:
            self.send_error(404)
    
    def serve_login_page(self, show_error=False, error_msg=None):
        """顯示登入頁面"""
        html = LOGIN_TEMPLATE.substitute(
            error_display="block" if show_error else "none",
            error_message=error_msg or "密碼錯誤，請重試"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())
    
    def handle_login(self):
        """處理登入請求"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()
        
        # 解析表單數據
        params = parse_qs(body)
        password = params.get('password', [''])[0]
        
        if not APP_PASSWORD:
            # 密碼未設定，拒絕登入
            self.serve_login_page(show_error=True, error_msg="伺服器未設定密碼，請聯繫管理員")
            return
        
        if password == APP_PASSWORD:
            # 密碼正確，創建 session
            token = create_session()
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"session={token}; Path=/; HttpOnly; Max-Age=86400")
            self.end_headers()
        else:
            # 密碼錯誤
            self.serve_login_page(show_error=True)
    
    def serve_html(self):
        # 生成車站選項
        station_options = "\n".join([
            f'<option value="{code}" {"selected" if code == "Taipei" else ""}>{name}</option>'
            for code, name in STATIONS
        ])
        station_options_dest = "\n".join([
            f'<option value="{code}">{name}</option>'
            for code, name in STATIONS
        ])
        
        # 生成時間選項
        time_options = "\n".join([
            f'<option value="{t}">{t}</option>'
            for t in TIMES
        ])
        
        # 使用 Template.substitute 替換佔位符
        html = HTML_TEMPLATE.substitute(
            station_options=station_options,
            station_options_dest=station_options_dest,
            time_options=time_options
        )
        
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())
    
    def serve_status(self):
        # 過濾掉不可序列化的欄位
        safe_state = {
            "status": app_state.get("status", "idle"),
            "message": app_state.get("message", ""),
            "logs": app_state.get("logs", []),
            "result": app_state.get("result")
        }
        self.send_json(safe_state)
    
    def handle_start(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()
        
        try:
            data = json.loads(body)
            
            # 更新 user_config.toml
            config_path = os.path.join(os.path.dirname(__file__), "user_config.toml")
            
            # 讀取現有配置
            with open(config_path, 'r', encoding='utf-8') as f:
                config = rtoml.load(f)
            
            # 更新配置
            if 'fields' not in config:
                config['fields'] = {}
            if 'THSRC' not in config['fields']:
                config['fields']['THSRC'] = {}
            
            thsrc = config['fields']['THSRC']
            thsrc['id'] = data.get('personalId', '')
            thsrc['start-station'] = data.get('startStation', 'Taipei')
            thsrc['dest-station'] = data.get('destStation', 'Taichung')
            thsrc['outbound-date'] = data.get('outboundDate', '')
            thsrc['outbound-time'] = data.get('outboundTime', '12:00')
            thsrc['preferred-seat'] = data.get('preferredSeat', '')
            thsrc['car-type'] = data.get('carType', 'normal')
            thsrc['train-no'] = data.get('trainNo', '')
            thsrc['email'] = data.get('email', '')
            thsrc['phone'] = data.get('phone', '')
            thsrc['tgo-id'] = data.get('tgoId', '')
            thsrc['tax-id'] = data.get('taxId', '')
            
            if 'ticket' not in thsrc:
                thsrc['ticket'] = {}
            
            thsrc['ticket']['adult'] = int(data.get('adult', 0))
            thsrc['ticket']['child'] = int(data.get('child', 0))
            thsrc['ticket']['teenager'] = int(data.get('teenager', 0))
            thsrc['ticket']['college'] = int(data.get('college', 0))
            thsrc['ticket']['disabled'] = int(data.get('disabled', 0))
            thsrc['ticket']['elder'] = int(data.get('elder', 0))
            
            # 處理愛心票和敬老票身分證
            if 'ids' not in thsrc:
                thsrc['ids'] = {}
            
            disabled_ids_raw = data.get('disabledIds', '')
            if disabled_ids_raw:
                thsrc['ids']['disabled'] = [id.strip() for id in disabled_ids_raw.split('\n') if id.strip()]
            else:
                thsrc['ids']['disabled'] = []
            
            elder_ids_raw = data.get('elderIds', '')
            if elder_ids_raw:
                thsrc['ids']['elder'] = [id.strip() for id in elder_ids_raw.split('\n') if id.strip()]
            else:
                thsrc['ids']['elder'] = []
            
            # 保存配置
            with open(config_path, 'w', encoding='utf-8') as f:
                rtoml.dump(config, f)
            
            # 取得車站中文名稱
            station_names = dict(STATIONS)
            start_name = station_names.get(data.get('startStation', ''), data.get('startStation', ''))
            dest_name = station_names.get(data.get('destStation', ''), data.get('destStation', ''))
            
            # 計算總票數
            total_tickets = (int(data.get('adult', 0)) + int(data.get('child', 0)) + 
                           int(data.get('teenager', 0)) + int(data.get('college', 0)) +
                           int(data.get('disabled', 0)) + int(data.get('elder', 0)))
            
            # 重置狀態並顯示搜尋參數
            app_state["status"] = "searching"
            app_state["message"] = "正在搜尋車票..."
            now = datetime.now().strftime("%H:%M:%S")
            app_state["logs"] = [
                {"time": now, "message": "🚀 訂票程式已啟動", "type": "success"},
                {"time": now, "message": f"📍 路線：{start_name} → {dest_name}", "type": "info"},
                {"time": now, "message": f"📅 日期：{data.get('outboundDate', '')} {data.get('outboundTime', '')} 後", "type": "info"},
                {"time": now, "message": f"🎫 票數：{total_tickets} 張", "type": "info"},
                {"time": now, "message": "⏳ 正在連線高鐵訂票系統...", "type": ""},
            ]
            app_state["result"] = None
            
            # 在背景執行訂票程式
            def run_bot():
                import subprocess
                try:
                    process = subprocess.Popen(
                        [sys.executable, "ticket_bot.py", "thsrc", "-a"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1
                    )
                    app_state["current_task"] = process
                    
                    for line in iter(process.stdout.readline, ''):
                        line = line.strip()
                        if line:
                            log_type = ""
                            message = line
                            
                            # 分類日誌類型並美化訊息
                            if "錯誤" in line or "Error" in line or "error" in line.lower():
                                log_type = "error"
                                if "驗證碼錯誤" in line:
                                    message = "❌ " + line
                            elif "成功" in line or "✓" in line or "Success" in line:
                                log_type = "success"
                                message = "✅ " + line
                            elif "Security code" in line:
                                log_type = "info"
                                message = "🔐 " + line
                            elif "驗證碼" in line:
                                log_type = "info"
                                message = "🔄 " + line
                            elif "HTTP" in line:
                                log_type = ""
                                message = "🌐 " + line
                            elif "Loading" in line or "載入" in line:
                                log_type = ""
                                message = "⏳ " + line
                            elif "查無" in line or "售完" in line:
                                log_type = "error"
                                message = "😢 " + line
                                app_state["message"] = line
                            elif "重試" in line:
                                log_type = "info"
                                message = "🔄 " + line
                                app_state["message"] = line
                            elif "車次" in line or "Train" in line:
                                log_type = "success"
                                message = "🚄 " + line
                            elif "座位" in line or "Seat" in line:
                                log_type = "success"
                                message = "💺 " + line
                            
                            app_state["logs"].append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "message": message[:120],
                                "type": log_type
                            })
                            
                            # 只保留最近 100 條日誌
                            if len(app_state["logs"]) > 100:
                                app_state["logs"] = app_state["logs"][-100:]
                            
                            # 更新狀態訊息
                            if "訂票成功" in line or "Booking success" in line:
                                app_state["status"] = "found"
                                app_state["message"] = "🎉 訂票成功！程式已自動停止。"
                            elif "Reservation No" in line or "訂位代號" in line:
                                app_state["status"] = "found"
                                # 提取訂位代號
                                if ":" in line:
                                    booking_id = line.split(":")[-1].strip()
                                    app_state["result"] = {"bookingId": booking_id}
                                    app_state["message"] = f"🎉 訂票成功！訂位代號：{booking_id}"
                            elif "確認訂票" in line:
                                app_state["message"] = "正在確認訂票..."
                            elif "Auto pick train" in line or "自動選擇" in line:
                                app_state["message"] = "已選擇車次，確認中..."
                    
                    process.wait()
                    
                    # 程式結束後的狀態處理
                    if app_state["status"] == "found":
                        app_state["logs"].append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "message": "🎉 訂票成功！程式已自動停止。",
                            "type": "success"
                        })
                    elif app_state["status"] == "searching":
                        app_state["status"] = "idle"
                        app_state["message"] = "程式已結束"
                        app_state["logs"].append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "message": "⏹️ 搜尋程式已結束",
                            "type": ""
                        })
                        
                except Exception as e:
                    app_state["status"] = "error"
                    app_state["message"] = str(e)
                    app_state["logs"].append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "message": f"❌ 錯誤: {e}",
                        "type": "error"
                    })
            
            thread = threading.Thread(target=run_bot, daemon=True)
            thread.start()
            
            self.send_json({"success": True, "message": "已開始搜尋"})
            
        except Exception as e:
            self.send_json({"success": False, "message": str(e)})
    
    def handle_stop(self):
        if app_state.get("current_task"):
            try:
                app_state["current_task"].terminate()
            except:
                pass
        
        app_state["status"] = "idle"
        app_state["message"] = "已停止"
        app_state["current_task"] = None
        
        self.send_json({"success": True})
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    
    def log_message(self, format, *args):
        pass  # 禁用預設日誌


def main():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), TicketBotHandler)
    
    print(f"""
╔══════════════════════════════════════════════════════════╗
║            🚄 高鐵訂票助手 - Web 介面                      ║
╠══════════════════════════════════════════════════════════╣
║  🌐 本地訪問: http://localhost:{port:<5}                     ║
║  📋 健康檢查: http://localhost:{port}/health               ║
╚══════════════════════════════════════════════════════════╝
""")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹️ 停止服務...")
        server.shutdown()


if __name__ == "__main__":
    main()
