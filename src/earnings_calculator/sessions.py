"""Requests session management for optional proxy-aware calendar fetching."""

import requests

from earnings_calculator.proxy import ProxyManager


class SessionManager:
    def __init__(self, proxy_manager: ProxyManager):
        self.proxy_manager = proxy_manager
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        s = requests.Session()
        if self.proxy_manager.proxy_enabled:
            p = self.proxy_manager.get_proxy()
            if p:
                s.proxies.update(p)
        return s

    def rotate_session(self):
        if self.proxy_manager.proxy_enabled:
            p = self.proxy_manager.rotate_proxy()
            if p:
                self.session.close()
                self.session = self._create_session()

    def get_session(self) -> requests.Session:
        return self.session
