# -*- coding: utf-8 -*-
"""
Plisio crypto payment gateway.
API docs: https://plisio.net/documentation
"""
import hashlib
import hmac
import json

import requests

from ..db import setting_get
from .crypto import fetch_crypto_prices

PLISIO_BASE_URL = "https://api.plisio.net/api/v1"


def normalize_bot_username(bot_username: str) -> str:
    """Strip leading @ from bot username."""
    return bot_username.lstrip("@")


def get_plisio_callback_urls(bot_username: str) -> dict:
    """Build callback URLs for a Plisio invoice (only used when server_public_url is set)."""
    base = (setting_get("server_public_url", "") or "").rstrip("/")
    if not base:
        return {}
    slug = normalize_bot_username(bot_username)
    return {
        "callback_url":         f"{base}/plisio/{slug}/callback",
        "success_callback_url": f"{base}/plisio/{slug}/success",
        "fail_callback_url":    f"{base}/plisio/{slug}/fail",
    }


def create_plisio_invoice(amount_toman: int, payment_id, user_id, bot_username: str, description: str):
    """
    Create a new Plisio invoice.

    Converts *amount_toman* to USDT using SwapWallet live rate,
    then calls the Plisio REST API.

    Returns:
        ``(True,  {"txn_id": ..., "invoice_url": ..., "amount_usdt": ..., "usdt_rate": ...})``  on success
        ``(False, {"error": ...})``                                                               on failure
    """
    api_key = (setting_get("plisio_api_key", "") or "").strip()
    if not api_key:
        return False, {"error": "کلید API Plisio ثبت نشده است."}

    # Get live USDT/IRT rate from SwapWallet API
    prices = fetch_crypto_prices()
    usdt_irt = prices.get("USDT", 0)
    if not usdt_irt or usdt_irt <= 0:
        return False, {"error": "دریافت نرخ USDT ناموفق بود. لطفاً مجدداً تلاش کنید."}

    amount_usdt  = round(amount_toman / usdt_irt, 4)

    # Minimum amount enforced by Plisio per currency
    PLISIO_MIN_USDT = 5.0
    if amount_usdt < PLISIO_MIN_USDT:
        min_toman = int(PLISIO_MIN_USDT * usdt_irt)
        from ..helpers import fmt_price
        return False, {"error": (
            f"حداقل مبلغ پرداخت از طریق Plisio برابر {PLISIO_MIN_USDT:.0f} USDT "
            f"(معادل {fmt_price(min_toman)} تومان) است.\n"
            "لطفاً درگاه دیگری انتخاب کنید یا مبلغ را افزایش دهید."
        )}

    # Crypto currency to receive — default USDT_TRX (USDT on TRON)
    crypto_cur  = ((setting_get("plisio_crypto_currency", "") or "") or "USDT_TRX").strip().upper()
    allowed_psys = (setting_get("plisio_allowed_psys_cids", "") or "").strip()
    expire_min   = ((setting_get("plisio_expire_min", "") or "") or "60").strip()

    params = {
        "api_key":      api_key,
        "currency":     crypto_cur,
        "order_name":   description[:100],
        "order_number": str(payment_id),
        "amount":       amount_usdt,
        "expire_min":   expire_min,
    }
    if allowed_psys:
        params["allowed_psys_cids"] = allowed_psys

    # Optional webhook callbacks (only if server_public_url is configured)
    urls = get_plisio_callback_urls(bot_username)
    if urls:
        params["callback_url"]         = urls["callback_url"]
        params["success_callback_url"] = urls["success_callback_url"]
        params["fail_callback_url"]    = urls["fail_callback_url"]

    try:
        resp = requests.get(
            f"{PLISIO_BASE_URL}/invoices/new",
            params=params,
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        return False, {"error": str(exc)}

    if data.get("status") != "success":
        inner = data.get("data", {})
        if isinstance(inner, dict):
            msg = inner.get("message") or inner.get("error") or str(inner)
        else:
            msg = str(inner)
        return False, {"error": msg or "خطای ناشناخته از Plisio"}

    invoice_data = data.get("data", {})
    txn_id       = invoice_data.get("txn_id", "")
    invoice_url  = invoice_data.get("invoice_url", "")
    return True, {"txn_id": txn_id, "invoice_url": invoice_url, "amount_usdt": amount_usdt, "usdt_rate": usdt_irt}


def check_plisio_invoice(txn_id: str):
    """
    Poll the status of an existing Plisio invoice.

    Returns:
        ``(True,  status_str)``  on success
        ``(False, None)``        on API error
    """
    api_key = (setting_get("plisio_api_key", "") or "").strip()
    if not api_key or not txn_id:
        return False, None
    try:
        resp = requests.get(
            f"{PLISIO_BASE_URL}/transactions/{txn_id}",
            params={"api_key": api_key},
            timeout=10,
        )
        data = resp.json()
    except Exception:
        return False, None

    if data.get("status") != "success":
        return False, None

    status = (data.get("data") or {}).get("status", "")
    return True, status


def verify_plisio_json_callback(data: dict) -> bool:
    """
    Verify a Plisio IPN POST callback using HMAC-SHA1.

    Pops ``verify_hash`` from *data* (mutates the dict), JSON-encodes the
    remaining fields (sorted keys, no extra spaces), computes HMAC-SHA1
    keyed with the API key, and compares with the received hash.

    Returns ``True`` if the signature is valid.
    """
    api_key = (setting_get("plisio_api_key", "") or "").strip()
    if not api_key:
        return False

    received_hash = data.pop("verify_hash", None)
    if not received_hash:
        return False

    payload  = json.dumps(data, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(api_key.encode(), payload.encode(), hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, received_hash)


def is_plisio_paid(status: str) -> bool:
    """Return True when the invoice is effectively paid."""
    return status in ("completed", "mismatch")


def is_plisio_pending(status: str) -> bool:
    """Return True when the invoice is still awaiting payment."""
    return status in ("new", "pending", "pending internal")


def is_plisio_failed(status: str) -> bool:
    """Return True when the invoice has failed/expired/been cancelled."""
    return status in ("expired", "error", "cancelled", "cancelled duplicate")
