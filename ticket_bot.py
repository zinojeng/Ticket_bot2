"""
This module is to download subtitle from stream services.
"""
import os
import sys
import argparse
import logging
import re
from datetime import datetime
import time
from zoneinfo import ZoneInfo
from logging import INFO, DEBUG

# Load .env file for API keys (override system env vars)
try:
    from dotenv import load_dotenv
    # 確保從腳本所在目錄載入 .env，並覆蓋現有環境變數
    import pathlib
    env_path = pathlib.Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path, override=True)
except ImportError:
    pass

from pathlib import Path
from services import service_map
from configs.config import Config, app_name, filenames, directories, __version__
from utils.io import load_toml


def main() -> None:
    """args command"""

    support_services = ', '.join(
        sorted((service['name'] for service in service_map), key=str.lower))

    parser = argparse.ArgumentParser(
        description="Support auto buy tickets from THSR ticket",
        add_help=False)
    parser.add_argument('service',
                        type=str,
                        help="service name")
    parser.add_argument('-a',
                        '--auto',
                        dest='auto',
                        action='store_true',
                        help="auto pick the ticket")
    parser.add_argument('-l',
                        '--list',
                        dest='list',
                        action='store_true',
                        help="list the tickets")
    parser.add_argument(
        '-locale',
        '--locale',
        dest='locale',
        help="interface language",
    )
    parser.add_argument('-p',
                        '--proxy',
                        dest='proxy',
                        nargs='?',
                        help="proxy")
    parser.add_argument(
        '-d',
        '--debug',
        action='store_true',
        help="enable debug logging",
    )
    parser.add_argument(
        '-c',
        '--config',
        dest='config_file',
        help="custom config file path (default: user_config.toml)",
    )
    parser.add_argument(
        '-h',
        '--help',
        action='help',
        default=argparse.SUPPRESS,
        help="show this help message and exit"
    )
    parser.add_argument(
        '-v',
        '--version',
        action='version',
        version=f'{app_name} {__version__}',
        help="app's version"
    )

    args = parser.parse_args()

    # 載入設定檔（支援自訂路徑）
    if args.config_file:
        config_path = Path(args.config_file)
        if not config_path.is_absolute():
            config_path = directories.package_root / config_path
        logging.info(f"使用自訂設定檔: {config_path}")
    else:
        config_path = filenames.root_config
    
    config = Config.from_toml(config_path)
    config.directories['logs'] = directories.logs
    schedules = config.schedules
    fields = config.fields

    if args.debug:
        os.makedirs(config.directories['logs'], exist_ok=True)
        log_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_file_path = str(filenames.log).format(
            app_name=app_name, log_time=log_time)
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            level=logging.DEBUG,
            handlers=[
                logging.FileHandler(log_file_path, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    else:
        logging.basicConfig(
            format='%(message)s',
            level=logging.INFO,
        )

    start = datetime.now()

    service = next((service for service in service_map
                   if args.service.lower() == service['keyword']), None)

    if service:
        log = logging.getLogger(service['class'].__module__)
        if args.debug:
            log.setLevel(DEBUG)
        else:
            log.setLevel(INFO)

        service_config = load_toml(
            str(filenames.config).format(service=service['name']))

        args.log = log
        args.config = service_config
        args.service = service['name']

        if schedules[service['name']].get('datetime'):
            schedule_time = schedules[service['name']]['datetime'].strip()
            timezone = ZoneInfo('Asia/Taipei')
            current_time = datetime.now(timezone)
            
            # 支援多種格式：
            # - "HH:MM" → 今天的指定時間
            # - "YYYY-MM-DD" → 指定日期的 00:00
            # - "YYYY-MM-DD HH:MM" → 完整日期時間
            if re.search(r'^\d+:\d+$', schedule_time):
                # 只有時間 (HH:MM)
                schedule_time = f"{current_time.date()} {schedule_time}"
            elif re.search(r'^\d{4}-\d{2}-\d{2}$', schedule_time):
                # 只有日期 (YYYY-MM-DD)，補上 00:00
                schedule_time = f"{schedule_time} 00:00"

            schedule_time = datetime.strptime(
                schedule_time, '%Y-%m-%d %H:%M').replace(tzinfo=timezone)
            logging.info("The bot will auto buy tickets on %s", schedule_time)
            
            # 比較完整的日期時間，而不是只比較時間部分
            while current_time < schedule_time:
                current_time = datetime.now(timezone)
                time_diff = schedule_time - current_time
                hours, remainder = divmod(int(time_diff.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                print(
                    f"\r⏳ 等待中... 剩餘 {hours:02d}:{minutes:02d}:{seconds:02d} | 目標: {schedule_time.strftime('%Y-%m-%d %H:%M:%S')}", end='')
                time.sleep(1)
            print()  # 換行

        start = datetime.now()
        service['class'](args).main()
        logging.info("\n%s took %.3f seconds", app_name, float(
            (datetime.now() - start).total_seconds()))

    else:
        logging.warning(
            "\nOnly support buying ticket from %s ", support_services)
        sys.exit(1)


if __name__ == "__main__":
    main()
