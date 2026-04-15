#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seamless Iran Agent — Main daemon process.

Loop behaviour:
  1. Send heartbeat every HEARTBEAT_INTERVAL seconds.
  2. Every PANEL_TEST_INTERVAL seconds, test panel login and report result.
  3. On any API or panel error: log, wait, retry — never crash the loop.

Run as a systemd service (see service/seamless-iran-agent.service).

Usage:
    python agent.py
"""
import os
import sys
import time
import signal

sys.path.insert(0, os.path.dirname(__file__))

from lib.config_loader import load_config
from lib.api_client    import BotApiClient, ApiError
from lib.panel_client  import XuiPanelClient
from lib.logger        import get_logger

log = get_logger("agent")

_RUNNING = True


def _handle_signal(signum, frame):
    global _RUNNING
    log.info("Signal %d received — shutting down gracefully.", signum)
    _RUNNING = False


def run_agent(cfg) -> None:
    log.info("Starting Seamless Iran Agent")
    log.info("  Agent UUID : %s", cfg.agent_uuid)
    log.info("  Bot API    : %s", cfg.bot_api_url)
    log.info("  Panel      : %s:%d", cfg.panel_host, cfg.panel_port)
    log.info("  Heartbeat  : every %d s", cfg.heartbeat_interval)
    log.info("  Panel test : every %d s", cfg.panel_test_interval)

    api = BotApiClient(
        base_url     = cfg.bot_api_url,
        agent_uuid   = cfg.agent_uuid,
        agent_secret = cfg.agent_secret,
        timeout      = cfg.request_timeout,
        proxies      = cfg.proxies(),
    )
    panel = XuiPanelClient(
        host       = cfg.panel_host,
        port       = cfg.panel_port,
        panel_path = cfg.panel_path,
        username   = cfg.panel_username,
        password   = cfg.panel_password,
        timeout    = cfg.request_timeout,
        proxies    = cfg.proxies(),
    )

    last_heartbeat  = 0.0
    last_panel_test = 0.0
    panel_ids: list[int] = []

    while _RUNNING:
        now = time.monotonic()

        # ── Heartbeat ──────────────────────────────────────────────────────────
        if now - last_heartbeat >= cfg.heartbeat_interval:
            if api.heartbeat():
                log.info("Heartbeat OK")
                # Refresh panel list on successful heartbeat
                try:
                    panels    = api.get_panels()
                    panel_ids = [p["id"] for p in panels]
                except ApiError as exc:
                    log.warning("Could not fetch panel list: %s", exc)
            else:
                log.warning("Heartbeat FAILED — will retry next cycle")
            last_heartbeat = now

        # ── Panel login test ───────────────────────────────────────────────────
        if now - last_panel_test >= cfg.panel_test_interval:
            success, message = panel.test_login()
            if success:
                log.info("Panel login test: OK")
            else:
                log.warning("Panel login test FAILED: %s", message)

            # Report to bot API for each known panel_id
            for pid in panel_ids:
                ok = api.report_panel_test(pid, success, message)
                if not ok:
                    log.warning("Failed to report panel test for panel #%d", pid)
            last_panel_test = now

        # ── Sleep (short slice for responsive shutdown) ────────────────────────
        time.sleep(min(5, cfg.heartbeat_interval))

    log.info("Agent stopped.")


def main() -> None:
    cfg = load_config(validate="runtime")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    # Initial panel test before entering loop
    log.info("Running initial panel login test...")
    panel = XuiPanelClient(
        host       = cfg.panel_host,
        port       = cfg.panel_port,
        panel_path = cfg.panel_path,
        username   = cfg.panel_username,
        password   = cfg.panel_password,
        timeout    = cfg.request_timeout,
        proxies    = cfg.proxies(),
    )
    success, message = panel.test_login()
    if success:
        log.info("Initial panel test: OK")
    else:
        log.warning("Initial panel test FAILED: %s (continuing anyway)", message)

    run_agent(cfg)


if __name__ == "__main__":
    main()
