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

PLISIO_BASE_URL = "https://api.plisio.net/api/v1"


def normalize_bot_username(bot_username: str) -> str:
    """Strip leading @ from bot username."""
    return bot_username.lstrip("@")


def get_plisio_callback_urls(bot_username: str) -> dict:
    """Build callback URLs for a Plisio invoice."""
    base = (setting_get("server_public_url", "") or "").rstrip("/")
    slug = normalize_bot_username(bot_username)
    return {
        "callback_url":         f"{base}/plisio/{slug}/callback",
        "success_callback_url": f"{base}/plisio/{slug}/success",
        "fail_callback_url":    f"{base}/plisio/{slug}/fail",
    }


def create_plisio_invoice(amount_toman: int, payment_id, user_id, bot_username: str, description: str):
    """
    Create a new Plisio invoice.

    Converts *amount_toman* to USD using the ``plisio_usd_rate`` setting,
    then calls the Plisio REST API.

    Returns:
        ``(True,  {"txn_id": ..., "invoice_url": ...})``  on success
        ``(False, {"error": ...})``                        on failure
    """
    api_key = (setting_get("plisio_api_key", "") or "").strip()
    if not api_key:
        return False, {"error": "کلید API Plisio ثبت نشده است."}

    try:
        usd_rate = float(setting_get("plisio_usd_rate", "60000") or "60000")
    except (ValueError, TypeError):
        usd_rate = 60000.0
    if usd_rate <= 0:
        return False, {"error": "نرخ دلار نامعتبر است."}

    amount_usd      = round(amount_toman / usd_rate, 4)
    source_currency = ((setting_get("plisio_source_currency", "") or "") or "USD").strip()
    allowed_psys    = (setting_get("plisio_allowed_psys_cids", "") or "").strip()
    expire_min      = ((setting_get("plisio_expire_min", "") or "") or "60").strip()

    urls = get_plisio_callback_urls(bot_username)

    params = {
        "api_key":              api_key,
        "currency":             source_currency,
        "order_name":           description[:100],
        "order_number":         str(payment_id),
        "amount":               amount_usd,
        "source_currency":      source_currency,
        "callback_url":         urls["callback_url"],
        "success_callback_url": urls["success_callback_url"],
        "fail_callback_url":    urls["fail_callback_url"],
        "expire_min":           expire_min,
    }
    if allowed_psys:
        params["allowed_psys_cids"] = allowed_psys

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
    return True, {"txn_id": txn_id, "invoice_url": invoice_url}


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
