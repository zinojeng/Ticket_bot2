"""
This module is to buy tickets form THSRC
"""

from __future__ import annotations
import base64
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
import pyperclip
from services.base_service import BaseService
from configs.config import user_agent
from utils.validate import check_roc_id, check_tax_id


class THSRC(BaseService):
    """
    Service code for THSRC (https://irs.thsrc.com.tw/IMINT/).
    """

    def __init__(self, args):
        super().__init__(args)
        # self._ = get_locale(__name__, self.locale)
        self.start_station = self.select_station(
            'start', default_value=self.config['station']['Taipei'])
        self.dest_station = self.select_station(
            'dest', default_value=self.config['station']['Zuouing'])
        self.outbound_date = self.select_date()
        self.outbound_time = self.select_time(outbound_date=self.outbound_date)
        self.ticket_num = self.select_ticket_num()
        self.car_type = self.select_car_type()
        self.preferred_seat = self.select_preferred_seat()

    def print_error_message(self, html_page):
        """Print error messsage"""
        page = BeautifulSoup(html_page, 'html.parser')
        error_messages = []
        for error_text in page.find_all(class_='feedbackPanelERROR'):
            error_message = error_text.text.strip()
            self.logger.error('Error: %s', error_message)
            error_messages.append(error_message)
            # 只有在「選擇的日期超過目前開放預訂之日期」時才退出（因為這表示日期設定錯誤）
            if '選擇的日期超過目前開放預訂之日期' in error_message:
                self.logger.error("❌ 日期超過可預訂範圍，請修改 user_config.toml 中的 outbound-date")
                sys.exit(1)
        return error_messages

    def get_station(self, station_name):
        """Get station value"""

        station_name = station_name.strip().lower().capitalize()

        station_translation = {
            '南港': 'Nangang',
            '台北': 'Taipei',
            '板橋': 'Banqiao',
            '桃園': 'Taoyuan',
            '新竹': 'Hsinchu',
            '苗栗': 'Miaoli',
            '台中': 'Taichung',
            '彰化': 'Changhua',
            '雲林': 'Yunlin',
            '嘉義': 'Chiayi',
            '台南': 'Tainan',
            '左營': 'Zuouing',
        }

        if not re.search(r'[a-zA-Z]+', station_name):
            station_name = station_translation.get(
                station_name.replace('臺', '台'))

        if self.config['station'].get(station_name):
            return self.config['station'].get(station_name)

        self.logger.error('Station not found: %s', station_name)
        sys.exit(1)

    def select_station(self, tavel_type: str, default_value: int) -> int:
        """Select start/dest station"""

        if not self.fields[f'{tavel_type}-station']:
            self.logger.info(f"\nSelect {tavel_type} station:")
            for station_name in self.config['station']:
                self.logger.info(
                    '%s: %s', self.config['station'][station_name], station_name)

            input_value = input(
                f"{tavel_type} station (defualt: {default_value}): ").strip()
            return default_value if input_value == '' or not input_value.isdigit() else int(input_value)
        else:
            return self.get_station(self.fields[f'{tavel_type}-station'])

    def select_date(self) -> str:
        """Select date"""

        today = str(date.today())
        # last_avail_date = today + timedelta(days=DAYS_BEFORE_BOOKING_AVAILABLE)
        if not self.fields['outbound-date']:
            input_value = input(f"\nSelect outbound date (defualt: {today}): ")
            return input_value.replace('-', '/') or today.replace('-', '/')
        else:
            return self.fields['outbound-date'].replace('-', '/')

    def select_time(self, outbound_date: str, default_value: int = 10) -> str:
        """Select time"""

        if self.fields['inbound-time'] and datetime.strptime(self.fields['inbound-time'], '%H:%M').time() <= datetime.strptime(self.fields['outbound-time'], '%H:%M').time():
            self.logger.error(
                "\nInbound time must be later than outbound time!")
            sys.exit(1)

        if not self.fields['outbound-time']:
            self.logger.info('\nSelect outbound time:')
            for idx, t_str in enumerate(self.config['available-timetable'], start=1):
                t_int = int(t_str[:-1])
                if t_str[-1] == "A" and (t_int // 100) == 12:
                    t_int = f"{(t_int % 1200):04d}"  # type: ignore
                elif t_int != 1230 and t_str[-1] == "P":
                    t_int += 1200

                t_str = str(t_int).zfill(4)
                if t_str == '0001':
                    t_str = '0000'

                date_time_str = f'{outbound_date} {t_str[:-2]}:{t_str[-2:]}'

                if datetime.now().timestamp() <= datetime.strptime(
                        date_time_str, "%Y/%m/%d %H:%M").timestamp():
                    self.logger.info(f'{idx}. {date_time_str}')
                else:
                    if idx == default_value:
                        default_value += 1

            index = input(f'outbound time (default: {default_value}): ')
            if index == '' or not index.isdigit():
                index = default_value
            else:
                index = int(index)
                if index < 1 or index > len(self.config['available-timetable']):
                    index = default_value
            return self.config['available-timetable'][index-1]
        else:
            t_int = int(self.fields['outbound-time'].replace(':', ''))
            if t_int % 100 >= 30:
                t_int = int(t_int/100)*100 + 30
            else:
                t_int = int(t_int/100)*100

            if t_int == 0:
                t_str = '1201A'
            elif t_int == 30:
                t_str = '1230A'
            elif t_int == 1200:
                t_str = '1200N'
            elif t_int == 1230:
                t_str = '1230P'
            elif t_int < 1200:
                t_str = f'{t_int}A'
            else:
                t_str = f'{t_int-1200}P'

            return t_str

    def select_ticket_num(self, default_value: int = 1) -> list:
        """Select ticket number"""

        total = 0
        tickets = list()
        # 票種順序: adult, child, disabled, elder, college, teenager
        ticket_types = ['adult', 'child', 'disabled', 'elder', 'college', 'teenager']
        
        for ticket in ticket_types:
            if ticket in self.fields['ticket']:
                ticket_num = int(self.fields['ticket'][ticket])
                total += ticket_num
                if ticket_num >= 0:
                    tickets.append(
                        f"{ticket_num}{self.config['ticket-type'][ticket]}")
                else:
                    tickets.append('')
            else:
                # 該票種未設定，預設為 0
                tickets.append(f"0{self.config['ticket-type'].get(ticket, 'T')}")

        if total > self.config['max-ticket-num']:
            self.logger.error(
                "\nYou can only order a maximum of %s tickets!", self.config['max-ticket-num'])
            sys.exit()
        elif total == 0:
            tickets = [
                f"{default_value}{self.config['ticket-type']['adult']}", '0H', '0W', '0E', '0P', '0T']
        return tickets

    def select_car_type(self, default_value: int = 0) -> str:
        """Select class"""

        car_type = self.config['car-type'].get(self.fields['car-type'])

        if not car_type:
            car_type = default_value

        return car_type

    def select_preferred_seat(self, default_value: int = 0) -> str:
        """Select preferred seat"""

        preferred_seat = self.config['preferred-seat'].get(
            self.fields['preferred-seat'])

        if not preferred_seat:
            preferred_seat = default_value

        return preferred_seat

    def get_security_code(self, captcha_url):
        """OCR captcha - holey.cc 與 Gemini 3 雙重比對方案"""
        import httpx
        
        try:
            res = self.session.get(captcha_url, timeout=60)
            if res.status_code != 200:
                self.logger.error(res.text)
                return None
            
            base64_str = base64.b64encode(res.content).decode("utf-8")
            holey_result = None
            gemini_result = None
            
            # Step 1: 使用 holey.cc OCR（專門為高鐵驗證碼訓練）
            try:
                base64_url_safe = base64_str.replace('+', '-').replace('/', '_').replace('=', '')
                data = {'base64_str': base64_url_safe}
                with httpx.Client(timeout=30) as ocr_client:
                    ocr_res = ocr_client.post(
                        self.config['api']['captcha_ocr'], json=data)
                if ocr_res.status_code == 200:
                    holey_result = ocr_res.json().get('data')
                    self.logger.info("+ holey.cc 識別: %s", holey_result)
            except Exception as e:
                self.logger.warning(f"holey.cc OCR 失敗: {e}")
            
            # Step 2: 使用 Gemini 3 識別（如果設定了 GEMINI_API_KEY）
            gemini_api_key = os.getenv('GEMINI_API_KEY')
            if gemini_api_key:
                # Debug: 顯示 API key 前幾個字元確認是否正確讀取
                self.logger.info(f"🔑 GEMINI_API_KEY: {gemini_api_key[:10]}...{gemini_api_key[-4:]}")
                self.logger.info("✨ 使用 Gemini 3 Flash 識別中...")
                gemini_result = self._ocr_with_gemini("gemini-3-flash-preview", base64_str, gemini_api_key)
                if gemini_result:
                    self.logger.info(f"+ Gemini 3 識別: {gemini_result}")
            
            # Step 3: 比對結果並輸出最終答案
            if holey_result and gemini_result:
                if holey_result.upper() == gemini_result.upper():
                    self.logger.info("🎯 兩者一致，信心度高！")
                    return gemini_result
                else:
                    self.logger.warning(f"⚡ 結果不一致! (holey.cc: {holey_result} vs Gemini: {gemini_result})")
                    # 仲裁判斷：讓 Gemini 3 再次分析原圖和兩個結果，做最終決定
                    self.logger.info("🤔 啟動仲裁判斷...")
                    final_result = self._ocr_arbitrate_with_gemini(
                        base64_str, holey_result, gemini_result, gemini_api_key
                    )
                    if final_result:
                        self.logger.info(f"⚖️ 仲裁結果: {final_result}")
                        return final_result
                    else:
                        # 仲裁失敗時，優先採用 holey.cc（專門為高鐵驗證碼訓練）
                        self.logger.info(f"🔧 仲裁失敗，採用 holey.cc 結果: {holey_result}")
                        return holey_result
            
            # 備原方案：如果只有其中一個成功
            final_code = gemini_result or holey_result
            if final_code:
                self.logger.info("+ 最終驗證碼: %s", final_code)
                return final_code
            
            return None
                
        except (httpx.TimeoutException, httpx.RequestError) as e:
            self.logger.warning(f"⚠️ 網路超時，重試中... ({e})")
            return None

    def _ocr_with_gemini(self, model, base64_image, api_key):
        """Use Gemini 3 API for independent captcha recognition"""
        import httpx
        
        # 嘗試使用 gemini-2.0-flash (目前最穩定支援 Vision 的版本) 
        # 或保留傳入的 model 名稱
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        prompt = "Read the 4 characters in this CAPTCHA image. Output EXACTLY 4 characters (A-Z, 0-9) ONLY. No spaces, no explanation."

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64_image
                        }
                    }
                ]
            }],
            "generationConfig": {
                "maxOutputTokens": 256,  # Gemini 3 是思考模型，需要更多 token
                "temperature": 0.1,
                "topP": 0.1
            }
        }

        try:
            with httpx.Client(timeout=30) as client:
                res = client.post(api_url, json=payload)
                if res.status_code == 200:
                    result = res.json()
                    # Debug: 顯示 API 回應
                    self.logger.debug(f"Gemini 回應: {result}")
                    if 'candidates' in result and result['candidates']:
                        content = result['candidates'][0].get('content', {})
                        parts = content.get('parts', [])
                        if parts:
                            raw_text = parts[0].get('text', '').strip()
                            self.logger.debug(f"Gemini 原始輸出: '{raw_text}'")
                            code = ''.join(c for c in raw_text if c.isascii() and c.isalnum()).upper()
                            if len(code) >= 4:
                                return code[:4]
                            else:
                                self.logger.warning(f"⚠️ Gemini 輸出不足4字元: '{raw_text}' → '{code}'")
                    else:
                        self.logger.warning(f"⚠️ Gemini 無 candidates: {result}")
                else:
                    self.logger.warning(f"Gemini API 錯誤: {res.status_code}")
                    self.logger.warning(f"回應內容: {res.text}")
        except Exception as e:
            self.logger.warning(f"Gemini 呼叫失敗: {e}")
        
        return None
    
    def _ocr_arbitrate_with_gemini(self, base64_image, result_a, result_b, api_key):
        """讓 Gemini 3 仲裁兩個不一致的識別結果"""
        import httpx
        
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
        
        prompt = f"""This CAPTCHA image has been recognized by two different OCR systems with conflicting results:
- System A (specialized OCR): {result_a}
- System B (AI vision): {result_b}

Look at the image carefully and determine which result is CORRECT, or if both are wrong, provide the correct 4-character code.

IMPORTANT:
- The CAPTCHA contains exactly 4 characters (A-Z, 0-9)
- Characters that often get confused: 0/O, 1/I, 5/S, 8/B, 2/Z, 6/G, 9/P, D/0, H/N, W/M
- Focus on subtle differences between the two results

Output ONLY the correct 4-character code. No explanation."""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64_image
                        }
                    }
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
                    self.logger.warning(f"仲裁 API 錯誤: {res.status_code}")
        except Exception as e:
            self.logger.warning(f"仲裁失敗: {e}")
        
        return None
    
    def get_jsessionid(self, max_retries=3):
        """Get jsessionid and security code from captcha url"""
        self.logger.info("\nLoading...")

        # 清除舊的 JSESSIONID，確保取得新的 session
        self.session.cookies.delete('JSESSIONID', domain='irs.thsrc.com.tw')

        # 設置 Cookie 同意（高鐵網站現在需要先同意 Cookie 政策）
        self.session.cookies.set('cookieAccepted', 'true', domain='irs.thsrc.com.tw')
        self.session.cookies.set('isShowCookiePolicy', 'N', domain='irs.thsrc.com.tw')

        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info(f"連線高鐵網站... (嘗試 {attempt}/{max_retries})")
                res = self.session.get(self.config['page']['reservation'], timeout=60)

                if res.status_code == 200:
                    page = BeautifulSoup(res.text, 'html.parser')
                    captcha_img = page.find('img', class_='captcha-img')
                    if not captcha_img:
                        self.logger.warning("找不到驗證碼圖片，重試中...")
                        time.sleep(2)
                        continue
                    captcha_url = 'https://irs.thsrc.com.tw' + captcha_img['src']
                    # 優先從響應 cookies 取得，否則從 session cookies 取得
                    jsessionid = res.cookies.get('JSESSIONID') or self.session.cookies.get('JSESSIONID')
                    self.logger.info(f"Session ID: {jsessionid[:20]}..." if jsessionid else "No session ID")
                    return jsessionid, captcha_url
                else:
                    self.logger.warning(f"HTTP {res.status_code}，重試中...")
                    time.sleep(2)
            except Exception as e:
                self.logger.warning(f"連線失敗: {e}")
                if attempt < max_retries:
                    wait_time = attempt * 3  # 指數退避
                    self.logger.info(f"等待 {wait_time} 秒後重試...")
                    time.sleep(wait_time)
                else:
                    self.logger.error("❌ 連線高鐵網站失敗，請稍後再試")
                    sys.exit(1)

        self.logger.error("❌ 多次重試後仍無法連線")
        sys.exit(1)

    def update_captcha(self, jsessionid):
        """Get security code from captcha url"""
        self.logger.info("Update captcha")

        res = self.session.get(self.config['api']['update_captcha'].format(
            jsessionid=jsessionid, random_value=random.random()), timeout=200)

        if res.status_code == 200:
            captcha_url = 'https://irs.thsrc.com.tw' + \
                re.search('src="(.+?)"', res.text).group(1)
            return captcha_url
        else:
            self.logger.error(res.text)
            sys.exit(1)

    def booking_form(self, jsessionid, security_code):
        """1. Fill booking form"""

        if self.fields['train-no']:
            booking_method = 'radio33'  # 車次搜尋
            self.outbound_time = ''
        else:
            booking_method = 'radio31'  # 時間搜尋
            self.fields['train-no'] = ''

        headers = {
            'Referer': 'https://irs.thsrc.com.tw/IMINT/',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': user_agent,
        }

        data = {
            'BookingS1Form:hf:0': '',
            'tripCon:typesoftrip': '0',
            'trainCon:trainRadioGroup': self.car_type,
            'seatCon:seatRadioGroup': self.preferred_seat,
            'bookingMethod': booking_method,
            'selectStartStation': self.start_station,
            'selectDestinationStation': self.dest_station,
            'toTimeInputField': self.outbound_date,
            'backTimeInputField': self.outbound_date,
            'toTimeTable': self.outbound_time,
            'toTrainIDInputField': self.fields['train-no'].strip(),
            'backTimeTable': '',
            'backTrainIDInputField': '',
            'ticketPanel:rows:0:ticketAmount': self.ticket_num[0],
            'ticketPanel:rows:1:ticketAmount': self.ticket_num[1],
            'ticketPanel:rows:2:ticketAmount': self.ticket_num[2],
            'ticketPanel:rows:3:ticketAmount': self.ticket_num[3],
            'ticketPanel:rows:4:ticketAmount': self.ticket_num[4],
            'ticketPanel:rows:5:ticketAmount': self.ticket_num[5],  # 少年票
            'trainTypeContainer:typesoftrain': '0',  # 車次需求: 0=所有車次
            'ticketTypeNum': '',  # 隱藏欄位
            'homeCaptcha:securityCode': security_code,
            'SubmitButton': '開始查詢',  # 修正按鈕文字
            'portalTag': 'false',
        }

        form_url = self.config['api']['confirm_train'].format(
            jsessionid=jsessionid)

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                res = self.session.post(
                    form_url,
                    headers=headers,
                    data=data,
                    timeout=60,
                )

                if res.status_code == 200:
                    return res
                else:
                    self.logger.warning(f"HTTP {res.status_code}，重試中...")
                    time.sleep(2)
            except Exception as e:
                self.logger.warning(f"查詢失敗: {e}")
                if attempt < max_retries:
                    wait_time = attempt * 2
                    self.logger.info(f"等待 {wait_time} 秒後重試...")
                    time.sleep(wait_time)
                else:
                    self.logger.error(res.text if 'res' in dir() else str(e))
                    sys.exit(1)

        self.logger.error("❌ 多次重試後查詢失敗")
        sys.exit(1)

    def confirm_train(self, html_page, default_value: int = 1):
        """2. Confirm train"""
        trains = []
        has_discount = False
        
        # 取得時間區間設定
        outbound_time_end = self.fields.get('outbound-time-end', '')
        
        for train in html_page.find_all('input', {'name': 'TrainQueryDataViewPanel:TrainGroup'}):
            departure_time = train['querydeparture']
            arrival_time = train['queryarrival']
            
            # 過濾抵達時間（如果有設定 inbound-time）
            if self.fields['inbound-time']:
                if datetime.strptime(arrival_time, '%H:%M').time() > datetime.strptime(self.fields['inbound-time'], '%H:%M').time():
                    continue
            
            # 過濾出發時間結束（如果有設定 outbound-time-end）
            if outbound_time_end:
                if datetime.strptime(departure_time, '%H:%M').time() > datetime.strptime(outbound_time_end, '%H:%M').time():
                    continue
            
            duration = train.parent.findNext('div').find('div', class_='duration').text.replace(
                '\n', '').replace('schedule', '').replace('directions_railway', '').split('｜')
            schedule = duration[0]
            train_no = duration[1]
            discount = train.parent.findNext('div').find(
                'div', class_='discount').text.replace('\n', '')
            if discount:
                has_discount = True

            trains.append({
                'departure_time': departure_time,
                'arrival_time': arrival_time,
                'duration': schedule,
                'discount': discount,
                'no': train_no,
                'value': train['value']
            })

        if not trains:
            time_range_msg = ""
            if outbound_time_end:
                time_range_msg = f"（時間區間：{self.fields['outbound-time']} ~ {outbound_time_end}）"
            if self.fields['inbound-time']:
                self.logger.info(
                    f'\n在 {self.outbound_date} {time_range_msg} 沒有符合條件的班次（抵達時間 <= {self.fields["inbound-time"]}），請調整時間設定！')
            else:
                self.logger.info(
                    f'\n在 {self.outbound_date} {time_range_msg} 沒有符合條件的班次，請調整時間設定！')
            sys.exit(0)

        # 顯示時間區間資訊
        if outbound_time_end:
            self.logger.info(f'\n🕐 時間區間：{self.fields["outbound-time"]} ~ {outbound_time_end}')
        
        self.logger.info('\nSelect train:')

        for idx, train in enumerate(trains, start=1):
            self.logger.info(
                f"{idx}. {train['departure_time']} -> {train['arrival_time']} ({train['duration']}) | {train['no']}\t{train['discount']}")

        if self.list:
            return

        if self.auto:
            if has_discount:
                trains = list(
                    filter(lambda train: train['discount'], trains)) or trains
            if self.fields['inbound-time']:
                trains = list(filter(lambda train: datetime.strptime(self.fields['inbound-time'], '%H:%M') < datetime.strptime(
                    train['arrival_time'], '%H:%M') + timedelta(minutes=20), trains)) or trains

            trains = [min(trains, key=lambda train: datetime.strptime(
                train['duration'], '%H:%M').time())]
            self.logger.info(
                f"\nAuto pick train: {trains[0]['departure_time']} -> {trains[0]['arrival_time']} ({trains[0]['duration']}) | {trains[0]['no']}\t{trains[0]['discount']}")
            selected_opt = 0
        else:
            selected_opt = int(
                input(f'train (default: {default_value}): ') or default_value) - 1

        headers = {
            'Referer': self.config['page']['interface'].format(interface=1),
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': user_agent,
        }

        data = {
            'BookingS2Form:hf:0': '',
            'TrainQueryDataViewPanel:TrainGroup': trains[selected_opt]['value'],
            'SubmitButton': 'Confirm',
        }

        res = self.session.post(
            self.config['api']['confirm_ticket'],
            headers=headers,
            data=data,
        )

        if res.status_code == 200:
            return res
        else:
            self.logger.error(res.text)
            sys.exit(1)

    def confirm_ticket(self, html_page):
        """3. Confirm ticket"""

        dummy_id = self.fields['id']
        if not dummy_id:
            dummy_id = input("\nInput id: ")

        if self.fields['train-no']:
            interface = 1
        else:
            interface = 2

        headers = {
            'Referer': self.config['page']['interface'].format(interface=interface),
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': user_agent,
        }

        candidates = html_page.find_all(
            'input',
            attrs={
                'name': 'TicketMemberSystemInputPanel:TakerMemberSystemDataView:memberSystemRadioGroup'
            },
        )

        tax_id = self.fields['tax-id']
        tgo_id = self.fields['tgo-id']
        if self.fields['tgo-id']:
            ticket_member = candidates[1].attrs['value']
            if not check_roc_id(tgo_id):
                tgo_id = input("\nInput tgo id: ")
        elif tax_id:
            ticket_member = candidates[2].attrs['value']
            if not check_tax_id(tax_id):
                tax_id = input("\nInput tax id: ")
        else:
            ticket_member = candidates[0].attrs['value']

        passenger_count = 0
        for ticket in self.ticket_num:
            passenger_count += int(ticket[:-1])

        data = {
            'BookingS3FormSP:hf:0': '',
            'diffOver': '1',
            'isSPromotion': '1',
            'passengerCount': str(passenger_count),
            'isGoBackM': '',
            'backHome': '',
            'TgoError': '1',
            'idInputRadio': '0' if check_roc_id(dummy_id) else '1',
            'dummyId': dummy_id,
            'dummyPhone': self.fields['phone'],
            'email': self.fields['email'],
            'TicketMemberSystemInputPanel:TakerMemberSystemDataView:memberSystemRadioGroup': ticket_member,
            'TicketMemberSystemInputPanel:TakerMemberSystemDataView:memberSystemRadioGroup:memberShipNumber': tgo_id,
            'TicketMemberSystemInputPanel:TakerMemberSystemDataView:memberSystemRadioGroup:GUINumber:': tax_id,
            'agree': 'on',
        }

        # 處理所有乘客的身分證欄位
        # 找到所有乘客身分證輸入欄位
        passenger_id_inputs = html_page.find_all(
            'input',
            attrs={
                'name': re.compile(r'passengerDataIdNumber$')
            }
        )
        
        # 為每位乘客填入身分證
        for i, input_field in enumerate(passenger_id_inputs):
            field_name = input_field.attrs.get('name', '')
            # 預設使用訂票人身分證，或者對應的特殊票種身分證
            data[field_name] = dummy_id  # 使用訂票人身分證
        
        # 處理愛心票 - 覆蓋對應的身分證
        disableds = html_page.find_all(
            'input',
            attrs={
                'value': '愛心票'
            },
        )
        disabled_ids = self.fields.get('ids', {}).get('disabled', [])
        for disabled, disabled_id in zip(disableds, disabled_ids):
            data[disabled.attrs['name']] = disabled.attrs['value']
            if disabled_id:
                data[disabled.attrs['name'].replace(
                    'passengerDataTypeName', 'passengerDataIdNumber')] = disabled_id.strip()

        # 處理敬老票 - 覆蓋對應的身分證
        elders = html_page.find_all(
            'input',
            attrs={
                'value': '敬老票'
            },
        )
        elder_ids = self.fields.get('ids', {}).get('elder', [])
        for elder, elder_id in zip(elders, elder_ids):
            data[elder.attrs['name']] = elder.attrs['value']
            if elder_id:
                data[elder.attrs['name'].replace(
                    'passengerDataTypeName', 'passengerDataIdNumber')] = elder_id.strip()

        res = self.session.post(
            self.config['api']['submit'].format(interface=interface),
            headers=headers,
            data=data,
        )

        if res.status_code == 200:
            return res
        else:
            self.logger.error(res.text)
            sys.exit(1)

    def print_result(self, html_page):
        """4. Print result"""

        reservation_no = html_page.find(
            'p', class_='pnr-code').get_text(strip=True)
        payment_status = html_page.find(
            'p', class_='payment-status').get_text(strip=True)
        car_type = html_page.find(
            'div', class_='car-type').find('p', class_='info-data').get_text(strip=True)
        ticket_type = html_page.find(
            'div', class_='ticket-type').find('div').get_text(strip=True)
        ticket_price = html_page.find(
            'span', id='setTrainTotalPriceValue').get_text(strip=True)
        card = html_page.find('div', class_='ticket-card')
        onbound_date = card.find('span', class_='date').get_text(strip=True)
        train_no = card.find('span', id='setTrainCode0').get_text(strip=True)
        departure_time = card.find(
            'p', class_='departure-time').get_text(strip=True)
        departure_station = card.find(
            'p', class_='departure-stn').get_text(strip=True)
        arrival_time = card.find(
            'p', class_='arrival-time').get_text(strip=True)
        arrival_station = card.find(
            'p', class_='arrival-stn').get_text(strip=True)
        duration = card.find(
            'span', id='InfoEstimatedTime0').get_text(strip=True)
        seats = [seat.get_text(strip=True) for seat in html_page.find(
            'div', class_='detail').find_all('div', class_='seat-label')]

        self.logger.info("\nBooking success!")
        self.logger.info(
            "\n---------------------- Ticket ----------------------")
        self.logger.info("Reservation No: %s", reservation_no)
        self.logger.info("Payment Status: %s", payment_status)
        self.logger.info("Car Type: %s", car_type)
        self.logger.info("Ticket Type: %s", ticket_type)
        self.logger.info("Price: %s", ticket_price)
        self.logger.info(
            "----------------------------------------------------")
        self.logger.info("Date: %s", onbound_date)
        self.logger.info("Train No: %s", train_no)
        self.logger.info("Duration: %s", duration)
        self.logger.info("%s (%s) -> %s (%s)", departure_time,
                         departure_station, arrival_time, arrival_station)
        self.logger.info(
            "----------------------------------------------------")
        self.logger.info("Seats: %s", ', '.join(seats))
        self.logger.info(
            "\n\nGo to the reservation record to confirm the ticket and pay!\n (%s) ", self.config['page']['history'])

        if not os.getenv("COLAB_RELEASE_TAG"):
            pyperclip.copy(reservation_no)
            self.logger.info("\nReservation No. has been copied to clipboard!")

    def main(self):
        """Buy ticket process"""
        
        import time
        
        search_attempt = 0
        while True:  # 持續搜尋直到訂到票
            search_attempt += 1
            self.logger.info(f"\n{'='*50}")
            self.logger.info(f"🔍 第 {search_attempt} 次搜尋...")
            self.logger.info(f"{'='*50}")
            
            jsessionid = ''
            captcha_url = ''
            while not jsessionid and not captcha_url:
                jsessionid, captcha_url = self.get_jsessionid()

            result_url = ''
            retry_count = 0
            max_retries = 10  # 驗證碼最多重試 10 次，失敗後重新取得 Session
            found_train = False
            no_ticket_error = False
            
            while result_url != self.config['page']['interface'].format(interface=1):
                security_code = self.get_security_code(captcha_url)
                
                # 如果取得驗證碼失敗（網路超時），重新開始
                if security_code is None:
                    self.logger.warning("⚠️ 取得驗證碼失敗，重新開始...")
                    time.sleep(5)
                    break
                
                booking_form_result = self.booking_form(jsessionid, security_code)
                result_url = booking_form_result.url

                if result_url != self.config['page']['interface'].format(interface=1):
                    error_msg = self.print_error_message(booking_form_result.text)
                    retry_count += 1
                    
                    # 檢查是否為「查無車次」錯誤
                    if '查無可售車次' in booking_form_result.text or '已售完' in booking_form_result.text:
                        self.logger.warning("⚠️ 查無可售車次或已售完，30秒後重新搜尋...")
                        no_ticket_error = True
                        time.sleep(30)  # 等待 30 秒後重試
                        break
                    
                    if retry_count >= max_retries:
                        self.logger.warning(f"⚠️ 驗證碼重試 {max_retries} 次仍失敗，重新取得 Session...")
                        break  # 重新開始整個流程
                    
                    # 每次失敗立即更新驗證碼重試
                    self.logger.info(f"🔄 驗證碼錯誤，更新中... ({retry_count}/{max_retries})")
                    captcha_url = self.update_captcha(jsessionid=jsessionid)
                else:
                    found_train = True
                    self.logger.info(f"✅ 驗證碼正確！找到車次列表")
            
            if found_train:
                break  # 找到車次，繼續訂票流程
            
            if no_ticket_error:
                continue  # 查無車次，重新搜尋
            
            # 驗證碼重試過多，重新開始
            self.logger.info("🔄 重新開始搜尋...")

        confirm_train_page = BeautifulSoup(
            booking_form_result.text, 'html.parser')

        if not self.fields['train-no']:
            result_url = ''
            train_retry = 0
            max_train_retries = 3
            
            while result_url != self.config['page']['interface'].format(interface=2):
                confirm_train_result = self.confirm_train(confirm_train_page)
                if self.list:
                    return
                result_url = confirm_train_result.url

                if result_url != self.config['page']['interface'].format(interface=2):
                    error_msgs = self.print_error_message(confirm_train_result.text)
                    train_retry += 1
                    
                    if error_msgs:
                        self.logger.error(f"❌ 選擇車次失敗: {', '.join(error_msgs)}")
                    
                    if train_retry >= max_train_retries:
                        self.logger.error("❌ 選擇車次重試次數過多")
                        sys.exit(1)
                    
                    # 更新頁面重試
                    confirm_train_page = BeautifulSoup(confirm_train_result.text, 'html.parser')
                else:
                    self.logger.info("✅ 車次選擇成功！")

            confirm_ticket_page = BeautifulSoup(
                confirm_train_result.text, 'html.parser')
            interface = 3
        else:
            confirm_ticket_page = confirm_train_page
            interface = 2

        result_url = ''
        confirm_retry = 0
        max_confirm_retries = 5
        
        while result_url != self.config['page']['interface'].format(interface=interface):
            confirm_ticket_result = self.confirm_ticket(confirm_ticket_page)
            result_url = confirm_ticket_result.url

            if result_url != self.config['page']['interface'].format(interface=interface):
                error_msgs = self.print_error_message(confirm_ticket_result.text)
                confirm_retry += 1
                
                # 如果有錯誤訊息，顯示並退出
                if error_msgs:
                    self.logger.error(f"❌ 確認訂票失敗: {', '.join(error_msgs)}")
                    if confirm_retry >= max_confirm_retries:
                        self.logger.error("❌ 確認訂票重試次數過多，請檢查身分證資料")
                        sys.exit(1)
                
                # 更新頁面內容重試
                confirm_ticket_page = BeautifulSoup(confirm_ticket_result.text, 'html.parser')
            else:
                self.logger.info("✅ 訂票確認成功！")

        result_page = BeautifulSoup(confirm_ticket_result.text, 'html.parser')
        self.print_result(result_page)
        
        # 訂票成功，自動停止程式
        self.logger.info("\n🎉 訂票成功！程式自動停止。")
        sys.exit(0)