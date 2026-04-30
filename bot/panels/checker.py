# -*- coding: utf-8 -*-
"""
Background daemon that checks every 30 seconds whether each active panel
is reachable and updates its connection_status in the database.
Also periodically checks panel-created configs for expiration.
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

_INTERVAL        = 30   # seconds between full panel health-check cycles
_EXPIRY_INTERVAL = 300  # seconds between expiry check cycles (5 min)
_expiry_counter  = 0


def _check_all_panels() -> None:
    """Run one health-check pass over all active panels."""
    from ..db import get_active_panels, update_panel_status
    from ..helpers import now_str
    from .client import PanelClient

    panels = get_active_panels()
    for panel in panels:
        client = PanelClient(
            protocol=panel["protocol"],
            host=panel["host"],
            port=panel["port"],
            path=panel["path"] or "",
            username=panel["username"],
            password=panel["password"],
        )
        ok, err = client.health_check()
        status = "connected" if ok else "disconnected"
        if err:
            import re as _re
            err = _re.sub(r"<[^>]+>", "[...]", str(err))[:300]
        update_panel_status(panel["id"], status, err or "")
        log.debug("Panel %s → %s", panel["name"], status)


def _check_panel_configs_expiry() -> None:
    """
    Check all non-expired panel_configs:
    1. If expire_at has passed (local check):
       - If auto_renew is enabled: deduct balance first, then renew on panel.
         If balance is insufficient: disable auto_renew, mark expired, notify user.
       - Otherwise: mark expired and notify user.
    2. Also verify against panel API (client.enable == False).
    """
    from ..db import (
        get_unexpired_panel_configs, get_panel,
        mark_panel_config_expired, mark_panel_config_notified,
        get_package, get_user, update_balance,
        update_panel_config_field,
    )
    from ..bot_instance import bot
    from .client import PanelClient
    from datetime import datetime, timedelta

    configs = get_unexpired_panel_configs()
    for cfg in configs:
        try:
            cfg = dict(cfg)
            # ── Local expire_at check ──────────────────────────────────────────
            expire_at = cfg["expire_at"]
            if expire_at:
                try:
                    exp_dt = datetime.strptime(expire_at[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    exp_dt = None
                if exp_dt and datetime.now() >= exp_dt:
                    # ── Auto-renew attempt ─────────────────────────────────────
                    auto_renewed = False
                    if int(cfg.get("auto_renew") or 0) and cfg.get("package_id"):
                        try:
                            from ..payments import get_effective_price
                            pkg  = get_package(cfg["package_id"])
                            user = get_user(cfg["user_id"])
                            if pkg and user:
                                price   = get_effective_price(cfg["user_id"], pkg)
                                balance = int(user["balance"] or 0)
                                if price > 0 and balance < price:
                                    # Insufficient balance — disable auto_renew
                                    update_panel_config_field(cfg["id"], "auto_renew", 0)
                                    try:
                                        bot.send_message(
                                            cfg["user_id"],
                                            "⚠️ <b>تمدید خودکار ناموفق</b>\n\n"
                                            f"سرویس <b>{cfg.get('client_name') or ''}</b> به اتمام رسید "
                                            "اما موجودی کیف پول شما برای تمدید خودکار کافی نیست.\n"
                                            "تمدید خودکار این سرویس غیرفعال شد.\n\n"
                                            "برای تمدید یا خرید سرویس جدید اقدام کنید.",
                                            parse_mode="HTML",
                                        )
                                    except Exception:
                                        pass
                                else:
                                    # Deduct balance first, then renew
                                    if price > 0:
                                        update_balance(cfg["user_id"], -price)
                                    panel = get_panel(cfg["panel_id"])
                                    renew_ok = False
                                    if panel:
                                        client = PanelClient(
                                            protocol=panel["protocol"],
                                            host=panel["host"],
                                            port=panel["port"],
                                            path=panel["path"] or "",
                                            username=panel["username"],
                                            password=panel["password"],
                                        )
                                        client.reset_client_traffic(
                                            cfg["inbound_id"], cfg["client_name"] or ""
                                        )
                                        dur_days = int(pkg["duration_days"] or 0)
                                        if dur_days:
                                            new_exp_dt  = datetime.utcnow() + timedelta(days=dur_days)
                                            new_exp_str = new_exp_dt.strftime("%Y-%m-%d %H:%M:%S")
                                            new_exp_ms  = int(new_exp_dt.timestamp() * 1000)
                                        else:
                                            new_exp_str = None
                                            new_exp_ms  = 0
                                        ok_r, _ = client.enable_client(
                                            inbound_id=cfg["inbound_id"],
                                            client_uuid=cfg["client_uuid"],
                                            email=cfg["client_name"] or "",
                                            traffic_bytes=int((pkg["volume_gb"] or 0) * 1073741824),
                                            expire_ms=new_exp_ms,
                                        )
                                        if ok_r:
                                            renew_ok = True
                                            update_panel_config_field(cfg["id"], "expire_at",  new_exp_str)
                                            update_panel_config_field(cfg["id"], "is_expired",  0)
                                            update_panel_config_field(cfg["id"], "is_disabled", 0)
                                    if renew_ok:
                                        auto_renewed = True
                                        try:
                                            price_text = f"{price:,} تومان" if price > 0 else "رایگان"
                                            bot.send_message(
                                                cfg["user_id"],
                                                "✅ <b>تمدید خودکار انجام شد</b>\n\n"
                                                f"سرویس <b>{cfg.get('client_name') or ''}</b> "
                                                f"با موفقیت تمدید شد.\n"
                                                f"مبلغ {price_text} از کیف پول شما کسر شد.",
                                                parse_mode="HTML",
                                            )
                                        except Exception:
                                            pass
                                        try:
                                            from ..ui.notifications import admin_renewal_notify as _arn
                                            _tn_pc = ""
                                            try:
                                                _tn_pc = pkg["type_name"]
                                            except Exception:
                                                pass
                                            _arn(
                                                cfg["user_id"],
                                                {
                                                    "config_id": cfg["id"],
                                                    "service_name": cfg.get("client_name") or "",
                                                    "type_name": _tn_pc,
                                                },
                                                pkg,
                                                price,
                                                "تمدید خودکار",
                                            )
                                        except Exception:
                                            pass
                                    else:
                                        # Renewal failed — refund and fall through to expire
                                        if price > 0:
                                            update_balance(cfg["user_id"], price)
                        except Exception as ae:
                            log.error("Auto-renew error for panel_config #%s: %s", cfg["id"], ae)

                    if not auto_renewed:
                        mark_panel_config_expired(cfg["id"])
                        if not cfg["expired_notified"]:
                            try:
                                bot.send_message(
                                    cfg["user_id"],
                                    "⚠️ <b>سرویس شما به اتمام رسید.</b>\n\n"
                                    "برای تمدید یا خرید سرویس جدید اقدام کنید.",
                                    parse_mode="HTML",
                                )
                                mark_panel_config_notified(cfg["id"])
                            except Exception:
                                pass
                    continue

            # ── Panel API check (confirm disable status) ───────────────────────
            panel = get_panel(cfg["panel_id"])
            if not panel or not panel["is_active"]:
                continue

            client = PanelClient(
                protocol=panel["protocol"],
                host=panel["host"],
                port=panel["port"],
                path=panel["path"] or "",
                username=panel["username"],
                password=panel["password"],
            )
            ok, _ = client.login()
            if not ok:
                continue

            ok2, info = client.get_client_traffics(cfg["client_name"] or "")
            if ok2 and info:
                if not info.get("enable", True):
                    mark_panel_config_expired(cfg["id"])
                    if not cfg["expired_notified"]:
                        try:
                            bot.send_message(
                                cfg["user_id"],
                                "⚠️ <b>سرویس شما به اتمام رسید.</b>\n\n"
                                "برای تمدید یا خرید سرویس جدید اقدام کنید.",
                                parse_mode="HTML",
                            )
                            mark_panel_config_notified(cfg["id"])
                        except Exception:
                            pass

        except Exception as exc:
            log.error("Expiry check error for panel_config #%s: %s", cfg["id"], exc)


def _checker_loop() -> None:
    global _expiry_counter
    while True:
        try:
            _check_all_panels()
        except Exception as exc:
            log.error("Panel checker error: %s", exc)

        _expiry_counter += 1
        if _expiry_counter >= (_EXPIRY_INTERVAL // _INTERVAL):
            _expiry_counter = 0
            try:
                _check_panel_configs_expiry()
            except Exception as exc:
                log.error("Panel expiry checker error: %s", exc)

        time.sleep(_INTERVAL)


def start_panel_checker() -> None:
    """Start the background panel health-checker thread (daemon)."""
    t = threading.Thread(target=_checker_loop, daemon=True, name="panel-checker")
    t.start()
