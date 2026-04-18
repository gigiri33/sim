# -*- coding: utf-8 -*-
"""
License Manager — سیستم لایسنس چندلایه
مسئول: فعال‌سازی، بررسی دوره‌ای، limited mode و ارسال نوتیفیکیشن
"""
import hashlib
import json
import logging
import os
import platform
import socket
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from functools import wraps

log = logging.getLogger("license_manager")

# ── Constants ─────────────────────────────────────────────────────────────────
LICENSE_API_URL           = os.getenv("LICENSE_API_URL", "https://license.seamless.dev/api/v1")
LICENSE_CHECK_INTERVAL    = int(os.getenv("LICENSE_CHECK_INTERVAL", "1800"))   # 30 min
LICENSE_NOTIFY_INTERVAL   = int(os.getenv("LICENSE_NOTIFY_INTERVAL_MINUTES", "360")) * 60  # 6h → seconds
LICENSE_GRACE_MINUTES     = int(os.getenv("LICENSE_GRACE_MINUTES", "60"))

_SETTINGS_KEY_STATE          = "license_state"           # active | expired | inactive
_SETTINGS_KEY_API_KEY        = "license_api_key"
_SETTINGS_KEY_EXPIRES_AT     = "license_expires_at"
_SETTINGS_KEY_MACHINE_ID     = "license_machine_id"
_SETTINGS_KEY_LAST_CHECK     = "license_last_check"
_SETTINGS_KEY_LAST_NOTIFY    = "license_last_notify"
_SETTINGS_KEY_OWNER_TG_ID    = "license_owner_telegram_id"
_SETTINGS_KEY_OWNER_USERNAME = "license_owner_username"
_SETTINGS_KEY_BOT_USERNAME   = "license_bot_username"

# In-process cache
_lock               = threading.Lock()
_cached_active: bool | None = None
_cached_at: float           = 0.0
_CACHE_TTL: float           = 300.0   # 5 minutes


# ── Machine ID ────────────────────────────────────────────────────────────────

def _generate_machine_id() -> str:
    """Generate a stable machine fingerprint (hashed)."""
    parts = []
    try:
        parts.append(socket.gethostname())
    except Exception:
        pass
    try:
        parts.append(platform.node())
    except Exception:
        pass
    try:
        parts.append(platform.machine())
    except Exception:
        pass
    # Try to get MAC or a persistent machine-id from /etc/machine-id
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r") as fh:
                mid = fh.read().strip()
                if mid:
                    parts.append(mid)
                    break
        except Exception:
            pass
    seed = "|".join(parts) or "seamless-default"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


# ── Settings I/O (lazy import to avoid circular imports) ──────────────────────

def _setting_get(key: str, default: str = "") -> str:
    try:
        from .db import setting_get
        v = setting_get(key, default)
        return v if v is not None else default
    except Exception:
        return default


def _setting_set(key: str, value: str) -> None:
    try:
        from .db import setting_set
        setting_set(key, value)
    except Exception as e:
        log.error("Could not persist setting %s: %s", key, e)


# ── Core helpers ──────────────────────────────────────────────────────────────

def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_expiry(expires_at: str) -> float | None:
    """Return unix timestamp from ISO string, or None if unparseable."""
    if not expires_at:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(expires_at, fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _invalidate_cache() -> None:
    global _cached_at
    with _lock:
        _cached_at = 0.0


# ── API call ──────────────────────────────────────────────────────────────────

def _call_license_api(endpoint: str, payload: dict) -> dict:
    """POST to the license server. Returns parsed JSON or raises."""
    url = f"{LICENSE_API_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Seamless-Bot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            return json.loads(body)
        except Exception:
            raise RuntimeError(f"License API HTTP {e.code}: {body[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"License API unreachable: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"License API error: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def get_or_create_machine_id() -> str:
    """Return persisted machine_id, creating it if needed."""
    mid = _setting_get(_SETTINGS_KEY_MACHINE_ID)
    if not mid:
        mid = _generate_machine_id()
        _setting_set(_SETTINGS_KEY_MACHINE_ID, mid)
    return mid


def activate_license(
    api_key: str,
    bot_username: str = "",
    owner_telegram_id: int = 0,
    owner_username: str = "",
) -> dict:
    """
    Attempt to activate the license with the provided api_key.
    Returns {"ok": True, "expires_at": "...", "message": "..."} or
            {"ok": False, "message": "..."}
    """
    api_key = api_key.strip()
    if not api_key:
        return {"ok": False, "message": "کلید API نمی‌تواند خالی باشد."}

    machine_id = get_or_create_machine_id()

    payload = {
        "api_key":           api_key,
        "machine_id":        machine_id,
        "bot_username":      bot_username,
        "owner_telegram_id": owner_telegram_id,
        "owner_username":    owner_username,
    }

    try:
        result = _call_license_api("/activate", payload)
    except RuntimeError as e:
        log.warning("License activation failed: %s", e)
        # If the server cannot be reached, treat as network error (not invalid key)
        return {"ok": False, "message": f"خطا در اتصال به سرور لایسنس:\n{e}"}

    if result.get("ok") or result.get("status") == "active":
        expires_at = result.get("expires_at", "")
        _setting_set(_SETTINGS_KEY_STATE,          "active")
        _setting_set(_SETTINGS_KEY_API_KEY,        api_key)
        _setting_set(_SETTINGS_KEY_EXPIRES_AT,     expires_at)
        _setting_set(_SETTINGS_KEY_LAST_CHECK,     _now_iso())
        _setting_set(_SETTINGS_KEY_BOT_USERNAME,   bot_username)
        _setting_set(_SETTINGS_KEY_OWNER_TG_ID,    str(owner_telegram_id))
        _setting_set(_SETTINGS_KEY_OWNER_USERNAME, owner_username)
        _invalidate_cache()
        log.info("License activated. Expires: %s", expires_at)
        return {"ok": True, "expires_at": expires_at, "message": result.get("message", "لایسنس با موفقیت فعال شد.")}
    else:
        msg = result.get("message") or result.get("error") or "لایسنس نامعتبر است."
        log.warning("License activation rejected: %s", msg)
        return {"ok": False, "message": msg}


def check_license(force: bool = False) -> bool:
    """
    Check license validity (with in-process cache).
    Returns True if license is currently active.
    """
    global _cached_active, _cached_at

    with _lock:
        if not force and _cached_active is not None and (time.monotonic() - _cached_at) < _CACHE_TTL:
            return _cached_active

    active = _check_license_internal(force=force)

    with _lock:
        _cached_active = active
        _cached_at = time.monotonic()

    return active


def _check_license_internal(force: bool = False) -> bool:
    """The actual license check logic (no caching)."""
    state      = _setting_get(_SETTINGS_KEY_STATE, "inactive")
    api_key    = _setting_get(_SETTINGS_KEY_API_KEY)
    expires_at = _setting_get(_SETTINGS_KEY_EXPIRES_AT)
    last_check = _setting_get(_SETTINGS_KEY_LAST_CHECK)

    # No key at all → inactive
    if not api_key:
        if state != "inactive":
            _setting_set(_SETTINGS_KEY_STATE, "inactive")
        return False

    # Check expiry from cached value first
    if expires_at:
        exp_ts = _parse_expiry(expires_at)
        if exp_ts is not None:
            grace = LICENSE_GRACE_MINUTES * 60
            now = _now_ts()
            if now > exp_ts + grace:
                _setting_set(_SETTINGS_KEY_STATE, "expired")
                return False

    # Decide if we need to call the remote API
    should_call_api = force
    if not should_call_api and last_check:
        try:
            last_ts = datetime.strptime(last_check, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            if _now_ts() - last_ts > LICENSE_CHECK_INTERVAL:
                should_call_api = True
        except Exception:
            should_call_api = True
    elif not last_check:
        should_call_api = True

    if should_call_api:
        machine_id = get_or_create_machine_id()
        try:
            result = _call_license_api("/check", {
                "api_key":    api_key,
                "machine_id": machine_id,
            })
            _setting_set(_SETTINGS_KEY_LAST_CHECK, _now_iso())
            remote_state = result.get("status", "inactive")
            if remote_state == "active":
                new_exp = result.get("expires_at", expires_at)
                _setting_set(_SETTINGS_KEY_STATE,      "active")
                _setting_set(_SETTINGS_KEY_EXPIRES_AT, new_exp or "")
                _invalidate_cache()
                return True
            else:
                _setting_set(_SETTINGS_KEY_STATE, "expired")
                _invalidate_cache()
                return False
        except RuntimeError as e:
            # Network unreachable: fall back to cached state with grace period
            log.warning("Remote license check failed (falling back to cache): %s", e)
            # If state was already active and expiry hasn't passed, keep running
            if state == "active" and expires_at:
                exp_ts = _parse_expiry(expires_at)
                if exp_ts and _now_ts() < exp_ts + LICENSE_GRACE_MINUTES * 60:
                    return True
            return state == "active"

    return state == "active"


def is_license_active() -> bool:
    """Fast check (uses cache). Use this in handlers."""
    return check_license(force=False)


def is_limited_mode() -> bool:
    """True when bot should operate in limited mode (no active license)."""
    return not is_license_active()


def require_license() -> bool:
    """
    Strict check — bypasses cache.
    Use in critical paths (worker, API, startup).
    """
    return check_license(force=True)


def get_license_status_text() -> str:
    """Return a human-readable Farsi status block."""
    state      = _setting_get(_SETTINGS_KEY_STATE, "inactive")
    expires_at = _setting_get(_SETTINGS_KEY_EXPIRES_AT, "")
    last_check = _setting_get(_SETTINGS_KEY_LAST_CHECK, "")
    machine_id = _setting_get(_SETTINGS_KEY_MACHINE_ID, "")
    bot_uname  = _setting_get(_SETTINGS_KEY_BOT_USERNAME, "")
    owner_id   = _setting_get(_SETTINGS_KEY_OWNER_TG_ID, "")
    owner_un   = _setting_get(_SETTINGS_KEY_OWNER_USERNAME, "")

    state_label = {
        "active":   "✅ فعال",
        "expired":  "❌ منقضی‌شده",
        "inactive": "🔴 غیرفعال",
    }.get(state, f"❓ {state}")

    lines = [
        "🔐 <b>وضعیت لایسنس</b>",
        "",
        f"وضعیت: <b>{state_label}</b>",
    ]

    if expires_at:
        lines.append(f"انقضا: <code>{expires_at}</code>")
        exp_ts = _parse_expiry(expires_at)
        if exp_ts:
            remaining = exp_ts - _now_ts()
            if remaining > 0:
                days = int(remaining // 86400)
                hours = int((remaining % 86400) // 3600)
                lines.append(f"زمان باقی‌مانده: <b>{days} روز و {hours} ساعت</b>")
            else:
                lines.append("زمان باقی‌مانده: <b>منقضی شده</b>")

    if last_check:
        lines.append(f"آخرین بررسی: <code>{last_check}</code>")
    if machine_id:
        lines.append(f"Machine ID: <code>{machine_id}</code>")
    if bot_uname:
        lines.append(f"ربات: @{bot_uname}")
    if owner_id:
        lines.append(f"مالک ID: <code>{owner_id}</code>")
    if owner_un:
        lines.append(f"مالک: @{owner_un}")

    return "\n".join(lines)


def notify_expired_if_needed(bot_instance, owner_id: int) -> None:
    """
    Send expiry notification to owner if license has expired and
    the notify interval has passed.
    """
    if is_license_active():
        return

    last_notify_str = _setting_get(_SETTINGS_KEY_LAST_NOTIFY, "")
    if last_notify_str:
        try:
            last_ts = datetime.strptime(last_notify_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            if _now_ts() - last_ts < LICENSE_NOTIFY_INTERVAL:
                return
        except Exception:
            pass

    msg = (
        "🚫 <b>لایسنس ربات شما به پایان رسیده و ربات در حال حاضر خاموش است.</b>\n\n"
        "برای تمدید، دیگر وقتشه رباتت رو به Seamless Premium ارتقا بدی 🚀\n"
        "ربات با کلی امکانات\n\n"
        "برای اطلاعات بیشتر و خرید اشتراک به @Emad_Habibnia پیام بدهید."
    )
    try:
        bot_instance.send_message(owner_id, msg, parse_mode="HTML")
        _setting_set(_SETTINGS_KEY_LAST_NOTIFY, _now_iso())
        log.info("Sent expiry notification to owner %d", owner_id)
    except Exception as e:
        log.warning("Could not send expiry notification: %s", e)


# ── Decorator ─────────────────────────────────────────────────────────────────

def license_required(handler_func):
    """
    Decorator for telebot message/callback handlers.
    If license is inactive → show limited-mode message to regular users.
    Admins/owners always pass through.
    """
    @wraps(handler_func)
    def wrapper(*args, **kwargs):
        # Import here to avoid circular imports
        from .helpers import is_admin
        from .config import ADMIN_IDS

        # Determine user id from first argument (Message or CallbackQuery)
        target = args[0] if args else None
        uid = None
        if target is not None:
            if hasattr(target, "from_user") and target.from_user:
                uid = target.from_user.id
            elif hasattr(target, "chat") and target.chat:
                uid = target.chat.id

        # Admins/owners always bypass license check
        if uid and (uid in ADMIN_IDS or is_admin(uid)):
            return handler_func(*args, **kwargs)

        if is_license_active():
            return handler_func(*args, **kwargs)

        # Limited mode — reject for regular users
        _send_limited_mode_message(target)
        return None

    return wrapper


def _send_limited_mode_message(target) -> None:
    """Send the limited-mode rejection message."""
    try:
        from .bot_instance import bot
        msg = (
            "🚫 ربات در حال حاضر غیرفعال است.\n\n"
            "برای تمدید اشتراک به @Emad_Habibnia پیام بدهید."
        )
        if hasattr(target, "message") and target.message:
            # CallbackQuery
            try:
                bot.answer_callback_query(target.id, "🚫 ربات غیرفعال است.", show_alert=True)
            except Exception:
                pass
            try:
                bot.send_message(target.message.chat.id, msg, parse_mode="HTML")
            except Exception:
                pass
        elif hasattr(target, "chat") and target.chat:
            # Message
            try:
                bot.send_message(target.chat.id, msg, parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        log.debug("Could not send limited mode message: %s", e)


# ── Background checker ────────────────────────────────────────────────────────

def _license_background_loop(bot_instance, owner_id: int) -> None:
    """Runs in a daemon thread. Periodically checks and enforces license state."""
    while True:
        try:
            was_active = is_license_active()
            now_active = check_license(force=True)

            if was_active and not now_active:
                log.warning("License transitioned to EXPIRED/INACTIVE. Enabling limited mode.")
                _invalidate_cache()

            if not now_active and owner_id:
                notify_expired_if_needed(bot_instance, owner_id)

        except Exception as e:
            log.error("License background loop error: %s", e)

        time.sleep(LICENSE_CHECK_INTERVAL)


def start_license_background_check(bot_instance, owner_id: int) -> threading.Thread:
    """Start the background license checker thread."""
    t = threading.Thread(
        target=_license_background_loop,
        args=(bot_instance, owner_id),
        daemon=True,
        name="license-checker",
    )
    t.start()
    log.info("License background checker started (interval=%ds)", LICENSE_CHECK_INTERVAL)
    return t


# ── Activation flow helpers ───────────────────────────────────────────────────

LIMITED_MODE_TEXT = (
    "🔒 <b>ربات در حالت محدود (Limited Mode) اجرا می‌شود.</b>\n\n"
    "لایسنس فعال‌سازی نشده یا منقضی شده است.\n"
    "برای فعال‌سازی، از منوی زیر اقدام کنید."
)

ACTIVATION_SUCCESS_TEXT = (
    "✅ <b>لایسنس با موفقیت فعال شد!</b>\n\n"
    "ربات اکنون در حالت کامل اجرا می‌شود.\n"
    "تاریخ انقضا: {expires_at}"
)

ACTIVATION_FAIL_TEXT = (
    "❌ <b>فعال‌سازی لایسنس ناموفق بود.</b>\n\n"
    "پیام خطا: {message}\n\n"
    "کلید API را بررسی کرده و دوباره تلاش کنید،\n"
    "یا با @Emad_Habibnia تماس بگیرید."
)

API_KEY_PROMPT_TEXT = (
    "🔐 <b>فعال‌سازی لایسنس</b>\n\n"
    "لطفاً <b>API Key</b> لایسنس خود را وارد کنید.\n"
    "این کلید را از @Emad_Habibnia دریافت می‌کنید.\n\n"
    "⬅️ برای لغو /cancel بزنید."
)
