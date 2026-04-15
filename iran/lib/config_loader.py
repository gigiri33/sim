# -*- coding: utf-8 -*-
"""
Config loader for the Iran agent.

Uses only Python standard library — zero external dependencies.
Parses KEY=VALUE files with the same semantics as python-dotenv:
  - Lines starting with # are comments
  - Blank lines are ignored
  - Inline comments after # are stripped (unless value is quoted)
  - Already-set env vars are NOT overwritten
"""
import os
import sys


def _load_env_file(path: str) -> None:
    """Parse a simple KEY=VALUE env file and inject missing keys into os.environ."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip()
            # Strip inline comment for unquoted values
            if value and value[0] not in ('"', "'"):
                value = value.split("#")[0].strip()
            else:
                # Remove surrounding quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


# Load config files (same precedence order as python-dotenv)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # iran/
_load_env_file(os.path.join(_BASE_DIR, "config.env"))
_load_env_file(os.path.join(_BASE_DIR, ".env"))


class AgentConfig:
    """Immutable configuration snapshot read from environment variables."""

    def __init__(self):
        self.bot_api_url         = os.getenv("BOT_API_URL", "").rstrip("/")
        self.registration_token  = os.getenv("REGISTRATION_TOKEN", "").strip()
        self.agent_uuid          = os.getenv("AGENT_UUID", "").strip()
        self.agent_secret        = os.getenv("AGENT_SECRET", "").strip()
        self.agent_name          = os.getenv("AGENT_NAME", "Iran Agent").strip()
        self.panel_name          = os.getenv("PANEL_NAME", "My Panel").strip()
        self.panel_host          = os.getenv("PANEL_HOST", "127.0.0.1").strip()
        self.panel_port          = int(os.getenv("PANEL_PORT", "2053") or 2053)
        self.panel_path          = os.getenv("PANEL_PATH", "").strip().strip("/")
        self.panel_username      = os.getenv("PANEL_USERNAME", "").strip()
        self.panel_password      = os.getenv("PANEL_PASSWORD", "").strip()
        self.heartbeat_interval  = int(os.getenv("HEARTBEAT_INTERVAL", "60") or 60)
        self.panel_test_interval = int(os.getenv("PANEL_TEST_INTERVAL", "300") or 300)
        self.request_timeout     = int(os.getenv("REQUEST_TIMEOUT", "15") or 15)
        self.proxy_url           = os.getenv("PROXY_URL", "").strip() or None

    @property
    def is_registered(self) -> bool:
        return bool(self.agent_uuid and self.agent_secret)

    def validate_for_registration(self) -> list[str]:
        """Return a list of missing/invalid field names."""
        errors = []
        if not self.bot_api_url:
            errors.append("BOT_API_URL")
        if not self.registration_token:
            errors.append("REGISTRATION_TOKEN")
        if not self.agent_name:
            errors.append("AGENT_NAME")
        if not self.panel_name:
            errors.append("PANEL_NAME")
        if not self.panel_host:
            errors.append("PANEL_HOST")
        if not (1 <= self.panel_port <= 65535):
            errors.append("PANEL_PORT (must be 1–65535)")
        if not self.panel_username:
            errors.append("PANEL_USERNAME")
        if not self.panel_password:
            errors.append("PANEL_PASSWORD")
        return errors

    def validate_for_runtime(self) -> list[str]:
        """Return a list of missing/invalid field names for normal operation."""
        errors = []
        if not self.bot_api_url:
            errors.append("BOT_API_URL")
        if not self.agent_uuid:
            errors.append("AGENT_UUID")
        if not self.agent_secret:
            errors.append("AGENT_SECRET")
        return errors

    def proxies(self) -> dict | None:
        if self.proxy_url:
            return {"http": self.proxy_url, "https": self.proxy_url}
        return None


def load_config(validate: str = "runtime") -> AgentConfig:
    """
    Load and validate configuration.

    Args:
        validate: 'runtime' | 'registration' | 'none'

    Raises SystemExit on validation failure.
    """
    cfg    = AgentConfig()
    errors: list[str] = []
    if validate == "runtime":
        errors = cfg.validate_for_runtime()
    elif validate == "registration":
        errors = cfg.validate_for_registration()

    if errors:
        print(f"❌ Missing or invalid configuration: {', '.join(errors)}")
        print("   Check your config.env file.")
        sys.exit(1)

    return cfg
