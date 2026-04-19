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
        update_panel_status(panel["id"], status, err or "")
        log.debug("Panel %s → %s", panel["name"], status)


def _check_panel_configs_expiry() -> None:
    """
    Check all non-expired panel_configs:
    1. If expire_at has passed (local check), mark expired and notify user.
    2. Also verify against panel API (client.enable == False).
    """
    from ..db import (
        get_unexpired_panel_configs, get_panel,
        mark_panel_config_expired, mark_panel_config_notified,
    )
    from ..bot_instance import bot
    from .client import PanelClient
    from datetime import datetime

    configs = get_unexpired_panel_configs()
    for cfg in configs:
        try:
            # ── Local expire_at check ──────────────────────────────────────────
            expire_at = cfg["expire_at"]
            if expire_at:
                try:
                    exp_dt = datetime.strptime(expire_at, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    exp_dt = None
                if exp_dt and datetime.now() >= exp_dt:
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
