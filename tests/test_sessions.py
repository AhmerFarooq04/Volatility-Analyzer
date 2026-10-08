"""Tests for SessionManager."""

from unittest.mock import patch

import requests

from earnings_calculator.proxy import ProxyManager
from earnings_calculator.sessions import SessionManager


class TestSessionManager:
    def test_creates_requests_session(self):
        pm = ProxyManager()
        sm = SessionManager(pm)
        assert isinstance(sm.get_session(), requests.Session)

    def test_session_with_proxy(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        pm.proxies = [{"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"}]
        sm = SessionManager(pm)
        session = sm.get_session()
        assert "http" in session.proxies

    def test_rotate_creates_new_sessions(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        p1 = {"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"}
        p2 = {"http": "http://2.2.2.2:80", "https": "http://2.2.2.2:80"}
        pm.proxies = [p1, p2]
        pm.current_proxy = p1
        sm = SessionManager(pm)
        old_session = sm.get_session()
        sm.rotate_session()
        new_session = sm.get_session()
        # After rotation, we should have a different session object
        assert new_session is not old_session

    def test_rotate_no_op_when_disabled(self):
        pm = ProxyManager()
        pm.proxy_enabled = False
        sm = SessionManager(pm)
        old_session = sm.get_session()
        sm.rotate_session()
        assert sm.get_session() is old_session

    def test_rotate_closes_old_sessions(self):
        pm = ProxyManager()
        pm.proxy_enabled = True
        p1 = {"http": "http://1.1.1.1:80", "https": "http://1.1.1.1:80"}
        p2 = {"http": "http://2.2.2.2:80", "https": "http://2.2.2.2:80"}
        pm.proxies = [p1, p2]
        pm.current_proxy = p1
        sm = SessionManager(pm)
        old_session = sm.session
        with patch.object(old_session, "close") as mock_close:
            sm.rotate_session()
            mock_close.assert_called_once()
