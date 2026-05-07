# -*- coding: utf-8 -*-
"""
CentralPay payment gateway — create payment links and verify orders.
API docs: https://centralapi.org/webservice/basic/
Auth: api_key in JSON body
Payment: GET redirect to returnUrl after payment
"""

import json
import random
import urllib.request
import urllib.error
import urllib.parse

from ..db import setting_get, get_user

CENTRALPAY_DEFAULT_GETLINK_URL = "https://centralapi.org/webservice/basic/getLink.php"
CENTRALPAY_DEFAULT_VERIFY_URL  = "https://centralapi.org/webservice/basic/verify.php"

# User-facing error messages
_ERR_MESSAGES = {
    "invalid_api_key":  "کلید API سنترال‌پی نامعتبر است.",
    "duplicate_orderId": "شناسه سفارش تکراری است. لطفاً دوباره تلاش کنید.",
    "invalid_orderId":  "پرداختی با این شناسه در سنترال‌پی پیدا نشد.",
    "amount_mismatch":  "مبلغ پرداختی با مبلغ سفارش مطابقت ندارد. لطفاً با پشتیبانی تماس بگیرید.",
    "callback_not_set": "آدرس Callback سنترال‌پی تنظیم نشده است.",
}


def _get_api_key() -> str:
    return (setting_get("centralpay_api_key", "") or "").strip()


def _get_getlink_url() -> str:
    url = (setting_get("centralpay_getlink_url", "") or "").strip()
    return url or CENTRALPAY_DEFAULT_GETLINK_URL


def _get_verify_url() -> str:
    url = (setting_get("centralpay_verify_url", "") or "").strip()
    return url or CENTRALPAY_DEFAULT_VERIFY_URL


def _get_link_type() -> str:
    """
    CentralPay getLink `type`.

    Default is `deposit` per CentralPay's basic API docs. Some merchant panels
    may not have deposit methods active; in that case support/admin can change
    this setting to the type provided by CentralPay support without code changes.
    """
    val = (setting_get("centralpay_link_type", "deposit") or "deposit").strip()
    return val or "deposit"


def get_centralpay_callback_base_url() -> str:
    """Return the base URL for CentralPay callback (returnUrl)."""
    dedicated = (setting_get("centralpay_callback_base_url", "") or "").strip().rstrip("/")
    if dedicated and (dedicated.startswith("https://") or dedicated.startswith("http://")):
        return dedicated
    # fallback to server_public_url
    base = (setting_get("server_public_url", "") or "").strip().rstrip("/")
    if base and (base.startswith("https://") or base.startswith("http://")):
        return base
    return ""


def build_centralpay_return_url(payment_id: int, bot_username: str) -> str:
    """Build the returnUrl for a specific payment."""
    base = get_centralpay_callback_base_url()
    if not base:
        return ""
    slug = (bot_username or "").lstrip("@").strip().lower()
    # create_centralpay_link() generates the final unique CentralPay orderId and
    # rewrites this placeholder query param before sending the request.
    return f"{base}/centralpay/callback?orderId={payment_id}&bot={urllib.parse.quote(slug)}"


def _return_url_with_order_id(return_url: str, cp_order_id: str) -> str:
    """Normalize callback URL and force query-string orderId to cp_order_id."""
    parsed = urllib.parse.urlparse(return_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    bot_slug = (query.get("bot") or _bot_username_from_return_url(return_url) or "").lstrip("@").strip().lower()
    query["orderId"] = str(cp_order_id)
    if bot_slug:
        query["bot"] = bot_slug
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        "/centralpay/callback",
        "",
        urllib.parse.urlencode(query),
        "",
    ))


def _decode_response(resp) -> tuple:
    raw = resp.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return "", {}
    try:
        return raw, json.loads(raw)
    except Exception:
        return raw, raw


def _extract_message(data) -> str:
    if isinstance(data, dict):
        inner = data.get("data") or data.get("Data") or {}
        if isinstance(inner, dict):
            msg = inner.get("message") or inner.get("Message") or inner.get("error") or ""
            if msg:
                return str(msg)[:300]
        for key in ("message", "Message", "error", "Error", "msg"):
            if data.get(key):
                return str(data[key])[:300]
        return json.dumps(data, ensure_ascii=False)[:300]
    return str(data)[:300]


def _bot_username_from_return_url(return_url: str) -> str:
    try:
        parts = [p for p in urllib.parse.urlparse(return_url).path.split("/") if p]
        if "centralpay" in parts:
            idx = parts.index("centralpay")
            if len(parts) > idx + 1:
                candidate = parts[idx + 1].lstrip("@").strip()
                if candidate and candidate != "callback":
                    return candidate
    except Exception:
        pass
    return ""


def _user_identifier(user_id: int) -> str:
    try:
        row = get_user(user_id)
        username = (row["username"] if row and "username" in row.keys() else "") or ""
        if username.strip():
            return username.strip().lstrip("@")
    except Exception:
        pass
    return str(user_id)


def create_centralpay_link(amount_toman: int, user_id: int, order_id, return_url: str):
    """
    Call POST /getLink.php to create a CentralPay payment link.

    A unique 6-hex suffix is appended to order_id before sending to CentralPay
    so the same payment_id can never collide with a previous submission.

    Returns:
        (True,  {"redirect_url": ..., "cp_order_id": ..., "raw": ...})   on success
        (False, {"error": ..., "raw": ...})                               on failure
    """
    api_key = _get_api_key()
    if not api_key:
        return False, {"error": "کلید API سنترال‌پی ثبت نشده است. از پنل مدیریت ← تنظیمات ← درگاه‌ها اقدام کنید.", "raw": {}}

    if not return_url:
        return False, {"error": _ERR_MESSAGES["callback_not_set"], "raw": {}}

    # Generate a unique CentralPay orderId (purely numeric, no hyphens) to avoid
    # duplicate_orderId rejections when the same payment_id is retried.
    # Format: {payment_id}{5_random_digits}  e.g. 14283429
    _unique_digits = random.randint(10000, 99999)
    cp_order_id = f"{order_id}{_unique_digits}"

    final_return_url = _return_url_with_order_id(return_url, cp_order_id)

    link_type = _get_link_type()
    bot_username = (
        dict(urllib.parse.parse_qsl(urllib.parse.urlparse(final_return_url).query)).get("bot")
        or _bot_username_from_return_url(final_return_url)
        or "unknown"
    )
    user_identifier = _user_identifier(user_id)
    description = f"Bot: @{bot_username} | User: @{user_identifier} | PaymentID: {order_id}"
    payload_dict = {
        "api_key":   api_key,
        "type":      link_type,
        "amount":    int(amount_toman),
        "userId":    user_id,
        "orderId":   cp_order_id,
        "returnUrl": final_return_url,
        "description": description,
    }
    payload = json.dumps(payload_dict).encode("utf-8")

    url = _get_getlink_url()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "ConfigFlow/1.0",
        },
        method="POST",
    )
    try:
        print(f"[CentralPay] getLink request: type={link_type} amount={int(amount_toman)} userId={user_id} orderId={cp_order_id} (payment_id={order_id}) returnUrl={final_return_url} description={description}")
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw, parsed = _decode_response(resp)
        print(f"[CentralPay] getLink response: {raw[:500]}")
    except urllib.error.HTTPError as e:
        try:
            raw_body = e.read().decode("utf-8", errors="replace").strip()
            try:
                parsed_err = json.loads(raw_body) if raw_body else {}
            except Exception:
                parsed_err = raw_body
        except Exception:
            parsed_err = f"HTTP {e.code}: {e.reason}"
        err_msg = _extract_message(parsed_err)
        print(f"[CentralPay] getLink HTTP {e.code}: {err_msg}")
        return False, {"error": f"خطای درگاه سنترال‌پی (HTTP {e.code}):\n{err_msg}", "raw": parsed_err}
    except Exception as exc:
        print(f"[CentralPay] getLink error: {exc}")
        return False, {"error": str(exc), "raw": {}}

    if not isinstance(parsed, dict):
        return False, {"error": f"پاسخ ناشناخته از API سنترال‌پی: {str(parsed)[:200]}", "raw": parsed}

    success = parsed.get("success") or parsed.get("Success")
    if not success:
        data_inner = parsed.get("data") or parsed.get("Data") or {}
        raw_msg = ""
        if isinstance(data_inner, dict):
            raw_msg = str(data_inner.get("message") or data_inner.get("Message") or "")
        if not raw_msg:
            raw_msg = _extract_message(parsed)
        friendly = _ERR_MESSAGES.get(raw_msg, raw_msg or "خطای ناشناخته از سنترال‌پی")
        return False, {"error": friendly, "raw": parsed}

    data_inner = parsed.get("data") or parsed.get("Data") or {}
    redirect_url = ""
    if isinstance(data_inner, dict):
        redirect_url = (
            data_inner.get("redirectUrl") or data_inner.get("redirect_url") or
            data_inner.get("paymentUrl")  or data_inner.get("payment_url") or ""
        )
    if not redirect_url:
        redirect_url = (
            parsed.get("redirectUrl") or parsed.get("redirect_url") or
            parsed.get("paymentUrl")  or ""
        )

    if not redirect_url:
        return False, {"error": f"سنترال‌پی لینک پرداخت برنگرداند: {raw[:300]}", "raw": parsed}

    return True, {"redirect_url": redirect_url, "cp_order_id": cp_order_id, "return_url": final_return_url, "type": link_type, "raw": parsed}


def verify_centralpay_order(order_id):
    """
    Call POST /verify.php to verify a CentralPay payment.

    Returns:
        (True,  {"status": "paid", "reference_id": ..., "amount": ...,
                 "user_id": ..., "user_card_number": ..., "raw": ...})   on success
        (False, {"status": "failed", "error": ..., "raw": ...})          on failure
    """
    api_key = _get_api_key()
    if not api_key:
        return False, {"status": "error", "error": "کلید API سنترال‌پی ثبت نشده است.", "raw": {}}

    payload = json.dumps({
        "api_key": api_key,
        "orderId": str(order_id),
    }).encode("utf-8")

    url = _get_verify_url()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "ConfigFlow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw, parsed = _decode_response(resp)
        print(f"[CentralPay] verify orderId={order_id} response: {raw[:500]}")
    except urllib.error.HTTPError as e:
        try:
            raw_body = e.read().decode("utf-8", errors="replace").strip()
            try:
                parsed_err = json.loads(raw_body) if raw_body else {}
            except Exception:
                parsed_err = raw_body
        except Exception:
            parsed_err = f"HTTP {e.code}: {e.reason}"
        err_msg = _extract_message(parsed_err)
        print(f"[CentralPay] verify HTTP {e.code}: {err_msg}")
        return False, {"status": "error", "error": f"خطای API سنترال‌پی (HTTP {e.code}): {err_msg}", "raw": parsed_err}
    except Exception as exc:
        print(f"[CentralPay] verify error: {exc}")
        return False, {"status": "error", "error": str(exc), "raw": {}}

    if not isinstance(parsed, dict):
        return False, {"status": "error", "error": f"پاسخ ناشناخته از API سنترال‌پی: {str(parsed)[:200]}", "raw": parsed}

    success = parsed.get("success") or parsed.get("Success")

    if success:
        data_inner = parsed.get("data") or parsed.get("Data") or {}
        if not isinstance(data_inner, dict):
            data_inner = {}
        reference_id     = str(data_inner.get("referenceId") or data_inner.get("reference_id") or "")
        amount           = data_inner.get("amount") or data_inner.get("Amount") or 0
        returned_user_id = data_inner.get("userId") or data_inner.get("user_id") or 0
        card_number      = str(data_inner.get("userCardNumber") or data_inner.get("user_card_number") or "")
        return True, {
            "status":           "paid",
            "reference_id":     reference_id,
            "amount":           int(amount) if amount else 0,
            "user_id":          int(returned_user_id) if returned_user_id else 0,
            "user_card_number": card_number,
            "raw":              parsed,
        }

    # failed
    data_inner = parsed.get("data") or parsed.get("Data") or {}
    raw_msg = ""
    if isinstance(data_inner, dict):
        raw_msg = str(data_inner.get("message") or data_inner.get("Message") or "")
    if not raw_msg:
        raw_msg = _extract_message(parsed)
    friendly = _ERR_MESSAGES.get(raw_msg, raw_msg or "پرداخت تأیید نشد.")
    return False, {"status": "failed", "error": friendly, "raw": parsed}


def normalize_centralpay_verify_response(resp: dict) -> str:
    """
    Normalise a verify response to one of:
      "paid" | "failed" | "error" | "unknown"
    """
    if not resp or not isinstance(resp, dict):
        return "unknown"
    status = resp.get("status", "")
    if status == "paid":
        return "paid"
    if status in ("failed", "error"):
        return status
    # Check raw API response
    raw = resp.get("raw") or {}
    if not isinstance(raw, dict):
        return "unknown"
    success = raw.get("success") or raw.get("Success")
    if success:
        return "paid"
    data_inner = raw.get("data") or raw.get("Data") or {}
    if isinstance(data_inner, dict):
        msg = str(data_inner.get("message") or data_inner.get("Message") or "").lower()
        if msg == "invalid_orderid":
            return "failed"
        if msg == "invalid_api_key":
            return "error"
    return "unknown"
