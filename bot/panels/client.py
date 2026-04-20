# -*- coding: utf-8 -*-
"""
HTTP client for 3x-ui / Sanaei panels.

Handles login and health-check only.  No inbound or client management yet.
Passwords are stored and transmitted as plain text; add encryption later if
needed.
"""
import time
import warnings
import logging

import requests
from requests.exceptions import RequestException, Timeout, SSLError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20   # seconds – normal requests
LONG_TIMEOUT    = 60   # seconds – slow proxy / high-latency connections
MAX_RETRIES     = 3    # login + call retries for panel operations
RETRY_DELAY     = 2    # seconds to wait between retries

# Suppress InsecureRequestWarning raised by verify=False (self-signed certs are
# common in self-hosted 3x-ui deployments).
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


class PanelClient:
    """Thin client for a single 3x-ui panel."""

    def __init__(self, protocol: str, host: str, port: int,
                 path: str, username: str, password: str,
                 sub_url_base: str = ""):
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
        # sub_url_base: base URL for subscription links (may differ from panel URL)
        # e.g. "http://stareh.parhiiz.top:2096"  — no trailing slash, no path prefix
        self.sub_url_base = sub_url_base.strip().rstrip("/") if sub_url_base else ""

        self._session    = requests.Session()
        self._logged_in  = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ensure_logged_in(self) -> tuple:
        """
        Log in if not already authenticated.
        Returns (True, None) on success or (False, error_str) on failure.
        """
        if self._logged_in:
            return True, None
        ok, err = self.login()
        if ok:
            self._logged_in = True
        return ok, err

    def _api_call(self, method: str, url: str, **kwargs) -> tuple:
        """
        Execute an API call with automatic login + retry on failure.
        Retries up to MAX_RETRIES times; re-logs in before each retry.
        Returns the raw requests.Response or raises RequestException.
        """
        last_err = None
        for attempt in range(MAX_RETRIES):
            # Force fresh login on every retry (re-auth)
            self._logged_in = False
            ok, err = self._ensure_logged_in()
            if not ok:
                last_err = err
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                continue
            try:
                resp = self._session.request(method, url, **kwargs)
                return resp
            except Timeout:
                last_err = "اتصال منقضی شد (timeout)"
            except RequestException as exc:
                last_err = str(exc)
            if attempt < MAX_RETRIES - 1:
                self._logged_in = False
                time.sleep(RETRY_DELAY)
        raise RequestException(last_err or "خطای ناشناخته پس از چند تلاش")

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
                        self._logged_in = True
                        return True, None
                    return False, data.get("msg") or "احراز هویت ناموفق"
                except ValueError:
                    # Panel returned 200 but non-JSON body — treat as success
                    # (some versions redirect to the dashboard).
                    self._logged_in = True
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

    # ── Sanaei / 3x-ui extended API ───────────────────────────────────────────

    def get_inbounds(self) -> tuple:
        """
        Fetch list of all inbounds from the panel.
        Returns (True, list[dict]) or (False, error_str).
        API: GET /panel/api/inbounds/list
        """
        try:
            resp = self._api_call(
                "GET", f"{self.base_url}/panel/api/inbounds/list",
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, data.get("obj", [])
                return False, data.get("msg") or "دریافت اینباندها ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def find_inbound_by_port(self, port: int):
        """
        Find an inbound by its listen port.
        Returns the inbound dict or None if not found.
        """
        ok, inbounds = self.get_inbounds()
        if not ok or not inbounds:
            return None
        for ib in inbounds:
            if int(ib.get("port", -1)) == int(port):
                return ib
        return None

    def find_inbound_by_id(self, inbound_id: int):
        """
        Find an inbound by its numeric ID.
        Returns the inbound dict or None if not found.
        """
        ok, inbounds = self.get_inbounds()
        if not ok or not inbounds:
            return None
        for ib in inbounds:
            if int(ib.get("id", -1)) == int(inbound_id):
                return ib
        return None

    def create_client(self, inbound_id: int, email: str,
                      traffic_bytes: int, expire_ms: int) -> tuple:
        """
        Add a new client to the given inbound.
        API: POST /panel/api/inbounds/addClient
        Payload: {"id": inbound_id, "settings": "{\"clients\":[...]}"}  
        Returns (True, (uuid_str, sub_id)) or (False, error_str).
        """
        import uuid as _uuid
        import json as _json
        client_uuid = str(_uuid.uuid4())
        sub_id = client_uuid.replace("-", "")[:16]
        settings_obj = {
            "clients": [{
                "id": client_uuid,
                "flow": "",
                "email": email,
                "limitIp": 0,
                "totalGB": traffic_bytes,
                "expiryTime": expire_ms,
                "enable": True,
                "tgId": "",
                "subId": sub_id,
                "reset": 0,
            }]
        }
        payload = {
            "id": inbound_id,
            "settings": _json.dumps(settings_obj),
        }
        try:
            resp = self._api_call(
                "POST", f"{self.base_url}/panel/api/inbounds/addClient",
                json=payload,
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, (client_uuid, sub_id)
                return False, data.get("msg") or "ساخت کلاینت ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def get_client_traffics(self, email: str) -> tuple:
        """
        Get client traffic/status info by email.
        API: GET /panel/api/inbounds/getClientTraffics/:email
        Returns (True, client_dict) or (False, error_str).
        """
        try:
            resp = self._api_call(
                "GET", f"{self.base_url}/panel/api/inbounds/getClientTraffics/{email}",
                timeout=DEFAULT_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, data.get("obj")
                return False, data.get("msg") or "کلاینت یافت نشد"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def disable_client(self, inbound_id: int, client_uuid: str,
                       email: str, traffic_bytes: int = 0,
                       expire_ms: int = 0) -> tuple:
        """
        Disable (set enable=False) an existing client.
        API: POST /panel/api/inbounds/updateClient/:clientId
        Returns (True, None) or (False, error_str).
        """
        import json as _json
        settings_obj = {
            "clients": [{
                "id": client_uuid,
                "email": email,
                "enable": False,
                "totalGB": traffic_bytes,
                "expiryTime": expire_ms,
            }]
        }
        payload = {
            "id": inbound_id,
            "settings": _json.dumps(settings_obj),
        }
        try:
            resp = self._api_call(
                "POST", f"{self.base_url}/panel/api/inbounds/updateClient/{client_uuid}",
                json=payload,
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, None
                return False, data.get("msg") or "غیرفعال‌سازی ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def enable_client(self, inbound_id: int, client_uuid: str,
                      email: str, traffic_bytes: int = 0,
                      expire_ms: int = 0) -> tuple:
        """
        Enable (set enable=True) an existing client.
        API: POST /panel/api/inbounds/updateClient/:clientId
        Returns (True, None) or (False, error_str).
        """
        import json as _json
        settings_obj = {
            "clients": [{
                "id": client_uuid,
                "email": email,
                "enable": True,
                "totalGB": traffic_bytes,
                "expiryTime": expire_ms,
            }]
        }
        payload = {
            "id": inbound_id,
            "settings": _json.dumps(settings_obj),
        }
        try:
            resp = self._api_call(
                "POST", f"{self.base_url}/panel/api/inbounds/updateClient/{client_uuid}",
                json=payload,
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, None
                return False, data.get("msg") or "فعال‌سازی ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def update_client_sub(self, inbound_id: int, client_uuid: str,
                          email: str, new_sub_id: str,
                          traffic_bytes: int = 0, expire_ms: int = 0,
                          enable: bool = True) -> tuple:
        """
        Update client settings including a new sub_id (subscription token).
        API: POST /panel/api/inbounds/updateClient/:clientId
        Returns (True, None) or (False, error_str).
        """
        import json as _json
        settings_obj = {
            "clients": [{
                "id": client_uuid,
                "email": email,
                "enable": enable,
                "totalGB": traffic_bytes,
                "expiryTime": expire_ms,
                "subId": new_sub_id,
            }]
        }
        payload = {
            "id": inbound_id,
            "settings": _json.dumps(settings_obj),
        }
        try:
            resp = self._api_call(
                "POST", f"{self.base_url}/panel/api/inbounds/updateClient/{client_uuid}",
                json=payload,
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, None
                return False, data.get("msg") or "بروزرسانی ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def delete_client(self, inbound_id: int, client_uuid: str) -> tuple:
        """
        Delete a client from an inbound.
        API: POST /panel/api/inbounds/{inbound_id}/delClient/{client_uuid}
        Returns (True, None) or (False, error_str).
        """
        try:
            resp = self._api_call(
                "POST", f"{self.base_url}/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}",
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, None
                return False, data.get("msg") or "حذف کلاینت ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def reset_client_traffic(self, inbound_id: int, email: str) -> tuple:
        """
        Reset a client's traffic counter.
        API: POST /panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}
        Returns (True, None) or (False, error_str).
        """
        try:
            resp = self._api_call(
                "POST", f"{self.base_url}/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}",
                timeout=LONG_TIMEOUT, verify=False,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return True, None
                return False, data.get("msg") or "ریست ترافیک ناموفق"
            return False, f"HTTP {resp.status_code}"
        except RequestException as exc:
            return False, str(exc)

    def get_sub_url(self, client_uuid: str) -> str:
        """Return the subscription URL for this client.
        Uses subId (first 16 chars of UUID without dashes) as per 3x-ui spec.
        If sub_url_base is configured, uses that instead of the panel base URL.
        Otherwise, includes the panel path (Sanaei sub endpoint is under the panel path).
        """
        sub_id = client_uuid.replace("-", "")[:16]
        if self.sub_url_base:
            base = self.sub_url_base
        else:
            base = f"{self.protocol}://{self.host}:{self.port}"
            if self.path and self.path not in ("/", ""):
                base += self.path
        return f"{base}/sub/{sub_id}"

    def fetch_client_config(self, sub_id: str) -> tuple:
        """
        Fetch the actual config text from the subscription URL.
        3x-ui returns a base64-encoded string of config link(s), one per line.
        Returns (True, [config_line, ...]) or (False, error_str).
        """
        import base64 as _b64
        # Build the subscription URL directly (sub_id is already the 16-char token)
        if self.sub_url_base:
            base = self.sub_url_base
        else:
            base = f"{self.protocol}://{self.host}:{self.port}"
            if self.path and self.path not in ("/", ""):
                base += self.path
        url = f"{base}/sub/{sub_id}"
        try:
            resp = requests.get(url, timeout=LONG_TIMEOUT, verify=False)
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            raw = resp.content
            # Try base64 decoding (3x-ui returns base64-encoded config list)
            try:
                decoded = _b64.b64decode(raw).decode("utf-8", errors="replace")
            except Exception:
                decoded = raw.decode("utf-8", errors="replace")
            lines = [l.strip() for l in decoded.splitlines() if l.strip()]
            if lines:
                return True, lines
            return False, "محتوای ساب خالی است"
        except Timeout:
            return False, "اتصال منقضی شد"
        except RequestException as exc:
            return False, str(exc)
