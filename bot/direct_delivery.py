# -*- coding: utf-8 -*-
"""
Direct panel config delivery system.

Replaces the delivery_queue / delivery_worker / reconciliation system.

When a panel payment is confirmed, call:
    fulfill_panel_payment_direct(payment_id)

This function:
- Verifies the payment is for a panel package
- Attempts to create all missing configs immediately
- Retries every RETRY_INTERVAL_SECS for up to MAX_TOTAL_SECS
- If panel never comes online, refunds the undelivered amount to wallet
- Is idempotent — safe to call multiple times for the same payment_id

The delivery_queue and delivery_slots tables are left intact for historical
compatibility but NO new rows are inserted into them by this module.
"""

import logging
import threading
import time

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
RETRY_INTERVAL_SECS = 30        # seconds between retry attempts
MAX_TOTAL_SECS      = 300       # 5 minutes total delivery window
MAX_ATTEMPTS        = 11        # t=0,30,60,...,300  (11 attempts with 30s gaps)

# ── Per-payment in-flight guard ────────────────────────────────────────────────
_inflight_lock = threading.Lock()
_inflight: set = set()          # payment IDs currently being delivered


def _is_conn_err(e_str: str) -> bool:
    s = e_str.lower()
    return any(x in s for x in [
        "connection refused", "max retries exceeded", "failed to establish",
        "newconnectionerror", "httpsconnectionpool", "remotedisconnected",
        "connection timed out", "read timed out", "timeout",
        "connection reset", "connection aborted", "connectionreseterror",
        "econnreset", "broken pipe", "reset by peer",
        "name or service not known", "nameresolutionerror",
    ])


def _notify_admin(text: str):
    """Best-effort admin notification."""
    try:
        from .config import ADMIN_IDS
        from .bot_instance import bot
        for aid in ADMIN_IDS:
            try:
                bot.send_message(aid, text, parse_mode="HTML")
            except Exception:
                pass
    except Exception:
        pass
    try:
        from .group_manager import send_to_topic
        send_to_topic("error_log", text)
    except Exception:
        pass


def _send_user(uid: int, text: str):
    """Best-effort user message."""
    try:
        from .bot_instance import bot
        bot.send_message(uid, text, parse_mode="HTML")
    except Exception:
        pass


def _check_panel_online(panel) -> bool:
    """Return True if the panel accepts a login request."""
    try:
        from .panels.client import PanelClient
        import socket as _socket
        pc = PanelClient(
            protocol=panel["protocol"],
            host=panel["host"],
            port=panel["port"],
            path=panel["path"] or "",
            username=panel["username"],
            password=panel["password"],
        )
        orig = _socket.getdefaulttimeout()
        try:
            _socket.setdefaulttimeout(10)
            ok, _ = pc.health_check()
        finally:
            _socket.setdefaulttimeout(orig)
        return bool(ok)
    except Exception:
        return False


def _attempt_create_one(uid: int, package_id: int, payment_id: int,
                         desired_name, slot_index: int, is_test: int):
    """
    Try to create a single panel config.
    Returns (ok: bool, pc_id: int|None, client_name: str, error: str).
    """
    try:
        from .handlers.callbacks import _create_panel_config
        ok, result, pc_id, c_name = _create_panel_config(
            uid=uid,
            package_id=package_id,
            payment_id=payment_id,
            chat_id=None,
            desired_name=desired_name,
            is_test=int(is_test or 0),
            slot_index=slot_index,
        )
        if ok:
            return True, pc_id, c_name or "", ""
        return False, None, "", str(result)
    except Exception as exc:
        return False, None, "", str(exc)


def _deliver_config_to_user(uid: int, pc_id: int, package_row):
    """Send the config message to the user (best-effort)."""
    try:
        from .handlers.callbacks import _deliver_panel_config_to_user
        _deliver_panel_config_to_user(uid, pc_id, package_row)
    except Exception as exc:
        log.error("[DirectDelivery] deliver to user failed pc=%s uid=%s: %s", pc_id, uid, exc)


def _run_delivery(payment_id: int):
    """
    Core delivery loop. Runs in a daemon thread.
    Retries every RETRY_INTERVAL_SECS for up to MAX_TOTAL_SECS.
    """
    from .db import (
        get_payment, get_package, get_payment_service_names, get_panel,
        count_panel_configs_for_payment, get_panel_configs_for_payment,
        set_payment_delivery_status, increment_delivery_attempt,
        mark_delivery_started, refund_undelivered_to_wallet,
        get_user,
    )
    from .helpers import fmt_price, esc

    try:
        payment = get_payment(payment_id)
        if not payment:
            log.error("[DirectDelivery] payment %s not found", payment_id)
            return

        uid         = payment["user_id"]
        package_id  = payment["package_id"]
        amount      = int(payment["amount"] or 0)
        quantity    = max(1, int(payment["quantity"] or 1) if "quantity" in payment.keys() else 1)
        payment_method = payment["payment_method"] or "unknown"

        package_row = get_package(package_id)
        if not package_row:
            log.error("[DirectDelivery] package %s not found for payment %s", package_id, payment_id)
            return

        # Only handle panel packages
        try:
            config_source = package_row["config_source"] or "manual"
        except Exception:
            config_source = "manual"

        if config_source != "panel":
            log.warning("[DirectDelivery] payment %s is not a panel package — skipping", payment_id)
            return

        # Load service names (user-chosen names)
        service_names = get_payment_service_names(payment_id) or []

        # Determine which panel this package uses
        try:
            panel_id = package_row["panel_id"]
        except Exception:
            panel_id = None

        panel = get_panel(panel_id) if panel_id else None

        unit_price = max(0, amount // quantity) if quantity else amount

        log.info(
            "[DirectDelivery] START payment_id=%s uid=%s package=%s qty=%s amount=%s",
            payment_id, uid, package_id, quantity, amount
        )

        mark_delivery_started(payment_id)
        set_payment_delivery_status(payment_id, "delivering")

        t_start = time.time()
        attempt = 0
        delivered_pc_ids   = []
        delivered_names    = []

        while attempt < MAX_ATTEMPTS:
            elapsed = time.time() - t_start

            # Check how many are already delivered
            existing = get_panel_configs_for_payment(payment_id)
            existing_indices = {int(r["delivery_slot_index"]) for r in existing if r["delivery_slot_index"] is not None}
            existing_count   = len(existing)

            if existing_count >= quantity:
                # All delivered — we're done
                log.info(
                    "[DirectDelivery] payment_id=%s all %s configs delivered",
                    payment_id, quantity
                )
                set_payment_delivery_status(
                    payment_id, "delivered",
                    delivered=existing_count,
                    finished=True
                )
                try:
                    from .ui.notifications import check_and_give_referral_purchase_reward
                    check_and_give_referral_purchase_reward(uid)
                except Exception:
                    pass
                return

            # Which slot indices still need creation?
            missing_indices = [i for i in range(quantity) if i not in existing_indices]

            log.info(
                "[DirectDelivery] attempt=%s payment_id=%s uid=%s existing=%s missing=%s elapsed=%.0fs",
                attempt + 1, payment_id, uid, existing_count, len(missing_indices), elapsed
            )

            increment_delivery_attempt(payment_id)

            # Check panel connectivity first
            panel_ok = _check_panel_online(panel) if panel else False

            if not panel_ok:
                log.warning(
                    "[DirectDelivery] panel offline attempt=%s payment_id=%s uid=%s",
                    attempt + 1, payment_id, uid
                )
                attempt += 1
                if elapsed + RETRY_INTERVAL_SECS < MAX_TOTAL_SECS:
                    time.sleep(RETRY_INTERVAL_SECS)
                    continue
                else:
                    break

            # Panel is online — create missing configs
            newly_created = 0
            newly_delivered = 0
            last_error = ""

            for slot_i in missing_indices:
                desired = None
                if service_names and slot_i < len(service_names):
                    desired = service_names[slot_i]

                ok, pc_id, c_name, err = _attempt_create_one(
                    uid, package_id, payment_id, desired, slot_i, 0
                )
                if ok and pc_id:
                    newly_created += 1
                    delivered_pc_ids.append(pc_id)
                    delivered_names.append(c_name)
                    # Deliver to user immediately
                    _deliver_config_to_user(uid, pc_id, package_row)
                    newly_delivered += 1
                    log.info(
                        "[DirectDelivery] created pc_id=%s slot=%s payment_id=%s",
                        pc_id, slot_i, payment_id
                    )
                else:
                    last_error = err
                    log.warning(
                        "[DirectDelivery] create failed slot=%s payment_id=%s: %s",
                        slot_i, payment_id, err
                    )
                # Small gap between API calls
                if slot_i != missing_indices[-1]:
                    time.sleep(1)

            # Re-check total
            current_count = count_panel_configs_for_payment(payment_id)
            set_payment_delivery_status(
                payment_id, "delivering",
                delivered=current_count,
                error=last_error if last_error else None
            )

            if current_count >= quantity:
                # All done
                log.info(
                    "[DirectDelivery] payment_id=%s all %s configs delivered after attempt %s",
                    payment_id, quantity, attempt + 1
                )
                set_payment_delivery_status(
                    payment_id, "delivered",
                    delivered=current_count,
                    finished=True
                )
                # Notify referral reward
                try:
                    from .ui.notifications import check_and_give_referral_purchase_reward
                    check_and_give_referral_purchase_reward(uid)
                except Exception:
                    pass
                # Admin success notification
                try:
                    _user = get_user(uid)
                    _uname = f"@{_user['username']}" if _user and _user.get("username") else "—"
                    _fname = (_user.get("full_name") or "—") if _user else "—"
                    _notify_admin(
                        f"✅ <b>تحویل مستقیم کامل شد</b>\n\n"
                        f"👤 کاربر: <code>{uid}</code>\n"
                        f"📛 نام: {_fname}\n"
                        f"🆔 یوزرنیم: {_uname}\n"
                        f"📦 پکیج: {package_row['name']}\n"
                        f"💳 پرداخت: <code>{payment_id}</code>\n"
                        f"✅ تحویل: {current_count}/{quantity}\n"
                        f"🔁 تلاش: {attempt + 1}"
                    )
                except Exception:
                    pass
                return

            attempt += 1
            if elapsed + RETRY_INTERVAL_SECS < MAX_TOTAL_SECS:
                time.sleep(RETRY_INTERVAL_SECS)

        # ── Timeout reached ────────────────────────────────────────────────────
        final_count = count_panel_configs_for_payment(payment_id)
        undelivered = max(0, quantity - final_count)

        log.warning(
            "[DirectDelivery] TIMEOUT payment_id=%s uid=%s delivered=%s/%s",
            payment_id, uid, final_count, quantity
        )

        # Refund undelivered amount
        refunded = 0
        try:
            refunded = refund_undelivered_to_wallet(
                payment_id=payment_id,
                user_id=uid,
                quantity=quantity,
                delivered_count=final_count,
                total_amount=amount,
            )
        except Exception as _re:
            log.error("[DirectDelivery] refund failed payment_id=%s: %s", payment_id, _re)

        # User message
        if final_count > 0 and undelivered > 0:
            refund_msg = f"\n\n💰 مبلغ {fmt_price(refunded)} تومان به کیف پول شما برگشت داده شد." if refunded > 0 else ""
            _send_user(uid,
                f"⚠️ پرداخت شما تأیید شد. {final_count} کانفیگ ارسال شد، اما {undelivered} کانفیگ "
                f"به دلیل عدم اتصال پنل تحویل نشد و مبلغ آن به کیف پول شما برگشت."
                + refund_msg
            )
        elif final_count <= 0:
            refund_msg = f"\n\n💰 مبلغ {fmt_price(refunded)} تومان به کیف پول شما برگشت داده شد." if refunded > 0 else ""
            _send_user(uid,
                "⚠️ پرداخت شما تأیید شد، اما پنل تا ۵ دقیقه متصل نشد. مبلغ سفارش به کیف پول شما برگشت."
                + refund_msg
            )

        # Admin notification
        try:
            _user = get_user(uid)
            _uname = f"@{_user['username']}" if _user and _user.get("username") else "—"
            _fname = (_user.get("full_name") or "—") if _user else "—"
            _notify_admin(
                f"⚠️ <b>تحویل مستقیم با تایم‌اوت پایان یافت</b>\n\n"
                f"👤 کاربر: <code>{uid}</code>\n"
                f"📛 نام: {_fname}\n"
                f"🆔 یوزرنیم: {_uname}\n"
                f"📦 پکیج: {package_row['name']}\n"
                f"💳 پرداخت: <code>{payment_id}</code>\n"
                f"✅ تحویل‌شده: {final_count}/{quantity}\n"
                f"💸 برگشت داده شد: {fmt_price(refunded)} تومان"
            )
        except Exception:
            pass

    except Exception as exc:
        log.exception("[DirectDelivery] unhandled error payment_id=%s: %s", payment_id, exc)
        try:
            set_payment_delivery_status(payment_id, "delivering", error=str(exc))
        except Exception:
            pass
    finally:
        with _inflight_lock:
            _inflight.discard(payment_id)


def fulfill_panel_payment_direct(payment_id: int):
    """
    Entry point: called from every payment success path for panel config purchases.

    Starts the delivery in a daemon thread so the calling payment handler returns
    immediately (avoiding Telegram callback timeouts).

    Idempotent: if a thread is already running for this payment_id, does nothing.
    """
    from .db import get_payment, get_package

    try:
        payment = get_payment(payment_id)
        if not payment:
            log.warning("[DirectDelivery] fulfill called for unknown payment_id=%s", payment_id)
            return

        # Only handle panel config purchases
        package_id = payment["package_id"]
        if not package_id:
            return
        package_row = get_package(package_id)
        if not package_row:
            return
        try:
            config_source = package_row["config_source"] or "manual"
        except Exception:
            config_source = "manual"
        if config_source != "panel":
            return

        # Idempotency: only one thread per payment
        with _inflight_lock:
            if payment_id in _inflight:
                log.info("[DirectDelivery] payment_id=%s already in-flight, skipping", payment_id)
                return
            _inflight.add(payment_id)

    except Exception as exc:
        log.error("[DirectDelivery] fulfill setup error payment_id=%s: %s", payment_id, exc)
        return

    t = threading.Thread(
        target=_run_delivery,
        args=(payment_id,),
        daemon=True,
        name=f"direct-delivery-{payment_id}",
    )
    t.start()
    log.info("[DirectDelivery] launched thread for payment_id=%s", payment_id)
