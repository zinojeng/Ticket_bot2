"""
高鐵退票服務模組
用於查詢訂位紀錄並執行退票操作
"""

from __future__ import annotations
import base64
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from bs4 import BeautifulSoup
import httpx
import rtoml


class THSRCCancel:
    """
    高鐵退票服務類
    """

    def __init__(self, config_path: str = 'cancel_config.toml'):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # 設定 console handler
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
            self.logger.addHandler(handler)
        
        # 載入設定
        self.config_path = config_path
        self.load_config()
        
        # 載入 THSRC 設定
        thsrc_config_path = os.path.join(os.path.dirname(__file__), '..', 'configs', 'THSRC.toml')
        with open(thsrc_config_path, 'r', encoding='utf-8') as f:
            self.thsrc_config = rtoml.load(f)
        
        # 建立 HTTP Session
        self.session = httpx.Client(
            timeout=60,
            follow_redirects=True,
            headers={
                'User-Agent': self.settings.get('headers', {}).get(
                    'User-Agent',
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'
                )
            }
        )

    def load_config(self):
        """載入設定檔"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = rtoml.load(f)
            
            self.cancellations = []
            self.settings = config.get('settings', {})
            self.headers_config = config.get('headers', {})
            
            # 方式一：批次退票（一個身分證 + 多個訂位代號）
            batch = config.get('batch', {})
            if batch.get('enabled', False) and batch.get('id') and batch.get('pnr_list'):
                batch_id = batch['id'].strip()
                pnr_list_str = batch['pnr_list'].strip()
                
                # 解析訂位代號清單（支援逗號、換行、空格分隔）
                pnr_list = []
                for pnr in re.split(r'[,\n\s]+', pnr_list_str):
                    pnr = pnr.strip()
                    if pnr:
                        pnr_list.append(pnr)
                
                for pnr in pnr_list:
                    self.cancellations.append({
                        'id': batch_id,
                        'pnr': pnr,
                        'enabled': True
                    })
                
                self.logger.info(f"📋 批次模式：{len(pnr_list)} 筆待退票（身分證: {batch_id[:4]}****{batch_id[-2:]}）")
            
            # 方式二：個別退票（舊格式）
            individual = [c for c in config.get('cancellations', []) if c.get('enabled', False) and c.get('id') and c.get('pnr')]
            if individual:
                self.cancellations.extend(individual)
                self.logger.info(f"📋 個別模式：{len(individual)} 筆待退票")
            
            if not self.cancellations:
                self.logger.info("📋 沒有待退票資料")
            
        except FileNotFoundError:
            self.logger.error(f"❌ 找不到設定檔: {self.config_path}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"❌ 載入設定檔失敗: {e}")
            sys.exit(1)

    def get_security_code(self, captcha_url: str) -> str | None:
        """OCR 驗證碼 - 使用 holey.cc + Gemini 3 雙重比對"""
        try:
            res = self.session.get(captcha_url, timeout=60)
            if res.status_code != 200:
                self.logger.error(f"取得驗證碼圖片失敗: {res.status_code}")
                return None
            
            base64_str = base64.b64encode(res.content).decode("utf-8")
            holey_result = None
            gemini_result = None
            
            # Step 1: holey.cc OCR
            try:
                base64_url_safe = base64_str.replace('+', '-').replace('/', '_').replace('=', '')
                data = {'base64_str': base64_url_safe}
                with httpx.Client(timeout=30) as ocr_client:
                    ocr_res = ocr_client.post(self.thsrc_config['api']['captcha_ocr'], json=data)
                if ocr_res.status_code == 200:
                    holey_result = ocr_res.json().get('data')
                    self.logger.info(f"+ holey.cc 識別: {holey_result}")
            except Exception as e:
                self.logger.warning(f"holey.cc OCR 失敗: {e}")
            
            # Step 2: Gemini 3 識別
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if gemini_api_key:
                self.logger.info("✨ 使用 Gemini 3 Flash 識別中...")
                gemini_result = self._ocr_with_gemini(base64_str, gemini_api_key)
                if gemini_result:
                    self.logger.info(f"+ Gemini 3 識別: {gemini_result}")
            
            # Step 3: 比對結果
            if holey_result and gemini_result:
                if holey_result.upper() == gemini_result.upper():
                    self.logger.info("🎯 兩者一致，信心度高！")
                    return gemini_result
                else:
                    self.logger.warning(f"⚡ 結果不一致! (holey.cc: {holey_result} vs Gemini: {gemini_result})")
                    self.logger.info("🤔 啟動仲裁判斷...")
                    final_result = self._ocr_arbitrate_with_gemini(
                        base64_str, holey_result, gemini_result, gemini_api_key
                    )
                    if final_result:
                        self.logger.info(f"⚖️ 仲裁結果: {final_result}")
                        return final_result
                    else:
                        self.logger.info(f"🔧 仲裁失敗，採用 holey.cc 結果: {holey_result}")
                        return holey_result
            
            # 備援方案
            final_code = gemini_result or holey_result
            if final_code:
                self.logger.info(f"+ 最終驗證碼: {final_code}")
                return final_code
            
            return None
            
        except Exception as e:
            self.logger.warning(f"⚠️ 取得驗證碼失敗: {e}")
            return None

    def _ocr_with_gemini(self, base64_image: str, api_key: str) -> str | None:
        """使用 Gemini 3 API 識別驗證碼"""
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
        
        prompt = "Read the 4 characters in this CAPTCHA image. Output EXACTLY 4 characters (A-Z, 0-9) ONLY. No spaces, no explanation."

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": base64_image}}
                ]
            }],
            "generationConfig": {
                "maxOutputTokens": 256,
                "temperature": 0.1,
                "topP": 0.1
            }
        }

        try:
            with httpx.Client(timeout=30) as client:
                res = client.post(api_url, json=payload)
                if res.status_code == 200:
                    result = res.json()
                    if 'candidates' in result and result['candidates']:
                        content = result['candidates'][0].get('content', {})
                        parts = content.get('parts', [])
                        if parts:
                            raw_text = parts[0].get('text', '').strip()
                            code = ''.join(c for c in raw_text if c.isascii() and c.isalnum()).upper()
                            if len(code) >= 4:
                                return code[:4]
                else:
                    self.logger.warning(f"Gemini API 錯誤: {res.status_code}")
        except Exception as e:
            self.logger.warning(f"Gemini 呼叫失敗: {e}")
        
        return None

    def _ocr_arbitrate_with_gemini(self, base64_image: str, result_a: str, result_b: str, api_key: str) -> str | None:
        """讓 Gemini 3 仲裁兩個不一致的識別結果"""
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
        
        prompt = f"""This CAPTCHA image has been recognized by two different OCR systems with conflicting results:
- System A (specialized OCR): {result_a}
- System B (AI vision): {result_b}

Look at the image carefully and determine which result is CORRECT.
Characters that often get confused: 0/O, 1/I, 5/S, 8/B, 2/Z, 6/G, 9/P

Output ONLY the correct 4-character code. No explanation."""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": base64_image}}
                ]
            }],
            "generationConfig": {
                "maxOutputTokens": 256,
                "temperature": 0.1,
                "topP": 0.1
            }
        }

        try:
            with httpx.Client(timeout=30) as client:
                res = client.post(api_url, json=payload)
                if res.status_code == 200:
                    result = res.json()
                    if 'candidates' in result and result['candidates']:
                        content = result['candidates'][0].get('content', {})
                        parts = content.get('parts', [])
                        if parts:
                            raw_text = parts[0].get('text', '').strip()
                            code = ''.join(c for c in raw_text if c.isascii() and c.isalnum()).upper()
                            if len(code) >= 4:
                                return code[:4]
        except Exception as e:
            self.logger.warning(f"仲裁失敗: {e}")
        
        return None

    def get_history_page(self, max_retries: int = 3) -> tuple[str, str]:
        """取得訂位紀錄查詢頁面的 Session 和驗證碼 URL"""
        self.logger.info("\n📡 連線高鐵訂位紀錄查詢頁面...")
        
        # 清除舊 cookies
        self.session.cookies.clear()
        self.session.cookies.set('cookieAccepted', 'true', domain='irs.thsrc.com.tw')
        self.session.cookies.set('isShowCookiePolicy', 'N', domain='irs.thsrc.com.tw')
        
        history_url = self.thsrc_config['page']['history']
        
        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info(f"嘗試連線... ({attempt}/{max_retries})")
                res = self.session.get(history_url, timeout=60)
                
                if res.status_code == 200:
                    page = BeautifulSoup(res.text, 'html.parser')
                    
                    # 找驗證碼圖片
                    # 退票頁面使用 img-captcha 類別（訂票頁面是 captcha-img）
                    captcha_img = page.find('img', class_='img-captcha')
                    if not captcha_img:
                        self.logger.warning("找不到驗證碼圖片，重試中...")
                        time.sleep(2)
                        continue
                    
                    captcha_url = 'https://irs.thsrc.com.tw' + captcha_img['src']
                    jsessionid = res.cookies.get('JSESSIONID') or self.session.cookies.get('JSESSIONID')
                    
                    self.logger.info(f"✅ Session ID: {jsessionid[:20]}..." if jsessionid else "⚠️ No session ID")
                    return jsessionid, captcha_url
                else:
                    self.logger.warning(f"HTTP {res.status_code}，重試中...")
                    time.sleep(2)
                    
            except Exception as e:
                self.logger.warning(f"連線失敗: {e}")
                if attempt < max_retries:
                    time.sleep(attempt * 3)
        
        self.logger.error("❌ 無法連線高鐵網站")
        sys.exit(1)

    def login_history(self, jsessionid: str, roc_id: str, pnr: str, security_code: str) -> httpx.Response:
        """登入訂位紀錄查詢頁面"""
        headers = {
            'Referer': self.thsrc_config['page']['history'],
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.headers_config.get('User-Agent', ''),
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        # 根據高鐵網站 HTML 結構的正確欄位名稱
        data = {
            'typesofid': '0',  # 0: 身分證, 1: 護照
            'rocId': roc_id,
            'orderId': pnr,
            'divCaptcha:securityCode': security_code,
            'SubmitButton': '查詢',
        }
        
        login_url = f'https://irs.thsrc.com.tw/IMINT/;jsessionid={jsessionid}?wicket:interface=:0:HistoryForm::IFormSubmitListener'
        
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info(f"📤 送出查詢請求... (嘗試 {attempt}/{max_retries})")
                res = self.session.post(login_url, headers=headers, data=data, timeout=180)
                return res
            except Exception as e:
                self.logger.warning(f"查詢超時: {e}")
                if attempt < max_retries:
                    self.logger.info(f"⏳ 等待 {attempt * 5} 秒後重試...")
                    time.sleep(attempt * 5)
                else:
                    self.logger.error(f"❌ 登入失敗: {e}")
                    return None
        return None

    def print_error_message(self, html_page: BeautifulSoup) -> list:
        """印出錯誤訊息"""
        error_messages = []
        for error_text in html_page.find_all(class_='feedbackPanelERROR'):
            error_message = error_text.text.strip()
            self.logger.error(f'Error: {error_message}')
            error_messages.append(error_message)
        return error_messages

    def parse_booking_info(self, html_page: BeautifulSoup) -> dict | None:
        """解析訂位資訊"""
        try:
            # 嘗試找到訂位資訊區塊
            info = {}
            
            # 訂位代號
            pnr_elem = html_page.find('span', class_='pnr-code') or html_page.find('p', class_='pnr-code')
            if pnr_elem:
                info['pnr'] = pnr_elem.get_text(strip=True)
            
            # 付款狀態
            payment_elem = html_page.find('p', class_='payment-status')
            if payment_elem:
                info['payment_status'] = payment_elem.get_text(strip=True)
            
            # 車票資訊
            card = html_page.find('div', class_='ticket-card')
            if card:
                date_elem = card.find('span', class_='date')
                if date_elem:
                    info['date'] = date_elem.get_text(strip=True)
                
                train_elem = card.find('span', id=lambda x: x and x.startswith('setTrainCode'))
                if train_elem:
                    info['train_no'] = train_elem.get_text(strip=True)
                
                departure_time = card.find('p', class_='departure-time')
                departure_stn = card.find('p', class_='departure-stn')
                arrival_time = card.find('p', class_='arrival-time')
                arrival_stn = card.find('p', class_='arrival-stn')
                
                if departure_time and departure_stn and arrival_time and arrival_stn:
                    info['departure_time'] = departure_time.get_text(strip=True)
                    info['departure_station'] = departure_stn.get_text(strip=True)
                    info['arrival_time'] = arrival_time.get_text(strip=True)
                    info['arrival_station'] = arrival_stn.get_text(strip=True)
            
            # 座位資訊
            seats = html_page.find_all('div', class_='seat-label')
            if seats:
                info['seats'] = [s.get_text(strip=True) for s in seats]
            
            return info if info else None
            
        except Exception as e:
            self.logger.warning(f"解析訂位資訊失敗: {e}")
            return None

    def cancel_booking(self, html_page: BeautifulSoup) -> httpx.Response | None:
        """執行退票操作"""
        try:
            # 找到取消訂位的表單和按鈕
            cancel_form = html_page.find('form', id=lambda x: x and 'Cancel' in str(x))
            cancel_btn = html_page.find('input', {'value': '取消訂位'}) or \
                         html_page.find('button', string=re.compile('取消')) or \
                         html_page.find('a', string=re.compile('取消訂位'))
            
            if not cancel_btn:
                # 嘗試找其他可能的取消按鈕
                cancel_btn = html_page.find(lambda tag: tag.name in ['input', 'button', 'a'] and 
                                           '取消' in tag.get_text())
            
            if cancel_btn:
                # 根據按鈕類型決定如何提交
                if cancel_btn.name == 'a':
                    cancel_url = cancel_btn.get('href')
                    if cancel_url and not cancel_url.startswith('http'):
                        cancel_url = 'https://irs.thsrc.com.tw' + cancel_url
                    res = self.session.get(cancel_url, timeout=60)
                else:
                    # 表單提交
                    form = cancel_btn.find_parent('form')
                    if form:
                        action = form.get('action', '')
                        if not action.startswith('http'):
                            action = 'https://irs.thsrc.com.tw' + action
                        
                        # 收集表單資料
                        data = {}
                        for inp in form.find_all('input'):
                            name = inp.get('name')
                            value = inp.get('value', '')
                            if name:
                                data[name] = value
                        
                        res = self.session.post(action, data=data, timeout=60)
                    else:
                        self.logger.warning("找不到取消表單")
                        return None
                
                return res
            else:
                self.logger.warning("⚠️ 找不到取消訂位按鈕（可能已取票或不可取消）")
                return None
                
        except Exception as e:
            self.logger.error(f"執行退票失敗: {e}")
            return None

    def process_single_cancellation(self, roc_id: str, pnr: str) -> bool:
        """處理單筆退票"""
        self.logger.info(f"\n{'='*50}")
        self.logger.info(f"🎫 處理退票: {pnr}")
        self.logger.info(f"   身分證: {roc_id[:4]}****{roc_id[-2:]}")
        self.logger.info(f"{'='*50}")
        
        max_captcha_retries = self.settings.get('max_captcha_retries', 10)
        
        for attempt in range(1, max_captcha_retries + 1):
            # 取得頁面和驗證碼
            jsessionid, captcha_url = self.get_history_page()
            
            # 識別驗證碼
            security_code = self.get_security_code(captcha_url)
            if not security_code:
                self.logger.warning(f"⚠️ 驗證碼識別失敗，重試中... ({attempt}/{max_captcha_retries})")
                time.sleep(2)
                continue
            
            # 登入查詢
            login_result = self.login_history(jsessionid, roc_id, pnr, security_code)
            if not login_result or login_result.status_code != 200:
                self.logger.warning(f"⚠️ 登入失敗，重試中... ({attempt}/{max_captcha_retries})")
                time.sleep(2)
                continue
            
            page = BeautifulSoup(login_result.text, 'html.parser')
            
            # 檢查錯誤訊息
            errors = self.print_error_message(page)
            if errors:
                if any('驗證碼' in e or '檢測碼' in e for e in errors):
                    self.logger.info(f"🔄 驗證碼錯誤，重試中... ({attempt}/{max_captcha_retries})")
                    time.sleep(2)
                    continue
                elif any('查無' in e or '不存在' in e for e in errors):
                    self.logger.error(f"❌ 訂位代號 {pnr} 不存在或已取消")
                    return False
                else:
                    self.logger.error(f"❌ 登入失敗: {errors}")
                    return False
            
            # 成功登入，解析訂位資訊
            booking_info = self.parse_booking_info(page)
            if booking_info:
                self.logger.info("\n📋 訂位資訊:")
                self.logger.info(f"   訂位代號: {booking_info.get('pnr', pnr)}")
                self.logger.info(f"   付款狀態: {booking_info.get('payment_status', '未知')}")
                self.logger.info(f"   乘車日期: {booking_info.get('date', '未知')}")
                self.logger.info(f"   車次: {booking_info.get('train_no', '未知')}")
                self.logger.info(f"   行程: {booking_info.get('departure_station', '')} {booking_info.get('departure_time', '')} → {booking_info.get('arrival_station', '')} {booking_info.get('arrival_time', '')}")
                if booking_info.get('seats'):
                    self.logger.info(f"   座位: {', '.join(booking_info['seats'])}")
            
            # 確認是否要退票
            confirm = self.settings.get('confirm_before_cancel', True)
            if confirm:
                user_input = input("\n❓ 確定要取消此訂位嗎？(y/N): ").strip().lower()
                if user_input != 'y':
                    self.logger.info("⏭️ 跳過此筆退票")
                    return False
            
            # 執行退票
            self.logger.info("🔄 執行退票中...")
            cancel_result = self.cancel_booking(page)
            
            if cancel_result:
                cancel_page = BeautifulSoup(cancel_result.text, 'html.parser')
                cancel_errors = self.print_error_message(cancel_page)
                
                if cancel_errors:
                    self.logger.error(f"❌ 退票失敗: {cancel_errors}")
                    return False
                
                # 檢查是否成功
                if '取消' in cancel_result.text and ('成功' in cancel_result.text or '已取消' in cancel_result.text):
                    self.logger.info(f"✅ 訂位 {pnr} 已成功取消！")
                    return True
                else:
                    self.logger.info(f"⚠️ 退票結果不明確，請手動確認")
                    return True
            else:
                self.logger.warning("⚠️ 無法執行退票操作")
                return False
        
        self.logger.error(f"❌ 驗證碼重試 {max_captcha_retries} 次仍失敗")
        return False

    def run(self):
        """執行退票流程"""
        if not self.cancellations:
            self.logger.error("❌ 沒有啟用的退票資料，請檢查 cancel_config.toml")
            return
        
        self.logger.info("\n" + "="*60)
        self.logger.info("🚄 高鐵退票機器人啟動")
        self.logger.info("="*60)
        
        mode = self.settings.get('mode', 'all')
        delay = self.settings.get('delay_between', 5)
        
        success_count = 0
        fail_count = 0
        
        for i, cancel_item in enumerate(self.cancellations):
            roc_id = cancel_item.get('id', '').strip()
            pnr = cancel_item.get('pnr', '').strip()
            
            if not roc_id or not pnr:
                self.logger.warning(f"⚠️ 第 {i+1} 筆資料不完整，跳過")
                continue
            
            result = self.process_single_cancellation(roc_id, pnr)
            
            if result:
                success_count += 1
            else:
                fail_count += 1
            
            # 單筆模式只處理第一筆
            if mode == 'single':
                break
            
            # 多筆之間的延遲
            if i < len(self.cancellations) - 1:
                self.logger.info(f"\n⏳ 等待 {delay} 秒後處理下一筆...")
                time.sleep(delay)
        
        # 總結
        self.logger.info("\n" + "="*60)
        self.logger.info("📊 退票結果總結")
        self.logger.info("="*60)
        self.logger.info(f"   ✅ 成功: {success_count} 筆")
        self.logger.info(f"   ❌ 失敗: {fail_count} 筆")
        self.logger.info("="*60)
        
        return success_count > 0


def main():
    """主程式進入點"""
    import argparse
    
    parser = argparse.ArgumentParser(description='高鐵退票機器人')
    parser.add_argument('-c', '--config', default='cancel_config.toml', help='設定檔路徑')
    parser.add_argument('-y', '--yes', action='store_true', help='跳過確認，直接執行退票')
    parser.add_argument('--id', help='直接指定身分證字號')
    parser.add_argument('--pnr', help='直接指定訂位代號')
    
    args = parser.parse_args()
    
    # 如果直接指定參數，覆蓋設定
    if args.id and args.pnr:
        cancel_service = THSRCCancel(args.config)
        cancel_service.cancellations = [{'id': args.id, 'pnr': args.pnr, 'enabled': True}]
        if args.yes:
            cancel_service.settings['confirm_before_cancel'] = False
        cancel_service.run()
    else:
        cancel_service = THSRCCancel(args.config)
        if args.yes:
            cancel_service.settings['confirm_before_cancel'] = False
        cancel_service.run()


if __name__ == '__main__':
    main()
