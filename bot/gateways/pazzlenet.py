# -*- coding: utf-8 -*-
"""
PazzleNet (PuzzleNet) Rial payment gateway — create and verify payments via REST API.
Register at @puzzlenetpay_bot → فروشگاه → مشخصات من → API Key
"""

import json
import socket
import urllib.request
import urllib.error

from ..db import setting_get


def _friendly_network_error(exc: Exception) -> str:
    """Return a human-readable Farsi string for common network/DNS errors."""
    msg = str(exc)
    # Errno -3 / EAI_AGAIN: DNS lookup failed
    if isinstance(exc, (socket.gaierror, OSError)) and getattr(exc, 'errno', None) in (-3, 11001, 11004):
        return (
            f"خطای شبکه: آدرس سرور PazzleNet قابل دسترس نیست (DNS).\n"
            f"لطفاً اتصال اینترنت سرور را بررسی کنید.\n({msg})"
        )
    if isinstance(exc, urllib.error.URLError):
        return f"خطای شبکه — اتصال به PazzleNet ممکن نبود:\n{msg}"
    return msg

PAZZLENET_BASE_URL = "https://pay.puzzlenet.xyz:8443"


def _detect_public_ip() -> str:
    """Try to detect the server's public IP."""
    import urllib.request
    for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.read().decode().strip()
        except Exception:
            pass
    return ""


def get_pazzlenet_callback_url(bot_username: str) -> str:
    """
    Return the callback URL that must be registered in @puzzlenetpay_bot.
    Format: http://{ip}:{port}/pazzlenet/{bot_slug}/callback
    Uses server_public_url setting if set, otherwise auto-detects public IP.
    If server_public_url has no explicit port (http scheme), the webhook port
    is appended automatically to avoid Connection refused on port 80.
    """
    base = (setting_get("server_public_url", "") or "").strip().rstrip("/")
    if not base:
        ip = _detect_public_ip()
        if ip:
            port = (setting_get("plisio_webhook_port", "") or
                    setting_get("webhook_port", "") or "5050").strip()
            base = f"http://{ip}:{port}"
    else:
        from urllib.parse import urlparse as _urlparse
        _parsed = _urlparse(base)
        if not _parsed.port and _parsed.scheme == "http":
            _port = (setting_get("plisio_webhook_port", "") or
                     setting_get("webhook_port", "") or "5050").strip()
            base = f"http://{_parsed.hostname}:{_port}"
    if not base:
        return ""
    slug = (bot_username or "").lower().replace("@", "").strip()
    return f"{base}/pazzlenet/{slug}/callback"


def _decode_response_body(resp) -> tuple:
    """Read response and try to parse JSON."""
    raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return "", ""
    try:
        return raw, json.loads(raw)
    except Exception:
        return raw, raw


def _extract_error_message(data) -> str:
    if isinstance(data, dict):
        if "msg" in data:
            return str(data["msg"])[:500]
        if "message" in data:
            return str(data["message"])[:500]
        if "detail" in data:
            try:
                return json.dumps(data["detail"], ensure_ascii=False)[:500]
            except Exception:
                return str(data["detail"])[:500]
        return json.dumps(data, ensure_ascii=False)[:500]
    return str(data)[:500]


def _post_pazzlenet(path: str, payload: dict, timeout: int = 15):
    """POST request to PazzleNet API using api-key header.
    Returns: (success: bool, parsed_response)
    """
    api_key = setting_get("pazzlenet_api_key", "").strip()
    url = f"{PAZZLENET_BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "api-key": api_key,
            "User-Agent": "ConfigFlow/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _, parsed = _decode_response_body(resp)
        return True, parsed

    except urllib.error.HTTPError as e:
        try:
            raw_body = e.read().decode("utf-8", errors="replace").strip()
            try:
                parsed = json.loads(raw_body) if raw_body else {}
            except Exception:
                parsed = raw_body or f"HTTP {e.code}: {e.reason}"
        except Exception:
            parsed = f"HTTP {e.code}: {e.reason}"
        return False, {"error": _extract_error_message(parsed), "status_code": e.code, "raw": parsed}

    except Exception as e:
        return False, {"error": _friendly_network_error(e)}


def _get_pazzlenet(path: str, timeout: int = 15):
    """GET request to PazzleNet API using api-key header.
    Returns: (success: bool, parsed_response)
    """
    api_key = setting_get("pazzlenet_api_key", "").strip()
    url = f"{PAZZLENET_BASE_URL}{path}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "api-key": api_key,
            "User-Agent": "ConfigFlow/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _, parsed = _decode_response_body(resp)
        return True, parsed

    except urllib.error.HTTPError as e:
        try:
            raw_body = e.read().decode("utf-8", errors="replace").strip()
            try:
                parsed = json.loads(raw_body) if raw_body else {}
            except Exception:
                parsed = raw_body or f"HTTP {e.code}: {e.reason}"
        except Exception:
            parsed = f"HTTP {e.code}: {e.reason}"
        return False, {"error": _extract_error_message(parsed), "status_code": e.code, "raw": parsed}

    except Exception as e:
        return False, {"error": _friendly_network_error(e)}


def create_pazzlenet_invoice(amount_toman: int, user_id: int):
    """
    Create a PazzleNet payment request.

    POST /api/payment/create
    Headers: api-key: {api_key}
    Body: {"chat_id": user_id, "amount": amount_toman}

    Returns:
        (True, {"payment_id": ..., "payment_link": ...}) on success
        (False, {"error": ...}) on failure
    """
    api_key = setting_get("pazzlenet_api_key", "").strip()
    if not api_key:
        return False, {
            "error": "کلید API پازل‌نت ثبت نشده است. از پنل مدیریت ← تنظیمات ← درگاه‌ها اقدام کنید."
        }

    payload = {
        "chat_id": int(user_id),
        "amount": int(amount_toman),
    }

    success, result = _post_pazzlenet("/api/payment/create", payload)

    if not success:
        return False, result

    print("[PazzleNet] create payment raw response:", result)

    if isinstance(result, dict):
        api_status = result.get("status")
        if api_status is False or api_status == 0:
            api_msg = result.get("msg") or result.get("message") or result.get("error") or ""
            return False, {"error": f"خطای درگاه PazzleNet:\n{api_msg}" if api_msg else
                           f"درگاه PazzleNet خطا برگرداند.\nجواب API: {json.dumps(result, ensure_ascii=False)[:500]}"}

        data = result.get("data", result)
        if isinstance(data, dict):
            payment_id = data.get("payment_id") or data.get("id")
            payment_link = (
                data.get("payment_link")
                or data.get("link")
                or data.get("url")
                or data.get("pay_url")
            )
            if payment_id and payment_link:
                return True, {"payment_id": str(payment_id), "payment_link": str(payment_link)}

        return False, {
            "error": f"پاسخ API ناشناخته است. جواب API: {json.dumps(result, ensure_ascii=False)[:500]}"
        }

    return False, {"error": f"پاسخ API ناشناخته: {str(result)[:300]}"}


def check_pazzlenet_payment(pazzlenet_payment_id: str):
    """
    Check the status of a PazzleNet payment.

    GET /api/payment/{payment_id}

    Returns:
        (True, response_data) on success
        (False, {"error": ...}) on failure
    """
    api_key = setting_get("pazzlenet_api_key", "").strip()
    if not api_key:
        return False, {"error": "کلید API ثبت نشده است."}

    success, result = _get_pazzlenet(f"/api/payment/{pazzlenet_payment_id}")

    if not success:
        print(f"[PazzleNet] check payment FAILED id={pazzlenet_payment_id!r} result={result!r}")
        return False, result

    print(f"[PazzleNet] check payment OK id={pazzlenet_payment_id!r} result={result!r}")
    return True, result


_PAID_VALUES = {"paid", "success", "successful", "completed", "done", "confirmed", "approved"}


def is_pazzlenet_paid(status) -> bool:
    """
    Best-effort detection of successful payment from PazzleNet check response.

    PazzleNet API check response:  {"status": true, "data": {"paid": true|false, ...}}
      - outer "status" is a *boolean API-call success flag* — NOT payment status.
      - payment status lives inside "data".

    PazzleNet webhook callback body: {"payment_id": ..., "status": "confirmed", ...}
      - flat structure, no "data" key.
      - "status" here is a *string* like "confirmed".
    """
    if isinstance(status, dict):
        # ── Wrapped API response: {"status": true|false, "data": {...}} ──────
        # The outer "status" bool means "API call OK", not "payment confirmed".
        # ONLY recurse into "data" — do NOT trust the outer boolean status.
        inner = status.get("data")
        if isinstance(inner, dict):
            return is_pazzlenet_paid(inner)

        # ── Flat dict (inner "data" object OR webhook callback body) ─────────
        # Check paid boolean flag
        if status.get("paid") is True or status.get("paid") == 1:
            return True

        # Check status *string* (webhook: {"status": "confirmed"})
        # Intentionally skip boolean True — that's an API wrapper flag, not here.
        raw_status = status.get("status", "")
        if isinstance(raw_status, str) and raw_status.lower() in _PAID_VALUES:
            return True

        for key in ("payment_status", "state", "result"):
            val = status.get(key, "")
            if isinstance(val, str) and val.lower() in _PAID_VALUES:
                return True

    if isinstance(status, str) and status.lower() in _PAID_VALUES:
        return True

    return False
