# -*- coding: utf-8 -*-
"""
HTTP client for communicating with the bot's API server (foreign side).

Uses only Python standard library (urllib) — zero external dependencies.
All requests use the agent's UUID + secret for authentication.
Secrets are never logged.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .logger import get_logger

log = get_logger("api_client")


class ApiError(Exception):
    """Raised when the API returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _build_opener(proxies: dict | None) -> urllib.request.OpenerDirector:
    """Build a urllib opener with optional HTTP proxy support."""
    proxy_url = (proxies or {}).get("https") or (proxies or {}).get("http")
    if proxy_url:
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    else:
        handler = urllib.request.ProxyHandler({})  # explicitly disable env proxies
    return urllib.request.build_opener(handler)


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
        self._base    = base_url.rstrip("/")
        self._uuid    = agent_uuid
        self._secret  = agent_secret  # never logged
        self._timeout = timeout
        self._opener  = _build_opener(proxies)

    def _headers(self) -> dict[str, str]:
        return {
            "X-Agent-UUID":   self._uuid,
            "X-Agent-Secret": self._secret,
            "Content-Type":   "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        url  = self._base + path
        body = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=body, method="POST")
        for k, v in self._headers().items():
            req.add_header(k, v)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                raise ApiError(data.get("error", f"HTTP {exc.code}"), status_code=exc.code)
            except (json.JSONDecodeError, ValueError):
                raise ApiError(f"HTTP {exc.code}: {raw[:200]}", status_code=exc.code)
        except urllib.error.URLError as exc:
            raise ApiError(f"Connection error to {url}: {exc.reason}")
        except Exception as exc:
            raise ApiError(f"Request failed: {exc}")

    def _get(self, path: str) -> dict:
        url = self._base + path
        req = urllib.request.Request(url, method="GET")
        for k, v in self._headers().items():
            req.add_header(k, v)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                raise ApiError(data.get("error", f"HTTP {exc.code}"), status_code=exc.code)
            except (json.JSONDecodeError, ValueError):
                raise ApiError(f"HTTP {exc.code}: {raw[:200]}", status_code=exc.code)
        except urllib.error.URLError as exc:
            raise ApiError(f"Connection error to {url}: {exc.reason}")
        except Exception as exc:
            raise ApiError(f"Request failed: {exc}")

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
        """Check API reachability (no auth required). Returns True on success."""
        try:
            self._get("/health")
            return True
        except ApiError:
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
    Register a new agent with the bot API.
    Returns the response dict containing agent_uuid and agent_secret.
    Raises ApiError on failure.
    """
    opener  = _build_opener(proxies)
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
    url  = base_url.rstrip("/") + "/iran/agents/register"
    body = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
            raise ApiError(data.get("error", f"HTTP {exc.code}"), status_code=exc.code)
        except (json.JSONDecodeError, ValueError):
            raise ApiError(f"HTTP {exc.code}: {raw[:200]}", status_code=exc.code)
    except urllib.error.URLError as exc:
        raise ApiError(f"Connection error to {base_url}: {exc.reason}")
    except Exception as exc:
        raise ApiError(f"Registration failed: {exc}")
