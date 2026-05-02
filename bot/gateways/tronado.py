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
import urllib.parse

from ..db import setting_get
from .crypto import fetch_crypto_prices

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

    # Convert toman → TRX (case-insensitive lookup)
    prices = fetch_crypto_prices()
    trx_irt = next((v for k, v in prices.items() if k.upper() == "TRX"), 0)
    if not trx_irt or trx_irt <= 0:
        # Fallback: fetch TRX/USDT from CoinGecko + USDT/IRT from SwapWallet
        try:
            import urllib.request as _ur
            with _ur.urlopen("https://api.coingecko.com/api/v3/simple/price?ids=tron&vs_currencies=usd", timeout=8) as _r:
                _cg = json.loads(_r.read().decode())
            trx_usd = float(_cg.get("tron", {}).get("usd", 0) or 0)
            usdt_irt = next((v for k, v in prices.items() if k.upper() in ("USDT", "USDTTRC20")), 0)
            if trx_usd > 0 and usdt_irt > 0:
                trx_irt = trx_usd * usdt_irt
        except Exception:
            pass
    if not trx_irt or trx_irt <= 0:
        return False, {"error": "دریافت نرخ TRX ناموفق بود. لطفاً مجدداً تلاش کنید."}
    tron_amount = round(amount_toman / trx_irt, 6)
    print(f"[Tronado] TRX rate: {trx_irt}, toman: {amount_toman}, TronAmount: {tron_amount}")

    # wageFromBusinessPercentage: 100 = merchant absorbs Tronado's 20% fee
    # (customer pays exactly TronAmount — no surprise surcharges)
    # Set lower if you want Tronado to add part of their fee to the customer's bill.
    try:
        wage_pct = int(setting_get("tronado_wage_from_business", "100") or "100")
        wage_pct = max(0, min(100, wage_pct))
    except ValueError:
        wage_pct = 100
    payload = {
        "TronAmount":              tron_amount,
        "PaymentID":               str(order_id),
        "UserTelegramId":          int(user_id),
        "WalletAddress":           wallet_address,
        "Description":             (description or "")[:200],
        "wageFromBusinessPercentage": wage_pct,
        "apiVersion":              1,
    }
    if callback_url and (callback_url.startswith("https://") or callback_url.startswith("http://")):
        payload["CallbackUrl"] = callback_url
    elif callback_url:
        print(f"[Tronado] Skipping CallbackUrl — unexpected scheme (got: {callback_url[:50]})")

    print(f"[Tronado] Sending payload: {payload}")

    # API docs show form-data (--form) for GetOrderToken, not JSON
    form_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/GetOrderToken",
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
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

    # Normalize token field — API returns Data.Token and Data.FullPaymentUrl
    data_inner = parsed.get("Data") or parsed.get("data")
    if isinstance(data_inner, dict):
        token = (
            data_inner.get("Token") or data_inner.get("token")
            or data_inner.get("OrderToken") or data_inner.get("orderToken")
        )
        full_pay_url = (
            data_inner.get("FullPaymentUrl") or data_inner.get("fullPaymentUrl") or ""
        )
    else:
        token = None
        full_pay_url = ""

    if not token:
        token = (
            parsed.get("Token") or parsed.get("token")
            or parsed.get("OrderToken") or parsed.get("orderToken")
        )

    if not token:
        err_msg = _extract_error(parsed)
        return False, {"error": f"خطا در دریافت توکن از ترونادو:\n{err_msg}", "raw": parsed}

    # Prefer FullPaymentUrl from API; fall back to building from token
    payment_url = full_pay_url if full_pay_url else build_tronado_payment_url(str(token))
    return True, {
        "token":       str(token),
        "payment_url": payment_url,
        "tron_amount": tron_amount,
        "trx_rate":    trx_irt,
    }


def is_tronado_callback_valid(payload: dict) -> bool:
    """
    Return True if the incoming POST payload looks like a valid Tronado payment callback.
    Tronado only sends a callback on SUCCESSFUL payment, so any valid callback = paid.
    Observed formats:
      - {PaymentID, TronAmount, ActualTronAmount, Wallet, CallbackUrl}
      - {UniqueCode, Hash, Wallet, PaymentID, UserTelegramId}  (same as GetStatus paid response)
    """
    if not isinstance(payload, dict):
        return False
    # Format 1: has UniqueCode + Hash (confirmed paid response format)
    if payload.get("UniqueCode") and payload.get("Hash"):
        return True
    # Format 2: classic callback fields
    has_id = bool(
        payload.get("PaymentID") or payload.get("paymentId")
        or payload.get("payment_id") or payload.get("OrderId") or payload.get("orderId")
        or payload.get("TronAmount") or payload.get("tronAmount")
    )
    return has_id


TRONADO_STATUS_BASE_URL = "https://bot.tronado.cloud"


def _tronado_order_status_url() -> str:
    """The GetStatus endpoint lives outside the versioned API path."""
    base = (setting_get("tronado_api_base_url", "") or "").strip().rstrip("/")
    # Strip /api/vN suffix if present — GetStatus uses /Order/GetStatus without versioning
    import re as _re
    root = _re.sub(r"/api/v\d+$", "", base) if base else TRONADO_STATUS_BASE_URL
    return f"{root}/Order/GetStatus"


def get_tronado_payment_status(order_id_or_token: str) -> dict:
    """
    Call POST /Order/GetStatus with the order token (or Tronado order ID).
    Per docs: Id can be the Tronado order token, or trndorderid_{our_payment_id}, or TXID.
    Returns parsed response dict, or {} on failure.
    """
    api_key = (setting_get("tronado_api_key", "") or "").strip()
    if not api_key or not order_id_or_token:
        return {}
    url = _tronado_order_status_url()
    # API docs show form-data (--form) for GetStatus, not JSON
    form_data = urllib.parse.urlencode({"Id": order_id_or_token}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept":       "application/json",
            "x-api-key":    api_key,
            "User-Agent":   "ConfigFlow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            _, parsed = _decode_response_body(resp)
        print(f"[Tronado] GetStatus({order_id_or_token[:16]}…): {str(parsed)[:200]}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        print(f"[Tronado] GetStatus error: {exc}")
        return {}


def get_tronado_status_by_payment_id(payment_id_str: str) -> dict:
    """
    Call POST /Order/GetStatus using the trndorderid_ prefix with our original PaymentID.
    Per docs: Id can be 'trndorderid_{our_order_id}'.
    """
    if not payment_id_str:
        return {}
    return get_tronado_payment_status(f"trndorderid_{payment_id_str}")


def is_tronado_response_paid(resp: dict) -> bool:
    """
    Return True if a GetStatus response indicates a paid/confirmed payment.
    Per API docs the response Data has IsPaid (bool) and OrderStatusTitle (string).
    Tronado also returns a flat dict with UniqueCode+Hash+Wallet when the payment
    is confirmed (same structure as the callback payload).
    """
    if not resp:
        return False
    # Flat paid-callback format: has UniqueCode and Hash at top level (no Error key)
    if isinstance(resp, dict) and resp.get("UniqueCode") and resp.get("Hash") and "Error" not in resp:
        return True
    data = resp.get("Data") or resp.get("data") or resp
    if isinstance(data, dict):
        # Primary check: IsPaid boolean (from API docs)
        is_paid = data.get("IsPaid") or data.get("isPaid")
        if is_paid is True:
            return True
        # Flat paid format nested inside Data
        if data.get("UniqueCode") and data.get("Hash") and "Error" not in data:
            return True
        # Fallback: check status title string
        status_val = (
            data.get("OrderStatusTitle") or data.get("Status") or data.get("status")
            or data.get("PaymentStatus") or data.get("paymentStatus") or ""
        )
        if str(status_val).lower() in ("paid", "completed", "success", "confirmed", "finish", "finished"):
            return True
    return False


def get_tronado_callback_base_url() -> str:
    """
    Return the base URL for Tronado callback registration.
    Accepts both https:// and http:// — use dedicated tronado_callback_url first,
    then fall back to server_public_url.
    """
    dedicated = (setting_get("tronado_callback_url", "") or "").strip().rstrip("/")
    if dedicated and (dedicated.startswith("https://") or dedicated.startswith("http://")):
        return dedicated
    base = (setting_get("server_public_url", "") or "").strip().rstrip("/")
    if base and (base.startswith("https://") or base.startswith("http://")):
        return base
    return ""


def build_tronado_callback_url(payment_id: int, bot_username: str) -> str:
    """Build the callback URL for a specific payment."""
    base = get_tronado_callback_base_url()
    if not base:
        return ""
    slug = (bot_username or "").lstrip("@").strip().lower()
    return f"{base}/tronado/{slug}/{payment_id}/callback"
