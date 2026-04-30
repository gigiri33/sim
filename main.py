# -*- coding: utf-8 -*-
"""
Entry point for the ConfigFlow Telegram Bot.

Run with:  python main.py
"""
import threading
import json

from bot.db import init_db
from bot.db import cleanup_stale_reservations
from bot.ui.helpers import set_bot_commands
from bot.db import setting_get, setting_set, add_locked_channel, get_payment, complete_payment, update_balance
from bot.admin.backup import _backup_loop
from bot.group_manager import _group_topic_loop
from bot.panels.checker import start_panel_checker
import bot.handlers  # noqa: F401 — registers all handlers
from bot.bot_instance import bot  # must come after to avoid being shadowed by the package name
from bot.license_manager import (
    check_license,
    get_or_create_machine_id,
    start_license_background_check,
    is_limited_mode,
    LIMITED_MODE_TEXT,
)


# ── Plisio webhook server (runs in a background thread) ───────────────────────
def _plisio_webhook_server():
    """
    Lightweight Flask server to receive Plisio IPN callbacks.
    Runs only when ``server_public_url`` is set in admin settings.
    """
    try:
        from flask import Flask, request, jsonify
    except ImportError:
        print("⚠️ Flask not installed — Plisio webhook disabled. Run: pip install flask")
        return

    from bot.gateways.plisio import (
        verify_plisio_json_callback,
        is_plisio_paid,
        get_plisio_webhook_port,
    )
    from bot.gateways.nowpayments import (
        verify_nowpayments_signature,
        is_nowpayments_paid,
    )
    from bot.helpers import fmt_price
    from bot.payments import apply_gateway_bonus_if_needed
    from bot.crypto_fulfillment import run_crypto_fulfillment_async

    def _run_fulfillment(gateway: str, payment_id: int):
        run_crypto_fulfillment_async(gateway, payment_id)

    _app = Flask(__name__)

    @_app.route("/plisio/<bot_username>/callback", methods=["POST"])
    def _plisio_callback(bot_username):
        try:
            data = request.get_json(force=True, silent=True) or {}
            if not data:
                return jsonify({"status": "error", "message": "empty body"}), 400
            if not verify_plisio_json_callback(dict(data)):
                print("PLISIO_WEBHOOK: invalid signature for txn", data.get("txn_id"))
                return jsonify({"status": "error", "message": "invalid signature"}), 403
            order_number = data.get("order_number", "")
            status       = data.get("status", "")
            if not order_number:
                return jsonify({"status": "ok"}), 200
            try:
                payment_id = int(order_number)
            except (ValueError, TypeError):
                return jsonify({"status": "ok"}), 200
            payment = get_payment(payment_id)
            if not payment or payment["status"] != "pending":
                return jsonify({"status": "ok"}), 200
            if not is_plisio_paid(status):
                # Not yet paid — ack so Plisio stops retrying for this status
                return jsonify({"status": "ok"}), 200

            kind   = payment["kind"]
            uid    = payment["user_id"]
            amount = payment["amount"]

            if kind == "wallet_charge":
                # Wallet charges: complete + credit balance immediately.
                if not complete_payment(payment_id):
                    return jsonify({"status": "ok"}), 200
                update_balance(uid, amount)
                try:
                    apply_gateway_bonus_if_needed(uid, "plisio", amount)
                except Exception:
                    pass
                try:
                    bot.send_message(
                        uid,
                        f"✅ پرداخت Plisio شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            else:
                # config_purchase / renewal / pnlcfg_renewal:
                # Complete and fulfill in a background thread so the webhook
                # response returns immediately and Plisio doesn't retry.
                threading.Thread(
                    target=_run_fulfillment,
                    args=("plisio", payment_id),
                    daemon=True,
                ).start()
        except Exception as exc:
            print("PLISIO_WEBHOOK_ERROR:", exc)
        return jsonify({"status": "ok"}), 200

    @_app.route("/plisio/<bot_username>/success", methods=["GET", "POST"])
    def _plisio_success(bot_username):
        return "✅ پرداخت با موفقیت انجام شد. به ربات تلگرام بازگردید.", 200

    @_app.route("/plisio/<bot_username>/fail", methods=["GET", "POST"])
    def _plisio_fail(bot_username):
        return "❌ پرداخت ناموفق بود. به ربات تلگرام بازگردید.", 200

    # ── NowPayments routes (sharing the same Flask app & port) ────────────
    @_app.route("/nowpayments/<bot_username>/callback", methods=["POST"])
    def _nowpayments_callback(bot_username):
        try:
            raw_body = request.get_data() or b""
            sig = request.headers.get("x-nowpayments-sig", "") or request.headers.get("X-Nowpayments-Sig", "")
            if not verify_nowpayments_signature(raw_body, sig):
                print("NOWPAYMENTS_WEBHOOK: invalid signature")
                return jsonify({"status": "error", "message": "invalid signature"}), 403
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except Exception:
                return jsonify({"status": "error", "message": "invalid json"}), 400
            order_id = data.get("order_id", "")
            status   = (data.get("payment_status") or "").lower()
            if not order_id:
                return jsonify({"status": "ok"}), 200
            try:
                payment_id = int(order_id)
            except (ValueError, TypeError):
                return jsonify({"status": "ok"}), 200
            payment = get_payment(payment_id)
            if not payment or payment["status"] != "pending":
                return jsonify({"status": "ok"}), 200
            if not is_nowpayments_paid(status):
                return jsonify({"status": "ok"}), 200

            kind   = payment["kind"]
            uid    = payment["user_id"]
            amount = payment["amount"]

            if kind == "wallet_charge":
                if not complete_payment(payment_id):
                    return jsonify({"status": "ok"}), 200
                update_balance(uid, amount)
                try:
                    apply_gateway_bonus_if_needed(uid, "nowpayments", amount)
                except Exception:
                    pass
                try:
                    bot.send_message(
                        uid,
                        f"✅ پرداخت NowPayments شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            else:
                # config_purchase / renewal / pnlcfg_renewal:
                # Complete and fulfill in a background thread.
                threading.Thread(
                    target=_run_fulfillment,
                    args=("nowpayments", payment_id),
                    daemon=True,
                ).start()
        except Exception as exc:
            print("NOWPAYMENTS_WEBHOOK_ERROR:", exc)
        return jsonify({"status": "ok"}), 200

    @_app.route("/nowpayments/<bot_username>/success", methods=["GET", "POST"])
    def _nowpayments_success(bot_username):
        return "✅ پرداخت با موفقیت انجام شد. به ربات تلگرام بازگردید.", 200

    @_app.route("/nowpayments/<bot_username>/cancel", methods=["GET", "POST"])
    def _nowpayments_cancel(bot_username):
        return "❌ پرداخت لغو شد. به ربات تلگرام بازگردید.", 200

    port = int(get_plisio_webhook_port())
    print(f"🌐 Payment webhook server (Plisio + NowPayments) starting on port {port}…")
    _app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def _start_plisio_webhook_server():
    # Always start the webhook listener — callback URL is auto-detected
    # from the server's public IP if `server_public_url` is not set.
    t = threading.Thread(target=_plisio_webhook_server, daemon=True)
    t.start()


def main():
    init_db()
    cleanup_stale_reservations()

    # ── Migrate legacy single-channel setting → locked_channels table ─────────
    legacy_channel = setting_get("channel_id", "").strip()
    if legacy_channel:
        add_locked_channel(legacy_channel)   # no-op if already in table (duplicate guard)
        setting_set("channel_id", "")        # clear legacy field to avoid showing it twice
        print(f"✅ Migrated legacy channel_id '{legacy_channel}' → locked_channels table.")

    set_bot_commands()

    # ── Layer 1: Ensure machine_id exists ─────────────────────────────────────
    get_or_create_machine_id()

    # ── Layer 2: Check license at startup (non-blocking — limited mode allowed) ─
    license_ok = check_license(force=True)
    if license_ok:
        print("✅ License is active.")
    else:
        print("⚠️  License inactive or expired — running in LIMITED MODE.")
        print("   Use /license_status or the admin panel to activate.")

    # ── Layer 3: Start background license checker ─────────────────────────────
    owner_id = 0
    try:
        admin_ids_str = setting_get("license_owner_telegram_id", "")
        if admin_ids_str and admin_ids_str.isdigit():
            owner_id = int(admin_ids_str)
        else:
            # Fall back to first ADMIN_IDS entry
            from bot.config import ADMIN_IDS
            if ADMIN_IDS:
                owner_id = next(iter(ADMIN_IDS))
    except Exception:
        pass
    start_license_background_check(bot, owner_id)

    # Start backup thread
    backup_thread = threading.Thread(target=_backup_loop, daemon=True)
    backup_thread.start()

    # Start group topic maintenance loop
    group_thread = threading.Thread(target=_group_topic_loop, daemon=True)
    group_thread.start()

    # Start panel health-check background thread
    start_panel_checker()

    # Start Plisio webhook server (only if server_public_url is set)
    _start_plisio_webhook_server()

    # Remove any active webhook before starting long-polling (prevents 409 conflict)
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"⚠️ Could not delete webhook: {e}")

    print("✅ Bot is running...")
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30,
        allowed_updates=[
            "message",
            "callback_query",
            "chat_member",      # needed for channel-leave detection
            "my_chat_member",   # bot kicked/added to channels/groups
        ],
    )


if __name__ == "__main__":
    main()
