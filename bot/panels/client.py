# -*- coding: utf-8 -*-
"""
HTTP client for 3x-ui / Sanaei panels.

Handles login and health-check only.  No inbound or client management yet.
Passwords are stored and transmitted as plain text; add encryption later if
needed.
"""
import base64 as _b64_module
import json as _json_module
import time
import uuid as _uuid_module
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

# ── VMess helpers ─────────────────────────────────────────────────────────────

def is_vmess_link(text: str) -> bool:
    """Return True if text looks like a vmess:// link."""
    return isinstance(text, str) and text.strip().startswith("vmess://")


def decode_vmess_link(vmess_url: str) -> dict:
    """
    Decode a vmess:// link into its JSON dict.
    Raises ValueError on bad input.
    """
    if not is_vmess_link(vmess_url):
        raise ValueError("Not a vmess:// link")
    b64 = vmess_url.strip()[8:].split("#")[0]
    # Fix missing base64 padding
    b64 += "=" * (-len(b64) % 4)
    try:
        decoded = _b64_module.b64decode(b64).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"VMess base64 decode error: {exc}") from exc
    try:
        obj = _json_module.loads(decoded)
    except Exception as exc:
        raise ValueError(f"VMess JSON parse error: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("VMess payload is not a JSON object")
    return obj


def encode_vmess_link(obj: dict) -> str:
    """Encode a dict to a vmess:// link (compact JSON, UTF-8 safe)."""
    raw = _json_module.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return "vmess://" + _b64_module.b64encode(raw.encode("utf-8")).decode()


def patch_vmess_link(vmess_url: str, new_uuid: str, new_name: str) -> str:
    """
    Return a new vmess:// link where only 'id' and 'ps' are replaced.
    All other fields (add, port, net, path, host, tls, aid, scy, …) are preserved.
    Raises ValueError on bad input.
    """
    obj = decode_vmess_link(vmess_url)
    obj["id"] = new_uuid
    obj["ps"] = new_name
    return encode_vmess_link(obj)


def validate_vmess_link(vmess_url: str) -> tuple:
    """
    Validate a vmess:// link.
    Returns (True, None) or (False, error_str).
    """
    if not is_vmess_link(vmess_url):
        return False, "Not a vmess:// link"
    try:
        obj = decode_vmess_link(vmess_url)
    except ValueError as exc:
        return False, str(exc)
    # id must be a valid UUID
    uid = obj.get("id", "")
    try:
        _uuid_module.UUID(str(uid))
    except Exception:
        return False, f"Invalid UUID in VMess id field: {uid!r}"
    # ps (name) must not be empty
    if not (obj.get("ps") or "").strip():
        return False, "VMess ps (name) field is empty"
    # add/host must exist if present
    if "add" in obj and not str(obj["add"]).strip():
        return False, "VMess add (host) field is empty"
    # Re-encode round-trip check
    try:
        re_encoded = encode_vmess_link(obj)
        decode_vmess_link(re_encoded)
    except Exception as exc:
        return False, f"VMess round-trip encode/decode failed: {exc}"
    return True, None


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
        On the first attempt, reuses the existing session if already logged in.
        On retries, forces a fresh login to recover from expired sessions.
        Returns the raw requests.Response or raises RequestException.
        """
        last_err = None
        for attempt in range(MAX_RETRIES):
            # Only force re-login on retries — not on the first attempt.
            # Forcing re-login on every call (including attempt 0) causes a
            # login storm when creating multiple configs in a loop: each
            # get_inbounds + addClient call re-authenticates, producing 3+
            # logins per config and triggering panel rate-limiting.
            if attempt > 0:
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

    def create_client_for_inbound(self, inbound_id: int, email: str,
                                  traffic_bytes: int, expire_ms: int,
                                  protocol: str = None) -> tuple:
        """
        Protocol-aware client creation.  Detects VMess vs VLESS from the inbound
        if `protocol` is not supplied.  For VMess, copies alterId/security
        defaults from an existing client in the same inbound if available.

        Returns (True, {uuid, sub_id, protocol, client_email, inbound_id})
             or (False, error_str).
        """
        # Detect protocol from inbound when not provided
        if not protocol:
            inbound = self.find_inbound_by_id(inbound_id)
            if not inbound:
                return False, f"اینباند {inbound_id} یافت نشد"
            protocol = (inbound.get("protocol") or "vless").lower().strip()
        else:
            protocol = protocol.lower().strip()

        client_uuid = str(_uuid_module.uuid4())
        sub_id = client_uuid.replace("-", "")[:16]

        if protocol == "vmess":
            # Pull alterId/security from an existing client in this inbound
            alter_id = 0
            security = "auto"
            try:
                inbound_obj = self.find_inbound_by_id(inbound_id)
                if inbound_obj:
                    settings_raw = inbound_obj.get("settings") or "{}"
                    if isinstance(settings_raw, str):
                        settings_parsed = _json_module.loads(settings_raw)
                    else:
                        settings_parsed = settings_raw
                    existing_clients = settings_parsed.get("clients", [])
                    if existing_clients:
                        sample = existing_clients[0]
                        alter_id = int(sample.get("alterId", 0) or 0)
                        security = str(sample.get("security", "auto") or "auto")
            except Exception:
                pass

            client_obj = {
                "id":         client_uuid,
                "alterId":    alter_id,
                "security":   security,
                "email":      email,
                "limitIp":    0,
                "totalGB":    traffic_bytes,
                "expiryTime": expire_ms,
                "enable":     True,
                "tgId":       "",
                "subId":      sub_id,
                "reset":      0,
            }
        else:
            # VLESS / Trojan / default path
            client_obj = {
                "id":         client_uuid,
                "flow":       "",
                "email":      email,
                "limitIp":    0,
                "totalGB":    traffic_bytes,
                "expiryTime": expire_ms,
                "enable":     True,
                "tgId":       "",
                "subId":      sub_id,
                "reset":      0,
            }

        settings_obj = {"clients": [client_obj]}
        payload = {
            "id":       inbound_id,
            "settings": _json_module.dumps(settings_obj),
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
                    return True, {
                        "uuid":         client_uuid,
                        "sub_id":       sub_id,
                        "protocol":     protocol,
                        "client_email": email,
                        "inbound_id":   inbound_id,
                    }
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

    def get_client_full(self, inbound_id: int, client_uuid: str) -> tuple:
        """
        Get the full client object from the inbound's settings JSON.
        This preserves all fields (flow, subId, totalGB, expiryTime, etc.)
        Returns (True, client_dict) or (False, error_str).
        """
        import json as _json
        ok, inbounds = self.get_inbounds()
        if not ok:
            return False, inbounds
        for ib in inbounds:
            if int(ib.get("id", -1)) == int(inbound_id):
                try:
                    settings = _json.loads(ib.get("settings", "{}"))
                    for client in settings.get("clients", []):
                        if client.get("id") == client_uuid:
                            return True, client
                except Exception as exc:
                    return False, str(exc)
                return False, "کلاینت در اینباند یافت نشد"
        return False, "اینباند یافت نشد"

    def _update_client(self, inbound_id: int, client_uuid: str,
                       overrides: dict) -> tuple:
        """
        Fetch the full current client object, apply overrides, then POST update.
        This preserves all existing fields (flow, subId, totalGB, expiryTime…).
        Returns (True, None) or (False, error_str).
        """
        import json as _json
        ok, current = self.get_client_full(inbound_id, client_uuid)
        if ok and current:
            client_obj = dict(current)
        else:
            # Fallback: build minimal object from what we know
            client_obj = {"id": client_uuid}
        client_obj.update(overrides)
        # Ensure id is always set
        client_obj["id"] = client_uuid
        settings_obj = {"clients": [client_obj]}
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

    def disable_client(self, inbound_id: int, client_uuid: str,
                       email: str = "", traffic_bytes: int = 0,
                       expire_ms: int = 0) -> tuple:
        """
        Disable (set enable=False) an existing client while preserving all other fields.
        Returns (True, None) or (False, error_str).
        """
        return self._update_client(inbound_id, client_uuid, {"enable": False})

    def enable_client(self, inbound_id: int, client_uuid: str,
                      email: str = "", traffic_bytes: int = 0,
                      expire_ms: int = 0) -> tuple:
        """
        Enable (set enable=True) an existing client while preserving all other fields.
        Returns (True, None) or (False, error_str).
        """
        return self._update_client(inbound_id, client_uuid, {"enable": True})

    def update_client_sub(self, inbound_id: int, client_uuid: str,
                          email: str, new_sub_id: str,
                          traffic_bytes: int = 0, expire_ms: int = 0,
                          enable: bool = True) -> tuple:
        """
        Update only the subId of an existing client while preserving all other fields.
        Returns (True, None) or (False, error_str).
        """
        return self._update_client(inbound_id, client_uuid, {"subId": new_sub_id})

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

    def add_client_volume(self, inbound_id: int, client_uuid: str,
                          extra_gb: float) -> tuple:
        """
        Add extra GB to the client's total traffic limit WITHOUT resetting used traffic.
        Reads current totalGB from panel, adds extra_gb to it, then patches via _update_client.
        Returns (True, new_total_bytes) or (False, error_str).
        """
        ok, current = self.get_client_full(inbound_id, client_uuid)
        if not ok:
            return False, current
        current_total = int(current.get("totalGB", 0) or 0)
        extra_bytes   = int(extra_gb * 1_073_741_824)
        new_total     = current_total + extra_bytes
        ok2, err2 = self._update_client(inbound_id, client_uuid, {"totalGB": new_total})
        if ok2:
            return True, new_total
        return False, err2

    def add_client_time(self, inbound_id: int, client_uuid: str,
                        extra_days: int) -> tuple:
        """
        Add extra days to the client's expiry WITHOUT touching volume.
        - If expiry is in the future → new_expiry = current_expiry + extra_days.
        - If expired (or unlimited/0) → new_expiry = now + extra_days.
        Returns (True, new_expiry_ms) or (False, error_str).
        """
        import time as _time
        ok, current = self.get_client_full(inbound_id, client_uuid)
        if not ok:
            return False, current
        current_exp_ms = int(current.get("expiryTime", 0) or 0)
        now_ms = int(_time.time() * 1000)
        if current_exp_ms > 0 and current_exp_ms > now_ms:
            new_exp_ms = current_exp_ms + extra_days * 86_400_000
        else:
            # Already expired or unlimited → start fresh from now
            new_exp_ms = now_ms + extra_days * 86_400_000
        ok2, err2 = self._update_client(inbound_id, client_uuid,
                                        {"expiryTime": new_exp_ms})
        if ok2:
            return True, new_exp_ms
        return False, err2

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
                decoded = _b64_module.b64decode(raw).decode("utf-8", errors="replace")
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

    def fetch_client_config_with_retry(self, sub_id: str, protocol: str = "",
                                       max_attempts: int = 3,
                                       delay_secs: float = 1.5) -> tuple:
        """
        Fetch the subscription content with a few retries to handle the brief
        propagation delay after addClient on busy panels.

        Returns (True, config_line_str) for the first line matching `protocol`
        (or first non-http line), or (False, error_str) if all attempts fail.
        """
        import time as _t
        last_err = "محتوای ساب خالی است"
        proto_prefix = f"{protocol.lower()}://" if protocol else ""
        for attempt in range(max_attempts):
            if attempt > 0:
                _t.sleep(delay_secs)
            ok, result = self.fetch_client_config(sub_id)
            if not ok:
                last_err = result
                continue
            lines = result  # list of config lines
            # Prefer a line matching the requested protocol
            if proto_prefix:
                for line in lines:
                    if line.lower().startswith(proto_prefix):
                        return True, line
            # Fallback: first non-http line
            for line in lines:
                if not line.startswith("http://") and not line.startswith("https://"):
                    return True, line
            # Fallback: any line
            if lines:
                return True, lines[0]
        return False, last_err
