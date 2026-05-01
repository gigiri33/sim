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
LICENSE_API_URL           = os.getenv("LICENSE_API_URL", "")
LICENSE_CHECK_INTERVAL    = int(os.getenv("LICENSE_CHECK_INTERVAL", "1800"))   # 30 min
LICENSE_NOTIFY_INTERVAL   = int(os.getenv("LICENSE_NOTIFY_INTERVAL_MINUTES", "360")) * 60  # 6h → seconds
LICENSE_GRACE_MINUTES     = int(os.getenv("LICENSE_GRACE_MINUTES", "60"))

_SETTINGS_KEY_STATE          = "license_state"           # active | expired | inactive
_SETTINGS_KEY_API_KEY        = "license_api_key"
_SETTINGS_KEY_API_URL        = "license_api_url_base"     # stored API URL (overrides env var)
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

def _get_api_base_url() -> str:
    """Return the active license API base URL: settings > env var."""
    stored = _setting_get(_SETTINGS_KEY_API_URL)
    if stored:
        return stored.rstrip("/")
    if LICENSE_API_URL:
        return LICENSE_API_URL.rstrip("/")
    raise RuntimeError(
        "آدرس سرور لایسنس (LICENSE_API_URL) تنظیم نشده است.\n"
        "هنگام فعال‌سازی، API URL را وارد کنید."
    )


def _call_license_api(endpoint: str, payload: dict) -> dict:
    """POST to the license server. Returns parsed JSON or raises."""
    base = _get_api_base_url()
    url = f"{base}/{endpoint.lstrip('/')}"
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
    api_url: str = "",
    bot_username: str = "",
    owner_telegram_id: int = 0,
    owner_username: str = "",
) -> dict:
    """
    Attempt to activate the license with the provided api_key and api_url.
    Returns {"ok": True, "expires_at": "...", "message": "..."} or
            {"ok": False, "message": "..."}
    """
    api_key = api_key.strip()
    if not api_key:
        return {"ok": False, "message": "کلید API نمی‌تواند خالی باشد."}

    # Save API URL first so _call_license_api can use it
    if api_url:
        _setting_set(_SETTINGS_KEY_API_URL, api_url.strip().rstrip("/"))

    machine_id = get_or_create_machine_id()

    payload = {
        "api_key":           api_key,
        "machine_id":        machine_id,
        "bot_username":      bot_username,
        "owner_telegram_id": owner_telegram_id,
    }

    try:
        result = _call_license_api("/activate", payload)
    except RuntimeError as e:
        log.warning("License activation failed: %s", e)
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
                "api_key":           api_key,
                "machine_id":        machine_id,
                "bot_username":      _setting_get(_SETTINGS_KEY_BOT_USERNAME),
                "owner_telegram_id": int(_setting_get(_SETTINGS_KEY_OWNER_TG_ID) or 0),
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
    Send expiry notification to all admins (from env) if license has expired
    and the notify interval has passed.
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
    # Send to all admins listed in env
    targets = _get_admin_ids()
    if owner_id and owner_id not in targets:
        targets.append(owner_id)
    sent_any = False
    for aid in targets:
        try:
            bot_instance.send_message(aid, msg, parse_mode="HTML")
            sent_any = True
            log.info("Sent expiry notification to admin %d", aid)
        except Exception as e:
            log.warning("Could not send expiry notification to %d: %s", aid, e)
    if sent_any:
        _setting_set(_SETTINGS_KEY_LAST_NOTIFY, _now_iso())


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


# ── Expiry warning helpers ────────────────────────────────────────────────────

_WARN_KEY_48H       = "license_warn_48h_sent"
_WARN_KEY_24H       = "license_warn_24h_sent"
_WARN_KEY_12H       = "license_warn_12h_sent"
_WARN_KEY_EXP       = "license_warn_exp_sent"
_WARN_PIN_48H       = "license_warn_pin_48h"
_WARN_PIN_24H       = "license_warn_pin_24h"
_WARN_PIN_12H       = "license_warn_pin_12h"
_WARN_PIN_EXP       = "license_warn_pin_exp"


def _get_admin_ids() -> list:
    """Return all admin IDs from environment (ADMIN_IDS)."""
    try:
        from .config import ADMIN_IDS
        return list(ADMIN_IDS)
    except Exception:
        return []


def _load_pin_map(key: str) -> dict:
    """Load {str(admin_id): message_id} map stored as JSON in settings."""
    raw = _setting_get(key)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _save_pin_map(key: str, mapping: dict) -> None:
    _setting_set(key, json.dumps(mapping))


def _unpin_stored(bot_instance, admin_id: int, key: str) -> None:
    """Unpin and remove the stored pinned message for a given admin."""
    mapping = _load_pin_map(key)
    mid = mapping.pop(str(admin_id), None)
    if mid:
        try:
            bot_instance.unpin_chat_message(admin_id, int(mid))
        except Exception:
            pass
    _save_pin_map(key, mapping)


def _send_and_pin_warn(bot_instance, admin_id: int, text: str, pin_key: str,
                       unpin_key: str | None = None) -> None:
    """Send warning message to admin, pin it, optionally unpin the previous one."""
    try:
        sent = bot_instance.send_message(admin_id, text, parse_mode="HTML")
        try:
            bot_instance.pin_chat_message(admin_id, sent.message_id, disable_notification=False)
        except Exception:
            pass
        mapping = _load_pin_map(pin_key)
        mapping[str(admin_id)] = sent.message_id
        _save_pin_map(pin_key, mapping)
        if unpin_key:
            _unpin_stored(bot_instance, admin_id, unpin_key)
    except Exception as e:
        log.warning("Could not send/pin warn to admin %d: %s", admin_id, e)


def _check_and_send_expiry_warnings(bot_instance) -> None:
    """
    Called every cycle. Sends 48h/24h/12h/expired warnings to all admins.
    Clears all warning flags when license is renewed (remaining > 48h).
    """
    state      = _setting_get(_SETTINGS_KEY_STATE, "inactive")
    expires_at = _setting_get(_SETTINGS_KEY_EXPIRES_AT, "")
    if not expires_at:
        return

    exp_ts = _parse_expiry(expires_at)
    if exp_ts is None:
        return

    remaining = exp_ts - _now_ts()
    admin_ids  = _get_admin_ids()

    # ── Renewal detected: remaining > 48h → clear all warning flags ───────────
    if remaining > 48 * 3600:
        if _setting_get(_WARN_KEY_48H) == "1":
            for aid in admin_ids:
                _unpin_stored(bot_instance, aid, _WARN_PIN_48H)
                _unpin_stored(bot_instance, aid, _WARN_PIN_24H)
                _unpin_stored(bot_instance, aid, _WARN_PIN_12H)
                _unpin_stored(bot_instance, aid, _WARN_PIN_EXP)
            _setting_set(_WARN_KEY_48H, "")
            _setting_set(_WARN_KEY_24H, "")
            _setting_set(_WARN_KEY_12H, "")
            _setting_set(_WARN_KEY_EXP, "")
        return

    # ── Expired ───────────────────────────────────────────────────────────────
    if remaining <= 0 and _setting_get(_WARN_KEY_EXP) != "1":
        msg = (
            "🚫 <b>لایسنس ربات شما به پایان رسید!</b>\n\n"
            "⛔️ ربات برای کاربران عادی غیرفعال شده است.\n\n"
            "برای تمدید و فعال‌سازی مجدد، هرچه سریع‌تر با ما در تماس باشید:\n"
            "👤 @emad_habibnia\n\n"
            "پس از تمدید، لایسنس به‌صورت خودکار فعال می‌شود. 🔄"
        )
        for aid in admin_ids:
            _send_and_pin_warn(bot_instance, aid, msg, _WARN_PIN_EXP, _WARN_PIN_12H)
        _setting_set(_WARN_KEY_EXP, "1")
        return

    # ── 12 ساعت مانده ─────────────────────────────────────────────────────────
    if remaining <= 12 * 3600 and _setting_get(_WARN_KEY_12H) != "1":
        hours_left = max(0, int(remaining // 3600))
        msg = (
            "⚠️ <b>هشدار جدی: لایسنس ربات شما کمتر از ۱۲ ساعت دیگر تمام می‌شود!</b>\n\n"
            f"⏳ زمان باقی‌مانده: حدود <b>{hours_left} ساعت</b>\n\n"
            "❌ اگر تا قبل از اتمام لایسنس اقدام نکنید، ربات برای کاربران عادی غیرفعال خواهد شد.\n\n"
            "📲 برای تمدید فوری همین الان پیام دهید:\n"
            "👤 @emad_habibnia\n\n"
            "⚡️ لطفاً هرچه زودتر اقدام کنید!"
        )
        for aid in admin_ids:
            _send_and_pin_warn(bot_instance, aid, msg, _WARN_PIN_12H, _WARN_PIN_24H)
        _setting_set(_WARN_KEY_12H, "1")
        return

    # ── 24 ساعت مانده ─────────────────────────────────────────────────────────
    if remaining <= 24 * 3600 and _setting_get(_WARN_KEY_24H) != "1":
        msg = (
            "🔔 <b>هشدار: لایسنس ربات شما ۲۴ ساعت دیگر تمام می‌شود!</b>\n\n"
            "⏳ زمان باقی‌مانده: <b>کمتر از ۲۴ ساعت</b>\n\n"
            "🔴 برای جلوگیری از غیرفعال شدن ربات، هر چه زودتر برای تمدید اقدام کنید.\n\n"
            "📲 جهت تمدید با ما در تماس باشید:\n"
            "👤 @emad_habibnia\n\n"
            "✅ پس از تمدید، ربات به‌صورت خودکار فعال می‌ماند."
        )
        for aid in admin_ids:
            _send_and_pin_warn(bot_instance, aid, msg, _WARN_PIN_24H, _WARN_PIN_48H)
        _setting_set(_WARN_KEY_24H, "1")
        return

    # ── 48 ساعت مانده ─────────────────────────────────────────────────────────
    if remaining <= 48 * 3600 and _setting_get(_WARN_KEY_48H) != "1":
        msg = (
            "🔔 <b>یادآوری: لایسنس ربات شما ۴۸ ساعت دیگر به پایان می‌رسد.</b>\n\n"
            "⏳ زمان باقی‌مانده: <b>کمتر از ۴۸ ساعت</b>\n\n"
            "💡 برای جلوگیری از غیرفعال شدن ربات و حفظ سرویس‌دهی بی‌وقفه، "
            "لطفاً هر چه زودتر برای تمدید اقدام نمایید.\n\n"
            "📲 جهت تمدید به آیدی زیر پیام دهید:\n"
            "👤 @emad_habibnia\n\n"
            "🙏 با تشکر از اعتماد شما."
        )
        for aid in admin_ids:
            _send_and_pin_warn(bot_instance, aid, msg, _WARN_PIN_48H)
        _setting_set(_WARN_KEY_48H, "1")


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

            # Expiry countdown warnings (48h / 24h / 12h / expired)
            _check_and_send_expiry_warnings(bot_instance)

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
    "🔐 <b>فعال‌سازی لایسنس — مرحله ۱ از ۲</b>\n\n"
    "لطفاً <b>API Key</b> لایسنس خود را وارد کنید.\n"
    "این کلید را از @Emad_Habibnia دریافت می‌کنید.\n\n"
    "⬅️ برای لغو /cancel بزنید."
)

API_URL_PROMPT_TEXT = (
    "🌐 <b>فعال‌سازی لایسنس — مرحله ۲ از ۲</b>\n\n"
    "لطفاً <b>API URL</b> سرور لایسنس را وارد کنید.\n"
    "<i>مثال: http://209.50.228.1:5000/api/license</i>\n\n"
    "این آدرس را از @Emad_Habibnia دریافت می‌کنید.\n\n"
    "⬅️ برای لغو /cancel بزنید."
)
