# -*- coding: utf-8 -*-
"""
3x-ui panel client — handles login and connection tests.

Only HTTP is used (no HTTPS requirement for local LAN connections).
Secrets are never logged — callers must not pass them to log calls.
"""
from __future__ import annotations

import json
import os

try:
    import requests as _requests
    from requests import Session as _Session
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

from .logger import get_logger

log = get_logger("panel_client")


class PanelError(Exception):
    """Raised when the panel responds with an error or is unreachable."""


class XuiPanelClient:
    """
    Minimal 3x-ui REST client.

    Responsibilities:
      - Login (obtain session cookie)
      - Verify login success
      - Clean session management (no persistent state between test cycles)

    Does NOT create clients or modify panel data (that is future work).
    """

    def __init__(
        self,
        host: str,
        port: int,
        panel_path: str = "",
        username: str = "",
        password: str = "",
        timeout: int = 15,
        proxies: dict | None = None,
    ):
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError("requests package required. Run: pip install requests")

        scheme = "http"
        base   = f"{scheme}://{host}:{port}"
        if panel_path:
            base += "/" + panel_path.strip("/")
        self._base     = base
        self._username = username
        self._password = password  # never logged
        self._timeout  = timeout
        self._proxies  = proxies or {}

    def _login_url(self) -> str:
        return self._base + "/login"

    def _list_url(self) -> str:
        return self._base + "/xui/inbound/list"

    def test_login(self) -> tuple[bool, str]:
        """
        Attempt to login to the 3x-ui panel.

        Returns:
            (success: bool, message: str)

        The message is safe to log and return to the admin.
        Password is NEVER included in the return value or logs.
        """
        session = _requests.Session()
        try:
            resp = session.post(
                self._login_url(),
                data={
                    "username": self._username,
                    "password": self._password,
                },
                timeout=self._timeout,
                proxies=self._proxies,
                allow_redirects=True,
            )
        except _requests.exceptions.ConnectionError:
            return False, f"Cannot connect to panel at {self._base}"
        except _requests.exceptions.Timeout:
            return False, f"Connection timed out ({self._timeout}s)"
        except Exception as exc:
            return False, f"Request error: {type(exc).__name__}"

        # 3x-ui returns JSON {"success": true, ...} on valid login
        try:
            data = resp.json()
            if data.get("success"):
                return True, "Login successful"
            # Extract a safe error message from response
            msg = data.get("msg") or data.get("message") or "Login rejected by panel"
            # Sanitize: don't echo back any token/cookie
            return False, str(msg)[:200]
        except (json.JSONDecodeError, ValueError):
            # Some panels redirect on success (older versions)
            if resp.status_code in (200, 302) and len(session.cookies) > 0:
                return True, "Login successful (cookie obtained)"
            return False, f"Unexpected response (HTTP {resp.status_code})"
        finally:
            session.close()
