# -*- coding: utf-8 -*-
"""
3x-ui panel client — handles login and connection tests.

Uses only Python standard library (urllib + http.cookiejar) — zero
external dependencies.  Secrets are never logged.
"""
from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

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
        scheme = "http"
        base   = f"{scheme}://{host}:{port}"
        if panel_path:
            base += "/" + panel_path.strip("/")
        self._base     = base
        self._username = username
        self._password = password  # never logged
        self._timeout  = timeout
        self._proxies  = proxies or {}

    def _build_opener(self) -> urllib.request.OpenerDirector:
        jar      = http.cookiejar.CookieJar()
        handlers: list = [urllib.request.HTTPCookieProcessor(jar)]
        proxy_url = self._proxies.get("https") or self._proxies.get("http")
        if proxy_url:
            handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        else:
            handlers.append(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener(*handlers)

    def test_login(self) -> tuple[bool, str]:
        """
        Attempt to login to the 3x-ui panel.

        Returns:
            (success: bool, message: str)

        The message is safe to log and return to the admin.
        Password is NEVER included in the return value or logs.
        """
        opener    = self._build_opener()
        login_url = self._base + "/login"
        form_data = urllib.parse.urlencode({
            "username": self._username,
            "password": self._password,
        }).encode("utf-8")
        req = urllib.request.Request(login_url, data=form_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with opener.open(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                    if data.get("success"):
                        return True, "Login successful"
                    msg = data.get("msg") or data.get("message") or "Login rejected by panel"
                    return False, str(msg)[:200]
                except (json.JSONDecodeError, ValueError):
                    # Some older panels redirect to dashboard on success
                    if resp.status == 200:
                        return True, "Login successful"
                    return False, f"Unexpected response (HTTP {resp.status})"
        except urllib.error.HTTPError as exc:
            return False, f"Panel returned HTTP {exc.code}"
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", str(exc))
            return False, f"Cannot connect to panel at {self._base}: {reason}"
        except Exception as exc:
            return False, f"Request error: {type(exc).__name__}"
