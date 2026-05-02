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

    from bot.db import get_conn
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
                print("NOWPAYMENTS_WEBHOOK: invalid signature — set nowpayments_ipn_secret in bot settings")
                return jsonify({"status": "error", "message": "invalid signature"}), 403
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except Exception:
                return jsonify({"status": "error", "message": "invalid json"}), 400

            print(f"NOWPAYMENTS_WEBHOOK: received — order_id={data.get('order_id')!r}  "
                  f"invoice_id={data.get('invoice_id')!r}  "
                  f"payment_id={data.get('payment_id')!r}  "
                  f"status={data.get('payment_status')!r}")

            order_id      = str(data.get("order_id") or "").strip()
            np_invoice_id = str(data.get("invoice_id") or "").strip()
            status        = (data.get("payment_status") or "").lower()

            # ── Primary lookup: order_id == our internal payment_id ────────
            payment_id = None
            if order_id:
                try:
                    payment_id = int(order_id)
                except (ValueError, TypeError):
                    payment_id = None

            # ── Fallback: look up by NowPayments invoice_id stored in receipt_text ──
            if not payment_id and np_invoice_id:
                try:
                    with get_conn() as _c:
                        row = _c.execute(
                            "SELECT id FROM payments WHERE receipt_text=? AND payment_method='nowpayments' AND status='pending'",
                            (np_invoice_id,)
                        ).fetchone()
                    if row:
                        payment_id = row["id"]
                        print(f"NOWPAYMENTS_WEBHOOK: resolved via invoice_id fallback → payment_id={payment_id}")
                except Exception as _le:
                    print(f"NOWPAYMENTS_WEBHOOK: invoice_id fallback error: {_le}")

            if not payment_id:
                print("NOWPAYMENTS_WEBHOOK: no matching payment found — dropping")
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

    # ── PazzleNet routes (sharing the same Flask app & port) ──────────────
    @_app.route("/pazzlenet/<bot_username>/callback", methods=["GET", "POST"])
    def _pazzlenet_callback(bot_username):
        try:
            # PazzleNet may send JSON body or query-string parameters
            data = {}
            if request.content_length and request.content_length > 0:
                data = request.get_json(force=True, silent=True) or {}
            if not data:
                data = dict(request.args) or {}

            # Extract the PazzleNet payment ID from the callback
            pz_pid = (
                data.get("payment_id")
                or data.get("id")
                or data.get("order_id")
                or data.get("order_number")
                or ""
            )
            if not pz_pid:
                return jsonify({"status": "ok"}), 200

            pz_pid = str(pz_pid).strip()

            # Find our internal payment by the PazzleNet payment ID stored in receipt_text
            from bot.db import get_conn as _gc
            with _gc() as _c:
                row = _c.execute(
                    "SELECT id FROM payments WHERE receipt_text=? AND payment_method='pazzlenet' AND status='pending'",
                    (pz_pid,)
                ).fetchone()
            if not row:
                return jsonify({"status": "ok"}), 200

            payment_id = row["id"]
            payment = get_payment(payment_id)
            if not payment or payment["status"] != "pending":
                return jsonify({"status": "ok"}), 200

            from bot.gateways.pazzlenet import is_pazzlenet_paid as _pz_paid
            if not _pz_paid(data):
                # Callback status not paid yet — ack it
                return jsonify({"status": "ok"}), 200

            kind   = payment["kind"]
            uid    = payment["user_id"]
            amount = payment["amount"]

            if kind == "wallet_charge":
                if not complete_payment(payment_id):
                    return jsonify({"status": "ok"}), 200
                update_balance(uid, amount)
                try:
                    apply_gateway_bonus_if_needed(uid, "pazzlenet", amount)
                except Exception:
                    pass
                try:
                    bot.send_message(
                        uid,
                        f"✅ پرداخت PazzleNet شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            else:
                # config_purchase / renewal / pnlcfg_renewal
                threading.Thread(
                    target=_run_fulfillment,
                    args=("pazzlenet", payment_id),
                    daemon=True,
                ).start()
        except Exception as exc:
            print("PAZZLENET_WEBHOOK_ERROR:", exc)
        return jsonify({"status": "ok"}), 200

    # ── Tronado routes ────────────────────────────────────────────────────────
    @_app.route("/tronado/<bot_username>/<int:payment_id>/callback", methods=["POST"])
    def _tronado_callback(bot_username, payment_id):
        try:
            payload = request.get_json(force=True, silent=True) or {}
            from bot.gateways.tronado import is_tronado_callback_valid as _td_valid
            if not _td_valid(payload):
                return jsonify({"status": "ok"}), 200

            payment = get_payment(payment_id)
            if not payment or payment["status"] != "pending" or payment["payment_method"] != "tronado":
                return jsonify({"status": "ok"}), 200

            kind   = payment["kind"]
            uid    = payment["user_id"]
            amount = payment["amount"]

            if kind == "wallet_charge":
                if not complete_payment(payment_id):
                    return jsonify({"status": "ok"}), 200
                update_balance(uid, amount)
                try:
                    apply_gateway_bonus_if_needed(uid, "tronado", amount)
                except Exception:
                    pass
                try:
                    bot.send_message(
                        uid,
                        f"✅ پرداخت ترونادو شما تأیید شد و کیف پول شارژ شد.\n\n💰 مبلغ: {fmt_price(amount)} تومان",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            else:
                threading.Thread(
                    target=_run_fulfillment,
                    args=("tronado", payment_id),
                    daemon=True,
                ).start()
        except Exception as exc:
            print("TRONADO_WEBHOOK_ERROR:", exc)
        return jsonify({"status": "ok"}), 200

    import time as _time
    import socket as _socket
    import os as _os
    import signal as _signal
    port = int(get_plisio_webhook_port())
    print(f"🌐 Payment webhook server starting on port {port}…")

    # ── Kill only OUR OWN previous instance via PID file ──────────────────────
    # Do NOT use fuser -k — that would kill other bots on the same server
    # that happen to share this port number.
    _pid_file = _os.path.join(_os.path.dirname(__file__), f".webhook_{port}.pid")
    try:
        if _os.path.exists(_pid_file):
            _old_pid = int(open(_pid_file).read().strip())
            if _old_pid != _os.getpid():
                try:
                    _os.kill(_old_pid, _signal.SIGTERM)
                    print(f"[Webhook] Sent SIGTERM to previous webhook process (PID {_old_pid})")
                    _time.sleep(1)
                    try:
                        _os.kill(_old_pid, _signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except ProcessLookupError:
                    pass
    except Exception as _pid_err:
        print(f"[Webhook] PID cleanup warning: {_pid_err}")
    try:
        open(_pid_file, "w").write(str(_os.getpid()))
    except Exception:
        pass

    def _make_reuse_server(host, p, app):
        """Create a Werkzeug server with SO_REUSEADDR + SO_REUSEPORT set on the
        socket *before* bind so the port is immediately available after restart."""
        from werkzeug.serving import make_server as _wz_make_server
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.bind((host, p))
        sock.listen(128)
        srv = _wz_make_server(host, p, app)
        srv.socket.close()
        srv.socket = sock
        return srv

    for _attempt in range(10):
        try:
            _srv = _make_reuse_server("0.0.0.0", port, _app)
            print(f" * Webhook server listening on 0.0.0.0:{port}")
            _srv.serve_forever()
            break
        except (OSError, SystemExit) as _bind_err:
            if _attempt < 9:
                print(f"⚠️ Port {port} still in use, retrying in 2s… (attempt {_attempt + 1}/10)")
                _time.sleep(2)
            else:
                print(f"❌ Cannot bind port {port} after 10 attempts: {_bind_err}")
        except Exception as _bind_err:
            print(f"❌ Webhook server error: {_bind_err}")
            break


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
