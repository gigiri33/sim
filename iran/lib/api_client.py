# -*- coding: utf-8 -*-
"""
HTTP client for communicating with the bot's API server (foreign side).

All requests use the agent's UUID + secret for authentication.
Secrets are never logged.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False

from .logger import get_logger

log = get_logger("api_client")


class ApiError(Exception):
    """Raised when the API returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BotApiClient:
    """
    Thin wrapper around the bot's HTTP API.

    All methods raise ApiError on failure so callers can handle gracefully.
    """

    def __init__(
        self,
        base_url: str,
        agent_uuid: str,
        agent_secret: str,
        timeout: int = 15,
        proxies: dict | None = None,
    ):
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError(
                "requests package is required. Run: pip install requests"
            )
        self._base     = base_url.rstrip("/")
        self._uuid     = agent_uuid
        self._secret   = agent_secret  # never logged
        self._timeout  = timeout
        self._proxies  = proxies or {}

    def _headers(self) -> dict:
        return {
            "X-Agent-UUID":   self._uuid,
            "X-Agent-Secret": self._secret,
            "Content-Type":   "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        url = self._base + path
        try:
            resp = _requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
                proxies=self._proxies,
            )
        except _requests.exceptions.ConnectionError as exc:
            raise ApiError(f"Connection error to {url}: {exc}")
        except _requests.exceptions.Timeout:
            raise ApiError(f"Request timed out: {url}")
        except Exception as exc:
            raise ApiError(f"Request failed: {exc}")

        try:
            data = resp.json()
        except Exception:
            raise ApiError(f"Non-JSON response ({resp.status_code}): {resp.text[:200]}")

        if not resp.ok:
            raise ApiError(
                data.get("error", f"HTTP {resp.status_code}"),
                status_code=resp.status_code,
            )
        return data

    def _get(self, path: str) -> dict:
        url = self._base + path
        try:
            resp = _requests.get(
                url,
                headers=self._headers(),
                timeout=self._timeout,
                proxies=self._proxies,
            )
        except _requests.exceptions.ConnectionError as exc:
            raise ApiError(f"Connection error to {url}: {exc}")
        except _requests.exceptions.Timeout:
            raise ApiError(f"Request timed out: {url}")
        except Exception as exc:
            raise ApiError(f"Request failed: {exc}")

        try:
            data = resp.json()
        except Exception:
            raise ApiError(f"Non-JSON response ({resp.status_code}): {resp.text[:200]}")

        if not resp.ok:
            raise ApiError(
                data.get("error", f"HTTP {resp.status_code}"),
                status_code=resp.status_code,
            )
        return data

    # ── Public methods ─────────────────────────────────────────────────────────

    def heartbeat(self) -> bool:
        """Send a heartbeat. Returns True on success."""
        try:
            self._post(f"/iran/agents/{self._uuid}/heartbeat", {})
            return True
        except ApiError as exc:
            log.warning("Heartbeat failed: %s", exc)
            return False

    def report_panel_test(self, panel_id: int, success: bool, message: str = "") -> bool:
        """Report panel test result. Returns True on success."""
        try:
            self._post(f"/iran/agents/{self._uuid}/panel-test", {
                "panel_id": panel_id,
                "success":  success,
                "message":  message,
            })
            return True
        except ApiError as exc:
            log.warning("report_panel_test failed for panel %d: %s", panel_id, exc)
            return False

    def get_panels(self) -> list[dict]:
        """Fetch the list of panels assigned to this agent."""
        data = self._get(f"/iran/agents/{self._uuid}/panels")
        return data.get("panels", [])

    def health_check(self) -> bool:
        """Ping the /health endpoint (no auth required)."""
        url = self._base + "/health"
        try:
            resp = _requests.get(url, timeout=self._timeout, proxies=self._proxies)
            return resp.ok
        except Exception:
            return False


def register_agent(
    base_url: str,
    registration_token: str,
    agent_name: str,
    panel_name: str,
    panel_host: str,
    panel_port: int,
    panel_path: str,
    panel_username: str,
    panel_password: str,
    timeout: int = 15,
    proxies: dict | None = None,
) -> dict:
    """
    One-shot registration call.
    Returns dict with agent_uuid, agent_secret, panel_id on success.
    Raises ApiError on failure.
    """
    if not _REQUESTS_AVAILABLE:
        raise RuntimeError("requests package is required. Run: pip install requests")

    url     = base_url.rstrip("/") + "/iran/agents/register"
    payload = {
        "registration_token": registration_token,
        "agent_name":         agent_name,
        "panel_name":         panel_name,
        "panel_host":         panel_host,
        "panel_port":         panel_port,
        "panel_path":         panel_path,
        "panel_username":     panel_username,
        "panel_password":     panel_password,
    }
    try:
        resp = _requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
            proxies=proxies or {},
        )
    except _requests.exceptions.ConnectionError as exc:
        raise ApiError(f"Cannot connect to {url}: {exc}")
    except _requests.exceptions.Timeout:
        raise ApiError(f"Connection timed out: {url}")
    except Exception as exc:
        raise ApiError(f"Request failed: {exc}")

    try:
        data = resp.json()
    except Exception:
        raise ApiError(f"Non-JSON response ({resp.status_code}): {resp.text[:200]}")

    if not resp.ok:
        raise ApiError(
            data.get("error", f"HTTP {resp.status_code}"),
            status_code=resp.status_code,
        )
    return data
