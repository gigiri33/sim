#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Iran Agent — Panel login test utility.

Tests the login to the configured 3x-ui panel and reports the result
to the bot API.

Usage:
    python test_panel.py          # test and report to API
    python test_panel.py --local  # test only, no API report
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from lib.config_loader import load_config
from lib.panel_client  import XuiPanelClient
from lib.api_client    import BotApiClient, ApiError
from lib.logger        import get_logger

log = get_logger("test_panel")


def test_panel(cfg, report: bool = True) -> bool:
    """
    Test panel login.
    If report=True, send the result to the bot API.
    Returns True if login succeeded.
    """
    log.info("Testing login to panel: %s:%d", cfg.panel_host, cfg.panel_port)

    client          = XuiPanelClient(
        host        = cfg.panel_host,
        port        = cfg.panel_port,
        panel_path  = cfg.panel_path,
        username    = cfg.panel_username,
        password    = cfg.panel_password,
        timeout     = cfg.request_timeout,
        proxies     = cfg.proxies(),
    )
    success, message = client.test_login()

    if success:
        log.info("Panel login OK: %s", message)
    else:
        log.error("Panel login FAILED: %s", message)

    if report and cfg.is_registered:
        api = BotApiClient(
            base_url     = cfg.bot_api_url,
            agent_uuid   = cfg.agent_uuid,
            agent_secret = cfg.agent_secret,
            timeout      = cfg.request_timeout,
            proxies      = cfg.proxies(),
        )
        # We need the panel_id; fetch panels to get it
        try:
            panels = api.get_panels()
            for panel in panels:
                api.report_panel_test(
                    panel_id = panel["id"],
                    success  = success,
                    message  = message,
                )
            log.info("Panel test result reported to API.")
        except ApiError as exc:
            log.warning("Failed to report panel test: %s", exc)

    return success


def main() -> None:
    local_only = "--local" in sys.argv
    validate   = "none" if local_only else "runtime"
    cfg        = load_config(validate=validate)

    if local_only:
        # Reload with minimal validation for panel fields only
        errors = []
        if not cfg.panel_host:
            errors.append("PANEL_HOST")
        if not cfg.panel_username:
            errors.append("PANEL_USERNAME")
        if not cfg.panel_password:
            errors.append("PANEL_PASSWORD")
        if errors:
            print(f"❌ Missing: {', '.join(errors)}")
            sys.exit(1)

    success = test_panel(cfg, report=not local_only)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
