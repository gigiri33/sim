# -*- coding: utf-8 -*-
"""
Persistent delivery queue worker.

When a panel config cannot be created/delivered immediately (e.g., panel
unreachable), the order is stored in the `delivery_queue` table.  This
background thread retries every DELIVERY_RETRY_INTERVAL_SECONDS seconds:

  1. Fetch all pending queue items whose next_retry_at <= now.
  2. For each distinct panel_id, do a quick connectivity check.
     - If the panel is down, skip all items for that panel (log once).
     - If the panel is up, retry delivery for each item.
  3. On success: deliver config to user, mark item as delivered.
  4. On failure: schedule next retry; log the error.

Configuration (read from DB settings, with hardcoded defaults):
  delivery_retry_interval   — seconds between worker cycles   (default 300)
  delivery_max_retries      — 0 = unlimited                   (default 0)
  panel_healthcheck_timeout — seconds for login connectivity   (default 10)
"""

import logging
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# ── Defaults (can be overridden via DB settings) ──────────────────────────────
DELIVERY_RETRY_INTERVAL_SECONDS = 300
DELIVERY_MAX_RETRIES            = 0      # 0 = no limit
PANEL_HEALTHCHECK_TIMEOUT       = 10


# ── Internal state ─────────────────────────────────────────────────────────────
_worker_started = False
_worker_lock    = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg_int(key, default):
    try:
        from .db import setting_get
        v = setting_get(key, "")
        return int(v) if v else default
    except Exception:
        return default


def _now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _next_retry_str(delay_seconds: int) -> str:
    dt = datetime.utcnow() + timedelta(seconds=delay_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _notify_admin(text: str):
    """Send a message to admin IDs and the error_log group topic (best-effort)."""
    try:
        from .config import ADMIN_IDS
        from .bot_instance import bot
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass
    except Exception:
        pass
    try:
        from .group_manager import send_to_topic
        send_to_topic("error_log", text)
    except Exception:
        pass


def _check_panel_reachable(panel_id: int) -> bool:
    """
    Quick login-based connectivity check before retrying deliveries for a panel.
    Returns True only if login succeeds within PANEL_HEALTHCHECK_TIMEOUT seconds.
    """
    try:
        from .db import get_panel
        from .panels.client import PanelClient
        panel = get_panel(panel_id)
        if not panel or not panel["is_active"]:
            return False
        client = PanelClient(
            protocol=panel["protocol"],
            host=panel["host"],
            port=panel["port"],
            path=panel["path"] or "",
            username=panel["username"],
            password=panel["password"],
        )
        # Use a short socket timeout so we don't block the worker thread
        import socket as _socket
        _orig = _socket.getdefaulttimeout()
        try:
            _socket.setdefaulttimeout(
                _cfg_int("panel_healthcheck_timeout", PANEL_HEALTHCHECK_TIMEOUT)
            )
            ok, _ = client.health_check()
        finally:
            _socket.setdefaulttimeout(_orig)
        return bool(ok)
    except Exception as exc:
        log.debug("[DeliveryWorker] panel %s connectivity check exception: %s", panel_id, exc)
        return False


def _get_panel_id_for_package(package_id: int):
    """Return the panel_id for a package, or None."""
    try:
        from .db import get_package
        pkg = get_package(package_id)
        if pkg:
            return pkg["panel_id"]
    except Exception:
        pass
    return None


def _deliver_one(item) -> tuple:
    """
    Try to create AND deliver a panel config for a single queue item.

    Returns (success: bool, error_str: str, panel_config_id: int or None).

    Idempotency:
    - If item already has a `panel_config_id` (partial success from previous
      attempt), we skip client creation and go straight to delivery.
    - If `client_uuid` is stored, we *also* skip creation (client already
      exists on the panel).
    """
    from .handlers.callbacks import (
        _create_panel_config,
        _deliver_panel_config_to_user,
    )
    from .db import get_package, mark_delivery_delivered, update_delivery_progress

    uid        = item["user_id"]
    chat_id    = item["chat_id"]
    package_id = item["package_id"]
    payment_id = item["payment_id"]
    desired    = item["desired_name"]
    is_test    = int(item["is_test"] or 0)
    queue_id   = item["id"]

    pkg = get_package(package_id)

    # ── Case 1: client was already created previously (panel_config_id stored) ─
    pc_id = item["panel_config_id"]
    if pc_id:
        log.info("[DeliveryWorker] item %s: panel_config %s already exists, re-delivering", queue_id, pc_id)
        try:
            _deliver_panel_config_to_user(chat_id, pc_id, pkg)
            return True, "", pc_id
        except Exception as exc:
            return False, f"delivery after partial success: {exc}", pc_id

    # ── Case 2: normal attempt — create client + deliver ──────────────────────
    ok, result, new_pc_id, c_name = _create_panel_config(
        uid=uid,
        package_id=package_id,
        payment_id=payment_id,
        chat_id=None,          # IMPORTANT: no chat_id so no user messages from inside
        desired_name=desired,
        is_test=is_test,
    )

    if not ok:
        return False, str(result), None

    # Persist partial success so a crash before delivery doesn't re-create the client
    try:
        from .db import get_panel_config
        pc = get_panel_config(new_pc_id)
        update_delivery_progress(
            queue_id,
            new_pc_id,
            pc["client_uuid"] if pc else None,
            pc["client_name"] if pc else None,
        )
    except Exception:
        pass

    try:
        _deliver_panel_config_to_user(chat_id, new_pc_id, pkg)
    except Exception as exc:
        log.error("[DeliveryWorker] delivery message failed for item %s pc %s: %s", queue_id, new_pc_id, exc)
        # Config was created successfully — still count as delivered so user
        # doesn't get a duplicate client on next retry.  Admin will see the error.
        return True, f"created but send failed: {exc}", new_pc_id

    return True, "", new_pc_id


# ── Main worker cycle ─────────────────────────────────────────────────────────

def _run_delivery_cycle():
    from .db import get_due_deliveries, update_delivery_retry, mark_delivery_delivered, mark_delivery_failed

    retry_interval = _cfg_int("delivery_retry_interval", DELIVERY_RETRY_INTERVAL_SECONDS)
    max_retries    = _cfg_int("delivery_max_retries",    DELIVERY_MAX_RETRIES)

    items = get_due_deliveries()
    if not items:
        return

    log.info("[DeliveryWorker] cycle: %d item(s) due", len(items))

    # Group items by panel_id to avoid redundant connectivity checks
    panel_reachable: dict = {}   # panel_id → bool

    for item in items:
        item   = dict(item)
        qid    = item["id"]
        uid    = item["user_id"]
        pkg_id = item["package_id"]

        # ── Connectivity pre-check ────────────────────────────────────────────
        panel_id = _get_panel_id_for_package(pkg_id)
        if panel_id is not None:
            if panel_id not in panel_reachable:
                reachable = _check_panel_reachable(panel_id)
                panel_reachable[panel_id] = reachable
                if not reachable:
                    log.warning(
                        "[DeliveryWorker] panel %s unreachable — skipping %d item(s) for this panel",
                        panel_id,
                        sum(1 for i in items if _get_panel_id_for_package(i["package_id"]) == panel_id),
                    )
            if not panel_reachable[panel_id]:
                # Reschedule silently — no user message
                update_delivery_retry(
                    qid,
                    "panel unreachable (connectivity check)",
                    _next_retry_str(retry_interval),
                )
                continue

        log.info(
            "[DeliveryWorker] retrying item %s (attempt #%d) uid=%s pkg=%s payment=%s",
            qid, item["retry_count"] + 1, uid, pkg_id, item["payment_id"],
        )

        # ── Delivery attempt ──────────────────────────────────────────────────
        try:
            success, err, pc_id = _deliver_one(item)
        except Exception as exc:
            success = False
            err     = str(exc)
            pc_id   = None
            log.exception("[DeliveryWorker] unexpected error for item %s: %s", qid, exc)

        if success:
            mark_delivery_delivered(qid, pc_id)
            log.info("[DeliveryWorker] item %s delivered successfully (pc=%s uid=%s)", qid, pc_id, uid)
            # Notify admins of success
            try:
                from .db import get_panel, get_package
                pkg  = get_package(pkg_id)
                pkg_name = pkg["name"] if pkg else str(pkg_id)
                _notify_admin(
                    f"✅ <b>تحویل کانفیگ از صف انجام شد</b>\n\n"
                    f"👤 کاربر: <code>{uid}</code>\n"
                    f"📦 پکیج: {pkg_name}\n"
                    f"🗂 panel_config_id: <code>{pc_id}</code>\n"
                    f"🔁 تلاش شماره: {item['retry_count'] + 1}"
                )
            except Exception:
                pass
        else:
            retry_count = item["retry_count"] + 1
            # Permanent failure check
            if max_retries > 0 and retry_count >= max_retries:
                mark_delivery_failed(qid, err)
                log.error(
                    "[DeliveryWorker] item %s PERMANENTLY FAILED after %d retries uid=%s: %s",
                    qid, retry_count, uid, err,
                )
                _notify_admin(
                    f"🚨 <b>تحویل کانفیگ به‌طور دائمی شکست خورد</b>\n\n"
                    f"👤 کاربر: <code>{uid}</code>\n"
                    f"📦 پکیج: <code>{pkg_id}</code>\n"
                    f"💳 شناسه پرداخت: <code>{item['payment_id']}</code>\n"
                    f"🔁 تعداد تلاش: {retry_count}\n"
                    f"⚠️ خطا:\n<code>{err[:500]}</code>\n\n"
                    "⛔️ این سفارش نیاز به بررسی دستی دارد."
                )
            else:
                update_delivery_retry(qid, err, _next_retry_str(retry_interval))
                log.warning(
                    "[DeliveryWorker] item %s failed (attempt %d), next retry in %ds uid=%s: %s",
                    qid, retry_count, retry_interval, uid, err,
                )
                # Notify admins on each retry failure (condensed)
                _notify_admin(
                    f"⚠️ <b>تلاش تحویل کانفیگ از صف ناموفق بود</b>\n\n"
                    f"👤 کاربر: <code>{uid}</code>\n"
                    f"📦 پکیج: <code>{pkg_id}</code>\n"
                    f"🔁 تلاش شماره: {retry_count}\n"
                    f"⚠️ خطا:\n<code>{err[:400]}</code>"
                )


# ── Worker thread ──────────────────────────────────────────────────────────────

def _delivery_worker_loop():
    # Wait one full interval before first run so the bot finishes starting up
    interval = _cfg_int("delivery_retry_interval", DELIVERY_RETRY_INTERVAL_SECONDS)
    time.sleep(interval)
    while True:
        try:
            _run_delivery_cycle()
        except Exception as exc:
            log.error("[DeliveryWorker] cycle exception: %s", exc)
        interval = _cfg_int("delivery_retry_interval", DELIVERY_RETRY_INTERVAL_SECONDS)
        time.sleep(interval)


def start_delivery_worker():
    """Start the background delivery worker thread (idempotent)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    t = threading.Thread(
        target=_delivery_worker_loop,
        daemon=True,
        name="delivery-worker",
    )
    t.start()
    log.info(
        "[DeliveryWorker] started — interval=%ds max_retries=%d",
        _cfg_int("delivery_retry_interval", DELIVERY_RETRY_INTERVAL_SECONDS),
        _cfg_int("delivery_max_retries", DELIVERY_MAX_RETRIES),
    )
