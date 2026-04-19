# -*- coding: utf-8 -*-
"""
HTTP client for 3x-ui / Sanaei panels.

Handles login and health-check only.  No inbound or client management yet.
Passwords are stored and transmitted as plain text; add encryption later if
needed.
"""
import warnings
import logging

import requests
from requests.exceptions import RequestException, Timeout, SSLError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # seconds

# Suppress InsecureRequestWarning raised by verify=False (self-signed certs are
# common in self-hosted 3x-ui deployments).
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class PanelClient:
    """Thin client for a single 3x-ui panel."""

    def __init__(self, protocol: str, host: str, port: int,
                 path: str, username: str, password: str):
        self.protocol = protocol.strip().rstrip("/")
        self.host     = host.strip()
        self.port     = int(port)
        # normalise path: store without trailing slash, always starts with /
        p = path.strip()
        if p and not p.startswith("/"):
            p = "/" + p
        self.path     = p.rstrip("/")
        self.username = username.strip()
        self.password = password

        self._session = requests.Session()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def base_url(self) -> str:
        """Return the base URL without a trailing slash."""
        url = f"{self.protocol}://{self.host}:{self.port}"
        if self.path and self.path != "/":
            url += self.path
        return url

    # ── Public API ────────────────────────────────────────────────────────────

    def login(self) -> tuple:
        """
        Attempt to log in to the panel.

        Returns:
            (success: bool, error: str | None)
        """
        try:
            url  = f"{self.base_url}/login"
            resp = self._session.post(
                url,
                data={"username": self.username, "password": self.password},
                timeout=DEFAULT_TIMEOUT,
                verify=False,
                allow_redirects=True,
            )

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data.get("success") is True:
                        return True, None
                    return False, data.get("msg") or "احراز هویت ناموفق"
                except ValueError:
                    # Panel returned 200 but non-JSON body — treat as success
                    # (some versions redirect to the dashboard).
                    return True, None

            return False, f"HTTP {resp.status_code}"

        except Timeout:
            return False, "اتصال منقضی شد (timeout)"
        except SSLError as exc:
            msg = str(exc)
            if "WRONG_VERSION_NUMBER" in msg or "wrong version number" in msg.lower():
                return False, (
                    "خطای SSL: سرور از پروتکل HTTPS پشتیبانی نمی‌کند.\n"
                    "لطفاً پروتکل پنل را به «http» تغییر دهید."
                )
            return False, f"خطای SSL: {exc}"
        except RequestException as exc:
            return False, str(exc)

    def health_check(self) -> tuple:
        """
        Check whether the panel is reachable and credentials are valid.

        Returns:
            (connected: bool, error: str | None)
        """
        return self.login()
