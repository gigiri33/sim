# -*- coding: utf-8 -*-
"""
Business-logic services for Iran Panel management.

Exposed surface used by:
  - api.py          (HTTP endpoints for Iran agents)
  - admin handlers  (admin bot UI)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jdatetime

from .crypto_utils import (
    generate_reg_token,
    generate_agent_secret,
    generate_uuid,
    generate_salt,
    hash_with_salt,
    verify_hash,
    encrypt_secret,
    decrypt_secret,
)
from .db import (
    create_reg_token,
    consume_reg_token,
    get_reg_tokens,
    delete_reg_token,
    create_iran_agent,
    get_iran_agent_by_uuid,
    get_iran_agent,
    get_all_iran_agents,
    update_agent_heartbeat,
    update_agent_status,
    revoke_iran_agent,
    delete_iran_agent,
    create_iran_panel,
    get_iran_panel,
    get_all_iran_panels,
    get_panels_for_agent,
    update_iran_panel_status,
    toggle_iran_panel,
    delete_iran_panel,
    get_panel_logs,
    get_reg_tokens,
)

_TZ_TEHRAN = timezone(timedelta(hours=3, minutes=30))

# ── Token management ───────────────────────────────────────────────────────────

def make_registration_token(
    label: str,
    created_by: int,
    ttl_hours: int = 24,
) -> tuple[str, int]:
    """
    Create a one-time registration token for an Iran-side agent.

    Args:
        label:       Human-readable label (e.g. "Server Tehran-1").
        created_by:  Admin user_id who created this token.
        ttl_hours:   Token validity window (default 24 h).

    Returns:
        (token_plaintext, token_id)
    """
    token      = generate_reg_token()
    expiry_dt  = datetime.now(_TZ_TEHRAN) + timedelta(hours=ttl_hours)
    expires_at = jdatetime.datetime.fromgregorian(datetime=expiry_dt).strftime("%Y-%m-%d %H:%M:%S")
    token_id   = create_reg_token(token, label, expires_at, created_by)
    return token, token_id


# ── Agent registration ─────────────────────────────────────────────────────────

class RegistrationError(Exception):
    """Raised when agent registration fails for a known reason."""


def register_agent(
    reg_token: str,
    agent_name: str,
    panel_name: str,
    panel_host: str,
    panel_port: int,
    panel_path: str,
    panel_username: str,
    panel_password: str,
) -> dict:
    """
    Validate registration token and create agent + panel records.

    Returns a dict with:
      agent_uuid   – UUID for future requests
      agent_secret – plaintext secret for future auth (store on Iran side)
      panel_id     – ID of the created panel record

    Raises RegistrationError on any validation failure.
    """
    # 1. Validate inputs
    agent_name     = (agent_name or "").strip()
    panel_name     = (panel_name or "").strip()
    panel_host     = (panel_host or "").strip()
    panel_path     = (panel_path or "").strip().strip("/")
    panel_username = (panel_username or "").strip()
    panel_password = (panel_password or "").strip()

    if not agent_name:
        raise RegistrationError("agent_name is required")
    if not panel_name:
        raise RegistrationError("panel_name is required")
    if not panel_host:
        raise RegistrationError("panel_host is required")
    if not (1 <= panel_port <= 65535):
        raise RegistrationError("panel_port must be 1–65535")
    if not panel_username:
        raise RegistrationError("panel_username is required")
    if not panel_password:
        raise RegistrationError("panel_password is required")

    # 2. Generate agent identity
    agent_uuid     = generate_uuid()
    agent_secret   = generate_agent_secret()
    agent_salt     = generate_salt()
    agent_secret_h = hash_with_salt(agent_secret, agent_salt)

    # 3. Consume registration token (atomic — fails if already used / expired)
    token_row = consume_reg_token(reg_token, agent_uuid)
    if not token_row:
        raise RegistrationError(
            "Registration token is invalid, expired, or already used."
        )

    # 4. Encrypt panel password
    bot_token    = os.getenv("BOT_TOKEN", "")
    password_enc = encrypt_secret(panel_password, bot_token)

    # 5. Persist
    agent_id = create_iran_agent(agent_uuid, agent_name, agent_secret_h, agent_salt)
    panel_id = create_iran_panel(
        agent_id, panel_name, panel_host, panel_port,
        panel_path, panel_username, password_enc,
    )

    return {
        "agent_uuid":   agent_uuid,
        "agent_secret": agent_secret,   # returned ONCE — agent must save this
        "agent_id":     agent_id,
        "panel_id":     panel_id,
    }


# ── Agent authentication ───────────────────────────────────────────────────────

def authenticate_agent(agent_uuid: str, agent_secret: str) -> dict | None:
    """
    Verify agent_uuid + agent_secret.
    Returns agent row (dict) on success, None on failure.
    Revoked agents are rejected.
    """
    agent = get_iran_agent_by_uuid(agent_uuid)
    if not agent:
        return None
    if agent["status"] == "revoked":
        return None
    if not verify_hash(agent_secret, agent["secret_salt"], agent["secret_hash"]):
        return None
    return agent


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def process_heartbeat(agent_uuid: str, agent_secret: str) -> bool:
    """
    Record a heartbeat from an Iran agent.
    Returns True on success, False if authentication fails.
    """
    agent = authenticate_agent(agent_uuid, agent_secret)
    if not agent:
        return False
    update_agent_heartbeat(agent_uuid)
    return True


# ── Panel test result ──────────────────────────────────────────────────────────

def record_panel_test(
    agent_uuid: str,
    agent_secret: str,
    panel_id: int,
    success: bool,
    message: str = "",
) -> bool:
    """
    Record the result of a panel login test reported by the Iran agent.
    Returns True if stored, False if auth failed or panel not found.
    """
    agent = authenticate_agent(agent_uuid, agent_secret)
    if not agent:
        return False

    panel = get_iran_panel(panel_id)
    if not panel or panel["agent_id"] != agent["id"]:
        return False  # panel doesn't belong to this agent

    status = "active" if success else "failed"
    error  = None if success else (message or "Login test failed")
    update_iran_panel_status(panel_id, status, error, check_type="test")
    return True


# ── Admin helpers ──────────────────────────────────────────────────────────────

def get_panel_detail_with_password(panel_id: int) -> dict | None:
    """Return panel dict with decrypted password for display (admin only)."""
    panel = get_iran_panel(panel_id)
    if not panel:
        return None
    bot_token = os.getenv("BOT_TOKEN", "")
    try:
        panel["password_plain"] = decrypt_secret(panel["password_enc"], bot_token)
    except Exception:
        panel["password_plain"] = "⚠️ decryption failed"
    return panel


def list_panels_for_agent_response(agent_uuid: str, agent_secret: str) -> list[dict] | None:
    """
    Return a list of panel configs for the given agent (used by agent polling).
    Passwords are decrypted in this response since only the authenticated agent
    sees them and they need the credential to do the login test.
    Returns None on auth failure.
    """
    agent = authenticate_agent(agent_uuid, agent_secret)
    if not agent:
        return None
    panels = get_panels_for_agent(agent["id"])
    bot_token = os.getenv("BOT_TOKEN", "")
    result = []
    for p in panels:
        if not p["is_active"]:
            continue
        try:
            pw = decrypt_secret(p["password_enc"], bot_token)
        except Exception:
            pw = ""
        result.append({
            "id":           p["id"],
            "name":         p["name"],
            "host":         p["host"],
            "port":         p["port"],
            "panel_path":   p["panel_path"],
            "username":     p["username"],
            "password":     pw,
            "status":       p["status"],
        })
    return result
