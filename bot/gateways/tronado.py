# -*- coding: utf-8 -*-
"""
Tronado payment gateway — create orders and receive payment confirmations via webhook.
API docs: https://documenter.getpostman.com/view/48018954/2sB3HksMLT
Auth: x-api-key header
Payment URL: https://t.me/tronado_robot/customerpayment?startapp={TOKEN}
"""

import json
import urllib.request
import urllib.error

from ..db import setting_get

TRONADO_DEFAULT_BASE_URL = "https://bot.tronado.cloud/api/v3"
TRONADO_PAYMENT_URL_TEMPLATE = "https://t.me/tronado_robot/customerpayment?startapp={token}"


def _decode_response_body(resp) -> tuple:
    raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return "", {}
    try:
        return raw, json.loads(raw)
    except Exception:
        return raw, raw


def _extract_error(data) -> str:
    if isinstance(data, dict):
        for key in ("Message", "message", "error", "Error", "msg", "detail"):
            if data.get(key):
                return str(data[key])[:500]
        return json.dumps(data, ensure_ascii=False)[:500]
    return str(data)[:500]


def get_tronado_base_url() -> str:
    url = (setting_get("tronado_api_base_url", "") or "").strip().rstrip("/")
    return url or TRONADO_DEFAULT_BASE_URL


def build_tronado_payment_url(token: str) -> str:
    """Build the Tronado Mini App payment URL from a token."""
    return TRONADO_PAYMENT_URL_TEMPLATE.format(token=token)


def get_tronado_order_token(amount_toman: int, order_id: str, user_id: int,
                             description: str = "", callback_url: str = ""):
    """
    Call POST /GetOrderToken on Tronado API.

    Returns:
        (True,  {"token": ..., "payment_url": ...})  on success
        (False, {"error": ..., "raw": ...})           on failure
    """
    api_key = (setting_get("tronado_api_key", "") or "").strip()
    if not api_key:
        return False, {"error": "کلید API ترونادو ثبت نشده است. از پنل مدیریت ← تنظیمات ← درگاه‌ها اقدام کنید."}

    base_url = get_tronado_base_url()
    wallet_address = (setting_get("tronado_wallet_address", "") or "").strip()
    if not wallet_address:
        return False, {"error": "آدرس کیف پول ترون در درگاه ترونادو ثبت نشده است. از پنل مدیریت ← تنظیمات ← درگاه‌ها تنظیم کنید."}

    payload = {
        "Amount":         int(amount_toman),
        "PaymentID":      str(order_id),
        "UserTelegramId": int(user_id),
        "WalletAddress":  wallet_address,
        "Description":    (description or "")[:200],
    }
    if callback_url:
        payload["CallbackUrl"] = callback_url

    print(f"[Tronado] Sending payload: {json.dumps(payload)}")

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/GetOrderToken",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "x-api-key":    api_key,
            "User-Agent":   "ConfigFlow/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw, parsed = _decode_response_body(resp)
        print("[Tronado] GetOrderToken response:", raw[:500])
    except urllib.error.HTTPError as e:
        try:
            raw_body = e.read().decode("utf-8", errors="replace").strip()
            try:
                parsed_err = json.loads(raw_body) if raw_body else {}
            except Exception:
                parsed_err = raw_body or f"HTTP {e.code}: {e.reason}"
        except Exception:
            parsed_err = f"HTTP {e.code}: {e.reason}"
        err_msg = _extract_error(parsed_err)
        print(f"[Tronado] GetOrderToken HTTP {e.code}: {err_msg}")
        return False, {"error": f"خطای درگاه ترونادو (HTTP {e.code}):\n{err_msg}", "raw": parsed_err}
    except Exception as exc:
        print(f"[Tronado] GetOrderToken error: {exc}")
        return False, {"error": str(exc)}

    if not isinstance(parsed, dict):
        return False, {"error": f"پاسخ ناشناخته از API ترونادو: {str(parsed)[:300]}", "raw": parsed}

    # Normalize token field — API may use different capitalizations
    data_inner = parsed.get("data") or parsed.get("Data")
    if isinstance(data_inner, dict):
        token = (
            data_inner.get("Token") or data_inner.get("token")
            or data_inner.get("OrderToken") or data_inner.get("orderToken")
        )
    else:
        token = None

    if not token:
        token = (
            parsed.get("Token") or parsed.get("token")
            or parsed.get("OrderToken") or parsed.get("orderToken")
        )

    if not token:
        err_msg = _extract_error(parsed)
        return False, {"error": f"خطا در دریافت توکن از ترونادو:\n{err_msg}", "raw": parsed}

    payment_url = build_tronado_payment_url(str(token))
    return True, {
        "token":       str(token),
        "payment_url": payment_url,
    }


def is_tronado_callback_valid(payload: dict) -> bool:
    """
    Return True if the incoming POST payload looks like a valid Tronado payment callback.
    Tronado only sends a callback on SUCCESSFUL payment, so any valid callback = paid.
    A valid callback must have PaymentID and either TronAmount or Wallet.
    """
    if not isinstance(payload, dict):
        return False
    has_id = bool(
        payload.get("PaymentID") or payload.get("paymentId")
        or payload.get("payment_id") or payload.get("OrderId") or payload.get("orderId")
    )
    return has_id


def get_tronado_callback_base_url() -> str:
    """
    Return the base URL for Tronado callback registration.
    Tries server_public_url setting, then auto-detects public IP.
    Returns empty string if not determinable.
    """
    base = (setting_get("server_public_url", "") or "").strip().rstrip("/")
    if base:
        # Ensure port is present for http:// bare URLs
        try:
            import urllib.parse as _up
            parsed = _up.urlparse(base)
            if parsed.scheme == "http" and parsed.port is None:
                from ..gateways.nowpayments import get_nowpayments_webhook_port
                port = get_nowpayments_webhook_port()
                netloc = f"{parsed.hostname}:{port}"
                return _up.urlunparse(parsed._replace(netloc=netloc))
        except Exception:
            pass
        return base
    # Auto-detect
    try:
        from ..gateways.nowpayments import detect_public_ip, get_nowpayments_webhook_port
        ip = detect_public_ip()
        if ip:
            port = get_nowpayments_webhook_port()
            return f"http://{ip}:{port}"
    except Exception:
        pass
    return ""


def build_tronado_callback_url(payment_id: int, bot_username: str) -> str:
    """Build the callback URL for a specific payment."""
    base = get_tronado_callback_base_url()
    if not base:
        return ""
    slug = (bot_username or "").lstrip("@").strip().lower()
    return f"{base}/tronado/{slug}/{payment_id}/callback"
