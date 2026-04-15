#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Iran Agent — Health check utility.

Checks and prints the status of:
  1. Bot API connectivity (foreign server)
  2. Agent authentication (UUID + secret)
  3. Panel login (3x-ui)

Exit codes:
  0 — all checks passed
  1 — one or more checks failed

Usage:
    python healthcheck.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from lib.config_loader import load_config
from lib.api_client    import BotApiClient, ApiError
from lib.panel_client  import XuiPanelClient
from lib.logger        import get_logger

log = get_logger("healthcheck")

GREEN = "\033[92m"
RED   = "\033[91m"
RESET = "\033[0m"

def ok(msg: str) -> None:
    print(f"{GREEN}  ✓ {msg}{RESET}")

def fail(msg: str) -> None:
    print(f"{RED}  ✗ {msg}{RESET}")


def main() -> None:
    cfg     = load_config(validate="none")
    passed  = 0
    total   = 0

    print("\n── Seamless Iran Agent Health Check ──\n")

    # 1. API reachability
    total += 1
    if cfg.bot_api_url:
        api = BotApiClient(
            base_url     = cfg.bot_api_url,
            agent_uuid   = cfg.agent_uuid or "none",
            agent_secret = cfg.agent_secret or "none",
            timeout      = cfg.request_timeout,
            proxies      = cfg.proxies(),
        )
        if api.health_check():
            ok(f"Bot API reachable at {cfg.bot_api_url}")
            passed += 1
        else:
            fail(f"Bot API NOT reachable at {cfg.bot_api_url}")
    else:
        fail("BOT_API_URL not configured")

    # 2. Agent authentication
    total += 1
    if cfg.is_registered:
        api = BotApiClient(
            base_url     = cfg.bot_api_url,
            agent_uuid   = cfg.agent_uuid,
            agent_secret = cfg.agent_secret,
            timeout      = cfg.request_timeout,
            proxies      = cfg.proxies(),
        )
        if api.heartbeat():
            ok(f"Agent authenticated (UUID: {cfg.agent_uuid[:8]}...)")
            passed += 1
        else:
            fail("Agent authentication FAILED — wrong credentials or revoked")
    else:
        fail("Agent not registered (AGENT_UUID / AGENT_SECRET missing)")

    # 3. Panel login
    total += 1
    if cfg.panel_host and cfg.panel_username and cfg.panel_password:
        client = XuiPanelClient(
            host       = cfg.panel_host,
            port       = cfg.panel_port,
            panel_path = cfg.panel_path,
            username   = cfg.panel_username,
            password   = cfg.panel_password,
            timeout    = cfg.request_timeout,
            proxies    = cfg.proxies(),
        )
        success, message = client.test_login()
        if success:
            ok(f"Panel login OK ({cfg.panel_host}:{cfg.panel_port})")
            passed += 1
        else:
            fail(f"Panel login FAILED: {message}")
    else:
        fail("Panel credentials not configured")

    print(f"\n── Result: {passed}/{total} checks passed ──\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
