"""
Integration tests for the Iran agent flow:
register.py, test_panel.py, and agent heartbeat — using mocked HTTP calls.

All tests use only Python standard library mocks (unittest.mock).
No external dependencies (requests, etc.) are used.
"""
import io
import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iran"))

os.environ.update({
    "BOT_API_URL":         "http://fake-api:8080",
    "REGISTRATION_TOKEN":  "deadbeef" * 5,
    "AGENT_NAME":          "TestAgent",
    "PANEL_NAME":          "TestPanel",
    "PANEL_HOST":          "127.0.0.1",
    "PANEL_PORT":          "2053",
    "PANEL_PATH":          "",
    "PANEL_USERNAME":      "admin",
    "PANEL_PASSWORD":      "password",
    "AGENT_UUID":          "",
    "AGENT_SECRET":        "",
})


def _fake_cm(body: dict | list, status: int = 200):
    """
    Build a fake urllib context-manager response.

    Assigns `__enter__.return_value = self` so that
      with opener.open(...) as resp:
    binds `resp` to this mock, making `resp.read()` return the encoded JSON.
    """
    raw  = json.dumps(body).encode("utf-8")
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = raw
    resp.__enter__.return_value = resp
    return resp


def _url_error(msg: str):
    import urllib.error
    return urllib.error.URLError(msg)


def _http_error(status: int, body: dict):
    import urllib.error
    raw = json.dumps(body).encode("utf-8")
    return urllib.error.HTTPError(url="", code=status, msg="", hdrs=None, fp=io.BytesIO(raw))


def _make_api(proxies=None):
    """Create a BotApiClient with a patched _opener (no real network)."""
    from lib.api_client import BotApiClient
    api = BotApiClient(
        base_url     = "http://fake-api:8080",
        agent_uuid   = "uuid-123",
        agent_secret = "secret-456",
        timeout      = 5,
        proxies      = proxies,
    )
    # Replace the opener with a mock so no real HTTP is ever made
    api._opener = MagicMock()
    return api


# ── BotApiClient — heartbeat ───────────────────────────────────────────────────

class TestApiClientHeartbeat(unittest.TestCase):

    def test_heartbeat_success(self):
        api = _make_api()
        api._opener.open.return_value = _fake_cm({"status": "ok"})
        self.assertTrue(api.heartbeat())

    def test_heartbeat_http_403(self):
        api = _make_api()
        api._opener.open.side_effect = _http_error(403, {"error": "Forbidden"})
        self.assertFalse(api.heartbeat())

    def test_heartbeat_connection_error(self):
        api = _make_api()
        api._opener.open.side_effect = _url_error("Connection refused")
        self.assertFalse(api.heartbeat())


# ── BotApiClient — get_panels ──────────────────────────────────────────────────

class TestApiClientGetPanels(unittest.TestCase):

    def test_get_panels_success(self):
        api = _make_api()
        api._opener.open.return_value = _fake_cm({"panels": [
            {"id": 1, "name": "P1", "host": "1.2.3.4", "port": 2053}
        ]})
        panels = api.get_panels()
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["id"], 1)

    def test_get_panels_empty(self):
        api = _make_api()
        api._opener.open.return_value = _fake_cm({"panels": []})
        panels = api.get_panels()
        self.assertEqual(panels, [])

    def test_get_panels_raises_on_error(self):
        from lib.api_client import ApiError
        api = _make_api()
        api._opener.open.side_effect = _url_error("refused")
        with self.assertRaises(ApiError):
            api.get_panels()


# ── XuiPanelClient — test_login ───────────────────────────────────────────────

class TestXuiPanelClientLogin(unittest.TestCase):

    def _client(self):
        from lib.panel_client import XuiPanelClient
        return XuiPanelClient(
            host       = "127.0.0.1",
            port       = 2053,
            panel_path = "",
            username   = "admin",
            password   = "password",
            timeout    = 5,
        )

    def _patched_opener(self, client):
        """
        Inject a MagicMock opener into _build_opener so test_login uses it.
        Returns (mock_opener, patcher) — caller must start/stop the patcher.
        """
        mock_opener = MagicMock()
        patcher = patch.object(client, "_build_opener", return_value=mock_opener)
        return mock_opener, patcher

    def test_login_success_json(self):
        client = self._client()
        mock_opener, patcher = self._patched_opener(client)
        mock_opener.open.return_value = _fake_cm({"success": True, "msg": "ok"})
        with patcher:
            success, msg = client.test_login()
        self.assertTrue(success)
        self.assertIn("successful", msg.lower())

    def test_login_failure_json(self):
        client = self._client()
        mock_opener, patcher = self._patched_opener(client)
        mock_opener.open.return_value = _fake_cm({"success": False, "msg": "Wrong credentials"})
        with patcher:
            success, msg = client.test_login()
        self.assertFalse(success)
        self.assertIn("Wrong credentials", msg)

    def test_login_connection_error(self):
        client = self._client()
        mock_opener, patcher = self._patched_opener(client)
        mock_opener.open.side_effect = _url_error("refused")
        with patcher:
            success, msg = client.test_login()
        self.assertFalse(success)
        self.assertIn("127.0.0.1", msg)

    def test_login_http_error(self):
        client = self._client()
        mock_opener, patcher = self._patched_opener(client)
        mock_opener.open.side_effect = _http_error(500, {})
        with patcher:
            success, msg = client.test_login()
        self.assertFalse(success)
        self.assertIn("500", msg)


# ── register_agent ─────────────────────────────────────────────────────────────

class TestRegisterAgentFlow(unittest.TestCase):

    def _register(self, opener_side_effect=None, opener_return_value=None):
        from lib.api_client import register_agent
        with patch("lib.api_client._build_opener") as mock_build:
            mock_opener = MagicMock()
            mock_build.return_value = mock_opener
            if opener_side_effect:
                mock_opener.open.side_effect = opener_side_effect
            else:
                mock_opener.open.return_value = opener_return_value
            return register_agent(
                base_url           = "http://fake:8080",
                registration_token = "deadbeef" * 5,
                agent_name         = "TestAgent",
                panel_name         = "TestPanel",
                panel_host         = "1.2.3.4",
                panel_port         = 2053,
                panel_path         = "",
                panel_username     = "admin",
                panel_password     = "pass",
            )

    def test_register_success(self):
        body = {
            "agent_uuid":   "aaaabbbb-1234-1234-1234-aaaabbbbcccc",
            "agent_secret": "x" * 64,
        }
        result = self._register(opener_return_value=_fake_cm(body))
        self.assertEqual(result["agent_uuid"],        "aaaabbbb-1234-1234-1234-aaaabbbbcccc")
        self.assertEqual(len(result["agent_secret"]), 64)

    def test_register_bad_token(self):
        from lib.api_client import ApiError
        with self.assertRaises(ApiError) as ctx:
            self._register(opener_side_effect=_http_error(403, {"error": "Invalid token"}))
        self.assertIn("Invalid token", str(ctx.exception))


# ── Config loader ──────────────────────────────────────────────────────────────

class TestConfigLoader(unittest.TestCase):

    def test_load_env_file_parser(self):
        import tempfile
        from lib.config_loader import _load_env_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# comment\n")
            f.write("TEST_FOO=bar\n")
            f.write("TEST_BAZ=  baz value  # inline comment\n")
            f.write('TEST_QUOTED="hello world"\n')
            tmp = f.name

        for k in ("TEST_FOO", "TEST_BAZ", "TEST_QUOTED"):
            os.environ.pop(k, None)

        try:
            _load_env_file(tmp)
            self.assertEqual(os.environ.get("TEST_FOO"),    "bar")
            self.assertEqual(os.environ.get("TEST_BAZ"),    "baz value")
            self.assertEqual(os.environ.get("TEST_QUOTED"), "hello world")
        finally:
            os.unlink(tmp)
            for k in ("TEST_FOO", "TEST_BAZ", "TEST_QUOTED"):
                os.environ.pop(k, None)

    def test_existing_env_not_overwritten(self):
        import tempfile
        from lib.config_loader import _load_env_file

        os.environ["TEST_STABLE"] = "original"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("TEST_STABLE=overwritten\n")
            tmp = f.name
        try:
            _load_env_file(tmp)
            self.assertEqual(os.environ.get("TEST_STABLE"), "original")
        finally:
            os.unlink(tmp)
            os.environ.pop("TEST_STABLE", None)


if __name__ == "__main__":
    unittest.main()
