#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Iran Agent — Register with the bot API.

This script is run ONCE during installation.
It sends registration credentials to the bot API, receives agent_uuid and
agent_secret, then writes them to config.env.

Usage:
    python register.py

Environment (from config.env):
    BOT_API_URL, REGISTRATION_TOKEN, AGENT_NAME,
    PANEL_NAME, PANEL_HOST, PANEL_PORT, PANEL_PATH,
    PANEL_USERNAME, PANEL_PASSWORD
"""
import os
import sys

# Ensure lib/ is importable when run from the iran/ directory
sys.path.insert(0, os.path.dirname(__file__))

from lib.config_loader import load_config
from lib.api_client    import register_agent, ApiError
from lib.logger        import get_logger

log = get_logger("register")

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.env")


def _update_config_file(key: str, value: str) -> None:
    """Write or update a key=value line in config.env. Creates file if absent."""
    lines      = []
    found      = False
    config_path = CONFIG_FILE

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(key + "=") or stripped.startswith(f"# {key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def main() -> None:
    cfg = load_config(validate="registration")

    if cfg.is_registered:
        log.info("Agent is already registered (AGENT_UUID is set).")
        log.info("To re-register, clear AGENT_UUID and AGENT_SECRET from config.env.")
        sys.exit(0)

    log.info("Registering agent '%s' with %s ...", cfg.agent_name, cfg.bot_api_url)

    try:
        result = register_agent(
            base_url           = cfg.bot_api_url,
            registration_token = cfg.registration_token,
            agent_name         = cfg.agent_name,
            panel_name         = cfg.panel_name,
            panel_host         = cfg.panel_host,
            panel_port         = cfg.panel_port,
            panel_path         = cfg.panel_path,
            panel_username     = cfg.panel_username,
            panel_password     = cfg.panel_password,
            timeout            = cfg.request_timeout,
            proxies            = cfg.proxies(),
        )
    except ApiError as exc:
        log.error("Registration failed: %s", exc)
        sys.exit(1)

    agent_uuid   = result["agent_uuid"]
    agent_secret = result["agent_secret"]

    log.info("Registration successful!")
    log.info("  Agent UUID : %s", agent_uuid)
    log.info("  Panel ID   : %s", result.get("panel_id"))
    log.info("  Message    : %s", result.get("message", ""))

    # Persist credentials
    _update_config_file("AGENT_UUID",   agent_uuid)
    _update_config_file("AGENT_SECRET", agent_secret)

    log.info("Credentials saved to config.env.")
    log.info("You can now start the agent: python agent.py")


if __name__ == "__main__":
    main()
