"""
This module is base service
"""
from __future__ import annotations
import httpx
from configs.config import fields, user_agent
from utils.proxy import get_ip_info, get_proxy


class BaseService(object):
    """
    BaseService
    """

    def __init__(self, args):
        self.logger = args.log
        self.cookies = {}
        self.config = args.config
        self.service = args.service
        self.fields = fields[self.service]

        self.locale = args.locale
        self.auto = args.auto
        self.list = args.list

        # 使用 httpx 取代 requests（解決高鐵網站連線問題）
        proxy_url = None
        proxy = args.proxy
        if proxy:
            self.ip_info = get_ip_info()
            self.logger.info(
                'ip: %s (%s)', self.ip_info['ip'], self.ip_info['country'])

            if len("".join(i for i in proxy if not i.isdigit())) == 2:
                proxy = get_proxy(region=proxy, ip_info=self.ip_info,
                                  geofence=self.GEOFENCE, platform=self.platform)

            self.logger.debug('proxy: %s', proxy)
            if proxy:
                if "://" not in proxy:
                    proxy = f"https://{proxy}"
                self.proxy = proxy
                proxy_url = proxy
                self.logger.info(" + Set Proxy")
            else:
                self.logger.info(
                    " + Proxy was skipped as current region matches")

        self.session = httpx.Client(
            headers={
                'User-Agent': user_agent,
                "Accept": 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                "Accept-Language": 'zh-TW,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            },
            follow_redirects=True,
            timeout=httpx.Timeout(200.0),
            proxy=proxy_url,
        )

    def __del__(self):
        """關閉 httpx client"""
        if hasattr(self, 'session') and self.session:
            self.session.close()
